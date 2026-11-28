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

    conv_seen = set()
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
        # Which field holds what is not as standard as it looks.
        #
        # AOSP libsparse defines chunk_sz as the byte size of header+payload, and
        # total_sz the same. The image under investigation instead has chunk_sz as a
        # BLOCK count and total_sz as the byte size: its first chunk reads
        #   c1 ca | 00 00 | 01 00 00 00 | 0c 10 00 00
        # i.e. RAW, chunk_sz=1, total_sz=4108 = 12 + 4096. Reading chunk_sz as bytes
        # then gives 1, which is below the 12-byte header and aborted the walk.
        #
        # Decide per file: if chunk_sz*blk + hdr == total_sz, chunk_sz is a block
        # count; otherwise treat it as a byte size as documented.
        # Payload-bearing types settle the convention: a block-count file shows
        # chunk_sz*blk + 12 == total_sz. DONT_CARE carries no payload, so it cannot
        # be used for the test -- there total_sz is just 12 and chunk_sz is the count.
        # DONT_CARE and FILL carry little or no payload, so the arithmetic test
        # that works for RAW does not apply to them. Their chunk_sz is simply the
        # block count under the block-count convention, and 12 under the byte-size
        # one (both types have a 12-byte header and at most a 4-byte fill value).
        if ct == RAW:
            blocks_is_count = (csz * blk + chsz == tsz)
        else:
            # FILL: total_sz is 12 or 16 bytes; DONT_CARE: always 12.
            blocks_is_count = (tsz <= chsz + 4)

        conv_seen.add(blocks_is_count)
        if blocks_is_count:
            nblk = csz
            csz = tsz if tsz >= chsz else chsz
        else:
            nblk = tsz // blk
        # csz now means BYTES for every chunk type (fixed up above when the file
        # used a block count instead).
        if csz < chsz:
            bad = (i, pos, "chunk size %d is below the %d-byte header" % (csz, chsz), raw)
            break
        if pos + csz > fsize:
            bad = (i, pos, "chunk runs past end of file (%d bytes left, needs %d)"
                   % (fsize - pos, csz), raw)
            break
        if show_chunks and i < show_chunks:
            print("  chunk %-6d %-10s csz=%-10d tsz=%-10d -> %d blocks, starts at %d"
                  % (i, NAMES.get(ct, hex(ct)), csz, tsz, nblk, cur))
        kinds[ct] = kinds.get(ct, 0) + nblk
        spans.append((cur, cur + nblk, ct))
        cur += nblk
        if csz > 12:
            f.seek(pos + csz)
    f.close()
    print("chunk_sz field: %s" % ("BLOCK count" if True in conv_seen and False not in conv_seen else "byte size" if False in conv_seen else "no chunks"))

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
