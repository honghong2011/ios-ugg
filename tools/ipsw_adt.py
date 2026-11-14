#!/usr/bin/env python3
"""Extract the Apple device tree (ADT) for a device from an IPSW.

The /product node of the real device tree is what MobileGestalt reads at
runtime; without it the iOS userland still boots but several frameworks
misbehave (mido hit exactly this: a missing D211AP tree made backboardd
crash-loop on a b3a8 surface). It is an Apple artifact, so it is never
committed -- this pulls the single file out of the IPSW and unwraps the IM4P.

  ipsw_adt.py IPSW_OR_URL DEVICE OUT.adt

DEVICE is the IPSW identifier (iPhone10,4) or the D-code (d20ap).

Note on format: an ADT is NOT an FDT. It starts with u32 nprops / u32 nchildren
and has no magic, so validate it with adt.parse() rather than a magic check.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt  # noqa: E402

DEVCODES = {
    'iPhone10,3': 'd22ap',
    'iPhone10,4': 'd20ap',
    'iPhone10,5': 'd211ap',
    'iPhone10,6': 'd21ap',
}


def lzfse_decode(buf):
    """Decode an Apple bvx2 LZFSE block.

    Apple ships DeviceTree IM4Ps LZFSE-compressed (magic 'bvx2'). Python has no
    stdlib decoder, so try, in order: the lzfse CLI, pylezfse, and liblzfse via
    ctypes. Failing all three is a clear error, not a silent wrong result.
    """
    import shutil
    import subprocess

    exe = shutil.which('lzfse')
    if exe:
        out = subprocess.run([exe, '-decode'], input=buf, capture_output=True)
        if out.returncode == 0 and out.stdout:
            return out.stdout
        sys.exit('lzfse -decode failed: %s' % out.stderr[:200])

    try:
        import lzfse as pylezfse  # type: ignore
        return pylezfse.decompress(buf)
    except Exception:
        pass

    try:
        import ctypes
        import ctypes.util
        name = ctypes.util.find_library('lzfse') or 'liblzfse.so'
        lib = ctypes.CDLL(name)
        size = ctypes.c_size_t(len(buf) * 8)
        dst = ctypes.create_string_buffer(size.value)
        got = lib.lzfse_decode_buffer(dst, size, buf,
                                      ctypes.c_size_t(len(buf)), None)
        if got:
            return dst.raw[:got]
        sys.exit('liblzfse could not decode the payload')
    except OSError:
        sys.exit('the device tree is LZFSE-compressed and no decoder is '
                 'available; apt-get install lzfse')


def unwrap_im4p(buf):
    """Return the ADT payload of an IM4P-wrapped DeviceTree (DER container)."""
    tag, start, end = adt.der(buf, 0)
    if tag != 0x30:
        sys.exit('not a DER sequence (tag %#x)' % tag)
    items, off = [], start
    while off < end:
        t, vs, ve = adt.der(buf, off)
        items.append((t, buf[vs:ve]))
        off = ve
    if not items or items[0][1] != b'IM4P':
        sys.exit('not an IM4P container')
    payload = items[3][1]
    if payload[:4] == b'bvx2':
        payload = lzfse_decode(payload)
    return payload


def validate(fdt, out):
    """An ADT has no magic: prove it parses and contains /product."""
    try:
        root, consumed = adt.parse(fdt)
    except Exception as exc:
        sys.exit('%s does not parse as an ADT: %s' % (out, exc))
    names = []
    def walk(n):
        for name, _flags, value in n.props:
            if name == 'name':
                names.append(value.split(b'\0')[0].decode('latin1'))
        for c in n.children:
            walk(c)
    walk(root)
    if 'product' not in names:
        sys.exit('%s parses but has no /product node' % out)
    print('%s: %d bytes, %d nodes, /product present'
          % (out, len(fdt), len(names)), file=sys.stderr)


def main():
    # --check validates an ADT that already exists (the CI step uses it so it
    # can fail softly without taking the root build with it).
    if len(sys.argv) == 3 and sys.argv[1] == '--check':
        path = sys.argv[2]
        validate(open(path, 'rb').read(), path)
        return 0

    if len(sys.argv) < 4:
        sys.exit('usage: ipsw_adt.py IPSW_OR_URL DEVICE OUT.adt')
    ipsw, device, out = sys.argv[1], sys.argv[2], sys.argv[3]
    code = DEVCODES.get(device, device).lower()
    member = 'DeviceTree.%s.im4p' % code

    if os.path.exists(ipsw):
        import zipfile
        with zipfile.ZipFile(ipsw) as z:
            hits = [n for n in z.namelist() if n.endswith(member)]
            if not hits:
                sys.exit('%s has no member ending in %s' % (ipsw, member))
            print('member: %s' % hits[0], file=sys.stderr)
            raw = z.read(hits[0])
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        outdir = os.path.dirname(os.path.abspath(out))
        os.makedirs(outdir, exist_ok=True)
        import subprocess
        subprocess.run([sys.executable, os.path.join(here, 'remotezip.py'),
                        ipsw, member, outdir], check=True)
        got = [os.path.join(outdir, n) for n in os.listdir(outdir)
               if n.endswith(member.split('/')[-1])]
        if not got:
            sys.exit('remotezip did not produce %s' % member)
        raw = open(got[0], 'rb').read()

    fdt = unwrap_im4p(raw)
    open(out, 'wb').write(fdt)
    validate(fdt, out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
