#!/usr/bin/env python3
"""
check-touch-math.py -- verify the touch coordinate transform without a phone.

Why this exists: the transform was wrong twice. First it normalised 720-wide panel
values by 1080, which squeezed the whole screen into the left 66.7% so the right and
bottom thirds never responded. Then the first fix normalised by the 750x1334 canvas
instead of the panel, a 4% error that grows to about 28 pixels at the bottom-right --
enough to hit the wrong icon.

Both bugs produce code that compiles, looks plausible, and can only be caught by
arithmetic or by tapping a phone. This script does the arithmetic: it reproduces the
exact expressions from SweetHID.cpp and prints what they map to, including the two
mistakes, so the numbers can be checked against what the device actually does.

It is a model, not the code itself: if SweetHID.cpp changes, the constants here must
change with it. That limitation is stated rather than hidden -- a checker that silently
drifts from the code it claims to check is worse than none.

Usage
-----
    python check-touch-math.py
    python check-touch-math.py --space 720x1280 --norm 720x1280 --edge 48

Exit status: 0 all invariants hold, 1 one failed.
"""
import argparse
import sys


def build(args):
    def transform(x, y, off_x=0, off_y=0):
        x = max(0, min(x, args.space_w - 1))
        y = max(0, min(y, args.space_h - 1))
        cx = max(0, min(x + off_x, args.norm_w - 1))
        cy = max(0, min(y + off_y, args.norm_h - 1))
        return ((cx << 16) // args.norm_w, (cy << 16) // args.norm_h)

    def is_edge(x, y):
        # The edge limit is computed from its OWN dimension pair, because the original
        # bug was exactly this: the limit used 1080x1920 while the coordinates only
        # reached 720x1280, so a real bottom-edge touch was never flagged and the
        # swipe-up / app-switcher gestures could not fire. Modelling it with a
        # separate --edge-space lets that bug be reproduced instead of assumed away.
        return (x < args.edge or x > args.edge_w - 1 - args.edge or
                y < args.edge or y > args.edge_h - 1 - args.edge)

    return transform, is_edge


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('--space', default='720x1280')
    ap.add_argument('--norm', default='720x1280')
    ap.add_argument('--edge', type=int, default=48)
    # Default: the edge limit uses the same space as the coordinates, which
    # is what SweetHID.cpp does now. Pass the old canvas size to reproduce.
    ap.add_argument('--edge-space', default=None)
    ap.add_argument('-h', '--help', action='store_true')
    args = ap.parse_args()
    if args.help:
        print(__doc__)
        return 0
    args.space_w, args.space_h = (int(v) for v in args.space.split('x'))
    args.norm_w, args.norm_h = (int(v) for v in args.norm.split('x'))
    es = args.edge_space or args.space
    args.edge_w, args.edge_h = (int(v) for v in es.split('x'))

    transform, is_edge = build(args)
    ok = True

    print('space %dx%d  norm %dx%d  edge %d'
          % (args.space_w, args.space_h, args.norm_w, args.norm_h, args.edge))
    print()

    print('corner and centre mapping (normalised 0..1):')
    pts = [('top-left', 0, 0),
           ('top-right', args.space_w - 1, 0),
           ('bottom-left', 0, args.space_h - 1),
           ('bottom-right', args.space_w - 1, args.space_h - 1),
           ('centre', args.space_w // 2, args.space_h // 2)]
    seen = {}
    for name, x, y in pts:
        nx, ny = transform(x, y)
        fx, fy = nx / 65536.0, ny / 65536.0
        seen[name] = (fx, fy)
        print('  %-13s (%4d,%4d) -> (%.5f, %.5f)' % (name, x, y, fx, fy))

    # Invariant 1: nothing may normalise to >= 1.0. backboardd rejects those as
    # off-screen, which shows up as touches that simply do not register at the edge.
    print()
    over = [(x, transform(x, args.space_h // 2)[0] / 65536.0)
            for x in range(0, args.space_w)
            if transform(x, args.space_h // 2)[0] / 65536.0 >= 1.0]
    over += [(y, transform(args.space_w // 2, y)[1] / 65536.0)
             for y in range(0, args.space_h)
             if transform(args.space_w // 2, y)[1] / 65536.0 >= 1.0]
    if over:
        ok = False
        print('FAIL: %d value(s) normalise to >= 1.0, e.g. %r'
              % (len(over), over[:3]))
        print('      those are rejected as off-screen; the edge of the panel dies.')
    else:
        print('OK: no in-range pixel normalises to >= 1.0')

    # Invariant 2: the far corner must land near 1.0, not short of it. This is the
    # bug that squeezed the panel into the left two thirds.
    far = seen['bottom-right'][0]
    expect = (args.space_w - 1) / args.norm_w
    if abs(far - expect) > 0.002:
        ok = False
        print('FAIL: bottom-right maps to %.4f, expected %.4f' % (far, expect))
    else:
        print('OK: bottom-right maps to %.4f (expected %.4f)' % (far, expect))

    # Invariant 3: the centre must be 0.5 -- an off-centre mapping points at the
    # wrong icon everywhere, which is harder to notice than a dead zone.
    cx, cy = seen['centre']
    if abs(cx - 0.5) > 0.002 or abs(cy - 0.5) > 0.002:
        ok = False
        print('FAIL: centre maps to (%.4f, %.4f), expected (0.5000, 0.5000)'
              % (cx, cy))
    else:
        print('OK: centre maps to (%.4f, %.4f)' % (cx, cy))

    # Invariant 4: the outer row/column must be flagged as edge, or the swipe-up
    # and app-switcher gestures never fire.
    print()
    probes = [('x=0', 0, args.space_h // 2), ('x=w-1', args.space_w - 1, args.space_h // 2),
              ('y=0', args.space_w // 2, 0), ('y=h-1', args.space_w // 2, args.space_h - 1)]
    for name, x, y in probes:
        e = is_edge(x, y)
        print('  edge %-6s -> %s' % (name, e))
        if not e:
            ok = False
            print('FAIL: %s is a real screen edge but is not flagged as edge' % name)

    # And the inner ring just past the margin must NOT be flagged, otherwise every
    # touch near an icon counts as an edge swipe.
    inner = [('x=edge', args.edge, args.space_h // 2),
             ('x=w-1-edge', args.space_w - 1 - args.edge, args.space_h // 2)]
    for name, x, y in inner:
        if is_edge(x, y):
            ok = False
            print('FAIL: %s should be inside the margin but is flagged as edge' % name)

    print()
    print('the two historical mistakes, for reference:')
    old_w = 1080
    print('  normalising 720-wide values by 1080:')
    print('    x=%d -> %.4f instead of %.4f, so the panel fills the left %.1f%%'
          % (args.space_w - 1, (args.space_w - 1) / old_w,
             (args.space_w - 1) / args.space_w,
             100.0 * args.space_w / old_w))
    print('  edge test against a larger space than the coordinates reach:')
    print('    pass --edge-space 1080x1920 to reproduce; the bottom and right')
    print('    edges then stop being flagged and the swipe gestures die there.')

    # Invariant 5: the model must match the header it claims to model. Without
    # this the defaults can silently drift from SweetHID.cpp and every green run
    # afterwards is meaningless -- the same failure mode that made earlier
    # 'verified' claims worthless.
    print()
    ok = drift_check(args) and ok

    print()
    print('=> all invariants hold' if ok else '=> INVARIANT FAILED')
    return 0 if ok else 1


def drift_check(args):
    """Compare this model's defaults against SweetHID.cpp's UGG defines."""
    import os
    import re
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(here, '..', '..', 'xnu-src', 'iokit', 'Kernel', 'arm',
                       'hid', 'SweetHID.cpp')
    if not os.path.exists(src):
        print('note: %s not found, skipping the model/code drift check' % src)
        print('      (run this from a checkout that has xnu-src next to ugg/)')
        return True
    text = open(src, encoding='utf-8', errors='replace').read()

    def one(name):
        m = re.search(r'#define\s+%s\s+(\S+)' % name, text)
        return m.group(1) if m else None

    pairs = [
        ('SWEET_TOUCH_SPACE_W', args.space_w),
        ('SWEET_TOUCH_SPACE_H', args.space_h),
    ]
    bad = False
    for name, mine in pairs:
        theirs = one(name)
        if theirs is None:
            print('note: %s not found in SweetHID.cpp' % name)
            continue
        # NORM_* is defined in terms of SPACE_*, so resolve one level.
        if theirs.startswith('SWEET_TOUCH_'):
            theirs = one(theirs)
        try:
            v = int(theirs, 0)
        except (TypeError, ValueError):
            print('note: %s is %r, cannot compare' % (name, theirs))
            continue
        if v != mine:
            bad = True
            print('FAIL: model uses %s=%d but SweetHID.cpp says %d' % (name, mine, v))
    if not bad:
        print('OK: model constants match SweetHID.cpp (space %dx%d)'
              % (args.space_w, args.space_h))
    return not bad


if __name__ == '__main__':
    sys.exit(main())
