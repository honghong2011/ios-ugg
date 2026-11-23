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

    # /bin itself is checked alongside /bin/sh: "MISSING bin/sh" is ambiguous
    # between "the directory was never populated" and "the directory exists but
    # this entry does not", and those are different problems.
    for f in sbin/launchd usr/lib/dyld bin bin/sh bin/bash bin/dash \
             System/Library/xpc/launchd.plist \
             System/Library/Caches/com.apple.dyld \
             System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64 \
             private/var private/etc private/preboot; do
        p="$ROOT/$f"
        if [ -e "$p" ]; then
            if [ -f "$p" ]; then
                sz=$(wc -c < "$p" 2>/dev/null || echo "?")
                md=$(stat -c "%a" "$p" 2>/dev/null || echo "?")
                # Numeric ids alongside the names: stat resolves names through the
                # HOST's passwd/group file, so an unmapped gid prints UNKNOWN and
                # looks like a fault when the file is fine. The number always exists.
                ow=$(stat -c "%u:%g(%U:%G)" "$p" 2>/dev/null || echo "?")
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
    # libSystem exists only inside the dyld shared cache, so a missing or truncated
    # cache means launchd cannot resolve its imports even though /usr/lib/dyld is
    # present and executable. Size is the signal here: a populated arm64 cache for
    # iOS 16 is on the order of a GiB, and an empty file would pass any "exists" test.
    cache="$ROOT/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64"
    if [ -f "$cache" ]; then
        csz=$(wc -c < "$cache" 2>/dev/null || echo 0)
        # The magic is the stronger signal. A real cache begins "dyld_v1" followed by
        # the architecture; a 4-byte "dyld" is a stub. Checking size alone would let a
        # stub through if it were padded.
        cmagic=$(dd if="$cache" bs=1 count=7 2>/dev/null | od -An -tc | tr -d " \n")
        echo "# dyld shared cache: ${csz} bytes, magic ${cmagic}"
        if [ "$csz" -lt 104857600 ]; then
            echo "#   ^ WARNING: under 100 MiB. An iOS 16 arm64 cache is ~1 GiB;"
            echo "#     a small one means libSystem will not resolve and launchd"
            echo "#     will fail after exec succeeds."
        fi
        case "$cmagic" in
            *d*y*l*d*_*v*1*) : ;;
            *)
                echo "#   ^ WARNING: magic is not dyld_v1. This is a STUB, not a cache."
                echo "#     Real: Magic = \"dyld_v1  arm64e\" (ipsw) / \"dyld_v1   arm64\" (mido)."
                echo "#     libSystem lives only in this file, so nothing that links"
                echo "#     against it can run -- including launchd."
                ;;
        esac
    else
        echo "# dyld shared cache: ABSENT"
        echo "#   ^ libSystem lives only in the cache; without it launchd cannot"
        echo "#     run even though /usr/lib/dyld exists."
    fi
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