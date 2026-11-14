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

    # The boot milestones, in the order the kernel reaches them.
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

    low = scr.lower()
    if 'panic' in low:
        ann('error', 'qemu-panic', scr[-4000:])
    elif 'waiting for root device' in low:
        ann('notice', 'qemu-verdict', 'PASS: kernel ran to the root-device wait (M2)')
    elif 'SWEET FB' in scr or 'VM bootstrap done' in scr:
        ann('notice', 'qemu-verdict', 'kernel reached userspace prep, stopped before M2')
    else:
        ann('warning', 'qemu-verdict', 'kernel stopped early; see qemu-screen')
    return 0


if __name__ == '__main__':
    sys.exit(main())
