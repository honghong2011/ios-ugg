#!/usr/bin/env python3
"""probe-flash.py -- where does the card stop matching the image?

Reads 64 KiB windows at chosen 4 KiB block offsets straight off the phone, using the
same path the log grabber uses and that is known to work on this phone:

    adb push script -> run it on the phone -> it dd's to /sdcard -> adb pull

Reading via "adb exec-out dd" returned empty for every probe, which showed up as a
table of phantom SHORT READs. That is a transport fault, not a card fault, and the
tool must not confuse the two.

Usage
-----
    python probe-flash.py ios16-root.simg
    python probe-flash.py ios16-root.simg --points 0.70,1.14,3.05,6.59
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
        magic, major, minor, fhsz, chsz, blk, total_blks, total_chunks, csum = \
            struct.unpack("<IHHHHIIII", self.f.read(28))
        self.fhsz, self.chsz, self.blk = fhsz, chsz, blk
        self.size = total_blks * blk
        self.chunks = []
        cur = 0
        self.f.seek(fhsz)
        for i in range(total_chunks):
            ct, res, csz, tsz = struct.unpack("<HHII", self.f.read(12))
            data_off = self.f.tell()
            dblk = tsz // blk
            self.chunks.append((cur, cur + dblk, ct, data_off))
            cur += dblk
            self.f.seek(csz - 12, 1)

    def read(self, off, n):
        out = bytearray(n)
        b0 = off // self.blk
        b1 = (off + n + self.blk - 1) // self.blk
        for s, e, ct, data_off in self.chunks:
            lo, hi = max(s, b0), min(e, b1)
            if lo >= hi or ct != 0xCAC1:
                continue
            for b in range(lo, hi):
                self.f.seek(data_off + (b - s) * self.blk)
                piece = self.f.read(self.blk)
                dst = b * self.blk - off
                a, z = max(0, dst), min(n, dst + self.blk)
                if a < z:
                    out[a:z] = piece[a - dst:z - dst]
        return bytes(out)


def open_image(path):
    with open(path, "rb") as f:
        magic = struct.unpack("<I", f.read(4))[0]
    return Sparse(path) if magic == SPARSE_MAGIC else Raw(path)


def adb(args, timeout=None, binary=False):
    try:
        return subprocess.run(["adb"] + args, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        sys.exit("adb not found on PATH (or not next to this script)")


def pull_probe(blocks, workdir):
    """Read the given 4 KiB blocks off the phone via push/run/pull."""
    here = os.path.dirname(os.path.abspath(__file__))
    local_script = os.path.join(here, "ugg-probe.sh")
    if not os.path.exists(local_script):
        sys.exit("ugg-probe.sh is missing next to this script")

    r = adb(["push", local_script, "/tmp/ugg-probe.sh"])
    remote = "/tmp/ugg-probe.sh"
    if r.returncode != 0:
        r = adb(["push", local_script, "/sdcard/ugg-probe.sh"])
        remote = "/sdcard/ugg-probe.sh"
        if r.returncode != 0:
            sys.exit("could not push the probe script to the phone")

    outdir = "/sdcard/uggprobe"
    cmd = "sh %s %s %s" % (remote, outdir, " ".join(str(b) for b in blocks))
    run = adb(["shell", cmd], timeout=600)
    txt = run.stdout.decode(errors="replace")
    print(txt.strip())
    if "NO_PARTITION" in txt:
        sys.exit("the phone cannot see the userdata block device")
    if "DONE" not in txt:
        sys.exit("the phone-side probe did not finish")

    got = {}
    for b in blocks:
        dest = os.path.join(workdir, "b%d.bin" % b)
        if os.path.exists(dest):
            os.remove(dest)
        rr = adb(["pull", "%s/b%d.bin" % (outdir, b), dest])
        if rr.returncode != 0 or not os.path.exists(dest):
            got[b] = None
            continue
        with open(dest, "rb") as fh:
            got[b] = fh.read()
    return got


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    points = [0.70, 1.14, 1.90, 3.05, 4.34, 5.34, 6.59, 8.00, 10.00]
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
        print("no device listed by adb:")
        print(r.stdout.decode(errors="replace").strip())
        return 2
    for line in r.stdout.decode(errors="replace").strip().splitlines()[1:]:
        if line.strip():
            print("device: %s" % line.strip())

    img = open_image(img_path)
    print("image : %s (%.2f GiB expanded)" % (img_path, img.size / 2 ** 30))

    blocks = [int(g * 2 ** 30) // BLOCK for g in points]
    workdir = os.path.abspath(".")
    got = pull_probe(blocks, workdir)

    n = 65536
    print()
    print("  %-10s %-12s %s" % ("at GiB", "block", "result"))
    print("  " + "-" * 52)
    last_ok = None
    for g, b in zip(points, blocks):
        off = b * BLOCK
        want = img.read(off, n)
        card = got.get(b)
        if card is None:
            res = "READ FAILED"
        elif len(card) < len(want):
            res = "read %d of %d bytes" % (len(card), len(want))
        elif card == want:
            res = "MATCH"
            last_ok = g
        elif card == b"\x00" * len(card):
            res = "ALL ZERO on card"
        else:
            diff = sum(1 for x, y in zip(want, card) if x != y)
            res = "DIFFERS (%d/%d bytes)" % (diff, len(want))
        print("  %-10.4f %-12d %s" % (g, b, res))

    print()
    print("MATCH = the card holds the image there. ALL ZERO = never written.")
    print("The last MATCH before the first ALL ZERO is the end of what got flashed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
