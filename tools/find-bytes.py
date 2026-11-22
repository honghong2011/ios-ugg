#!/usr/bin/env python3
"""
find-bytes.py -- locate a byte pattern inside a sparse or raw image.

Why: the phone reads these four descriptors from catalog nodes 19174, 19193,
19462 and 19514:

    0x6a13d46a  0xad4610a9   (with fLink/bLink in one 8-byte run)
    0xf728c62a  0x51e416ab
    0x44f79524  0xbe5d3be1
    0x7843b47b  0x1c625ae5

The image says they should be valid nodes instead. If those exact bytes exist
somewhere else in the image, the flash wrote the right data to the wrong
offset, and the difference tells us by how much. If they appear nowhere, the
card holds data that is not from this image at all.

Usage
-----
    python find-bytes.py ios16-root.simg 6a13d46a
    python find-bytes.py ios16-root.img 6a13d46a f728c62a --context

Prints every occurrence with its byte offset and the image block it falls in.
"""

import os
import struct
import sys

SPARSE_MAGIC = 0xED26FF3A
CHUNK_RAW = 0xCAC1
CHUNK_FILL = 0xCAC2
CHUNK_DONT_CARE = 0xCAC3
CHUNK_CRC32 = 0xCAC4

BLOCK = 4096


def iter_regions(path):
    """Yield (file_offset_of_data, byte_length, out_block_start) for real data."""
    f = open(path, "rb")
    magic = struct.unpack("<I", f.read(4))[0]
    f.close()
    if magic != SPARSE_MAGIC:
        yield ("raw", path, 0, os.path.getsize(path), 0)
        return
    f = open(path, "rb")
    hdr = f.read(28)
    (magic, major, minor, fhsz, chsz, blk, total_blks, total_chunks,
     csum) = struct.unpack("<IHHHHIIII", hdr)
    f.seek(fhsz)
    out_block = 0
    for _ in range(total_chunks):
        ch = f.read(12)
        if len(ch) < 12:
            break
        ctype, _r, csz, tsz = struct.unpack("<HHII", ch)
        data_off = f.tell()
        payload = tsz - chsz
        if ctype == CHUNK_RAW:
            yield ("sparse", path, data_off, payload, out_block)
        elif ctype in (CHUNK_FILL, CHUNK_DONT_CARE):
            # FILL carries 4 bytes, DONT_CARE nothing; neither can hold a pattern
            pass
        f.seek(data_off + payload)
        out_block += csz


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ctx = "--context" in sys.argv
    if len(args) < 2:
        print(__doc__)
        return 2
    path = args[0]
    pats = [bytes.fromhex(p) for p in args[1:]]
    if not os.path.exists(path):
        print("no such file: %s" % path)
        return 2
    print("image  : %s" % path)
    for p in pats:
        print("pattern: %s" % p.hex(" "))
    print()

    hits = {p: [] for p in pats}
    scanned = 0
    for kind, _p, data_off, length, out_block in iter_regions(path):
        f = open(path, "rb")
        f.seek(data_off)
        buf = f.read(length)
        f.close()
        scanned += len(buf)
        for p in pats:
            start = 0
            while True:
                i = buf.find(p, start)
                if i < 0:
                    break
                out_off = out_block * BLOCK + i
                hits[p].append((out_off, out_block + i // BLOCK))
                start = i + 1
        if scanned % (256 << 20) < length:
            print("  scanned %6.2f GiB" % (scanned / 2 ** 30), flush=True)

    print()
    any_hit = False
    for p in pats:
        hs = hits[p]
        print("%s : %d occurrence(s)" % (p.hex(), len(hs)))
        for out_off, blk in hs[:10]:
            any_hit = True
            print("    image offset 0x%x (block %d)" % (out_off, blk))
            # how far is this from the node the kernel reads?
            for node, nodeblk in ((19174, 1734927), (19193, 1734965),
                                  (19462, 1735503), (19514, 1735607)):
                d = blk - nodeblk
                if abs(d) <= 64:
                    print("      that is node %d %+d blocks (node data would be"
                          " shifted by %d bytes)" % (node, d, d * BLOCK))
        if len(hs) > 10:
            print("    ... and %d more" % (len(hs) - 10))
    print()
    if not any_hit:
        print("Not present in this image at all -- so the bytes on the card did")
        print("not come from this file, from any offset.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
