#!/usr/bin/env python3
"""Turn a QEMU boot run into check annotations.

Kept as a file rather than a heredoc so the workflow YAML needs no embedded
Python (the indentation rules for that are a trap).
"""
import json, os, sys


def ann(kind, title, body):
    esc = body.replace('%', '%25').replace(chr(13), '').replace(chr(10), '%0A')
    print('::%s title=%s::%s' % (kind, title, esc[:40000]))


def main():
    scr = ''
    if os.path.exists('qout/fb.txt'):
        scr = open('qout/fb.txt', errors='replace').read()
    res = {}
    if os.path.exists('qout/result.json'):
        try:
            res = json.load(open('qout/result.json'))
        except Exception:
            pass
    ann('notice', 'qemu-result', json.dumps(res))
    ann('notice', 'qemu-screen', scr[-4000:] or '(blank)')

    # Markers. sweet_early_mark() also paints a 48px colour band per stage, which
    # corrupts the glyphs on the row it lands on, so a decoded '?' on its own is
    # not proof of anything; the words are.
    marks = [
        ('start.s', 'SWEET EARLY'),
        ('arm_init', 'Darwin Kernel Version'),
        ('pmap', 'pmap_startup'),
        ('vm_bootstrap', 'VM bootstrap done'),
        ('platform_expert', 'starting device-tree platform expert'),
        ('framebuffer', 'SWEET FB'),
        ('m2_root_wait', 'waiting for root device'),
    ]
    hit = [n for n, s in marks if s in scr]
    ann('notice', 'qemu-milestones', 'reached: ' + (', '.join(hit) or '(none)'))

    # Anything that is not a blank line and not only the stage-band residue
    # means the early console produced text, i.e. start.s ran and sweet_early_putc
    # reached the framebuffer.
    body = [ln for ln in scr.splitlines() if ln.strip()]
    printable = [ln for ln in body if any(c.isalnum() for c in ln)]
    ann('notice', 'qemu-text', 'non-blank rows: %d, rows with letters/digits: %d'
        % (len(body), len(printable)))

    low = scr.lower()

    # These strings are the real milestones, in the order the kernel reaches
    # them. bsd_init completing is the strongest signal QEMU can give here: it
    # cannot go further because it has no eMMC, so it waits forever for an
    # IOMedia/Apple_HFS device that will never appear (see the plan, section 28).
    bsd_stages = [
        'bsd_init: calling kauth_init',
        'bsd_init: calling bufferinit',
        'bsd_init: calling bsd_autoconf',
        'bsd_init: calling loopattach',
        'bsd_init: calling inittodr',
        'bsd_init: calling setconf',
    ]
    seen_bsd = [s for s in bsd_stages if s in scr]
    ann('notice', 'qemu-bsd_init', 'of %d stages: %d reached'
        % (len(bsd_stages), len(seen_bsd)))

    if 'panic' in low:
        ann('error', 'qemu-panic', scr[-4000:])
        ann('error', 'qemu-verdict', 'FAIL: kernel panicked')
    elif 'waiting on' in low and 'iomedia' in low:
        ann('notice', 'qemu-verdict',
            'PASS: bsd_init complete, waiting for an IOMedia/Apple_HFS root '
            '(M2; QEMU has no eMMC so it cannot go further)')
    elif 'waiting for root device' in low:
        ann('notice', 'qemu-verdict', 'PASS: kernel ran to the root-device wait (M2)')
    elif len(seen_bsd) >= 4:
        ann('notice', 'qemu-verdict', 'bsd_init mostly done (%d/%d stages)'
            % (len(seen_bsd), len(bsd_stages)))
    elif 'VM bootstrap done' in scr or 'SWEET FB' in scr:
        ann('notice', 'qemu-verdict', 'kernel reached userspace prep, stopped before bsd_init')
    elif printable:
        ann('warning', 'qemu-verdict', 'kernel is drawing text but stopped early')
    elif 'SWEET EARLY' in scr:
        ann('warning', 'qemu-verdict', 'early console reached; text partly unreadable')
    else:
        ann('warning', 'qemu-verdict', 'no decodable console output; see qemu-screen')
    return 0


if __name__ == '__main__':
    sys.exit(main())
