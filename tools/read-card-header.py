#!/usr/bin/env python3
"""read-card-header.py -- read the HFS+ volume header off the phone and decode the
catalogue extents. Read-only.

This is the decisive measurement for the flash question. The volume header lives at
byte 1024 of the partition, so it is the first thing written and the first thing to
check. If its extents match the image the card holds this image; if they match an
older build, the card was never overwritten; if it is zero, nothing was written at all.

The phone side uses push/run/pull because adb exec-out returned empty here.
"""
import os, struct, subprocess, sys

DEV = "/dev/block/by-name/userdata"
BLOCK = 4096


def adb(args, timeout=None):
    try:
        return subprocess.run(["adb"] + args, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        sys.exit("adb not found on PATH")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(here, "ugg-probe.sh")
    if not os.path.exists(script):
        sys.exit("ugg-probe.sh missing next to this script")

    r = adb(["devices"])
    if b"device" not in r.stdout:
        print("no device:"); print(r.stdout.decode(errors="replace"))
        return 2
    for line in r.stdout.decode(errors="replace").strip().splitlines()[1:]:
        if line.strip():
            print("device: %s" % line.strip())

    p = adb(["push", script, "/tmp/ugg-probe.sh"])
    remote = "/tmp/ugg-probe.sh"
    if p.returncode != 0:
        p = adb(["push", script, "/sdcard/ugg-probe.sh"])
        remote = "/sdcard/ugg-probe.sh"
        if p.returncode != 0:
            sys.exit("could not push the probe script")

    # Block 0 holds the volume header at offset 1024 within it.
    run = adb(["shell", "sh %s /sdcard/uggprobe 0" % remote], timeout=300)
    print(run.stdout.decode(errors="replace").strip())

    local = os.path.abspath("hdr_block0.bin")
    if os.path.exists(local):
        os.remove(local)
    g = adb(["pull", "/sdcard/uggprobe/b0.bin", local])
    if g.returncode != 0 or not os.path.exists(local):
        sys.exit("could not pull block 0")
    data = open(local, "rb").read()
    print("block 0: %d bytes" % len(data))
    print("first 32 bytes: %s" % data[:32].hex(" "))

    if len(data) < 1536:
        print("block 0 too short to contain a volume header")
        return 1
    vh = data[1024:1536]
    print("volume header: %s" % vh[:16].hex(" "))
    sig = vh[0:2]
    if sig not in (b"H+", b"HX"):
        print("NOT an HFS+ volume header (signature %r)" % sig)
        if data == b"\x00" * len(data):
            print("  the whole block is ZERO -> nothing was written at the start")
        return 1
    print("signature      : %r  (%s)" % (sig, "HFSX" if sig == b"HX" else "HFS+"))
    bs = struct.unpack(">I", vh[40:44])[0]
    total = struct.unpack(">I", vh[44:48])[0]
    free = struct.unpack(">I", vh[48:52])[0]
    print("block size     : %d" % bs)
    print("total blocks   : %d (%.2f GiB)" % (total, total * bs / 2**30))
    print("free blocks    : %d (%.2f GiB)" % (free, free * bs / 2**30))

    # Catalogue file: fork data at offset 272 of the volume header.
    # HFSPlusForkData at 272: logicalSize(u64), clumpSize(u32),
    # totalBlocks(u32), then 8 extents of {startBlock u32, blockCount u32} at +16.
    logical = struct.unpack(">Q", vh[272:280])[0]
    totalb = struct.unpack(">I", vh[284:288])[0]
    ext = []
    for i in range(8):
        start, count = struct.unpack(">II", vh[288 + i * 8:288 + i * 8 + 8])
        if count:
            ext.append((start, count))
    print("catalog size   : %d bytes (%.1f MiB), %d blocks" % (logical, logical / 2**20, totalb))
    print("catalog extents: %s" % "  ".join("%d+%d" % e for e in ext))
    return 0


if __name__ == "__main__":
    sys.exit(main())
