#!/usr/bin/env python3
"""
compare-volume-header.py -- decide whether the card holds the SAME volume as the image.

Why this exists, and why it must run first
------------------------------------------
Every "compare the card against the image" attempt so far has assumed the two hold the
same volume. They do not have to. The 0104 boot log reports the catalog extents the
kernel read FROM THE CARD's own volume header:

    UGG CHECK: catalog blockSize=4096 extents:
        183682+16384 211815+8192 1138210+8192 1729347+8192

and the image CI builds now has, from its own header:

        183682+16384 211896+8192 1138210+8192 1729468+8192

Same ext0 and ext2; ext1 starts 81 blocks later and ext3 121 blocks later. Two
different volumes. Comparing their bytes byte-for-byte is therefore guaranteed to
report 'everything after the first difference is wrong', which is true and useless --
it says nothing about the transfer.

So this runs FIRST and answers one question: is this even the same volume? Only if the
headers agree is a byte comparison meaningful.

Usage
-----
    python compare-volume-header.py IMAGE            # print the image's own layout
    python compare-volume-header.py IMAGE --extents "183682+16384 211815+8192 ..."
    python compare-volume-header.py IMAGE --card-extents-from LOG

The --card-extents-from form reads the extents out of a kernel console log, which is
the only place they exist without the phone attached.

Exit status: 0 the layouts match, 1 they differ (so do not compare bytes),
             2 the question could not be answered.
"""
import re
import struct
import sys

BS_DEFAULT = 4096


def read_raw(image, offset, n):
    """Read n bytes at offset, transparently expanding an Android sparse file."""
    import os
    if not os.path.exists(image):
        raise SystemExit('no such image: %s' % image)
    with open(image, 'rb') as f:
        head = f.read(28)
        f.seek(0)
        if len(head) >= 28 and struct.unpack_from('<I', head, 0)[0] == 0xED26FF3A:
            return read_sparse(f, offset, n)
        f.seek(offset)
        return f.read(n)


def read_sparse(f, offset, n):
    f.seek(0)
    hdr = f.read(28)
    (magic, major, minor, fhsz, chsz, blk, total_blks, total_chunks,
     csum) = struct.unpack('<IHHHHIIII', hdr)
    f.seek(fhsz)
    block = 0
    out = bytearray()
    want_lo, want_hi = offset, offset + n
    for _ in range(total_chunks):
        ch = f.read(12)
        if len(ch) < 12:
            break
        ctype, _r, csz, tsz = struct.unpack('<HHII', ch)
        payload = tsz - chsz
        start = block * blk
        end = start + csz * blk
        if end <= want_lo or start >= want_hi:
            block += csz
            if ctype == 0xCAC1:
                f.seek(payload, 1)
            elif ctype == 0xCAC2:
                f.seek(payload, 1)
            elif ctype == 0xCAC4:
                f.seek(payload, 1)
            continue
        if ctype == 0xCAC1:            # raw
            data = f.read(payload)
            out += data[max(0, want_lo - start):max(0, want_hi - start)]
        elif ctype == 0xCAC2:          # fill
            val = f.read(payload)
            out += (val * ((csz * blk) // max(1, len(val))))[:csz * blk][
                max(0, want_lo - start):max(0, want_hi - start)]
        elif ctype == 0xCAC3:          # don't care -> zeros
            out += bytes(max(0, min(want_hi, end) - max(want_lo, start)))
        elif ctype == 0xCAC4:          # crc
            f.seek(payload, 1)
        block += csz
        if len(out) >= n:
            break
    return bytes(out[:n])


def header_extents(blob):
    """Parse the HFS+ volume header sitting at offset 1024 of the volume."""
    h = blob[1024:1024 + 512]
    sig = h[0:2]
    if sig not in (b'H+', b'HX'):
        return None, 'not an HFS+ volume (signature %r)' % sig
    bs, = struct.unpack_from('>I', h, 40)
    total, = struct.unpack_from('>I', h, 44)
    # The catalog file is the 4th fork in the header: allocation, extents,
    # catalog, attributes.
    cat_off = 272
    fsize, = struct.unpack_from('>Q', h, cat_off)
    extents = []
    for i in range(8):
        start, count = struct.unpack_from('>II', h, cat_off + 16 + 8 * i)
        if count:
            extents.append((start, count))
    return {'bs': bs, 'total': total, 'size': fsize, 'extents': extents}, None


def fmt(exts):
    return ' '.join('%d+%d' % e for e in exts)


def main():
    # Skip option VALUES as well as option names, otherwise "--extents X" leaves X
    # in the positional list and it gets mistaken for the image path -- which happened
    # on this script's very first run.
    positional = []
    skip = False
    for a in sys.argv[1:]:
        if skip:
            skip = False
            continue
        if a in ('--extents', '--card-extents-from'):
            skip = True
            continue
        if a.startswith('--'):
            continue
        positional.append(a)
    if not positional:
        print(__doc__)
        return 2
    image = positional[0]

    card = None
    card_src = None
    for i, a in enumerate(sys.argv):
        if a == '--extents' and i + 1 < len(sys.argv):
            card = [(int(x.split('+')[0]), int(x.split('+')[1]))
                    for x in sys.argv[i + 1].split()]
            card_src = 'command line'
        if a == '--card-extents-from' and i + 1 < len(sys.argv):
            text = open(sys.argv[i + 1], encoding='utf-8', errors='replace').read()
            m = re.search(r'catalog blockSize=\d+ extents:(.*)', text)
            if not m:
                print('no "catalog blockSize=... extents:" line in %s'
                      % sys.argv[i + 1])
                return 2
            card = [(int(t.split('+')[0]), int(t.split('+')[1]))
                    for t in m.group(1).split() if '+' in t]
            card_src = sys.argv[i + 1]

    blob = read_raw(image, 0, 1024 + 512)
    if len(blob) < 1536:
        print('could not read the volume header from %s' % image)
        return 2
    hdr, err = header_extents(blob)
    if err:
        print('%s: %s' % (image, err))
        return 2

    print('image  : %s' % image)
    print('  block size   : %d' % hdr['bs'])
    print('  total blocks : %d' % hdr['total'])
    print('  catalog size : %d bytes' % hdr['size'])
    print('  catalog extents: %s' % fmt(hdr['extents']))

    if card is None:
        print()
        print('No card extents given, so nothing to compare. To answer the real')
        print('question, supply what the phone reported:')
        print('  --extents "183682+16384 211815+8192 1138210+8192 1729347+8192"')
        print('  --card-extents-from out/kernel-console.txt')
        return 0

    print()
    print('card   : from %s' % card_src)
    print('  catalog extents: %s' % fmt(card))
    print()

    n = max(len(hdr['extents']), len(card))
    same = True
    print('%-4s %-20s %-20s %s' % ('ext', 'image', 'card', 'check'))
    for i in range(n):
        a = hdr['extents'][i] if i < len(hdr['extents']) else None
        b = card[i] if i < len(card) else None
        if a == b:
            verdict = 'same'
        else:
            same = False
            if a and b:
                verdict = 'DIFFERS (%+d blocks start, %+d count)' % (b[0] - a[0],
                                                                     b[1] - a[1])
            else:
                verdict = 'DIFFERS (present on one side only)'
        print('%-4s %-20s %-20s %s'
              % ('ext%d' % i,
                 fmt([a]) if a else '-', fmt([b]) if b else '-', verdict))

    print()
    if same:
        print('=> SAME volume layout. A byte-by-byte comparison of the card against')
        print('   this image is meaningful; go ahead with verify-card.py.')
        return 0
    print('=> DIFFERENT volumes. The card holds a volume whose catalog is laid out')
    print('   differently, so it is NOT this image, damaged. Comparing bytes would')
    print('   report "everything after the first difference is wrong", which is')
    print('   true and useless: it says nothing about the transfer.')
    print()
    print('   Do NOT read "smaller extent numbers" as "older image". That inference')
    print('   was tried on this port and the data contradicted it: the card asked for')
    print('   node 19514 while the current image has no leaf above 19491, so the card')
    print('   holds MORE catalog content in the upper range, not less.')
    print()
    print('   What can be said: a different volume on the card means either the flash')
    print('   never ran (the card still holds an earlier write) or a different file')
    print('   was written. Which one cannot be decided from these numbers, and does')
    print('   not need to be: this check only answers "is it this image or not", and')
    print('   the answer is no.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
