#!/usr/bin/env python3
"""
emit-flash-expectations.py -- write the verify-flash.sh checks for THIS image.

Why this exists
---------------
verify-flash.sh used to carry hardcoded "the image expects: ..." byte strings for four
catalog nodes. Those bytes came from the volume that happened to be on the phone in
November, whose catalog extents were ext1 211815 and ext3 1729347. The image CI builds
now has ext1 211896 and ext3 1729468, so node 19174 lives 121 blocks further along.

Which means the old script would have reported a mismatch on a perfectly good flash --
and, worse, the mismatch would have looked exactly like the fault it was written to
detect. A checker pinned to a volume that no longer exists is a false-alarm generator.

So the expectations are derived from the image instead: read its volume header, map
node index to block, and print the first 16 bytes of each node. Feed the output into
verify-flash.sh, or compare it with what the card returns.

Usage
-----
    python emit-flash-expectations.py ios16-root.simg
    python emit-flash-expectations.py ios16-root.simg --nodes 19174,19193,19462,19514

Exit status: 0 wrote the expectations, 2 could not read the image.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load_checker():
    path = os.path.join(HERE, 'check-hfs-root.py')
    spec = importlib.util.spec_from_file_location('chr', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = load_checker()
be16, be32, be64 = C.be16, C.be32, C.be64


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        print(__doc__)
        return 2
    image = args[0]
    if not os.path.exists(image):
        print('no such image: %s' % image)
        return 2

    nodes = [19174, 19193, 19462, 19514]
    for i, a in enumerate(sys.argv):
        if a == '--nodes' and i + 1 < len(sys.argv):
            nodes = [int(x) for x in sys.argv[i + 1].split(',')]

    img = C.open_image(image)
    vh = img.read(C.HFSPLUS_VOLHEADER_OFF, 512)
    if vh[0:2] not in (b'H+', b'HX'):
        print('%s: not an HFS+ volume' % image)
        return 2
    blocksize = be32(vh, 40)

    fork = C.Fork(vh, C.CATALOG_FORK_OFF, 'catalog')
    bt = C.BTree(img, fork, blocksize, 'catalog')
    bt.load_header()
    node_size = bt.node_size
    if node_size == 0:
        print('catalog has no node size -- cannot map nodes')
        return 2

    print('# expectations derived from %s' % image)
    print('# block size %d, catalog node size %d, %d nodes'
          % (blocksize, node_size, bt.total_nodes))
    print('# catalog extents: %s'
          % ' '.join('%d+%d' % e for e in fork.extents))
    print('#')
    print('# Format for verify-flash.sh:')
    print('#   dump BLOCK "HEX16" "  (node N, kind)"')
    print()

    def extent_of(node_index):
        """Map a node index to (block, kind) using the catalog's own extent list."""
        want = node_index * node_size
        covered = 0
        for start, count in fork.extents:
            ext_bytes = count * blocksize
            if want < covered + ext_bytes:
                inner = want - covered
                return start + inner // blocksize
            covered += ext_bytes
        return None

    for n in nodes:
        if n >= bt.total_nodes:
            print('# node %d is beyond totalNodes -- skipped' % n)
            continue
        blk = extent_of(n)
        if blk is None:
            print('# node %d is not covered by any extent -- skipped' % n)
            continue
        head = img.read(blk * blocksize, 16)
        if len(head) < 16:
            print('# node %d: could not read block %d' % (n, blk))
            continue
        kind = head[8]
        label = {0x00: 'index', 0xff: 'leaf', 0x01: 'header'}.get(kind, 'kind 0x%02x' % kind)
        print('dump %d "%s" "  (node %d, %s)"'
              % (blk, ' '.join('%02x' % c for c in head), n, label))
    print()
    print('# If the card returns these exact bytes at these exact blocks, the flash')
    print('# placed this image correctly. Anything else means it did not.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
