#!/usr/bin/env python3
"""check-nodes.py -- read the exact blocks the kernel complained about, off the card,
and report what HFS+ thinks they are. Read-only.

Why this and not probe-flash: probing at whole GiB offsets lands wherever it lands,
which for a filesystem is mostly free space -- so "DIFFERS" there says nothing. The
kernel names specific catalogue nodes; each maps to an exact physical block through the
extents that the card own volume header reports. Those blocks are the only ones whose
contents matter.

    python check-nodes.py            # the nodes from the last boot log
    python check-nodes.py 19183 19203
"""
import os, struct, subprocess, sys

DEV = "/dev/block/by-name/userdata"
BLOCK = 4096
NODE = 8192

# From the card own volume header (read-card-header.py):
#   183682+16384  211840+8192  1138210+8192  1729287+8192
EXTS = [(183682, 16384), (211840, 8192), (1138210, 8192), (1729287, 8192)]


def node_to_block(n):
    first = 0
    for start, count in EXTS:
        nodes = count * BLOCK // NODE
        if n < first + nodes:
            return start + (n - first) * 2
        first += nodes
    return None


def adb(args, timeout=None):
    try:
        return subprocess.run(["adb"] + args, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        sys.exit("adb not found on PATH")


def main():
    nodes = [int(a) for a in sys.argv[1:] if a.isdigit()] or [19183, 19203, 19477, 19524]
    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(here, "ugg-probe.sh")
    if not os.path.exists(script):
        sys.exit("ugg-probe.sh missing next to this script")

    r = adb(["devices"])
    if b"device" not in r.stdout:
        print("no device:"); print(r.stdout.decode(errors="replace"))
        return 2

    p = adb(["push", script, "/tmp/ugg-probe.sh"])
    remote = "/tmp/ugg-probe.sh"
    if p.returncode != 0:
        p = adb(["push", script, "/sdcard/ugg-probe.sh"])
        remote = "/sdcard/ugg-probe.sh"
        if p.returncode != 0:
            sys.exit("could not push probe script")

    blocks = []
    for n in nodes:
        b = node_to_block(n)
        if b is None:
            print("node %d is outside the catalogue" % n)
            continue
        blocks.append((n, b))

    cmd = "sh %s /sdcard/uggnodes %s" % (remote, " ".join(str(b) for _, b in blocks))
    run = adb(["shell", cmd], timeout=300)
    print(run.stdout.decode(errors="replace").strip())

    print()
    print("  %-8s %-10s %-6s %-8s %s" % ("node", "block", "kind", "numRec", "verdict"))
    print("  " + "-" * 62)
    ok = 0
    for n, b in blocks:
        local = os.path.abspath("n%d.bin" % b)
        if os.path.exists(local):
            os.remove(local)
        g = adb(["pull", "/sdcard/uggnodes/b%d.bin" % b, local])
        if g.returncode != 0 or not os.path.exists(local):
            print("  %-8d %-10d read failed" % (n, b))
            continue
        data = open(local, "rb").read()
        if len(data) < 16:
            print("  %-8d %-10d short (%d bytes)" % (n, b, len(data)))
            continue
        fwd = struct.unpack(">I", data[0:4])[0]
        blk = struct.unpack(">I", data[4:8])[0]
        kind = data[8]
        nrec = struct.unpack(">H", data[10:12])[0]
        if kind in (0x00, 0x01, 0x02, 0xFF):
            verdict = "valid node (fLink %d)" % fwd if fwd < 20480 else "kind ok, fLink BAD %d" % fwd
            if fwd < 20480:
                ok += 1
        elif data == b"\x00" * len(data):
            verdict = "ALL ZERO"
        else:
            verdict = "not a node (first 4 bytes 0x%08x)" % fwd
        print("  %-8d %-10d 0x%02x   %-8d %s" % (n, b, kind, nrec, verdict))

    print()
    print("%d of %d node blocks are valid b-tree nodes." % (ok, len(blocks)))
    if ok == len(blocks):
        print("=> The card holds the image correctly. Any read error is the driver, not the flash.")
    else:
        print("=> Some node blocks do not hold nodes. The flash did not land as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
