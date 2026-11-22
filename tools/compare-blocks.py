#!/usr/bin/env python3
"""
compare-blocks.py -- diff two blocks of a sparse or raw image, and say whether
either one looks like an HFS b-tree node.

Context: the phone reads these bytes from catalog node 19174:

    6a 13 d4 6a ad 46 10 a9      (fLink / bLink)

but the image says that node is

    00 00 4a f9 00 00 00 05      (a valid leaf node, kind 0xff)

Those same bad bytes do exist in the image, at block 662899. This script shows
what is at both places so we can tell a shifted copy from a coincidence.

Usage
-----
    python compare-blocks.py ios16-root.simg 662899 1734927
    python compare-blocks.py ios16-root.img  662899 1734927 512
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


class Sparse:
    def __init__(self, path):
        self.f = open(path, "rb")
        hdr = self.f.read(28)
        (self.magic, self.major, self.minor, self.fhsz, self.chsz,
         self.blk, self.total_blks, self.total_chunks,
         self.csum) = struct.unpack("<IHHHHIIII", hdr)
        self.size = self.total_blks * self.blk
        self.map = []
        pos = self.fhsz
        out = 0
        for _ in range(self.total_chunks):
            self.f.seek(pos)
            ctype, _r, csz, tsz = struct.unpack("<HHII", self.f.read(12))
            self.map.append((out, ctype, csz, pos + self.chsz))
            out += csz
            pos += tsz

    def chunk_at(self, blkno):
        lo, hi = 0, len(self.map) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            start, ctype, csz, doff = self.map[mid]
            if blkno < start:
                hi = mid - 1
            elif blkno >= start + csz:
                lo = mid + 1
            else:
                return self.map[mid]
        return None

    def read(self, off, n):
        out = bytearray()
        while n > 0:
            blkno = off // self.blk
            ch = self.chunk_at(blkno)
            if ch is None:
                out += b"\x00" * n
                break
            start, ctype, csz, doff = ch
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


def node_verdict(d):
    if len(d) < 14:
        return "too short"
    fl = struct.unpack(">I", d[0:4])[0]
    bl = struct.unpack(">I", d[4:8])[0]
    kind = d[8]
    nr = struct.unpack(">H", d[10:12])[0]
    names = {0xFF: "leaf", 0x00: "index", 0x01: "header", 0x02: "map"}
    txt = "fLink=0x%08x bLink=0x%08x kind=0x%02x numRecords=%d" % (fl, bl, kind, nr)
    if kind in names:
        txt += "  (%s node)" % names[kind]
        if kind in (0xFF, 0x00) and fl < 20480 and bl < 20480:
            txt += "  -> plausible catalog node"
    else:
        txt += "  -> NOT a b-tree node (kind invalid)"
    return txt


def show(img, block, nbytes, label):
    d = img.read(block * BLOCK, nbytes)
    print("=== %s block %d (byte 0x%x)" % (label, block, block * BLOCK))
    for i in range(0, len(d), 16):
        row = d[i:i + 16]
        print("  %06x  %-47s  %s" % (i, row.hex(" "),
                                     "".join(chr(c) if 32 <= c < 127 else "." for c in row)))
    print("  %s" % node_verdict(d[:14]))
    return d


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if len(args) < 3:
        print(__doc__)
        return 2
    path, a, b = args[0], int(args[1], 0), int(args[2], 0)
    nbytes = int(args[3], 0) if len(args) > 3 else 256

    img = open_image(path)
    print("image : %s  (%d bytes logical, block %d)" % (path, img.size, img.blk))
    print()
    da = show(img, a, nbytes, "A")
    print()
    db = show(img, b, nbytes, "B")
    print()
    same = da == db
    print("A and B identical: %s" % same)
    if not same:
        diff = sum(1 for x, y in zip(da, db) if x != y)
        first = next((i for i, (x, y) in enumerate(zip(da, db)) if x != y), -1)
        print("differing bytes  : %d of %d, first at +0x%x" % (diff, min(len(da), len(db)), first))
        print()
        print("Interpretation:")
        va = node_verdict(da[:14])
        vb = node_verdict(db[:14])
        if "plausible catalog node" in va and "NOT a b-tree node" in vb:
            print("  A holds a real node and B does not.")
            print("  If the phone reads A's content at B's address, the data on the")
            print("  card is shifted or duplicated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
