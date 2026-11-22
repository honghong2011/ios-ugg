#!/bin/sh
# verify-flash.sh -- read back four catalog nodes from the raw block device.
#
# Why: the kernel reads 0x6a13d46a where the image has 0x00004af9 at the SAME
# block. check-hfs-root.py certifies the image, and the extent map the kernel
# prints matches the image exactly, so the divergence is in the bytes on the
# card. Reading them back directly decides whether the data ever arrived.
#
# Run it in TWRP after flashing, before booting:
#
#   adb push verify-flash.sh /tmp/
#   adb shell sh /tmp/verify-flash.sh
#
# Expected first 14 bytes of each node (image side):
#   19174  00 00 4a f9 00 00 00 05 ff 00 00 17 00 00
#   19193  00 00 01 fa 00 00 4a e6 ff 00 00 17 00 00
#   19462  00 00 00 00 00 00 4b 9a 00 00 00 b7 00 00
#   19514  00 00 00 02 00 00 4c 37 ff 00 00 1c 00 00
#
# Anything else means the card does not hold what the image holds.

set -u

# find the userdata block device
DEV=""
for d in /dev/block/sda38 /dev/block/mmcblk0p38 /dev/block/by-name/userdata \
         /dev/block/bootdevice/by-name/userdata; do
    if [ -e "$d" ]; then DEV="$d"; break; fi
done
if [ -z "$DEV" ]; then
    for d in /dev/block/sda* /dev/block/mmcblk0p*; do
        [ -e "$d" ] || continue
        if [ "$(cat /sys/class/block/$(basename $d)/size 2>/dev/null)" = "111132639" ]; then
            DEV="$d"; break
        fi
    done
fi
[ -n "$DEV" ] || { echo "cannot find the userdata device"; exit 1; }
echo "device: $DEV"
echo "size  : $(cat /sys/class/block/$(basename $DEV)/size 2>/dev/null) sectors"
echo

dump() {          # dump NODE ABS_BYTE EXPECTED
    echo "--- node $1 at byte $2"
    echo "    expect: $3"
    printf "    card  : "
    # dd prints to stdout; od reads it. 14 bytes is one od line.
    dd if="$DEV" bs=1 skip="$2" count=14 2>/dev/null | od -An -tx1 | tr -d '\n' | sed 's/^ *//'
    echo
}

dump 19174 12743405568 "00 00 4a f9 00 00 00 05 ff 00 00 17 00 00"
dump 19193 12743561216 "00 00 01 fa 00 00 4a e6 ff 00 00 17 00 00"
dump 19462 12745764864 "00 00 00 00 00 00 4b 9a 00 00 00 b7 00 00"
dump 19514 12746190848 "00 00 00 02 00 00 4c 37 ff 00 00 1c 00 00"

echo
echo "Also dump the same offsets from the image on your PC with"
echo "  python check-hfs-root.py --node 19174 19193 19462 19514 .simg"
echo "The two must match byte for byte."
