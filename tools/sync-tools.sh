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
FORCE=0
# Note: not "[ ... ] && X" -- under set -e a false test aborts the whole script.
for arg in "$@"; do
    case "$arg" in
        --check) CHECK=1 ;;
        -f|--force) FORCE=1 ;;
        *) echo "usage: $0 [--check] [-f|--force]" >&2; exit 2 ;;
    esac
done

# The tools the user actually runs from that folder. Keep this list short: it is
# what they double-click, not the whole toolbox.
FILES="pull-log.cmd ugg-grab-log.sh sweetlog-decode.ps1 怎么取日志.txt \
read-node.cmd read-node.sh verify-flash.sh verify-card.py simg-info.py \
check-hfs-root.py check-raw.py compare-blocks.py find-bytes.py decode-bad-nodes.py check-log-safety.py"

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
            # A file in the destination that nobody listed is either genuinely
            # obsolete or a tool someone added without updating FILES. This used to
            # delete it outright, which silently destroyed a tool added earlier the
            # same session -- the mirror is for the user, the repo is the source of
            # truth, so guessing 'obsolete' is the wrong default.
            #
            # Report it and leave it alone. -f/--force removes it, for when the
            # removal really is intended.
            if [ "$FORCE" = 1 ]; then
                rm -f "$d"
                echo "removed unlisted $b (--force)"
            else
                echo "UNLISTED $b (left in place; add it to FILES, or pass --force to remove)"
                drift=1
            fi
            ;;
    esac
done

if [ "$CHECK" = 1 ]; then
    [ "$drift" = 0 ] && echo "取日志工具/ is in sync"
    exit "$drift"
fi
echo "done"
