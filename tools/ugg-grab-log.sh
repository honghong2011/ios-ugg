#!/system/bin/sh
# Runs ON THE PHONE (TWRP). Dumps the kernel console log area from userdata.
#
# The kernel keeps the console in a 4 MiB ring, preceded by a 4 KiB header,
# and writes it into the LAST 1025 blocks of 4096 bytes of the partition.
#
# OFF BY 7 SECTORS IF YOU ARE NOT CAREFUL: the kernel addresses the area in
# 4 KiB blocks, so its idea of the partition length is  sectors/8  truncated,
# not  sectors  exactly.  On this phone that drops 7 sectors (3584 bytes), and
# reading "the last 8200 sectors" lands 3584 bytes too far in -- far enough to
# miss the header completely, which decodes as four megabytes of zeros.
# So the skip is computed in whole 4 KiB blocks, exactly like the kernel does.

OUT=/sdcard/sweetlog.bin
LOG_BLOCKS=1025
SPB=8                  # 4096-byte block / 512-byte sector

echo "=== ugg log grab ==="
echo "-- looking for userdata --"

D=""
for c in /dev/block/bootdevice/by-name/userdata \
         /dev/block/by-name/userdata \
         /dev/block/platform/soc/7824900.sdhci/by-name/userdata; do
    if [ -e "$c" ]; then D="$c"; break; fi
done

if [ -z "$D" ]; then
    echo "by-name not usable. Candidate list:"
    ls -l /dev/block/bootdevice/by-name/ 2>/dev/null | head -50
    echo "NO_PARTITION"
    exit 2
fi
echo "   device: $D"

SZ=""
if command -v blockdev >/dev/null 2>&1; then
    SZ=$(blockdev --getsz "$D" 2>/dev/null)
fi
case "$SZ" in
    ''|*[!0-9]*) SZ="" ;;
esac

if [ -z "$SZ" ]; then
    for s in /sys/class/block/*/size; do
        n=$(cat "$s" 2>/dev/null)
        case "$n" in ''|*[!0-9]*) continue;; esac
        b=$(basename "$(dirname "$s")")
        if [ -e "/dev/block/$b" ] && [ "/dev/block/$b" = "$D" ]; then SZ=$n; break; fi
    done
fi

if [ -z "$SZ" ]; then
    echo "   size unreadable, using the known UGG userdata size"
    SZ=$(( 111132639 ))
fi
echo "   sectors: $SZ"

# Same arithmetic as the kernel: whole 4 KiB blocks, truncated.
NB=$(( SZ / SPB ))
SKIP=$(( (NB - LOG_BLOCKS) * SPB ))
COUNT=$(( LOG_BLOCKS * SPB ))

if [ "$SKIP" -lt 0 ]; then echo "partition too small"; exit 4; fi
echo "   blocks: $NB (4 KiB each)"
echo "   skip: $SKIP sectors   count: $COUNT sectors"

echo "-- dd --"
rm -f "$OUT"
dd if="$D" of="$OUT" bs=512 skip=$SKIP count=$COUNT 2>&1
sync

[ -f "$OUT" ] || { echo WRITE_FAILED; exit 5; }
N=$(wc -c < "$OUT")
echo "   wrote: $N bytes (expected $(( COUNT * 512 )))"

echo "-- header --"
head -c 32 "$OUT" | od -An -tx1 -v
echo "-- magic --"
head -c 8 "$OUT"
echo ""
echo DONE
exit 0
