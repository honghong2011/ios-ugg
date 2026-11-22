#!/usr/bin/env python3
"""
check-log-safety.py -- prove the kernel's log area cannot overlap the HFS volume.

Why this exists: the ugg catalog B-tree is damaged on the card, and one of the
obvious suspects is the kernel's own persistent log, which writes to the END of the
userdata partition. If that range reached the catalog extents the driver would be
destroying the volume every few seconds, and no amount of reflashing would help.

It does not reach them, and this script shows why from the numbers the kernel itself
prints, so the conclusion can be rechecked instead of remembered:

    UGG EMMC: userdata first=1376256 nblocks=13891579
    SWEET LOG: flushed ... to block 0xe8f3fa
    UGG CHECK: catalog blockSize=4096 extents: 183682+16384 ...

Usage
-----
    python check-log-safety.py kernel-console.txt

Exit status: 0 the log area is safely clear of the volume, 1 it overlaps, 2 the log
did not contain the numbers needed to tell.
"""
import re
import sys

BLOCK = 4096
# One header block plus the 4 MiB ring: sweet_ufs.c SWEET_LOG_BLOCKS.
LOG_BLOCKS = 1 + (4 << 20) // BLOCK


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    try:
        text = open(path, encoding='utf-8', errors='replace').read()
    except OSError as e:
        print('cannot read %s: %s' % (path, e))
        return 2

    first = re.search(r'UGG EMMC: \w+ first=(\d+) nblocks=(\d+)', text)
    if not first:
        print('no "UGG EMMC: ... first=... nblocks=..." line -- cannot locate the partition')
        return 2
    first_blk, nblocks = int(first.group(1)), int(first.group(2))

    logm = re.search(r'SWEET LOG: flushed .* to block 0x([0-9a-fA-F]+)', text)
    if logm:
        log_base = int(logm.group(1), 16)
    else:
        # The driver computes it; use the same expression it does.
        log_base = first_blk + nblocks - LOG_BLOCKS

    extm = re.search(r'catalog blockSize=(\d+) extents:(.*)', text)
    if not extm:
        print('no "UGG CHECK: catalog ... extents:" line -- cannot locate the volume')
        return 2
    bsize = int(extm.group(1))
    exts = []
    for tok in extm.group(2).split():
        m = re.match(r'(\d+)\+(\d+)$', tok)
        if m:
            exts.append((int(m.group(1)), int(m.group(2))))
    if not exts:
        print('could not parse extents:', extm.group(2).strip())
        return 2

    part_end = first_blk + nblocks
    log_end = log_base + LOG_BLOCKS
    vol_end = first_blk + max(s + c for s, c in exts)

    print('partition  : blocks %d .. %d  (%.1f GiB)'
          % (first_blk, part_end - 1, nblocks * BLOCK / 2 ** 30))
    print('log area   : blocks %d .. %d  (%d blocks, %.1f MiB)'
          % (log_base, log_end - 1, LOG_BLOCKS, LOG_BLOCKS * BLOCK / 2 ** 20))
    print('volume end : block %d' % vol_end)
    gap = log_base - vol_end
    print('gap        : %d blocks = %.2f GiB' % (gap, gap * BLOCK / 2 ** 30))
    print()

    ok = True
    if log_base < first_blk:
        print('BAD: the log area starts BEFORE the partition')
        ok = False
    if log_end > part_end:
        print('BAD: the log area runs past the end of the partition')
        ok = False
    if log_base < vol_end:
        print('BAD: THE LOG OVERLAPS THE VOLUME -- the driver would be damaging it')
        ok = False

    if ok:
        print('OK: the log sits in the last %d blocks of the partition, %.2f GiB'
              % (LOG_BLOCKS, gap * BLOCK / 2 ** 30))
        print('    above the highest catalog extent. It cannot have damaged the')
        print('    volume, so look elsewhere for the corruption.')
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
