"""exact-match.py -- for each probe point, decide in plain terms what the card holds.

Compares a 4 KiB window read from the card against the same window in the image,
and reports: identical / zero / or "the image content appears to be here", which is
the test that distinguishes "never written" from "written somewhere else".

It searches the image for the card window within a small radius, so a whole-block
offset shows up as a number instead of a percentage.
"""
import os, struct, sys, importlib.util


def load_pf():
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("pf", os.path.join(here, "probe-flash.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    if len(sys.argv) < 3:
        print("usage: exact-match.py IMAGE CARDDUMPDIR [blocks...]")
        return 2
    image, dumpdir = sys.argv[1], sys.argv[2]
    pf = load_pf()
    img = pf.open_image(image)
    if not os.path.isdir(dumpdir):
        print("no such directory: %s" % dumpdir)
        return 2

    files = sorted(f for f in os.listdir(dumpdir) if f.startswith("b") and f.endswith(".bin"))
    if not files:
        print("no b<block>.bin files in %s" % dumpdir)
        return 2

    print("  %-10s %-12s %s" % ("block", "card", "verdict"))
    print("  " + "-" * 62)
    for fn in files:
        try:
            blk = int(fn[1:-4])
        except ValueError:
            continue
        card = open(os.path.join(dumpdir, fn), "rb").read()
        off = blk * 4096
        want = img.read(off, len(card))
        if card == want:
            verdict = "IDENTICAL to image"
        elif card == b"\x00" * len(card):
            verdict = "ALL ZERO -- never written"
        else:
            # Is this window present elsewhere in the image, a few blocks away?
            found = None
            probe = card[:512]
            for delta in range(-64, 65):
                if delta == 0:
                    continue
                o2 = off + delta * 4096
                if o2 < 0 or o2 + len(probe) > img.size:
                    continue
                if img.read(o2, len(probe)) == probe:
                    found = delta
                    break
            if found is not None:
                verdict = "image content found %+d blocks away" % found
            else:
                diff = sum(1 for a, b in zip(want, card) if a != b)
                verdict = "unrelated (%d/%d bytes differ)" % (diff, len(card))
        print("  %-10d %-12d %s" % (blk, len(card), verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
