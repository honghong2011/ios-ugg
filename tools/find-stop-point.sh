#!/bin/bash
# find-stop-point.sh -- binary-search the card for WHERE the flash stopped.
#
#   ./find-stop-point.sh ios16-root.simg
#   ./find-stop-point.sh ios16-root.simg --low-mb 800 --high-mb 4500
#
# Why this exists
# ---------------
# The 0104 console brackets the damage: every node below 0.839 GiB was good, the first
# bad node is at 4.342 GiB, and the damage is contiguous from there to the end of the
# catalog. One corrupt image part was ruled out, because the damage spans 2.29 GiB and
# crosses a part boundary. What fits is a write that stopped early: a clean prefix and
# a stale contiguous tail.
#
# That leaves exactly one number worth having: the address where writing stopped. It
# separates three very different faults -- a transport that gave up, a buffer limit at
# a round number, or a tail that was never written at all.
#
# Bisecting is the cheap way: each probe compares a small window against the image, so
# about 20 probes cover 16 GiB to within a few megabytes, and each probe pulls only a
# few MB off the phone. It is read-only: verify-card.py reads, nothing is written.
set -u

IMG=${1:?usage: find-stop-point.sh IMAGE [--low-mb N] [--high-mb N]}
shift

LOW=0
HIGH=16000          # MiB; the image is 16384 MiB, stop just below the end
PROBE_MB=4          # window compared per probe
while [ $# -gt 0 ]; do
    case "$1" in
        --low-mb)   LOW=$2; shift 2 ;;
        --high-mb)  HIGH=$2; shift 2 ;;
        --probe-mb) PROBE_MB=$2; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

HERE=$(cd "$(dirname "$0")" && pwd)
VC="$HERE/verify-card.py"
[ -f "$VC" ] || { echo "verify-card.py not found next to this script" >&2; exit 1; }
[ -f "$IMG" ] || { echo "no image at $IMG" >&2; exit 1; }

PY=python3
command -v python3 >/dev/null 2>&1 || PY=python

# probe MB: 0 when that window matches the image, 1 when it differs.
probe() {
    if "$PY" "$VC" "$IMG" --start-mb "$1" --chunk-mb "$PROBE_MB" >/dev/null 2>&1; then
        echo 0
    else
        echo 1
    fi
}

echo "image     : $IMG"
echo "searching : ${LOW} .. ${HIGH} MiB, ${PROBE_MB} MiB probes"
echo
echo "anchors first -- this should reproduce the bracket from the kernel log:"
for mb in 700 800 3400 4400 6300; do
    if [ "$(probe $mb)" = 0 ]; then
        echo "  ${mb} MiB  matches"
    else
        echo "  ${mb} MiB  DIFFERS"
    fi
done
echo

# If the low anchor already differs, bisecting from it is meaningless: the fault is
# earlier than assumed. Say so rather than returning a confident wrong answer.
if [ "$(probe $LOW)" != 0 ]; then
    echo "ERROR: ${LOW} MiB already differs, so the clean prefix is shorter than assumed." >&2
    echo "       Re-run with --low-mb 0 to search the whole image." >&2
    exit 1
fi
if [ "$(probe $HIGH)" = 0 ]; then
    echo "The window at ${HIGH} MiB matches, so the damage does not reach that far."
    echo "Lower --high-mb and re-run, or use verify-card.py --map for a region report."
    exit 1
fi

echo "bisecting between ${LOW} (matches) and ${HIGH} (differs)..."
while [ $((HIGH - LOW)) -gt $PROBE_MB ]; do
    MID=$(( (LOW + HIGH) / 2 ))
    if [ "$(probe $MID)" = 0 ]; then
        LOW=$MID
    else
        HIGH=$MID
    fi
    echo "  low=${LOW} high=${HIGH} MiB"
done

echo
echo "=== result ==="
echo "first differing window starts between ${LOW} and ${HIGH} MiB"
echo "that is image byte offset $(( LOW * 1024 * 1024 )) .. $(( HIGH * 1024 * 1024 ))"
echo
echo "What the number means:"
echo "  * a round value (1024, 2048, 4096 MiB) -> a size limit in a transport or buffer"
echo "  * right at a part boundary (1717, 3433, 5149 ...) -> the transfer handled that"
echo "    many parts and then stopped"
echo "  * anything else -> the connection or the device gave up mid-write"