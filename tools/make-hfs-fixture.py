#!/usr/bin/env python3
"""
make-hfs-fixture.py -- build a tiny HFS+ volume with a known file in it.

Why this exists: hfs-find.py walks an HFS+ catalog, and there was no way to tell
whether it was right except by pointing it at a 16 GiB image. Building a fixture by
hand found three real bugs in it in one sitting:

  * numRecords was read from 14 + 10 (a field position inside a HEADER node) instead
    of 10, so every leaf looked empty
  * the record offset table was walked with a stride of 4 bytes instead of 2, so only
    the first record of each leaf was ever seen -- which also meant no path deeper
    than one level could resolve
  * the catalog record type was read from data + 2 (that is 'flags') instead of data
    + 0, so every record looked like type 0

None of those are visible in a 16 GiB image until it fails, and all three are obvious
against a 8 MiB fixture with one folder and one file.

The volume contains:
    /           (root, CNID 1)
    /sbin       (folder, CNID 16)
    /sbin/launchd   (file, CNID 17, 64 bytes, one extent, Mach-O magic)

Usage
-----
    python make-hfs-fixture.py [OUT.img]

It is a test fixture, not a filesystem implementation: only what hfs-find.py needs is
laid out, and only one leaf node exists.
"""
import struct, subprocess, sys, os
BS, NODE, VOL_BLOCKS = 4096, 4096, 2048
# Default next to the tool; allow an override so a test can use a temp path.
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mini-hfs.img')
OUT = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT

def mknode(kind, numrec, records):
    n = bytearray(NODE); n[8] = kind
    struct.pack_into('>H', n, 10, numrec)
    for i, (roff, rec) in enumerate(records):
        struct.pack_into('>H', n, 14 + i * 2, roff)
        n[NODE - roff:NODE - roff + len(rec)] = rec
    return bytes(n)

def ck(parent, name):
    raw = name.encode('utf-16-be')
    body = struct.pack('>IH', parent, len(raw)//2) + raw
    out = struct.pack('>H', len(body)) + body
    return out + (b'\x00' if len(out) % 2 else b'')

def folder(cnid):
    r = bytearray(88); struct.pack_into('>H', r, 0, 2); struct.pack_into('>I', r, 8, cnid)
    return bytes(r)

def fil(cnid, size, blk, cnt):
    r = bytearray(248)
    struct.pack_into('>H', r, 0, 1); struct.pack_into('>I', r, 8, cnid)
    struct.pack_into('>Q', r, 88, size); struct.pack_into('>I', r, 104, 1)
    struct.pack_into('>II', r, 104, blk, cnt)
    return bytes(r)

vol = bytearray(VOL_BLOCKS * BS)
vh = bytearray(512); vh[0:2] = b'H+'
struct.pack_into('>I', vh, 40, BS); struct.pack_into('>I', vh, 44, VOL_BLOCKS)
struct.pack_into('>Q', vh, 272, 3*NODE); struct.pack_into('>II', vh, 288, 10, 3)
vol[1024:1536] = vh
hdr = bytearray(NODE); hdr[8] = 1
struct.pack_into('>H', hdr, 14, 1); struct.pack_into('>I', hdr, 16, 1)
struct.pack_into('>I', hdr, 24, 1); struct.pack_into('>I', hdr, 28, 1)
struct.pack_into('>H', hdr, 32, NODE); struct.pack_into('>I', hdr, 36, 3)

b1 = ck(1,'sbin') + folder(16)
b2 = ck(16,'launchd') + fil(17, 64, 20, 1)
roff, offs = 0, []
for b in (b1,b2):
    roff += len(b); offs.append(roff)
vol[10*BS:11*BS] = hdr
vol[11*BS:12*BS] = mknode(0xff, 2, list(zip(offs,(b1,b2))))
vol[20*BS:20*BS+8] = b'\xcf\xfa\xed\xfe\x0c\x00\x00\x01'
open(OUT,'wb').write(bytes(vol))
print("fixture:", OUT, len(vol), "bytes")
