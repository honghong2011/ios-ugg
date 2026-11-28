#!/usr/bin/env python3
"""simg-chunks.py -- report what the sparse image says about specific blocks.

This is the question that decides the flash investigation: for each block the phone
complains about, does the image carry RAW data there (so fastboot writes it), or is it
FILL (constant bytes) or DONT_CARE (fastboot skips and the card keeps old data)?

Runs on the PC against the .simg directly -- no adb, no phone. Python only, because the
PowerShell version of this idea was wrong three times and each attempt cost a round
trip.

    python simg-chunks.py ios16-root.simg
    python simg-chunks.py ios16-root.simg --blocks 1734885 1734925
"""
import os, struct, sys

SPARSE_MAGIC = 0xED26FF3A
RAW, FILL, DONT_CARE, CRC = 0xCAC1, 0xCAC2, 0xCAC3, 0xCAC4
NAMES = {RAW: "RAW", FILL: "FILL", DONT_CARE: "DONT_CARE", CRC: "CRC32"}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    blocks = [1734885, 1734925, 1735473, 1735567]
    for i, a in enumerate(sys.argv):
        if a == "--blocks" and i + 1 < len(sys.argv):
            blocks = [int(x) for x in sys.argv[i + 1].replace(",", " ").split()]
    if not args:
        print(__doc__)
        return 2
    path = args[0]
    if not os.path.exists(path):
        print("no such file: %s" % path)
        return 2

    f = open(path, "rb")
    hdr = f.read(28)
    magic, major, minor, fhsz, chsz, blk, total_blks, total_chunks, csum = \
        struct.unpack("<IHHHHIIII", hdr)
    if magic != SPARSE_MAGIC:
        print("NOT a sparse image (magic 0x%08X) -- a raw image has no chunk table,"
              " every block is written" % magic)
        return 1

    print("file        : %s (%d bytes)" % (path, os.path.getsize(path)))
    print("block size  : %d" % blk)
    print("total blocks: %d (%.2f GiB expanded)" % (total_blks, total_blks * blk / 2**30))
    print("chunks      : %d" % total_chunks)

    f.seek(fhsz)
    kinds = {}
    dc_runs = []
    fill_runs = []
    cur = 0
    # index of every chunk so a block can be looked up without a second pass
    spans = []
    for i in range(total_chunks):
        ct, res, csz, tsz = struct.unpack("<HHII", f.read(12))
        nblk = tsz // blk
        kinds[ct] = kinds.get(ct, 0) + nblk
        spans.append((cur, cur + nblk, ct))
        if ct == DONT_CARE:
            dc_runs.append((cur, nblk))
        elif ct == FILL:
            fill_runs.append((cur, nblk))
        cur += nblk
        if csz > 12:
            f.seek(csz - 12, 1)
    f.close()

    print()
    print("coverage by chunk type (blocks are 4096 B):")
    total = 0
    for ct, n in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print("  %-10s %10d blocks = %9.1f MiB" % (NAMES.get(ct, hex(ct)), n, n * blk / 2**20))
        total += n
    print("  %-10s %10d blocks  (header says %d)" % ("covered", total, total_blks))
    if total != total_blks:
        print("  WARNING: coverage does not match the header")

    print()
    print("  %-10s %-12s %s" % ("block", "covered by", "fastboot behaviour"))
    print("  " + "-" * 60)
    skipped = 0
    for b in blocks:
        kind = None
        for s, e, ct in spans:
            if s <= b < e:
                kind = ct
                break
        if kind is None:
            verdict = "not covered (past end of image)"
            label = "-"
        elif kind == RAW:
            verdict = "writes the data"
            label = "RAW"
        elif kind == FILL:
            verdict = "writes a constant, NOT the image bytes"
            label = "FILL"
            skipped += 1
        elif kind == DONT_CARE:
            verdict = "SKIPS -- the card keeps whatever it had"
            label = "DONT_CARE"
            skipped += 1
        else:
            verdict = "checksum chunk"
            label = "CRC32"
        print("  %-10d %-12s %s" % (b, label, verdict))

    print()
    if skipped:
        print("VERDICT: %d of %d probed blocks are NOT written from the image." % (skipped, len(blocks)))
        print("         Those regions on the card hold stale data. This explains the")
        print("         corrupt catalogue with a correctly written volume header.")
    else:
        print("VERDICT: every probed block is RAW. The sparse image does contain them,")
        print("         so a skipped-write is not the explanation.")
        if dc_runs:
            print("         (%d DONT_CARE runs exist elsewhere; largest %d blocks)" %
                  (len(dc_runs), max(n for _, n in dc_runs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
