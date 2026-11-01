#!/bin/bash
# Build the ugg shim and wrap it in the v0 boot image this LK accepts.
# UGG_DTBUNDLE: concatenated per-board FDTs (device-dumps, not in git).
# Without it the image is only structurally valid, not bootable.
set -euo pipefail
cd "$(dirname "$0")"
CC=aarch64-linux-gnu-gcc
OBJCOPY=aarch64-linux-gnu-objcopy
CFLAGS="-O2 -ffreestanding -nostdlib -fno-pic -mgeneral-regs-only -mstrict-align -fno-stack-protector -Wall -Wextra"
CSRCS="shim.c console.c mmu.c fdt.c loader.c"

mkdir -p out
OBJS=""
for f in start.S $CSRCS; do
	o=out/${f%.*}.o
	$CC $CFLAGS -c "$f" -o "$o"
	OBJS="$OBJS $o"
done
# The image runs wherever LK puts it with no relocation pass: only the
# header's image_size (start.o, linked at 0) may be an absolute address.
COBJS=$(for f in $CSRCS; do printf 'out/%s.o ' "${f%.*}"; done)
abs=$(aarch64-linux-gnu-readelf -r $COBJS | grep -c ABS64 || true)
[ "$abs" = 0 ] || { echo "error: $abs absolute relocations in C objects" >&2; exit 1; }

$CC $CFLAGS -static -T shim.ld -Wl,--build-id=none -Wl,--no-warn-rwx-segments -Wl,-N \
	$OBJS -o out/shim.elf
$OBJCOPY -O binary out/shim.elf out/Image
# LK copies the file; pad to image_size so .bss/stacks exist as zeroed bytes.
size=$(aarch64-linux-gnu-nm out/shim.elf | awk '$3=="_end"{print $1}')
truncate -s "$((16#$size))" out/Image

# Ramdisk: an xnu payload (tools/mkpayload.py) if given as $1, else an
# empty newc cpio. LK hands it over in /chosen/linux,initrd-*.
if [ -n "${1:-}" ]; then
	cp "$1" out/ramdisk.bin
else
	(cd out && rm -rf rd && mkdir rd && cd rd && find . | cpio -o -H newc --quiet | gzip -9 > ../ramdisk.bin)
fi

BUNDLE_ARGS=""
if [ -n "${UGG_DTBUNDLE:-}" ]; then
	BUNDLE_ARGS="--dtbundle $UGG_DTBUNDLE"
fi
python3 ../tools/pack-ugg.py --kernel out/Image --ramdisk out/ramdisk.bin \
	$BUNDLE_ARGS --cmdline "console=null" -o out/shim-boot.img

# Host render of the console layout.
gcc -O1 -Wall -o out/host_test console.c host_test.c && ./out/host_test
ls -l out/Image out/ramdisk.bin out/shim-boot.img
