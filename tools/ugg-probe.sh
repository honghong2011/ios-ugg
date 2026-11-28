#!/system/bin/sh
# Runs ON THE PHONE (TWRP). Reads 4 KiB block ranges of userdata into files under
# /sdcard, which the PC then pulls.
#
# Why not 'adb exec-out dd': the log grabber on this phone already uses
#   push script -> run on phone -> dd to /sdcard -> adb pull
# and that is the path that demonstrably works. exec-out returned empty for every
# probe when tried directly.
#
# Usage: sh ugg-probe.sh OUTDIR BLOCK [BLOCK ...]

OUTDIR=$1
shift
mkdir -p "$OUTDIR"

D=
for c in /dev/block/bootdevice/by-name/userdata /dev/block/by-name/userdata /dev/block/platform/soc/7824900.sdhci/by-name/userdata; do
    if [ -e "$c" ]; then D=$c; break; fi
done
if [ -z "$D" ]; then
    echo NO_PARTITION
    ls -l /dev/block/bootdevice/by-name/ 2>/dev/null | head -20
    exit 2
fi
echo device=$D

BS=4096
CNT=16

for b in $*; do
    case "$b" in ''|*[!0-9]*) continue;; esac
    f=$OUTDIR/b$b.bin
    rm -f "$f"
    dd if=$D of="$f" bs=$BS skip=$b count=$CNT 2>/dev/null
    sync
    n=$(wc -c < "$f" 2>/dev/null)
    echo "block $b -> $n bytes"
done

echo DONE
exit 0