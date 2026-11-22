#!/bin/sh
# write-image.sh -- write the iOS root image straight to userdata from TWRP.
#
# fastboot proved unreliable on this phone. Verified with dd reading the raw
# partition: block 1734927 holds 6a13d46a on the card while the same offset in
# the file holds 00004af9. The volume header (block 0) is correct, so the
# beginning lands and the data diverges later.
#
# Usage, from the PC:
#   adb push ios16-root.img /sdcard/
#   adb push write-image.sh /tmp/
#   adb shell sh /tmp/write-image.sh /sdcard/ios16-root.img
#
# Expect roughly 1-2 hours over USB2. Re-runnable.

SRC="$1"
CHUNK_KB=262144

DEV=""
for base in /dev/block/by-name /dev/block/platform/*/by-name /dev/block/bootdevice/by-name; do
    [ -e "$base/userdata" ] && { DEV="$base/userdata"; break; }
done
[ -n "$DEV" ] || { echo "CANNOT FIND USERDATA"; exit 1; }

[ -f "$SRC" ] || { echo "no such file: $SRC"; exit 1; }

SIZE=$(stat -c %s "$SRC" 2>/dev/null)
[ -n "$SIZE" ] || SIZE=$(wc -c < "$SRC")
TOTAL_KB=$((SIZE / 1024))

echo "source : $SRC ($SIZE bytes, $TOTAL_KB KiB)"
echo "target : $DEV -> $(readlink -f "$DEV" 2>/dev/null)"
echo

OFF_KB=0
N=0
while [ "$OFF_KB" -lt "$TOTAL_KB" ]; do
    N=$((N + 1))
    REMAIN=$((TOTAL_KB - OFF_KB))
    COUNT=$CHUNK_KB
    [ "$REMAIN" -lt "$COUNT" ] && COUNT=$REMAIN
    echo "--- chunk $N : offset $OFF_KB KiB, $COUNT KiB"
    dd if="$SRC" of="$DEV" bs=1024 skip="$OFF_KB" seek="$OFF_KB" count="$COUNT" conv=notrunc 2>&1 | tail -1
    OFF_KB=$((OFF_KB + COUNT))
done

echo
echo "=== sync ==="
sync

echo
echo "=== verifying the four catalog nodes ==="
for blk in 1734927 1734965 1735503 1735607; do
    printf "  block %-8s : " "$blk"
    dd if="$DEV" bs=4096 skip="$blk" count=1 2>/dev/null \
        | dd bs=1 count=8 2>/dev/null | od -An -tx1 | tr -d '\n' | sed 's/^ *//'
    echo
done
echo
echo "expected:"
echo "  1734927 : 00 00 4a f9 00 00 00 05"
echo "  1734965 : 00 00 01 fa 00 00 4a e6"
echo "  1735503 : 00 00 00 00 00 00 4b 9a"
echo "  1735607 : 00 00 00 02 00 00 4c 37"
echo
echo "if these match, the card now holds the image and the kernel can be booted"
