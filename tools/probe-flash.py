#!/usr/bin/env python3
"""probe-flash.py -- walk a list of offsets and report, for each, whether the card
still holds the image's bytes. Read-only, adb only.

Why: verify-card --at-gib proved 6.60 GiB is all zeros on the card while the image
has real catalogue data there, and 0.70 GiB reads fine. The next fact needed is
WHERE the good region ends, because that is the end of what actually got written.

    python probe-flash.py ios16-root.simg
    python probe-flash.py ios16-root.simg --points 0.70,1.14,3.05,6.60
"""
import os, struct, subprocess, sys

BLOCK = 4096
DEV = "/dev/block/by-name/userdata"
SPARSE_MAGIC = 0xED26FF3A


class Raw:
    def __init__(self, path):
        self.f = open(path, "rb")
        self.size = os.path.getsize(path)

    def read(self, off, n):
        self.f.seek(off)
        return self.f.read(n)


class Sparse:
    def __init__(self, path):
        self.f = open(path, "rb")
        hdr = self.f.read(28)
        magic, major, minor, fhsz, chsz, blk, total_blks, total_chunks, csum = \
            struct.unpack("<IHHHHIIII", hdr)
        self.magic = magic
        self.fhsz, self.chsz, self.blk = fhsz, chsz, blk
        self.total_blks = total_blks
        self.size = total_blks * blk
        self.chunks = []
        f = self.f
        f.seek(fhsz)
        cur = 0
        for i in range(total_chunks):
            ct, res, csz, tsz = struct.unpack("<HHII", f.read(12))
            data_off = f.tell()
            dblk = tsz // blk
            self.chunks.append((cur, cur + dblk, ct, data_off, tsz))
            cur += dblk
            f.seek(csz - 12, 1)

    def read(self, off, n):
        out = bytearray(n)
        want0 = off // self.blk
        want1 = (off + n + self.blk - 1) // self.blk
        for s, e, ct, data_off, tsz in self.chunks:
            lo, hi = max(s, want0), min(e, want1)
            if lo >= hi:
                continue
            if ct != 0xCAC1:      # FILL / DONT_CARE read as zeros
                continue
            for b in range(lo, hi):
                src = data_off + (b - s) * self.blk
                self.f.seek(src)
                chunk = self.f.read(self.blk)
                dst = b * self.blk - off
                a, z = max(0, dst), min(n, dst + self.blk)
                if a < z:
                    out[a:z] = chunk[a - dst:z - dst]
        return bytes(out)


def open_image(path):
    with open(path, "rb") as f:
        magic = struct.unpack("<I", f.read(4))[0]
    return Sparse(path) if magic == SPARSE_MAGIC else Raw(path)


def adb(args, timeout=None):
    try:
        return subprocess.run(["adb"] + args, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        sys.exit("adb not found on PATH")


def read_card(off, length):
    skip = off // BLOCK
    count = (length + BLOCK - 1) // BLOCK
    cmd = "dd if=%s bs=%d skip=%d count=%d 2>/dev/null" % (DEV, BLOCK, skip, count)
    return adb(["exec-out", cmd]).stdout


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    points = [0.70, 1.14, 1.90, 3.05, 4.34, 5.34, 6.59, 8.0, 10.0]
    for i, a in enumerate(sys.argv):
        if a == "--points" and i + 1 < len(sys.argv):
            points = [float(x) for x in sys.argv[i + 1].split(",")]
    if not args:
        print(__doc__)
        return 2
    img_path = args[0]
    if not os.path.exists(img_path):
        print("no such image: %s" % img_path)
        return 2

    r = adb(["devices"])
    if b"device" not in r.stdout:
        print("no device (needs TWRP or booted Android with adb)")
        return 2

    img = open_image(img_path)
    print("image : %s (%.2f GiB expanded)" % (img_path, img.size / 2 ** 30))
    print()
    print("  %-10s %-14s %s" % ("at", "block", "result"))
    print("  " + "-" * 56)
    last = None
    for g in points:
        off = int(g * 2 ** 30) // BLOCK * BLOCK
        n = 65536
        want = img.read(off, n)
        got = read_card(off, n)
        if len(got) < len(want):
            res = "SHORT READ"
        elif got == want:
            res = "MATCH"
        elif got == b"\x00" * len(got):
            res = "ALL ZERO on card"
        else:
            # how much of the window differs
            diff = sum(1 for a, b in zip(want, got) if a != b)
            res = "DIFFERS (%d of %d bytes)" % (diff, len(want))
        print("  %-10.4f %-14d %s" % (g, off // BLOCK, res))
        last = res
    print()
    print("Reading: MATCH means that part of the card holds the image. ALL ZERO means")
    print("it was never written. The boundary between them is where the flash stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
