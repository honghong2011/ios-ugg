#!/usr/bin/env python3
"""Pack an arm64 kernel Image into the boot image ugg's LK boots.

Facts taken from the installed boot image (64MB "boot" partition):
  header v0, page size 2048, kernel_addr 0x80008000, ramdisk_addr 0x81000000,
  tags_addr 0x80000100, and no separate dtb/dtbo partition.  The kernel
  section is Image.gz immediately followed by the DTB bundle (one FDT per
  board variant, 7 of them on the stock image); LK matches on
  qcom,msm-id/qcom,board-id and hands the chosen DTB to the kernel in x0.

LK ignores the header's load addresses when booting: the decompressed
kernel shows up at 0x10080000 and the ramdisk at 0x13600000 (read back
from /proc/iomem and /chosen).  The header still copies the stock values.
"""

import argparse
import hashlib
import struct
import sys
import zlib

PAGE = 2048
BASE = 0x80000000
KERNEL_OFFSET = 0x00008000
RAMDISK_OFFSET = 0x01000000
TAGS_OFFSET = 0x00000100
HEADER_SIZE = 1632          # fields + name + cmdline + id + extra_cmdline
FDT_MAGIC = b"\xd0\x0d\xfe\xed"


def gzip_bytes(data, level=9):
    """Deterministic gzip stream (mtime 0, no name), like `gzip -n -9`."""
    co = zlib.compressobj(level, zlib.DEFLATED, 31)
    return co.compress(data) + co.flush()


def pad(data, size=PAGE):
    return data + b"\0" * (-len(data) % size)


def build_image(kernel, ramdisk, bundle, cmdline):
    gz = gzip_bytes(kernel)
    if bundle and bundle[:4] != FDT_MAGIC:
        sys.exit("error: dt bundle does not start with an FDT magic")
    section = gz + bundle

    hdr = bytearray(HEADER_SIZE)
    struct.pack_into("<8s", hdr, 0, b"ANDROID!")
    struct.pack_into(
        "<10I", hdr, 8,
        len(section), BASE + KERNEL_OFFSET,
        len(ramdisk), BASE + RAMDISK_OFFSET,
        0, 0,
        BASE + TAGS_OFFSET,
        PAGE, 0, 0,
    )
    struct.pack_into("<16s", hdr, 48, b"ugg-shim")
    cmd = cmdline.encode()[:511] + b"\0"
    hdr[64:64 + len(cmd)] = cmd

    # Same id recipe as mkbootimg v0: sha1 over each size and payload.
    sha = hashlib.sha1()
    for blob in (section, ramdisk):
        sha.update(struct.pack("<I", len(blob)))
        sha.update(blob)
    hdr[576:608] = sha.hexdigest().encode()[:32]

    image = pad(bytes(hdr)) + pad(section) + pad(ramdisk)
    return image, gz, section


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kernel", required=True, help="raw arm64 Image")
    ap.add_argument("--ramdisk", required=True, help="gzip'd cpio ramdisk")
    ap.add_argument("--dtbundle", help="concatenated FDTs appended to Image.gz")
    ap.add_argument("--cmdline", default="console=null")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    kernel = open(a.kernel, "rb").read()
    ramdisk = open(a.ramdisk, "rb").read()
    bundle = open(a.dtbundle, "rb").read() if a.dtbundle else b""

    image, gz, section = build_image(kernel, ramdisk, bundle, a.cmdline)
    with open(a.out, "wb") as f:
        f.write(image)

    print("kernel Image     : %d bytes" % len(kernel))
    print("Image.gz         : %d bytes" % len(gz))
    print("DTB bundle       : %d bytes (starts at file offset 0x%x)"
          % (len(bundle), PAGE + len(gz)))
    print("kernel section   : %d bytes" % len(section))
    print("boot image       : %d bytes -> %s" % (len(image), a.out))


if __name__ == "__main__":
    main()
