#!/usr/bin/env python3
"""
diagnose.py -- run every check that applies to what you have, and say what it means.

Why this exists: the port now has nine diagnostic tools, each answering one question,
and the answers only mean something together. Someone coming back after a break has
to remember which to run, in what order, and how to combine them. That is how the
wrong conclusion gets drawn from a correct measurement -- which is the single most
expensive mistake in this project's history.

So this runs them all against whatever you point it at and prints one summary. It
never guesses: a check that cannot run says so and is marked SKIP, not OK.

Usage
-----
    python diagnose.py LOG                      # a kernel console log
    python diagnose.py --simg IMG               # the sparse image
    python diagnose.py --simg IMG --log LOG     # both
    python diagnose.py --dir QOUT               # a qemu-ugg output directory

Exit status: 0 nothing alarming found, 1 something needs attention,
             2 nothing could be checked.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run(tool, args):
    """Run a sibling tool; return (exit code, first meaningful line, full output)."""
    path = os.path.join(HERE, tool)
    if not os.path.exists(path):
        return None, 'tool missing: %s' % tool, ''
    p = subprocess.run([PY, path] + args, capture_output=True, text=True)
    out = (p.stdout or '') + (p.stderr or '')
    # Pick the most informative line: the verdict keywords first.
    line = ''
    for key in ('=>', 'FAIL', 'OK:', 'BAD', 'ERROR', 'No DONT_CARE', 'DONT_CARE covers'):
        for ln in out.splitlines():
            if key in ln:
                line = ln.strip()
                break
        if line:
            break
    if not line:
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        line = lines[-1] if lines else '(no output)'
    return p.returncode, line, out


def section(title):
    print()
    print('=' * 70)
    print(title)
    print('=' * 70)


def main():
    args = sys.argv[1:]
    log = qdir = simg = None
    i = 0
    while i < len(args):
        if args[i] == '--log' and i + 1 < len(args):
            log = args[i + 1]; i += 2
        elif args[i] == '--dir' and i + 1 < len(args):
            qdir = args[i + 1]; i += 2
        elif args[i] == '--simg' and i + 1 < len(args):
            simg = args[i + 1]; i += 2
        elif not args[i].startswith('--'):
            log = args[i]; i += 1
        else:
            i += 1

    if not (log or qdir or simg):
        print(__doc__)
        return 2

    results = []

    if simg:
        section('sparse image: %s' % simg)
        rc, line, out = run('simg-info.py', [simg, '--list-dont-care'])
        print(out.strip())
        # simg-info exits 1 for a RAW image, which is not a fault -- it is an answer
        # ('this is not sparse'). Reporting that as FAIL accuses a healthy file, and
        # this project has already lost rounds to checks that cry wolf.
        is_sparse = 'not a sparse image' not in out
        results.append(('simg-info', 0 if is_sparse else None,
                        'raw image' if not is_sparse else line))

        # The two paths the kernel actually tries to exec. If either is missing
        # from the image, errno 5 is not about the catalog and the whole direction
        # changes; if both are present, the catalog is the only explanation left.
        section('boot-critical paths resolved through the catalog')
        for want in ('/sbin/launchd', '/usr/lib/dyld'):
            rc, line, out = run('hfs-find.py', [simg, want])
            print(out.strip()[-600:])
            results.append(('hfs-find %s' % want, rc, line))

        section('image b-tree (this is what the kernel will walk)')
        rc, line, out = run('check-hfs-root.py', ['--all', simg])
        print(out.strip()[-1500:])
        results.append(('check-hfs-root', rc, line))

    if log:
        section('kernel log: %s' % log)
        rc, line, out = run('check-log-safety.py', [log])
        print(out.strip())
        results.append(('check-log-safety', rc, line))

        section('damage shape (bad part vs truncated write)')
        rc, line, out = run('check-parts.py', [log])
        print(out.strip())
        results.append(('check-parts', rc, line))

        section('bad node bytes (is it a byte-order fault?)')
        rc, line, out = run('decode-bad-nodes.py', [log])
        print(out.strip()[-1200:])
        results.append(('decode-bad-nodes', rc, line))

    if qdir:
        section('qemu output: %s' % qdir)
        rc, line, out = run('qemu-verdict.py', [qdir])
        print(out.strip())
        results.append(('qemu-verdict', rc, line))

    section('touch coordinate maths')
    rc, line, out = run('check-touch-math.py', [])
    print(out.strip()[-800:])
    results.append(('check-touch-math', rc, line))

    section('SUMMARY')
    # Exit status is not uniform across these tools, and pretending it is would make
    # the summary lie -- which is the exact failure this whole project keeps hitting.
    #   check-parts        exits 1 when a hypothesis is STILL OPEN (a finding, not a
    #                      fault); 0 when it is ruled out
    #   decode-bad-nodes   exits 0 on a clean read, 1 when it finds no text at all
    #   everything else    exits non-zero on a real problem
    # So the summary says what each exit code means for that tool, rather than
    # collapsing them into ok/FAIL.
    NOTES = {
        'check-parts': ('open', 'ruled out'),
        'decode-bad-nodes': ('inconclusive', 'readable'),
        'qemu-verdict': ('healthy', 'fault'),
        'check-log-safety': ('safe', 'OVERLAP'),
        'check-hfs-root': ('sane', 'PROBLEMS'),
        'check-touch-math': ('holds', 'FAILED'),
        'simg-info': ('ok', 'ok'),
        'hfs-find /sbin/launchd': ('found', 'ABSENT'),
        'hfs-find /usr/lib/dyld': ('found', 'ABSENT'),
    }
    worst = 0
    for name, rc, line in results:
        if rc is None:
            status = 'SKIP'
        else:
            good, bad = NOTES.get(name, ('ok', 'FAIL'))
            # check-parts: 1 means 'hypothesis open', which is informational, not a
            # failure of the check. It still deserves attention, so mark it 'note'.
            if name == 'check-parts':
                status = 'note' if rc == 1 else ('ok  ' if rc == 0 else 'FAIL')
            elif name == 'decode-bad-nodes':
                status = 'ok  ' if rc == 0 else 'note'
            else:
                status = 'ok  ' if rc == 0 else 'FAIL'
                if rc != 0:
                    worst = 1
        print('  %-18s %s  %s' % (name, status, line[:110]))

    print()
    if worst:
        print('Something failed above. Read that section -- and if it is a measurement,')
        print('remember the rule this project keeps relearning: a check that passes is')
        print('only worth something if it measured what you think it measured.')
    else:
        print('All applicable checks passed or were skipped. Remember that none of them')
        print('runs on the phone: they say the inputs are consistent, not that the')
        print('device boots.')
    return worst


if __name__ == '__main__':
    sys.exit(main())
