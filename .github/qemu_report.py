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
    if 'panic' in low:
        ann('error', 'qemu-panic', scr[-4000:])
    elif 'waiting for root device' in low:
        ann('notice', 'qemu-verdict', 'PASS: kernel ran to the root-device wait (M2)')
    elif 'SWEET FB' in scr or 'VM bootstrap done' in scr:
        ann('notice', 'qemu-verdict', 'kernel reached userspace prep, stopped before M2')
    elif printable:
        ann('notice', 'qemu-verdict', 'kernel is drawing text on the early console')
    elif 'SWEET EARLY' in scr:
        ann('notice', 'qemu-verdict', 'early console reached; text partly unreadable')
    else:
        ann('warning', 'qemu-verdict', 'no decodable console output; see qemu-screen')
    return 0


if __name__ == '__main__':
    sys.exit(main())
