#!/usr/bin/env python3
"""
check-parts.py -- does the damage line up with the image's part boundaries?

Why this exists: the iOS root ships as ~10 parts of 1800 MB (build-root.yml). If a
single part were truncated, misordered or corrupt, the damage on the card would begin
exactly at a part boundary -- and that is a completely different thing to fix from a
write-side fault (re-download one part vs. investigate the transfer).

The 0104 console brackets the damage: every node below 0.84 GiB was good, and the
first bad node is at 4.342 GiB. So the true boundary is somewhere in between, and
this script answers the only question that matters for the part hypothesis: does any
part boundary fall inside that bracket? If one does, the hypothesis is alive and a
targeted re-download is a cheap experiment. If none does, it is dead.

Usage
-----
    python check-parts.py kernel-console.txt
    python check-parts.py kernel-console.txt --part-mb 1800

Exit status: 0 no boundary inside the bracket (hypothesis dead),
            1 a boundary does fall inside it (worth testing),
             2 the log did not carry the numbers needed.
"""
import re
import sys

BS = 4096
FIRST_BLOCK = 1376256      # userdata start, printed by the driver as first=
PART_MB = 1800


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        print(__doc__)
        return 2
    part_mb = PART_MB
    for i, a in enumerate(sys.argv[1:]):
        if a == '--part-mb' and i + 2 < len(sys.argv):
            part_mb = int(sys.argv[i + 2])

    text = open(args[0], encoding='utf-8', errors='replace').read()

    # The bracket: highest node in a clean extent, and the first node reported bad.
    exts = []
    m = re.search(r'catalog blockSize=(\d+) extents:(.*)', text)
    if not m:
        print('no catalog extents line -- cannot bracket the damage')
        return 2
    for tok in m.group(2).split():
        mm = re.match(r'(\d+)\+(\d+)$', tok)
        if mm:
            exts.append((int(mm.group(1)), int(mm.group(2))))

    bad = re.search(r'first bad node=(\d+)', text)
    node_size = 8192
    if bad:
        first_bad_node = int(bad.group(1))
        # which extent holds it, and at what volume byte
        acc = 0
        off = None
        for s, c in exts:
            in_ext = c * BS // node_size
            if acc <= first_bad_node < acc + in_ext:
                off = s * BS + (first_bad_node - acc) * node_size
                break
            acc += in_ext
    else:
        # Fall back to the node numbers on the BAD lines.
        mm = re.findall(r'BAD node=(\d+)', text)
        if not mm:
            print('no "first bad node=" and no "BAD node=" lines -- cannot locate damage')
            return 2
        first_bad_node = int(mm[0])
        acc = 0
        off = None
        for s, c in exts:
            in_ext = c * BS // node_size
            if acc <= first_bad_node < acc + in_ext:
                off = s * BS + (first_bad_node - acc) * node_size
                break
            acc += in_ext

    if off is None:
        print('could not place node %d in any extent' % first_bad_node)
        return 2

    # Highest clean point: end of the last extent that had no bad nodes. We only
    # know ext boundaries, so use the end of the extent before the damaged one.
    clean_end = None
    for s, c in exts:
        if s * BS >= off:
            break
        clean_end = (s + c) * BS

    if clean_end is None:
        # The first extent is already damaged, so there is no clean prefix. Saying
        # so is the whole answer: nothing before the damage can be used as an anchor,
        # so a part-boundary argument cannot be applied at all. Crashing here with a
        # TypeError (as this used to) told the reader nothing and looked like the
        # tool was broken rather than the device.
        print('the FIRST extent is already damaged at node %d (%.3f GiB).'
              % (first_bad_node, off / 2 ** 30))
        print()
        print('There is no clean prefix, so there is no bracket to compare against')
        print('part boundaries. The damage starts at or before the beginning of the')
        print('catalog, which points at the write never completing its start -- or at')
        print('the volume header area itself. verify-card.py --map from offset 0')
        print('settles where it begins.')
        return 1
    lo_gib = clean_end / 2 ** 30
    hi_gib = off / 2 ** 30
    print('damage bracketed by:')
    print('  all good below : %.3f GiB (end of the last clean extent)' % lo_gib)
    print('  first bad at   : %.3f GiB (node %d)' % (hi_gib, first_bad_node))
    print()
    part_gib = part_mb * 1e6 / 2 ** 30
    total_gib = 16.0
    nparts = int(total_gib / part_gib) + 1
    print('parts: %d x %d MB = %.4f GiB each' % (nparts, part_mb, part_gib))
    print()
    inside = []
    for i in range(1, nparts):
        g = i * part_gib
        mark = ''
        if lo_gib < g < hi_gib:
            inside.append(i + 1)
            mark = '  <-- inside the bracket'
        print('  part %2d starts at %7.3f GiB%s' % (i + 1, g, mark))
    print()
    if inside:
        print('=> A part boundary falls inside the damaged bracket.')
        print()
        # A boundary inside the bracket is necessary but NOT sufficient: one bad
        # part damages exactly ONE part-sized window and stops. If the damage is
        # known to continue past that window -- e.g. the walk found every node in
        # two consecutive extents bad -- a single bad part cannot explain it, and
        # the bracket is wide only because the clean and damaged extents sit far
        # apart with no nodes in the gap.
        span_end = None
        mm = re.findall(r'ext(\d+) block (\d+) count (\d+) -> nodes (\d+)\.\.(\d+)',
                        text)
        damaged_exts = []
        for _i, blk, cnt, lo, hi in mm:
            n_lo, n_hi = int(lo), int(hi)
            if n_lo <= first_bad_node <= n_hi or first_bad_node < n_lo:
                damaged_exts.append((int(blk), int(cnt)))
        if len(damaged_exts) >= 2:
            span_end = (damaged_exts[-1][0] + damaged_exts[-1][1]) * BS / 2 ** 30
            span_gib = span_end - hi_gib
            boundaries = [i * part_gib for i in range(1, nparts)
                          if hi_gib < i * part_gib < span_end]
            print('   BUT the damage is contiguous across %d extents:' % len(damaged_exts))
            print('     %.3f GiB .. %.3f GiB  (>= %.2f GiB)' % (hi_gib, span_end, span_gib))
            print('     part boundaries crossed inside it: %s'
                  % [round(b, 3) for b in boundaries])
            print()
            print('   A single corrupt part would damage exactly one %.2f GiB window'
                  % part_gib)
            print('   and stop. This span crosses %d boundary(ies) and continues, so'
                  % len(boundaries))
            print('   one bad part CANNOT explain it.')
            print()
            print('   => The evidence favours a TRUNCATED WRITE: everything past some')
            print('      stop point is stale, which produces exactly this shape --')
            print('      a clean prefix and a contiguous damaged tail.')
            print('      verify-card.py first divergence IS that stop point.')
            return 1
        print('   The "one bad part" hypothesis is ALIVE. Cheapest test: re-download')
        print('   the parts named above, reassemble, and compare the same region.')
        return 1
    print('=> No part boundary falls inside the bracket.')
    print('   The damage did not start at a part edge, so a single corrupt part')
    print('   cannot explain it. Look at the write path instead.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
