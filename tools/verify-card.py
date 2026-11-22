#!/usr/bin/env python3
"""
verify-card.py -- compare the card against the image, READ ONLY, and report
exactly where they first disagree.

Why this exists
---------------
Every earlier round argued about the flash from a handful of node dumps. That is
how three rounds in a row reached a confident wrong answer. This walks the whole
partition instead: it streams the card through adb in chunks, compares it with
the sparse image on the PC, and prints the FIRST divergence plus a map of which
regions match. Neither hypothesis is assumed; the card is simply measured.

It never writes to the phone. The only adb verbs are 'shell dd' (read) and
'pull' is avoided entirely: dd writes to stdout and the bytes come back through
exec-out, so /sdcard is never touched (it lives on userdata, the thing we are
measuring).

Usage
-----
    python verify-card.py ios16-root.simg
    python verify-card.py ios16-root.simg --chunk-mb 64
    python verify-card.py ios16-root.simg --start-mb 4096      # resume a scan
    python verify-card.py ios16-root.simg --map                 # region report only

Exit status: 0 the whole compared range matches, 1 a divergence was found.
"""

import os
import struct
import subprocess
import sys

BLOCK = 4096
SPARSE_MAGIC = 0xED26FF3A
CHUNK_RAW = 0xCAC1
CHUNK_FILL = 0xCAC2
CHUNK_DONT_CARE = 0xCAC3
CHUNK_CRC32 = 0xCAC4

DEV = "/dev/block/by-name/userdata"


class Sparse:
    """Random access into an Android sparse image, no expansion on disk."""

    def __init__(self, path):
        self.f = open(path, "rb")
        hdr = self.f.read(28)
        (magic, major, _minor, fhsz, chsz, blk, total_blks, total_chunks,
         _csum) = struct.unpack("<IHHHHIIII", hdr)
        if magic != SPARSE_MAGIC:
            raise ValueError("not a sparse image (magic 0x%08x)" % magic)
        if major != 1:
            raise ValueError("unsupported sparse major %d" % major)
        self.blk = blk
        self.total_blks = total_blks
        self.size = total_blks * blk
        self.chunks = []
        pos = fhsz
        out = 0
        for _ in range(total_chunks):
            self.f.seek(pos)
            ctype, _r, csz, tsz = struct.unpack("<HHII", self.f.read(12))
            self.chunks.append((out, ctype, csz, pos + chsz))
            out += csz
            pos += tsz

    def read(self, off, n):
        out = bytearray()
        while n > 0:
            blkno = off // self.blk
            lo, hi, found = 0, len(self.chunks) - 1, None
            while lo <= hi:
                mid = (lo + hi) // 2
                start, ctype, csz, doff = self.chunks[mid]
                if blkno < start:
                    hi = mid - 1
                elif blkno >= start + csz:
                    lo = mid + 1
                else:
                    found = self.chunks[mid]
                    break
            if found is None:
                take = min(n, self.size - off)
                if take <= 0:
                    break
                out += b"\x00" * take
                off += take
                n -= take
                continue
            start, ctype, csz, doff = found
            take = min(n, (start + csz) * self.blk - off)
            if ctype == CHUNK_RAW:
                self.f.seek(doff + off - start * self.blk)
                out += self.f.read(take)
            elif ctype == CHUNK_FILL:
                self.f.seek(doff)
                fill = self.f.read(4)
                out += (fill * ((take + 3) // 4))[:take]
            else:
                out += b"\x00" * take
            off += take
            n -= take
        return bytes(out)


class Raw:
    def __init__(self, path):
        self.f = open(path, "rb")
        self.f.seek(0, 2)
        self.size = self.f.tell()
        self.blk = BLOCK

    def read(self, off, n):
        self.f.seek(off)
        return self.f.read(n)


def open_image(path):
    with open(path, "rb") as f:
        magic = struct.unpack("<I", f.read(4))[0]
    return Sparse(path) if magic == SPARSE_MAGIC else Raw(path)


def adb(args, timeout=None):
    try:
        return subprocess.run(["adb"] + args, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        # Say so plainly: a traceback here reads like the tool is broken, and the
        # actual cause is only that adb is not on PATH (or not next to the tool).
        sys.exit("adb not found on PATH. Install Android platform-tools, or put "
                 "adb.exe next to this script, then retry.")


def read_card(off, length):
    """Read length bytes at absolute partition byte offset off, via exec-out."""
    # bs=4096 with a block-aligned skip/count keeps every transfer block exact,
    # which matters because the UGG driver works in 4 KiB blocks.
    skip = off // BLOCK
    count = (length + BLOCK - 1) // BLOCK
    cmd = "dd if=%s bs=%d skip=%d count=%d 2>/dev/null" % (DEV, BLOCK, skip, count)
    r = adb(["exec-out", cmd])
    return r.stdout


def show(off, img_bytes, card_bytes, span=32):
    for i in range(0, len(img_bytes), span):
        if img_bytes[i:i + span] != card_bytes[i:i + span]:
            first = i
            break
    else:
        first = 0
    print("first differing bytes at partition offset %d (block %d, %.4f GiB)"
          % (off + first, (off + first) // BLOCK, (off + first) / 2 ** 30))
    print("  image:")
    for i in range(first, min(first + span, len(img_bytes)), span):
        print("    %06x  %s" % (off + i, img_bytes[i:i + span].hex(" ")))
    print("  card :")
    for i in range(first, min(first + span, len(card_bytes)), span):
        print("    %06x  %s" % (off + i, card_bytes[i:i + span].hex(" ")))
    seg = card_bytes[first:first + span]
    print("  card bytes as text: %r"
          % "".join(chr(c) if 32 <= c < 127 else "." for c in seg))

    # Endianness check, because that distinguishes two very different faults and
    # the difference decides what to fix.
    #
    # The 0104 console decodes like this: node 12288 holds "ORP." / "IMIX" as
    # stored, which is ".PRO" / "XIMI" when each 32-bit word is byte-reversed.
    # Those are the beginnings of ".PROXIMITY" and ".PHONE", i.e. catalog keys --
    # so the card may hold the RIGHT bytes in the WRONG order, not foreign data.
    #
    # If reversing every 4 bytes turns the card's bytes into the image's bytes, the
    # fault is a word-order bug (some path is swapping 32-bit words); if it does
    # not, the content is simply wrong and the writer is at fault.
    img_seg = img_bytes[first:first + span]

    def swapped(b):
        out = bytearray()
        for i in range(0, len(b) - 3, 4):
            out += b[i:i + 4][::-1]
        return bytes(out)

    rev = swapped(seg)
    if rev and rev == img_seg[:len(rev)]:
        print("  ** byte-reversed card == image: the card holds correct data in")
        print("     word-swapped order. Look for a 32-bit swap in the write path,")
        print("     not at the source image. **")
    else:
        match = sum(1 for a, b in zip(rev, img_seg) if a == b)
        print("  byte-reversed card vs image: %d/%d bytes agree%s"
              % (match, len(rev),
                 "  (partial -- consistent with a swap)" if match > len(rev) // 2
                 else "  (not a swap)"))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    chunk_mb = 64
    start_mb = 0
    want_map = "--map" in sys.argv
    for i, a in enumerate(sys.argv):
        if a == "--chunk-mb" and i + 1 < len(sys.argv):
            chunk_mb = int(sys.argv[i + 1])
        if a == "--start-mb" and i + 1 < len(sys.argv):
            start_mb = int(sys.argv[i + 1])

    if not args:
        print(__doc__)
        return 2
    img_path = args[0]
    if not os.path.exists(img_path):
        print("no such image: %s" % img_path)
        return 2

    r = adb(["devices"])
    if b"device" not in r.stdout:
        print("no device (needs TWRP or a booted Android with adb)")
        print(r.stdout.decode(errors="replace"))
        return 2

    img = open_image(img_path)
    chunk = chunk_mb << 20
    total = img.size
    print("image   : %s" % img_path)
    print("size    : %d bytes (%.2f GiB)" % (total, total / 2 ** 30))
    print("device  : %s" % DEV)
    print("chunk   : %d MiB   start at %d MiB" % (chunk_mb, start_mb))
    print()

    off = start_mb << 20
    regions = []          # (start_gib, end_gib, ok)
    first_bad = None
    while off < total:
        n = min(chunk, total - off)
        want = img.read(off, n)
        got = read_card(off, n)
        if len(got) < len(want):
            print("!! short read at %.3f GiB: got %d of %d bytes"
                  % (off / 2 ** 30, len(got), len(want)))
            if first_bad is None:
                first_bad = off + len(got)
            regions.append((off / 2 ** 30, (off + n) / 2 ** 30, False))
            break
        if got == want:
            regions.append((off / 2 ** 30, (off + n) / 2 ** 30, True))
        else:
            regions.append((off / 2 ** 30, (off + n) / 2 ** 30, False))
            if first_bad is None:
                first_bad = off
                print()
                print("=== FIRST DIVERGENCE in chunk %.3f-%.3f GiB"
                      % (off / 2 ** 30, (off + n) / 2 ** 30))
                show(off, want, got)
                print()
        print("  %7.3f GiB  %s" % ((off + n) / 2 ** 30,
                                   "match" if got == want else "DIFFERS"),
              flush=True)
        off += n
        if first_bad is not None and not want_map:
            # one divergence is enough to prove the flash is wrong; stop early
            # so a 16 GiB scan does not have to finish to be useful.
            print()
            print("stopping at the first divergence (use --map to scan it all)")
            break

    # Region summary: the point of a full scan is the boundary.
    print()
    print("=== regions")
    run_start, run_ok = None, None
    for a, b, ok in regions:
        if run_ok is None:
            run_start, run_ok = a, ok
        elif ok != run_ok:
            print("  %8.3f - %8.3f GiB  %s" % (run_start, a,
                                               "OK" if run_ok else "BAD"))
            run_start, run_ok = a, ok
    if run_ok is not None:
        print("  %8.3f - %8.3f GiB  %s" % (run_start, regions[-1][1],
                                           "OK" if run_ok else "BAD"))
    print()
    if first_bad is None:
        print("the compared range matches the image byte for byte")
        return 0
    print("FIRST DIVERGENCE at partition offset %d (block %d, %.4f GiB)"
          % (first_bad, first_bad // BLOCK, first_bad / 2 ** 30))
    return 1


if __name__ == "__main__":
    sys.exit(main())
