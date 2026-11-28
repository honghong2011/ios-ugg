#!/usr/bin/env python3
"""simg-chunks.py -- report what the sparse image says about specific blocks.

For each block the phone complains about, does the image carry RAW data there (so
fastboot writes it), FILL (a constant, not the data), or DONT_CARE (fastboot skips it
and the card keeps whatever it held before)?

Runs on the PC against the .simg -- no adb, no phone. Python only.

    python simg-chunks.py ios16-root.simg
    python simg-chunks.py ios16-root.simg --blocks 1734885,1734925
    python simg-chunks.py ios16-root.simg --list-chunks 10
"""
import os, struct, sys

SPARSE_MAGIC = 0xED26FF3A
RAW, FILL, DONT_CARE, CRC = 0xCAC1, 0xCAC2, 0xCAC3, 0xCAC4
NAMES = {RAW: "RAW", FILL: "FILL", DONT_CARE: "DONT_CARE", CRC: "CRC32"}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    blocks = [1734885, 1734925, 1735473, 1735567]
    show_chunks = 0
    for i, a in enumerate(sys.argv):
        if a == "--blocks" and i + 1 < len(sys.argv):
            blocks = [int(x) for x in sys.argv[i + 1].replace(",", " ").split()]
        if a == "--list-chunks" and i + 1 < len(sys.argv):
            show_chunks = int(sys.argv[i + 1])
    if not args:
        print(__doc__)
        return 2
    path = args[0]
    if not os.path.exists(path):
        print("no such file: %s" % path)
        return 2

    f = open(path, "rb")
    fsize = os.path.getsize(path)
    hdr = f.read(28)
    if len(hdr) < 28:
        print("file too short for a sparse header")
        return 1
    magic, major, minor, fhsz, chsz, blk, total_blks, total_chunks, csum = \
        struct.unpack("<IHHHHIIII", hdr)
    print("file        : %s (%d bytes)" % (path, fsize))
    print("magic       : 0x%08X  version %d.%d  fhdr %d  chdr %d" % (magic, major, minor, fhsz, chsz))
    if magic != SPARSE_MAGIC:
        print("NOT a sparse image. A raw image has no chunk table: every block is written.")
        return 1
    print("block size  : %d" % blk)
    print("total blocks: %d (%.2f GiB expanded)" % (total_blks, total_blks * blk / 2**30))
    print("chunks      : %d" % total_chunks)

    f.seek(fhsz)
    kinds = {}
    spans = []
    cur = 0
    bad = None
    for i in range(total_chunks):
        pos = f.tell()
        raw = f.read(12)
        if len(raw) < 12:
            bad = (i, pos, "file ended mid-header (%d of 12 bytes)" % len(raw), None)
            break
        ct, res, csz, tsz = struct.unpack("<HHII", raw)
        if csz < 12:
            bad = (i, pos, "chunk_sz %d is below the 12-byte header" % csz, raw)
            break
        if pos + csz > fsize:
            bad = (i, pos, "chunk_sz %d runs past end of file (%d bytes left)"
                   % (csz, fsize - pos), raw)
            break
        nblk = tsz // blk
        if show_chunks and i < show_chunks:
            print("  chunk %-6d %-10s csz=%-10d tsz=%-10d -> %d blocks, starts at %d"
                  % (i, NAMES.get(ct, hex(ct)), csz, tsz, nblk, cur))
        kinds[ct] = kinds.get(ct, 0) + nblk
        spans.append((cur, cur + nblk, ct))
        cur += nblk
        if csz > 12:
            f.seek(pos + csz)
    f.close()

    if bad:
        i, pos, why, raw = bad
        print()
        print("CHUNK TABLE IS NOT WALKABLE:")
        print("  chunk #%d at file offset %d: %s" % (i, pos, why))
        if raw is not None:
            print("  raw header bytes: %s" % raw.hex(" "))
            ct, res, csz, tsz = struct.unpack("<HHII", raw)
            print("  parsed as type=0x%04X csz=%d tsz=%d" % (ct, csz, tsz))
        print()
        print("  %d chunks were read successfully before this point." % i)
        print("  Those are enough to answer the block question below if the blocks")
        print("  fall inside them.")

    print()
    print("coverage so far (%d chunks walked):" % len(spans))
    total = 0
    for ct, n in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print("  %-10s %10d blocks = %9.1f MiB" % (NAMES.get(ct, hex(ct)), n, n * blk / 2**20))
        total += n
    print("  %-10s %10d blocks  (header says %d)" % ("covered", total, total_blks))

    print()
    print("  %-10s %-12s %s" % ("block", "covered by", "fastboot behaviour"))
    print("  " + "-" * 62)
    skipped = 0
    asked = 0
    for b in blocks:
        kind = None
        for s, e, ct in spans:
            if s <= b < e:
                kind = ct
                break
        asked += 1
        if kind is None:
            if bad:
                print("  %-10d %-12s unknown -- beyond the walkable part" % (b, "?"))
            else:
                print("  %-10d %-12s not covered (past end of image)" % (b, "-"))
        elif kind == RAW:
            print("  %-10d %-12s writes the data" % (b, "RAW"))
        elif kind == FILL:
            print("  %-10d %-12s writes a CONSTANT, not the image bytes" % (b, "FILL"))
            skipped += 1
        elif kind == DONT_CARE:
            print("  %-10d %-12s SKIPS -- card keeps old data" % (b, "DONT_CARE"))
            skipped += 1
        else:
            print("  %-10d %-12s checksum only" % (b, "CRC32"))

    print()
    if skipped:
        print("VERDICT: %d of %d blocks are NOT written from the image." % (skipped, asked))
        print("         Those regions hold stale card data, which fits a correct")
        print("         volume header next to a corrupt catalogue.")
    else:
        print("VERDICT: every probed block is RAW -- the image does contain them,")
        print("         so a skipped write is not the explanation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
