#!/usr/bin/env python3
"""
simg-info.py -- report what an Android sparse image actually contains.

Why: the ugg flash kept producing a card whose bytes are not the image's, and the
leading explanation was that img2simg encoded zero regions as DONT_CARE, which
fastboot skips instead of writing. That explanation is only testable if we look
at the chunk table of the real file, so this prints it:

    * the header (block size, total blocks, chunk count)
    * how many RAW / FILL / DONT_CARE / CRC32 chunks, and how many bytes each kind
      covers
    * where the DONT_CARE runs are (if any) and their total size

If DONT_CARE is absent the "stale zeros" theory is dead and the flash fault is
elsewhere. If DONT_CARE covers GiBs, that region of the card keeps whatever was
there before and the fix is to erase the partition first.

Usage
-----
    python simg-info.py ios16-root.simg
    python simg-info.py ios16-root.simg --list-dont-care     # every run, with sizes
"""

import os
import struct
import sys

SPARSE_MAGIC = 0xED26FF3A
CHUNK_RAW = 0xCAC1
CHUNK_FILL = 0xCAC2
CHUNK_DONT_CARE = 0xCAC3
CHUNK_CRC32 = 0xCAC4
NAMES = {CHUNK_RAW: "RAW", CHUNK_FILL: "FILL",
         CHUNK_DONT_CARE: "DONT_CARE", CHUNK_CRC32: "CRC32"}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    show_dc = "--list-dont-care" in sys.argv
    if not args:
        print(__doc__)
        return 2
    path = args[0]
    if not os.path.exists(path):
        print("no such image: %s" % path)
        return 2

    size_on_disk = os.path.getsize(path)
    f = open(path, "rb")
    hdr = f.read(28)
    if len(hdr) < 28:
        print("file is too short to be a sparse image")
        return 1
    (magic, major, minor, fhsz, chsz, blk, total_blks, total_chunks,
     csum) = struct.unpack("<IHHHHIIII", hdr)
    if magic != SPARSE_MAGIC:
        print("not a sparse image (magic 0x%08x) -- this is a raw image" % magic)
        return 1

    out_bytes = total_blks * blk
    print("file          : %s" % path)
    print("size on disk  : %d bytes (%.2f GiB)" % (size_on_disk,
                                                   size_on_disk / 2 ** 30))
    print("expanded size : %d bytes (%.2f GiB)" % (out_bytes, out_bytes / 2 ** 30))
    print("block size    : %d" % blk)
    print("total blocks  : %d" % total_blks)
    print("total chunks  : %d" % total_chunks)
    print()

    f.seek(fhsz)
    stats = {t: [0, 0] for t in (CHUNK_RAW, CHUNK_FILL, CHUNK_DONT_CARE, CHUNK_CRC32)}
    dc_runs = []
    block = 0
    for n in range(total_chunks):
        ch = f.read(12)
        if len(ch) < 12:
            print("truncated at chunk %d of %d" % (n, total_chunks))
            break
        ctype, _r, csz, tsz = struct.unpack("<HHII", ch)
        payload = tsz - chsz
        if ctype not in stats:
            print("unknown chunk type 0x%04x at %d" % (ctype, n))
            return 1
        covered = csz * blk
        stats[ctype][0] += 1
        stats[ctype][1] += covered
        if ctype == CHUNK_DONT_CARE:
            dc_runs.append((block, csz))
        block += csz
        f.seek(payload, os.SEEK_CUR)

    print("%-10s %8s  %14s  %7s" % ("type", "chunks", "bytes covered", "% of image"))
    for t in (CHUNK_RAW, CHUNK_FILL, CHUNK_DONT_CARE, CHUNK_CRC32):
        cnt, cov = stats[t]
        if cnt == 0 and t == CHUNK_CRC32:
            continue
        print("%-10s %8d  %14d  %6.2f%%" % (NAMES[t], cnt, cov,
                                            100.0 * cov / out_bytes if out_bytes else 0))
    print()

    dc_cnt, dc_bytes = stats[CHUNK_DONT_CARE]
    if dc_cnt == 0:
        print("No DONT_CARE chunks.")
        print("=> fastboot writes every block of this image, including the zeros")
        print("   (they arrive as FILL(0)), so 'stale Android data survives in the")
        print("   zero regions' CANNOT be the reason the card differs.")
        print("   Look elsewhere: transfer offset, USB, or the writer itself.")
    else:
        print("DONT_CARE covers %.3f GiB in %d run(s)." % (dc_bytes / 2 ** 30, dc_cnt))
        print("=> these ranges are NOT written by fastboot: the card keeps whatever")
        print("   the partition held before. If the partition had Android on it, that")
        print("   is Android data sitting where the image expects zeros/holes.")
        print("   Fix: 'fastboot erase userdata' first, then flash.")
        if show_dc:
            print()
            for start, csz in dc_runs[:400]:
                print("   blocks %10d..%10d  %8.3f..%8.3f GiB  %d blocks"
                      % (start, start + csz - 1, start * blk / 2 ** 30,
                         (start + csz) * blk / 2 ** 30, csz))
            if len(dc_runs) > 400:
                print("   ... and %d more runs" % (len(dc_runs) - 400))
    return 0


if __name__ == "__main__":
    sys.exit(main())
