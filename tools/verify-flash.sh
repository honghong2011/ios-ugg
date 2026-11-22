#!/bin/sh
# verify-flash.sh -- read catalog nodes straight off the card and compare with
# what the image holds. Run it in TWRP right after a flash, before booting.
#
#   adb push verify-flash.sh /tmp/ && adb shell sh /tmp/verify-flash.sh
#
# WHY THE OFFSETS ARE PARTITION-RELATIVE
# --------------------------------------
# /dev/block/by-name/userdata IS the partition, so block N of the image lives at
# byte N*4096 *inside that device*. An earlier version of this script used the
# absolute disk byte (first_block + N, i.e. +1376256 blocks) -- that is right for
# /dev/block/mmcblk0 and wrong for every by-name path, which is what the lookup
# below finds first. It read 5.25 GiB past the node and reported garbage.
#
# The four nodes are the ones HFS rejects first when the card is wrong:
#   node 19174 -> image block 1734927
#   node 19193 -> image block 1734965
#   node 19462 -> image block 1735503
#   node 19514 -> image block 1735607
#
# It also prints the volume header (partition block 0, +1024) and, with a second
# argument, ANY image block you name -- that is how you chase a suspected shift:
#
#   adb shell sh /tmp/verify-flash.sh 686351

set -u

DEV=""
for base in /dev/block/by-name /dev/block/platform/*/by-name \
            /dev/block/bootdevice/by-name /dev/block/platform/*/*/by-name; do
    [ -e "$base/userdata" ] && { DEV="$base/userdata"; break; }
done
if [ -z "$DEV" ]; then
    for d in /dev/block/mmcblk0p*; do
        [ -b "$d" ] || continue
        if [ "$(cat /sys/class/block/$(basename "$d")/size 2>/dev/null)" = "111132639" ]; then
            DEV="$d"
            break
        fi
    done
fi
[ -n "$DEV" ] || { echo "CANNOT FIND USERDATA"; exit 1; }

echo "userdata : $DEV"
echo "resolved : $(readlink -f "$DEV" 2>/dev/null)"
echo "size     : $(cat /sys/class/block/$(basename "$(readlink -f "$DEV" 2>/dev/null || echo "$DEV")")/size 2>/dev/null) sectors"
echo

# dump IMAGE_BLOCK EXPECTED_HEX [LABEL] -- offsets are INSIDE the partition.
dump() {
    echo "--- image block $1$3"
    echo "    image expects: $2"
    printf "    card  holds  : "
    dd if="$DEV" bs=4096 skip="$1" count=1 2>/dev/null \
        | dd bs=1 count=16 2>/dev/null | od -An -tx1 | tr -d '\n' | sed 's/^ *//'
    echo
}

# These expectations came from one particular image download, and the layout of
# the catalog changes whenever the image is rebuilt: the volume CI builds now puts
# node 19174 at block 1735048, not 1734927. Checking a fresh flash against the
# numbers below would then report a mismatch on a perfectly good write -- and that
# mismatch looks exactly like the fault this script exists to find.
#
# So they are only a fallback. Generate the correct ones from the image you actually
# flashed and pass the file as the first argument:
#
#   python ugg/tools/emit-flash-expectations.py ios16-root.simg > expect.txt
#   adb push expect.txt /tmp/ && adb push verify-flash.sh /tmp/
#   adb shell sh /tmp/verify-flash.sh /tmp/expect.txt
#
# Without a file the script still runs, but says plainly which layout it assumes.
EXPECT_FILE=
for a in "$@"; do
    case "$a" in
        /*.txt|*.txt) EXPECT_FILE=$a ;;
    esac
done

if [ -n "$EXPECT_FILE" ] && [ -f "$EXPECT_FILE" ]; then
    echo "expectations from: $EXPECT_FILE"
    # Lines look like: dump BLOCK "HEX16" "  (node N, kind)"
    while IFS= read -r line; do
        case "$line" in
            dump\ *)
                # 'dump BLOCK "HEX" "label"' -> pull each field out separately.
                blk=$(echo "$line" | sed -n "s/^dump \\([0-9][0-9]*\\) .*/\\1/p")
                hex=$(echo "$line" | sed -n "s/^dump [0-9][0-9]* \"\([^\"]*\)\".*/\\1/p")
                lbl=$(echo "$line" | sed -n "s/^dump [0-9][0-9]* \"[^\"]*\" *//p")
                dump "$blk" "$hex" "  $lbl"
                ;;
        esac
    done < "$EXPECT_FILE"
else
    if [ -n "$EXPECT_FILE" ]; then
        echo "WARNING: no expectations file at $EXPECT_FILE -- using built-in values,"
        echo "         which match ONE particular image build. If the card disagrees,"
        echo "         generate the file with emit-flash-expectations.py before blaming"
        echo "         the flash."
        echo
    fi
dump 1734927 "00 00 4a f9 00 00 00 05 ff 01 00 17 00 00 00 06" "  (node 19174, leaf)"
dump 1734965 "00 00 01 fa 00 00 4a e6 ff 00 00 17 00 00 00 00" "  (node 19193, leaf)"
dump 1735503 "00 00 00 00 00 00 4b 9a 00 00 00 b7 00 00 00 00" "  (node 19462, index)"
dump 1735607 "00 00 00 02 00 00 4c 37 ff 00 00 1c 00 00 00 00" "  (node 19514, leaf)"
fi

echo
echo "=== volume header: partition block 0, 1024 bytes in ==="
printf "    expect 48 58 00 05 (HFSX): "
dd if="$DEV" bs=4096 skip=0 count=1 2>/dev/null \
    | dd bs=1 skip=1024 count=16 2>/dev/null | od -An -tx1 | tr -d '\n' | sed 's/^ *//'
echo

# Any extra block number(s) on the command line: dump them too. Use this to test
# the 4 GiB-shift theory -- if the card at 1734927 holds the image's block 686351
# (1734927 - 1048576), the writer wrapped its byte offset at 2^32.
for extra in "$@"; do
    dump "$extra" "(whatever the image has there)" "  (requested)"
done

echo
cat <<'EOF'
Compare against the image on the PC:
    python check-hfs-root.py --node 19174 19193 19462 19514 ios16-root.simg
Both sides must match byte for byte. If the card is wrong, say so and stop --
booting on top of a bad card only produces a misleading kernel log.
EOF
