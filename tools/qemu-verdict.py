#!/usr/bin/env python3
"""
qemu-verdict.py -- turn a qemu-ugg run directory into a pass/fail decision.

Why this is a separate file: the same judgement was first written inline in the
workflow, where an indentation slip inside a heredoc silently broke the YAML, and
where the rules were invisible unless you read the CI config. Here it can be read,
run locally against a downloaded artifact, and tested.

The calibration, from real runs (see NOTES-UGG round 46):

  45032399238  text on screen, 7 undefined instructions, prefetch aborts  -> FAIL
  45035153390  blank screen, 370 IRQs, 0 faults, PC in _cpu_idle           -> PASS

So a fault is a failure, and a BLANK screen is the healthy outcome: the framebuffer
driver has taken the display and there is no userspace yet to draw anything. Text on
screen means the kernel printed its last words and died before that handover.

Usage
-----
    python qemu-verdict.py QOUTDIR

Exit status: 0 healthy, 1 fault or panic found, 2 the run left no usable evidence.
"""
import json
import os
import re
import sys

MIN_IRQS = 5          # below this the kernel never reached a running state
FAULT_RE = re.compile(
    r'Undefined Instruction|Prefetch Abort|Data Abort|panicked|panic\(\)')


def read(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return ''


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    d = sys.argv[1]
    if not os.path.isdir(d):
        print('no such directory: %s' % d)
        return 2

    log = read(os.path.join(d, 'qemu.log'))
    faults = len(FAULT_RE.findall(log))
    irqs = len(re.findall(r'Taking exception 5 \[IRQ\]', log))

    status = None
    rj = read(os.path.join(d, 'result.json'))
    if rj:
        try:
            status = json.loads(rj).get('status')
        except ValueError:
            status = None

    fb = read(os.path.join(d, 'fb.txt'))
    has_text = bool(re.search(r'[^\s]', fb))

    print('IRQs                    : %d' % irqs)
    print('faults                  : %d' % faults)
    print('framebuffer status      : %s' % (status or '(none)'))
    print('console text on screen  : %s' % ('yes' if has_text else 'no (expected)'))

    regs = read(os.path.join(d, 'regs.txt'))
    pc = re.search(r'PC=([0-9a-fA-F]+)', regs)
    if pc:
        print('parked PC               : 0x%s' % pc.group(1))

    if faults:
        print()
        print('::error title=qemu-fault::kernel faulted %d time(s)' % faults)
        for line in log.splitlines():
            if FAULT_RE.search(line):
                print('   ' + line)
                break
        return 1

    if status == 'panic':
        print()
        print('::error title=qemu-panic::decoded screen contains a panic')
        if has_text:
            for line in fb.splitlines()[-10:]:
                print('   ' + line)
        return 1

    if irqs < MIN_IRQS:
        print()
        print('::error title=qemu-too-quiet::only %d IRQs -- the kernel never ran' % irqs)
        return 2

    if has_text:
        # Not fatal by itself: the kernel may still be printing. But in a 25 s run
        # that reached the idle loop, leftover text usually means it died early.
        print()
        print('::warning title=qemu-text-on-screen::console text still visible after the run')

    print()
    print('::notice title=qemu-ok::%d IRQs, 0 faults, %s'
          % (irqs, 'screen blank (expected)' if not has_text else 'text on screen'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
