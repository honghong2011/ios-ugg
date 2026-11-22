#!/usr/bin/env python3
"""
write-image.py -- write the iOS root image into userdata from TWRP.

Why not the obvious ways:
  adb exec-in dd ... < image   returned success and wrote nothing on this
                               machine (no output from the script at all)
  adb push /sdcard/image       needs 16 GiB free and /sdcard lives ON userdata,
                               which is exactly what we are overwriting

So the image is cut into chunks on the PC, each chunk is pushed to /tmp (which
is RAM in TWRP), dd'd into userdata at its exact offset, then deleted. Only
well-tested adb verbs are used: push, shell, rm.

Usage
-----
    python write-image.py ios16-root.img
    python write-image.py ios16-root.img --chunk-mb 128
    python write-image.py ios16-root.img --start-mb 4096     # resume

Verifies the four catalog nodes at the end.
"""

import os
import subprocess
import sys
import tempfile
import time

DEV = "/dev/block/by-name/userdata"
TMP = "/tmp/uggchunk.img"

# node block -> expected first 8 bytes (from the image itself)
CHECKS = [
    (1734927, "00 00 4a f9 00 00 00 05"),
    (1734965, "00 00 01 fa 00 00 4a e6"),
    (1735503, "00 00 00 00 00 00 4b 9a"),
    (1735607, "00 00 00 02 00 00 4c 37"),
]


def adb(args, stdin=None, timeout=None):
    return subprocess.run(["adb"] + args, stdin=stdin,
                          capture_output=True, text=True, timeout=timeout)


def find_adb():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "adb.exe"),
                 os.path.join(here, "..", "adb", "adb.exe"),
                 os.path.join(here, "adb")):
        if os.path.exists(cand):
            return cand
    return "adb"


def read_nodes():
    out = []
    for blk, _exp in CHECKS:
        cmd = ("dd if=%s bs=4096 skip=%d count=1 2>/dev/null | "
               "dd bs=1 count=8 2>/dev/null | od -An -tx1 | tr -d '\\n'"
               % (DEV, blk))
        r = adb(["shell", cmd])
        out.append((blk, " ".join(r.stdout.split())))
    return out


def main():
    images = [a for a in sys.argv[1:] if not a.startswith("--")]
    chunk_mb = 256
    start_mb = 0
    for i, a in enumerate(sys.argv):
        if a == "--chunk-mb" and i + 1 < len(sys.argv):
            chunk_mb = int(sys.argv[i + 1])
        if a == "--start-mb" and i + 1 < len(sys.argv):
            start_mb = int(sys.argv[i + 1])

    if not images:
        print(__doc__)
        return 2
    img = images[0]
    if not os.path.exists(img):
        print("no such file: %s" % img)
        return 2

    global adb
    real_adb = find_adb()
    adb = lambda args, stdin=None, timeout=None: subprocess.run(
        [real_adb] + args, stdin=stdin, capture_output=True, text=True,
        timeout=timeout)

    size = os.path.getsize(img)
    total_mb = (size + (1 << 20) - 1) >> 20
    print("image : %s" % img)
    print("size  : %d bytes (%d MiB)" % (size, total_mb))
    print("chunk : %d MiB" % chunk_mb)
    print()

    r = adb(["devices"])
    if "recovery" not in r.stdout and "device" not in r.stdout:
        print("no device in TWRP")
        print(r.stdout)
        return 2
    print("device ok")

    # how much room does /tmp have?
    r = adb(["shell", "df -m /tmp 2>/dev/null | tail -1"])
    print("/tmp  : %s" % r.stdout.strip())

    # probe dd once: TWRP's dd wants a byte count, not a "1M" suffix
    probe = adb(["shell",
                 "dd --help 2>&1 | head -3; echo ---; "
                 "printf x | dd of=/dev/null bs=1048576 2>&1 | tail -1"])
    print("dd    : %s" % " / ".join(probe.stdout.split(chr(10))[:4]))

    started = time.time()
    off_mb = start_mb
    while off_mb < total_mb:
        this = min(chunk_mb, total_mb - off_mb)
        begin = off_mb << 20
        end = min(size, begin + (this << 20))

        with open(img, "rb") as f:
            f.seek(begin)
            data = f.read(end - begin)

        tmp_local = os.path.join(tempfile.gettempdir(), "uggchunk.img")
        with open(tmp_local, "wb") as f:
            f.write(data)

        p = adb(["push", tmp_local, TMP])
        if p.returncode != 0:
            print("push failed at %d MiB: %s" % (off_mb, p.stderr.strip()))
            return 1

        # bs is given in bytes: TWRP's dd rejects the "1M" suffix.
        seek = off_mb * (1 << 20)
        r = adb(["shell",
                 "dd if=%s of=%s bs=1048576 seek=%d conv=notrunc 2>&1 | tail -2"
                 % (TMP, DEV, seek)])
        adb(["shell", "rm -f %s" % TMP])

        line = r.stdout.strip()
        if "illegal" in line.lower() or "invalid" in line.lower():
            print()
            print("dd rejected the command, stopping:")
            print("  %s" % line)
            print()
            print("Send me that line and I will adapt the dd arguments.")
            return 1
        pct = 100.0 * (off_mb + this) / total_mb
        elapsed = time.time() - started
        print("  %5.1f%%  %6d/%d MiB  %s" % (pct, off_mb + this, total_mb, line),
              flush=True)
        off_mb += this

    print()
    print("sync...")
    adb(["shell", "sync"])
    time.sleep(2)

    print()
    print("=== verifying the four catalog nodes ===")
    got = read_nodes()
    ok = True
    for (blk, val), (_b, exp) in zip(got, CHECKS):
        good = val.replace(" ", "") == exp.replace(" ", "")
        ok = ok and good
        print("  block %-8d : %-24s %s" % (blk, val, "OK" if good else
                                          "expected %s" % exp))
    print()
    if ok:
        print("card data is correct -- boot the kernel image next")
        return 0
    print("card data still differs from the image")
    return 1


if __name__ == "__main__":
    sys.exit(main())
