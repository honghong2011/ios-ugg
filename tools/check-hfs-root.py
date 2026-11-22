#!/usr/bin/env python3
"""
check-hfs-root.py -- validate the iOS root image's B-trees without mounting it.

Why this exists
---------------
The ugg boot reaches /sbin/launchd and then dies with errno 5. The kernel log
shows:

    hfs_swap_BTNode: invalid forward link (0x6a13d46a >= 0x00005000)
    hfs: node=19174 fileID=4 volume=iOSRoot device=root_device

Node 19174 is in the CATALOG b-tree, and every one of those nodes is near its
end. hfs_swap_BTNode() rejects a node when its descriptor's forward link is not
a valid node index (hfs-src/core/hfs_endian.c:124), so the check below is the
same one the kernel makes: read each node, look at the first 4 bytes, compare
against totalNodes.

Nothing is mounted and nothing is written: this only reads.

Usage
-----
    python check-hfs-root.py ios16-root.simg          # sparse image, read in place
    python check-hfs-root.py ios16-root.img           # raw image
    python check-hfs-root.py --all ios16-root.simg    # also walk every node

Both the Android sparse image (.simg) and the raw .img are accepted; the sparse
one is decompressed on demand so the 16 GiB image never has to fit on disk.

Exit status: 0 = every b-tree node looked sane, 1 = problems were found.
"""

import os
import struct
import sys

K = 1024
M = 1024 * 1024

# BTNodeDescriptor.kind, from hfs_format.h:735-741. kBTLeafNode is 0xFF, not
# 4 -- getting this wrong makes every leaf node look "unknown" and every index
# node (kind 0) look like an uninitialised free node.
KBT_LEAF = 0xFF
KBT_INDEX = 0x00
KBT_HEADER = 0x01
KBT_MAP = 0x02
KIND_NAMES = {KBT_LEAF: "leaf", KBT_INDEX: "index",
              KBT_HEADER: "header", KBT_MAP: "map"}


# --------------------------------------------------------------------------
# Sparse image reader (Android simg), random access, no disk expansion
# --------------------------------------------------------------------------
SPARSE_MAGIC = 0xED26FF3A
CHUNK_RAW = 0xCAC1
CHUNK_FILL = 0xCAC2
CHUNK_DONT_CARE = 0xCAC3
CHUNK_CRC32 = 0xCAC4


class RawImage:
    def __init__(self, path):
        self.f = open(path, "rb")
        self.f.seek(0, os.SEEK_END)
        self.size = self.f.tell()
        self.kind = "raw"

    def read(self, off, n):
        if off >= self.size:
            return b""
        self.f.seek(off)
        return self.f.read(min(n, self.size - off))


class SparseImage:
    """Android sparse image with random access. Consecutive chunks are merged
    so reading a 4 GiB b-tree does not cost one seek per 4 KiB block."""

    def __init__(self, path):
        self.f = open(path, "rb")
        hdr = self.f.read(28)
        (magic, major, minor, fhsz, chsz, blk, total_blks, total_chunks,
         checksum) = struct.unpack("<IHHHHIIII", hdr)
        if magic != SPARSE_MAGIC:
            raise ValueError("not a sparse image")
        if major != 1:
            raise ValueError("unsupported sparse major version %d" % major)
        self.blk = blk
        self.total_blks = total_blks
        self.size = total_blks * blk
        self.kind = "sparse"

        # Walk the chunk headers. Each entry is (out_block, kind, length, data_off).
        self.chunks = []
        pos = fhsz
        out = 0
        for _ in range(total_chunks):
            self.f.seek(pos)
            ctype, _r, csz, tsz = struct.unpack("<HHII", self.f.read(12))
            data_off = pos + chsz
            self.chunks.append((out, ctype, csz, data_off))
            out += csz
            pos = data_off + (tsz - chsz)
        self.f.seek(0, os.SEEK_END)
        self.file_size = self.f.tell()

    def _chunk_at(self, blkno):
        lo, hi = 0, len(self.chunks) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            start, ctype, csz, doff = self.chunks[mid]
            if blkno < start:
                hi = mid - 1
            elif blkno >= start + csz:
                lo = mid + 1
            else:
                return self.chunks[mid]
        return None

    def read(self, off, n):
        if off >= self.size:
            return b""
        n = min(n, self.size - off)
        out = bytearray()
        while n > 0:
            blkno = off // self.blk
            inblk = off % self.blk
            ch = self._chunk_at(blkno)
            if ch is None:
                out += b"\x00" * n
                break
            start, ctype, csz, doff = ch
            room = (start + csz) * self.blk - off
            take = min(n, room)
            if ctype == CHUNK_RAW:
                self.f.seek(doff + (blkno - start) * self.blk + inblk)
                out += self.f.read(take)
            elif ctype == CHUNK_FILL:
                self.f.seek(doff)
                fill = self.f.read(4)
                out += (fill * ((take + 3) // 4))[:take]
            elif ctype == CHUNK_DONT_CARE:
                out += b"\x00" * take
            else:
                raise ValueError("chunk type 0x%04x has no data at %d"
                                 % (ctype, blkno))
            off += take
            n -= take
        return bytes(out)


def open_image(path):
    with open(path, "rb") as f:
        magic = struct.unpack("<I", f.read(4))[0]
    return SparseImage(path) if magic == SPARSE_MAGIC else RawImage(path)


# --------------------------------------------------------------------------
# HFS+ structures
# --------------------------------------------------------------------------
HFSPLUS_VOLHEADER_OFF = 1024
CATALOG_FORK_OFF = 272        # inside the volume header
EXTENTS_FORK_OFF = 192
ATTRIBUTES_FORK_OFF = 352


def be16(b, o):
    return struct.unpack_from(">H", b, o)[0]


def be32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def be64(b, o):
    return struct.unpack_from(">Q", b, o)[0]


class Fork:
    def __init__(self, vh, off, name):
        self.name = name
        self.logical = be64(vh, off)
        self.total_blocks = be32(vh, off + 12)
        self.extents = []
        for i in range(8):
            start = be32(vh, off + 16 + i * 8)
            count = be32(vh, off + 20 + i * 8)
            if count:
                self.extents.append((start, count))


class BTree:
    """A file fork seen as a b-tree: maps node index -> image byte offset."""

    def __init__(self, img, fork, blocksize, label):
        self.img = img
        self.fork = fork
        self.bs = blocksize
        self.label = label
        self.node_size = 0
        self.total_nodes = 0
        self.root_node = 0
        self.first_leaf = 0
        self.last_leaf = 0
        self.tree_depth = 1

    def _read_file(self, foff, n):
        """Read n bytes of this fork starting at logical byte foff."""
        out = bytearray()
        covered = 0
        for start, count in self.fork.extents:
            ext_bytes = count * self.bs
            if foff < covered + ext_bytes and n > 0:
                inner = max(0, foff - covered)
                take = min(n, ext_bytes - inner)
                if take > 0:
                    out += self.img.read(start * self.bs + inner, take)
                    n -= take
                    foff += take
            covered += ext_bytes
            if n <= 0:
                break
        if n > 0:
            out += b"\x00" * n
        return bytes(out)

    def load_header(self):
        node0 = self._read_file(0, 512)
        if len(node0) < 14 + 106:
            raise ValueError("%s: short header node" % self.label)
        fLink, bLink = be32(node0, 0), be32(node0, 4)
        kind = node0[8]
        self.node_size = be16(node0, 14 + 18)
        self.tree_depth = be16(node0, 14 + 0)
        self.root_node = be32(node0, 14 + 2)
        self.first_leaf = be32(node0, 14 + 10)
        self.last_leaf = be32(node0, 14 + 14)
        self.total_nodes = be32(node0, 14 + 22)
        return dict(fLink=fLink, bLink=bLink, kind=kind)

    def node_offset(self, idx):
        return idx * self.node_size

    def read_node(self, idx):
        return self._read_file(self.node_offset(idx), self.node_size)

    def covered_bytes(self):
        return sum(c for _s, c in self.fork.extents) * self.bs


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------
def check_btree(img, fork, blocksize, label, walk_all=True):
    problems = []
    bt = BTree(img, fork, blocksize, label)
    hdr = bt.load_header()
    if bt.total_nodes == 0 and not bt.node_size:
        print("  %s: empty (logical size %d)" % (label, fork.logical))
        return problems

    print("  %s" % label)
    print("    logical size : %d bytes (%.2f MiB)"
          % (fork.logical, fork.logical / M))
    print("    extents      : %d  -> %d blocks of %d bytes (%.2f MiB)"
          % (len(fork.extents), fork.total_blocks, blocksize,
             fork.total_blocks * blocksize / M))
    for i, (start, count) in enumerate(fork.extents):
        print("      ext%d      : block %-8d count %-8d byte 0x%x .. 0x%x"
              % (i, start, count, start * blocksize,
                 (start + count) * blocksize))
    print("    node size    : %d" % bt.node_size)
    print("    total nodes  : %d (0x%x)" % (bt.total_nodes, bt.total_nodes))
    print("    root/leaf    : %d / %d..%d"
          % (bt.root_node, bt.first_leaf, bt.last_leaf))

    if fork.total_blocks > sum(c for _s, c in fork.extents):
        problems.append("%s: extents cover %d of %d blocks (overflow b-tree "
                        "needed; only the first 8 extents were followed)"
                        % (label, sum(c for _s, c in fork.extents),
                           fork.total_blocks))

    need = bt.total_nodes * bt.node_size
    if bt.covered_bytes() < need:
        problems.append("%s: fork holds %d bytes but %d nodes x %d = %d "
                        "bytes are addressed"
                        % (label, bt.covered_bytes(), bt.total_nodes,
                           bt.node_size, need))

    if not bt.node_size or bt.node_size % 512:
        problems.append("%s: implausible node size %d" % (label, bt.node_size))
        return problems

    # Header node itself: links may legally point at itself.
    print("    header node  : fLink=%d bLink=%d kind=%d"
          % (hdr["fLink"], hdr["bLink"], hdr["kind"]))
    if hdr["kind"] != KBT_HEADER:
        problems.append("%s: header node kind is %d, expected %d (kBTHeaderNode)"
                        % (label, hdr["kind"], KBT_HEADER))

    if not walk_all:
        return problems

    bad = []
    kinds = {}
    for idx in range(bt.total_nodes):
        node = bt.read_node(idx)
        if len(node) < 14:
            bad.append((idx, "short read (%d bytes)" % len(node)))
            continue
        flink = be32(node, 0)
        blink = be32(node, 4)
        kind = node[8]
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind not in KIND_NAMES:
            bad.append((idx, "unknown node kind %d" % kind))
            continue
        if flink >= bt.total_nodes:
            bad.append((idx, "fLink 0x%08x >= totalNodes 0x%x"
                        % (flink, bt.total_nodes)))
        elif idx != 0 and flink == idx:
            bad.append((idx, "fLink points at itself"))
        if blink >= bt.total_nodes:
            bad.append((idx, "bLink 0x%08x >= totalNodes 0x%x"
                        % (blink, bt.total_nodes)))
        elif idx != 0 and blink == idx:
            bad.append((idx, "bLink points at itself"))

    print("    node kinds   : %s"
          % ", ".join("%s=%d" % (KIND_NAMES.get(k, "kind%d" % k), v)
                      for k, v in sorted(kinds.items())))
    if bad:
        print("    BAD NODES    : %d" % len(bad))
        for idx, why in bad[:25]:
            print("      node %-6d %s" % (idx, why))
        if len(bad) > 25:
            print("      ... and %d more" % (len(bad) - 25))
        problems.append("%s: %d nodes have an invalid descriptor"
                        % (label, len(bad)))
    else:
        print("    all %d nodes have a valid descriptor" % bt.total_nodes)
    return problems


def dump_block(img, blocksize, block, count, blkargs):
    """Print raw bytes of the image at a given allocation block."""
    off = block * blocksize
    data = img.read(off, count)
    print("image block %d = byte offset %d (0x%x), %d bytes" % (block, off, off, len(data)))
    for i in range(0, len(data), 16):
        row = data[i:i + 16]
        hexs = " ".join("%02x" % c for c in row)
        text = "".join(chr(c) if 32 <= c < 127 else "." for c in row)
        print("  %08x  %-47s  %s" % (i, hexs, text))
    if len(data) >= 10:
        f1 = be32(data, 0)
        f2 = be32(data, 4)
        kind = data[8]
        print()
        print("  as a b-tree node descriptor: fLink=0x%08x bLink=0x%08x kind=0x%02x"
              % (f1, f2, kind))
        if kind in (0, 1, 2, 0xFF):
            print("  -> this WOULD validate as a node")
        else:
            print("  -> this would NOT validate; kind %d is not a b-tree kind" % kind)
            print("  -> first 8 bytes as text: %r" % data[:8].decode("latin-1"))


def main():
    blkargs = None
    argv = sys.argv[1:]
    if "--dump" in argv:
        i = argv.index("--dump")
        rest = argv[i + 1:]
        nums = []
        consumed = 0
        for a in rest:
            try:
                nums.append(int(a, 0))
                consumed += 1
            except ValueError:
                break
            if len(nums) == 2:
                break
        if not nums:
            print("--dump needs a block number and an optional byte count")
            return 2
        blkargs = (nums[0], nums[1] if len(nums) > 1 else 256)
        del argv[i:i + 1 + consumed]
    args = [a for a in argv if not a.startswith("-")]
    walk_all = "--all" in sys.argv
    if walk_all:
        args = [a for a in args if a != "--all"]
    if len(args) != 1:
        print(__doc__)
        return 2
    path = args[0]

    print("=" * 72)
    print("check-hfs-root.py -- %s" % path)
    print("=" * 72)
    if not os.path.exists(path):
        print("no such file: %s" % path)
        return 2
    if blkargs is not None and not os.path.exists(path):
        print("no such file: %s" % path)
        return 2

    img = open_image(path)
    print("image    : %s, %d bytes logical (%.2f GiB)"
          % (img.kind, img.size, img.size / 2**30))

    vh = img.read(HFSPLUS_VOLHEADER_OFF, 512)
    if len(vh) < 512:
        print("volume header unreadable")
        return 1
    sig = vh[0:2]
    print("signature: %r" % sig)
    if sig not in (b"H+", b"HX"):
        print("NOT an HFS+ volume (expected 'H+' or 'HX' at offset 1024)")
        return 1
    version = be16(vh, 2)
    blocksize = be32(vh, 40)
    totalblocks = be32(vh, 44)
    freeblocks = be32(vh, 48)
    filecount = be32(vh, 32)
    foldercount = be32(vh, 36)

    print("version  : %d (%s)"
          % (version, "HFSX, case sensitive" if sig == b"HX" else "HFS+"))
    print("block size    : %d" % blocksize)
    print("total blocks  : %d (%.2f GiB)"
          % (totalblocks, totalblocks * blocksize / 2**30))
    print("free blocks   : %d (%.2f GiB)"
          % (freeblocks, freeblocks * blocksize / 2**30))
    print("files/folders : %d / %d" % (filecount, foldercount))

    if blocksize not in (512, 1024, 2048, 4096, 8192, 16384, 32768):
        print("implausible block size %d -- the volume header is damaged"
              % blocksize)
        return 1

    # Cross-check: does the allocation-block fire the extents point at hold
    # b-tree nodes? A node descriptor is fLink/bLink/kind/numRecords/reserved,
    # so kind must be a b-tree kind and the first two words must be small.
    print()
    print("What the extents actually point at")
    for off, label in ((CATALOG_FORK_OFF, "catalog"),):
        fork = Fork(vh, off, label)
        for i, (start, count) in enumerate(fork.extents):
            probe = img.read(start * blocksize, 32)
            if len(probe) < 32:
                print("  %s ext%d: unreadable" % (label, i))
                continue
            fl = be32(probe, 0)
            bl = be32(probe, 4)
            kind = probe[8]
            printable = all(32 <= c < 127 for c in probe[:8])
            verdict = "looks like a b-tree node" if (kind in (0, 1, 2, 0xFF)) else "does NOT look like a node"
            print("  %s ext%d block %d: fLink=0x%08x bLink=0x%08x kind=0x%02x  %s"
                  % (label, i, start, fl, bl, kind, verdict))
            if printable:
                print("      first 8 bytes are text: %r" % probe[:8].decode("latin-1"))

    if blkargs is not None:
        print()
        dump_block(img, blocksize, blkargs[0], blkargs[1], blkargs)
        return 0

    print()
    print("B-trees")
    problems = []
    for off, label in ((CATALOG_FORK_OFF, "catalog"),
                       (EXTENTS_FORK_OFF, "extents overflow"),
                       (ATTRIBUTES_FORK_OFF, "attributes")):
        fork = Fork(vh, off, label)
        if fork.logical == 0:
            print("  %s: empty" % label)
            continue
        try:
            problems += check_btree(img, fork, blocksize, label, walk_all)
        except Exception as e:            # keep going: one bad tree is enough
            print("  %s: could not be parsed: %s" % (label, e))
            problems.append("%s: parse error: %s" % (label, e))

    print()
    print("=" * 72)
    if problems:
        print("RESULT: %d problem(s)" % len(problems))
        for p in problems:
            print("  - %s" % p)
        print()
        print("If 'catalog' reports bad nodes, the root image itself is damaged")
        print("and it has to be rebuilt -- no kernel change can fix it.")
        return 1

    print("RESULT: no b-tree descriptor problems found.")
    print()
    print("If the phone still fails to load /sbin/launchd with errno 5 after")
    print("this passes, the damage is not in the b-tree links: re-run with")
    print("--all and look at which file the failing node belongs to, and check")
    print("the eMMC read path instead of the image.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
