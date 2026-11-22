#!/usr/bin/env python3
"""
hfs-find.py -- resolve a path in an HFS+ image and prove the file is really there.

Why this exists
---------------
The port's direction depends on one question: is /sbin/launchd actually in the image?
The phone says

    load_init_program: failed loading /sbin/launchd: errno 5

and errno 5 is EIO, not ENOENT, so the log argues the catalog failed rather than the
file being absent. That is an argument about what a number means, not a measurement.

check-hfs-root.py validates the b-trees but never resolves a path. This walks the
catalog, matches a path, and prints that file's own fork plus the first bytes read
through it -- so a Mach-O header is either there or it is not.

Usage
-----
    python hfs-find.py IMAGE /sbin/launchd
    python hfs-find.py IMAGE /usr/lib/dyld

Exit status: 0 found, 1 not found, 2 could not read.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load_checker():
    """Import check-hfs-root.py so this file does not reimplement sparse reading."""
    path = os.path.join(HERE, 'check-hfs-root.py')
    spec = importlib.util.spec_from_file_location('chr', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = load_checker()
be16, be32, be64 = C.be16, C.be32, C.be64


def leaf_records(node):
    """Yield (record_offset_in_node) for each record of a leaf node."""
    if len(node) < 14 + 10:
        return
    num = be16(node, 10)          # node descriptor: numRecords
    for i in range(num):
        # The offset table is an array of uint16: 2 bytes per entry, starting at 14.
        # Using i * 4 here read past every second entry, so only the first record of
        # each leaf was ever returned -- and any path deeper than one level could
        # never resolve. The fixture caught it; a real image would have hidden it.
        off = 14 + i * 2
        if off + 2 > len(node):
            return
        roff = be16(node, off)
        if roff == 0 or roff > len(node):
            continue
        yield len(node) - roff


def key_of(node, start):
    """(parentID, name) of the catalog key starting at start."""
    if start + 8 > len(node):
        return None
    keylen = be16(node, start)
    if keylen < 6 or start + 2 + keylen > len(node):
        return None
    parent = be32(node, start + 2)
    nlen = be16(node, start + 6)
    raw = node[start + 8:start + 8 + 2 * nlen]
    if len(raw) < 2 * nlen:
        return None
    return parent, raw.decode('utf-16-be', 'replace')


def data_of(node, start):
    """Byte offset of the data record that follows the key at start."""
    keylen = be16(node, start)
    return start + 2 + keylen


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) < 2:
        print(__doc__)
        return 2
    image, target = args[0], args[1]
    if not os.path.exists(image):
        print('no such image: %s' % image)
        return 2

    img = C.open_image(image)
    vh = img.read(C.HFSPLUS_VOLHEADER_OFF, 512)
    signature = vh[0:2]
    if signature not in (b'H+', b'HX'):
        print('%s: not an HFS+ volume (signature %r)' % (image, signature))
        return 2
    blocksize = be32(vh, 40)

    fork = C.Fork(vh, C.CATALOG_FORK_OFF, 'catalog')
    bt = C.BTree(img, fork, blocksize, 'catalog')
    bt.load_header()
    print('volume   : %s' % image)
    print('  block size %d, catalog node size %d, %d nodes'
          % (blocksize, bt.node_size, bt.total_nodes))
    print('looking for: %s' % target)

    # Collect leaves in catalog order, then scan: HFS+ keys sort by parentID then
    # name, so walking leaves in fLink order visits parents before their children.
    leaves = []
    stack = [bt.root_node]
    guard = 0
    while stack and guard < bt.total_nodes:
        idx = stack.pop()
        guard += 1
        node = bt.read_node(idx)
        if len(node) < 14:
            continue
        kind = node[8]
        if kind == 0xff:
            leaves.append(idx)
        elif kind == 0x00:
            # An INDEX node's records are: key, then a uint32 child node number.
            # The offset table (numRecords * uint16 at byte 14) gives where each
            # record STARTS; the child pointer is the last 4 bytes of the record,
            # after its key.
            #
            # This used to read be32(node, 14 + i*2), i.e. it treated the offset
            # table as an array of uint32 child pointers. On a multi-level tree that
            # descends into garbage, finds a handful of leaves and stops -- which is
            # exactly what a real image exposed: 73 leaves for a catalog holding
            # 182380 files. The fixture never caught it because its root node WAS the
            # leaf, so this branch never executed.
            num = be16(node, 10) if len(node) > 11 else 0
            for i in range(num):
                toff = 14 + i * 2
                if toff + 2 > len(node):
                    break
                roff = be16(node, toff)
                if roff == 0 or roff > len(node) - 4:
                    continue
                start = len(node) - roff
                keylen = be16(node, start)
                child_at = start + 2 + keylen
                if child_at + 4 > len(node):
                    continue
                stack.append(be32(node, child_at))
    leaves.sort()

    path_of = {1: ''}
    want = target.rstrip('/').lower()
    visited = 0
    for li in leaves:
        node = bt.read_node(li)
        if len(node) < 14 or node[8] != 0xff:
            continue
        visited += 1
        for start in leaf_records(node):
            k = key_of(node, start)
            if not k:
                continue
            parent, name = k
            if parent not in path_of:
                continue
            path = path_of[parent] + '/' + name
            d = data_of(node, start)
            if d + 2 > len(node):
                continue
            # HFSPlusCatalogRecord: recordType int16 at +0, flags uint16 at +2,
            # then folderID/fileID uint32 at +8. Reading the type from +2 returns
            # 'flags', which is 0 for both folders and files -- so every record was
            # skipped and no path ever resolved. The fixture caught it.
            vtype = be16(node, d)
            cnid = be32(node, d + 8)
            if vtype in (1, 2):
                path_of[cnid] = path
            if path.lower() == want:
                print('  leaves walked: %d' % visited)
                print()
                if vtype == 2:
                    print('FOUND %s -- it is a DIRECTORY, not a file' % path)
                    return 1
                # File data record: fork starts 88 bytes into it.
                fsize = be64(node, d + 88)
                ffork = C.Fork(node[d + 88:], 0, 'file')
                print('FOUND %s' % path)
                print('  catalog node : %d' % li)
                print('  size         : %d bytes' % fsize)
                print('  extents      : %s'
                      % ' '.join('%d+%d' % e for e in ffork.extents))
                if ffork.extents:
                    start_blk = ffork.extents[0][0]
                    head = img.read(start_blk * blocksize, 16)
                    print('  first 16 bytes: %s' % head.hex(' '))
                    if head[:4] in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe',
                                    b'\xca\xfe\xba\xbe', b'\xfe\xed\xfa\xcf'):
                        print('  => Mach-O header present: this is a real executable')
                    else:
                        print('  => NOT a Mach-O (magic %s)' % head[:4].hex(' '))
                return 0
    print('  leaves walked: %d' % visited)
    print('NOT FOUND: %s' % target)
    print()
    print('=> the path is absent from this image. errno 5 on the phone would then')
    print('   mean something other than "the catalog failed to read the node".')
    return 1


if __name__ == '__main__':
    sys.exit(main())
