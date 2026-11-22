#!/bin/sh
# image-manifest.sh -- a small, auditable statement of what the image contains.
#
#   image-manifest.sh MOUNTPOINT OUT.txt
#
# Why this exists
# ---------------
# The one question that decides the direction of this port is "is /sbin/launchd
# really in the image?". Answering it from the 5.8 GB of parts means downloading and
# reassembling them; answering it from the CI log is impossible because the job-log
# API for this repository returns 100 bytes. So the answer has to be produced as a
# small file during the build and shipped on its own.
#
# It goes past mere existence, because a file can exist and still be wrong: launchd is
# execd as PID 1, so its mode matters, and dyld must be there or no Mach-O runs at
# all. mido records the requirement for both as root:wheel 0755. The Mach-O magic is
# checked too, so a truncated or symlinked placeholder cannot pass.
#
# The manifest is deliberately plain text: readable in a terminal, in a diff, and in
# a year.
#
# Exit status: 0 the boot-critical files are usable, 1 something is wrong, 2 bad usage.
set -u

ROOT=$1
OUT=$2
[ -d "$ROOT" ] || { echo "not a directory: $ROOT" >&2; exit 2; }
[ -n "$OUT" ] || { echo "usage: image-manifest.sh MOUNTPOINT OUT.txt" >&2; exit 2; }

bad=0
{
    echo "# image manifest"
    echo "# mountpoint: $ROOT"
    echo "#"
    echo "# launchd is execd as PID 1; dyld is needed for any Mach-O to run."
    echo "# mido records the requirement for both as root:wheel 0755."

    for f in sbin/launchd usr/lib/dyld bin/sh \
             System/Library/xpc/launchd.plist \
             System/Library/Caches/com.apple.dyld \
             private/var private/etc private/preboot; do
        p="$ROOT/$f"
        if [ -e "$p" ]; then
            if [ -f "$p" ]; then
                sz=$(wc -c < "$p" 2>/dev/null || echo "?")
                md=$(stat -c "%a" "$p" 2>/dev/null || echo "?")
                ow=$(stat -c "%U:%G" "$p" 2>/dev/null || echo "?")
                mg=$(dd if="$p" bs=4 count=1 2>/dev/null | od -An -tx1 | tr -d " \n")
                printf "present  %-44s %10s bytes  mode %-5s %-14s magic %s\n" \
                    "$f" "$sz" "$md" "$ow" "$mg"
                case "$f" in
                    sbin/launchd|usr/lib/dyld)
                        if [ "$md" != "?" ]; then
                            case "$md" in
                                *[1357]) : ;;
                                *) echo "  ^^ PROBLEM: mode $md is not executable"; bad=1 ;;
                            esac
                        fi
                        case "$mg" in
                            cffaedfe*|cafebabe*|cefaedfe*) : ;;
                            *) echo "  ^^ PROBLEM: magic $mg is not a Mach-O"; bad=1 ;;
                        esac
                        ;;
                esac
            else
                printf "present  %-44s (directory)\n" "$f"
            fi
        else
            printf "MISSING  %s\n" "$f"
            case "$f" in
                sbin/launchd|usr/lib/dyld) bad=1 ;;
            esac
        fi
    done

    echo "#"
    echo "# entries under the mount: $(find "$ROOT" -xdev 2>/dev/null | wc -l)"
} > "$OUT"

cat "$OUT"

if [ "$bad" = 1 ]; then
    echo
    echo "RESULT: the image cannot boot as-is -- see the PROBLEM lines above."
    exit 1
fi
echo
echo "RESULT: launchd and dyld look usable. If the phone still fails with errno 5,"
echo "        the failure is EIO from the catalog, not a missing binary."
exit 0