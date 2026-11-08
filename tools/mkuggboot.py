#!/usr/bin/env python3
"""Assemble the final ugg boot image for `fastboot boot`.

  mkuggboot.py --shim shim/out/Image --kernel kernel.development.ugg \
      --adt ugg.adt --dtbundle msm8937-dtbundle.bin [--ramdisk empty.cpio.gz] \
      [--cmdline "..."] --out shim-boot.img

Steps (all local, no compiler needed):
  1. mkpayload.py builds the XNU payload (rebased kernel + ADT + boot_args).
  2. The payload is appended to the shim Image at a 16 KiB boundary, then the
     whole thing is gzipped ("Image.gz").
  3. The DTB bundle goes right after the gzip stream: this LK finds the DT past
     the gzip stream, selects one by qcom,msm-id/qcom,board-id and hands it to
     the kernel in x0. A raw Image or a DT outside the kernel section fails
     ("dtb not found" or a silent hang).
  4. Wrapped in the boot image header v0 (2048-byte pages) this LK expects.
"""
import argparse
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mkpayload  # noqa: E402


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pack_ugg = _load('pack_ugg', 'pack-ugg.py')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--shim', required=True, help='shim Image (shim/out/Image)')
    ap.add_argument('--kernel', required=True, help='kernel.development.ugg')
    ap.add_argument('--adt', required=True, help='ADT from mkadt.py --ugg')
    ap.add_argument('--dtbundle', required=True, help='concatenated DTBs for this phone')
    ap.add_argument('--ramdisk', help='gzip cpio ramdisk (optional; this LK ignores it)')
    ap.add_argument('--cmdline', default='debug=0xc serial=3 cpus=1 keepsyms=1')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    shim = open(a.shim, 'rb').read()
    ramdisk = open(a.ramdisk, 'rb').read() if a.ramdisk else b''
    bundle = open(a.dtbundle, 'rb').read()
    if bundle[:4] != b'\xd0\x0d\xfe\xed':
        sys.exit('error: DTB bundle does not start with an FDT magic')

    payload, info = mkpayload.build(a.kernel, a.adt, a.cmdline)
    print('payload          : %d bytes, virt_base %s entry %s kernel_end %s'
          % (len(payload), info['virt_base'], info['entry'], info['kernel_end']))

    image, gz, section = pack_ugg.build_image(shim, ramdisk, bundle, a.cmdline, payload)
    open(a.out, 'wb').write(image)
    print('shim Image       : %d bytes' % len(shim))
    print('payload appended : %d bytes (16K aligned)' % len(payload))
    print('Image.gz         : %d bytes' % len(gz))
    print('DTB bundle       : %d bytes' % len(bundle))
    print('boot image       : %d bytes -> %s' % (len(image), a.out))
    print('boot with        : fastboot boot %s' % a.out)


if __name__ == '__main__':
    main()
