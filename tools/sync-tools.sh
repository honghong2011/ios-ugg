#!/bin/sh
# sync-tools.sh -- keep 取日志工具/ identical to the canonical copies in ugg/tools/.
#
# Why: the user-facing folder is a convenience copy of a few repo tools, and the
# two drifted apart more than once (a stale verify-flash.sh with the wrong
# offsets, a deleted writer still sitting there). Copies are one-way: ugg/tools/
# is the source of truth, 取日志工具/ is the mirror. Run this before handing the
# folder to the user.
#
#   ./sync-tools.sh          # copy + report
#   ./sync-tools.sh --check  # report only, exit 1 if drifted (for CI)
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$HERE/ugg/tools
DST=$HERE/取日志工具
CHECK=0
# Note: not "[ ... ] && X" -- under set -e a false test aborts the whole script.
if [ "${1:-}" = "--check" ]; then
    CHECK=1
fi

# The tools the user actually runs from that folder. Keep this list short: it is
# what they double-click, not the whole toolbox.
FILES="pull-log.cmd ugg-grab-log.sh sweetlog-decode.ps1 怎么取日志.txt \
read-node.cmd read-node.sh verify-flash.sh verify-card.py \
check-hfs-root.py check-raw.py compare-blocks.py find-bytes.py"

[ -d "$DST" ] || { echo "missing $DST" >&2; exit 1; }

drift=0
for f in $FILES; do
    s=$SRC/$f
    d=$DST/$f
    if [ ! -f "$s" ]; then
        echo "!! $f: no canonical copy in ugg/tools" >&2
        drift=1
        continue
    fi
    if [ -f "$d" ] && cmp -s "$s" "$d"; then
        continue
    fi
    if [ "$CHECK" = 1 ]; then
        echo "DRIFT $f"
        drift=1
    else
        cp -f "$s" "$d"
        echo "synced $f"
    fi
done

# Anything in the mirror that the canonical folder no longer has is stale -- that
# is how write-image.* survived its own deletion.
for d in "$DST"/*; do
    [ -f "$d" ] || continue
    b=$(basename "$d")
    case " $FILES " in
        *" $b "*) ;;
        *)
            if [ "$CHECK" = 1 ]; then
                echo "STALE $b"
                drift=1
            else
                rm -f "$d"
                echo "removed stale $b"
            fi
            ;;
    esac
done

if [ "$CHECK" = 1 ]; then
    [ "$drift" = 0 ] && echo "取日志工具/ is in sync"
    exit "$drift"
fi
echo "done"
