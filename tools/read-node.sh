#!/bin/sh
# read-node.sh -- read catalog nodes straight off the raw partition.
#
# v3 fixes an offset bug that made v2 useless: /dev/block/by-name/userdata IS
# the partition, so skipping N blocks inside it lands at partition byte N*4096.
# v2 used the ABSOLUTE block (first_block + image_block), which is 1376256
# blocks (5.25 GiB) too far, and read zeros.
#
#   image block 1734927 (node 19174) -> dd bs=4096 skip=1734927
#   volume header                    -> dd bs=4096 skip=0, then 1024 bytes in

DEV=""
for base in /dev/block/by-name /dev/block/platform/*/by-name /dev/block/bootdevice/by-name; do
    [ -e "$base/userdata" ] && { DEV="$base/userdata"; break; }
done
if [ -z "$DEV" ]; then
    for d in /dev/block/mmcblk0p*; do
        [ -b "$d" ] || continue
        [ "$(cat /sys/class/block/$(basename "$d")/size 2>/dev/null)" = "111132639" ] && { DEV="$d"; break; }
    done
fi
[ -n "$DEV" ] || { echo "CANNOT FIND USERDATA"; exit 1; }

echo "userdata : $DEV"
echo "resolved : $(readlink -f "$DEV" 2>/dev/null)"
echo "size     : $(cat /sys/class/block/$(readlink -f "$DEV" | xargs basename)/size 2>/dev/null) sectors"
echo

read_block() {
    echo "--- image block $1 (partition byte $(( $1 ))*4096)"
    echo "    image expects: $2"
    printf "    card holds   : "
    dd if="$DEV" bs=4096 skip="$1" count=1 2>/dev/null \
        | dd bs=1 count=16 2>/dev/null | od -An -tx1 | tr -d '\n' | sed 's/^ *//'
    echo
}

read_block 1734927 "00 00 4a f9 00 00 00 05 ff 01 00 17 00 00 00 06"
read_block 1734965 "00 00 01 fa 00 00 4a e6 ff 00 00 17 00 00 00 00"
read_block 1735503 "00 00 00 00 00 00 4b 9a 00 00 00 b7 00 00 00 00"
read_block 1735607 "00 00 00 02 00 00 4c 37 ff 00 00 1c 00 00 00 00"

echo
echo "=== volume header, partition block 0 + 1024 bytes ==="
printf "    expect 48 58 (HX) : "
dd if="$DEV" bs=4096 skip=0 count=1 2>/dev/null \
    | dd bs=1 skip=1024 count=16 2>/dev/null | od -An -tx1 | tr -d '\n' | sed 's/^ *//'
echo

echo
echo "=== also the catalog ext4 header, image block 183682 ==="
printf "    expect 00 00 00 00 00 00 00 00 01 00 ... : "
dd if="$DEV" bs=4096 skip=183682 count=1 2>/dev/null \
    | dd bs=1 count=16 2>/dev/null | od -An -tx1 | tr -d '\n' | sed 's/^ *//'
echo
