#!/usr/bin/env python3
"""
decode-bad-nodes.py -- turn the BAD node lines of a kernel console log into text.

A kernel console log reports damaged B-tree nodes as 32-bit hex values:

    UGG CHECK: BAD node=12288 fLink=0x2e50524f bLink=0x58494d49 kind=0x54

Those fields are UCS-4-ish 8-byte B-tree node descriptors, but the bytes they
carry here are plainly ASCII. Whether they read as text depends on byte order,
which is itself the question: if the card holds English, the retrieval is wrong;
if the card holds noise that happens to look like English, the write was wrong.

So this prints every field three ways -- as stored (little endian), byte-reversed,
and as raw bytes -- and marks which one is printable. Run it on a log and the
answer is usually obvious at a glance.

Usage
-----
    python decode-bad-nodes.py kernel-console.txt
    python decode-bad-nodes.py kernel-console.txt --fields kind,fLink
"""
import re
import sys

RE = re.compile(r'BAD node=(\d+)\s+fLink=0x([0-9a-fA-F]+)\s+bLink=0x([0-9a-fA-F]+)'
                r'\s+kind=0x([0-9a-fA-F]+)')


def printable(b, min_run=3):
    """True when the bytes are mostly ASCII letters/punctuation."""
    ok = sum(1 for c in b if 32 <= c < 127)
    return ok >= min_run and ok == len(b)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        print(__doc__)
        return 2
    path = args[0]
    try:
        text = open(path, encoding='utf-8', errors='replace').read()
    except OSError as e:
        print('cannot read %s: %s' % (path, e))
        return 2

    rows = RE.findall(text)
    if not rows:
        print('no "UGG CHECK: BAD node=..." lines in %s' % path)
        return 1

    print('%d bad node(s)\n' % len(rows))
    hdr = '%-7s %-10s %-12s %-12s %s' % ('node', 'field', 'as stored', 'reversed', 'raw bytes')
    print(hdr)
    print('-' * len(hdr))

    stored_text = 0
    rev_text = 0
    noise = 0
    for node, fl, bl, kd in rows:
        for name, hx in (('fLink', fl), ('bLink', bl), ('kind', kd)):
            raw = int(hx, 16).to_bytes(4, 'little')
            rev = raw[::-1]
            # 'as stored' is what a little-endian load gives, which is what the
            # kernel printed; show both interpretations of the same bytes.
            a = ''.join(chr(c) if 32 <= c < 127 else '.' for c in raw)
            b = ''.join(chr(c) if 32 <= c < 127 else '.' for c in rev)
            if printable(rev):
                rev_text += 1
            if printable(raw):
                stored_text += 1
            if not printable(raw) and not printable(rev):
                noise += 1
            print('%-7s %-10s %-12s %-12s %s'
                  % (node, name, a, b, raw.hex(' ')))

    print()
    print('fields readable as stored   : %d' % stored_text)
    print('fields readable byte-reversed: %d' % rev_text)
    print()
    if rev_text > stored_text:
        print('=> More fields read as text byte-reversed than as stored, so there')
        print('   may be a 32-bit word swap. Confirm with tools/verify-card.py,')
        print('   which compares the card against the image directly: guessing from')
        print('   a handful of nodes is what went wrong in earlier rounds.')
    elif stored_text > rev_text:
        print('=> Text reads correctly as stored, so the words are not swapped.')
    elif stored_text:
        print('=> TIE: %d fields read as text either way, %d are noise.' % (stored_text, noise))
        print('   A clean byte-order fault would make nearly every field readable,')
        print('   so this is NOT a systematic word swap. Mixed readable and noisy')
        print('   regions mean the content is partly wrong in place, not reordered.')
        print('   Use tools/verify-card.py for the actual answer.')
    else:
        print('=> Neither reading is text: the regions are genuinely corrupted.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
