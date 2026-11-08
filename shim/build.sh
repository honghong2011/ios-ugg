#!/bin/bash
# Build the ugg shim (BOARD_UGG) to shim/out/Image.
#
# The shim is the "kernel" LK boots: it sets up the MMU, finds the XNU payload
# appended after its own _end (this LK does not honour ramdisk_addr - measured
# on the mi8937 family by the uglite port), copies the kernel to phys_base,
# builds boot_args and jumps into XNU.
#
# The final boot image is assembled separately (payload appended to Image,
# gzip, DTB bundle) by tools/ - this script only produces out/Image, because it
# needs a cross compiler while the packaging does not.
#
# Cross compiler: aarch64-linux-gnu-gcc if present, else clang with
# --target=aarch64-none-elf.
set -euo pipefail
cd "$(dirname "$0")"

BOARD_DEFS="-DBOARD_UGG"

if command -v aarch64-linux-gnu-gcc >/dev/null; then
	CC=aarch64-linux-gnu-gcc
	OBJCOPY=aarch64-linux-gnu-objcopy
	READELF=aarch64-linux-gnu-readelf
	NM=aarch64-linux-gnu-nm
	LDFLAGS="-Wl,--no-warn-rwx-segments"
else
	CC="clang --target=aarch64-none-elf"
	OBJCOPY=llvm-objcopy
	READELF=llvm-readelf
	NM=llvm-nm
	LDFLAGS="-fuse-ld=lld"
fi

# -fno-jump-tables: the exception handler's switch must not become a table of
# absolute addresses in .rodata (the image runs wherever LK puts it).
CFLAGS="-O2 -ffreestanding -nostdlib -fno-pic -fno-jump-tables -mgeneral-regs-only \
	-mstrict-align -fno-stack-protector -Wall -Wextra $BOARD_DEFS ${EXTRA_CFLAGS:-}"

SRCS="start.S shim.c console.c mmu.c fdt.c loader.c ufs.c probe.c"
CSRCS="shim.c console.c mmu.c fdt.c loader.c ufs.c probe.c"

mkdir -p out
OBJS=""
for f in $SRCS; do
	o="out/${f%.*}.o"
	$CC $CFLAGS -c "$f" -o "$o"
	OBJS="$OBJS $o"
done

# The image runs wherever LK puts it with no relocation pass: the C objects
# must not contain any absolute relocation.
COBJS=$(for f in $CSRCS; do printf 'out/%s.o ' "${f%.*}"; done)
abs=$($READELF -r $COBJS 2>/dev/null | grep -c ABS64 || true)
[ "$abs" = 0 ] || { echo "error: $abs absolute relocations in C objects" >&2; exit 1; }

$CC $CFLAGS -static -T shim.ld -Wl,--build-id=none $LDFLAGS -Wl,-N \
	$OBJS -o out/shim.elf
$OBJCOPY -O binary out/shim.elf out/Image

# LK copies the file; pad to _end so .bss/stacks exist as zeroed bytes.
size=$($NM out/shim.elf | awk '$3=="_end"{print $1}')
[ -n "$size" ] || { echo "error: no _end symbol" >&2; exit 1; }
truncate -s "$((16#$size))" out/Image

echo "shim board      : $BOARD_DEFS"
echo "shim Image      : $(stat -c%s out/Image) bytes (image_size field=0x$size)"
ls -l out/shim.elf out/Image
