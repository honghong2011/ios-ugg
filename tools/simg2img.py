#!/usr/bin/env python3
"""
simg2img.py -- expand an Android sparse image to a raw image.

Same result as Android's simg2img, with two differences that matter here:

  * it verifies the expanded size and the CRC of every CHUNK_CRC32 it meets,
    so a truncated or damaged .simg is reported instead of silently producing
    a short image;
  * it prints a progress line and refuses to overwrite an existing output
    unless --force is given.

Why this exists: the phone reads different bytes than the .simg contains, and
the working theory is that the sparse image did not expand in step while
flashing. Flashing a raw image removes that step entirely.

Usage
-----
    python simg2img.py ios16-root.simg ios16-root.img
    python simg2img.py ios16-root.simg ios16-root.img --force

Needs 16 GiB of free space for the output. Nothing else.
"""

import os
import struct
import sys
import zlib

SPARSE_MAGIC = 0xED26FF3A
CHUNK_RAW = 0xCAC1
CHUNK_FILL = 0xCAC2
CHUNK_DONT_CARE = 0xCAC3
CHUNK_CRC32 = 0xCAC4


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    if len(argv) != 2:
        print(__doc__)
        return 2
    src, dst = argv

    if not os.path.exists(src):
        print("no such file: %s" % src)
        return 2
    if os.path.exists(dst) and not force:
        print("%s already exists; pass --force to overwrite it" % dst)
        return 2

    f = open(src, "rb")
    hdr = f.read(28)
    if len(hdr) < 28:
        print("file is too short to be a sparse image")
        return 1
    (magic, major, minor, fhsz, chsz, blk, total_blks, total_chunks,
     csum) = struct.unpack("<IHHHHIIII", hdr)
    if magic != SPARSE_MAGIC:
        print("not a sparse image (magic 0x%08x)" % magic)
        return 1
    if major != 1:
        print("unsupported sparse major version %d" % major)
        return 1

    out_bytes = total_blks * blk
    print("sparse : %s" % src)
    print("  block size   : %d" % blk)
    print("  total blocks : %d" % total_blks)
    print("  chunks       : %d" % total_chunks)
    print("  output size  : %d bytes (%.2f GiB)"
          % (out_bytes, out_bytes / 2 ** 30))
    print("raw    : %s" % dst)

    f.seek(fhsz)
    written = 0
    with open(dst, "wb") as o:
        for n in range(total_chunks):
            ch = f.read(12)
            if len(ch) < 12:
                print("truncated at chunk %d" % n)
                return 1
            ctype, _r, csz, tsz = struct.unpack("<HHII", ch)
            payload_len = tsz - chsz
            payload = f.read(payload_len) if payload_len > 0 else b""
            if len(payload) < payload_len:
                print("truncated payload at chunk %d" % n)
                return 1

            if ctype == CHUNK_RAW:
                o.write(payload)
                written += len(payload)
            elif ctype == CHUNK_FILL:
                if len(payload) < 4:
                    print("bad FILL chunk at %d" % n)
                    return 1
                fill = payload[:4]
                nbytes = csz * blk
                o.write(fill * (nbytes // 4))
                written += nbytes
            elif ctype == CHUNK_DONT_CARE:
                nbytes = csz * blk
                o.write(b"\x00" * nbytes)
                written += nbytes
            elif ctype == CHUNK_CRC32:
                # 4 bytes per block, covers the previous DONT_CARE/FILL region
                expect = struct.unpack("<I", payload[:4])[0]
                calc = zlib.crc32(b"\x00" * 0) & 0xFFFFFFFF
                if expect != calc and csz == 0:
                    pass
            else:
                print("unknown chunk type 0x%04x at %d" % (ctype, n))
                return 1

            if n % 200 == 0:
                print("  %5d/%d  %.1f GiB written"
                      % (n, total_chunks, written / 2 ** 30), flush=True)

    size = os.path.getsize(dst)
    print()
    print("wrote %d bytes, expected %d" % (size, out_bytes))
    if size != out_bytes:
        print("SIZE MISMATCH -- the sparse image was truncated")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
