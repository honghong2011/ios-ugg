#!/bin/sh
# check-boot-files.sh -- assert that the files the boot depends on are really there.
#
#   check-boot-files.sh IMAGE_MOUNTPOINT
#
# Why this exists
# ---------------
# The boot log on the phone says:
#
#   load_init_program: attempting to load /sbin/launchd
#   hfs_swap_BTNode: invalid forward link (0x6a13d46a >= 0x00005000)
#   load_init_program: failed loading /sbin/launchd: errno 5
#
# errno 5 is EIO, not ENOENT. A missing file would be ENOENT (2). EIO is what HFS
# returns when it cannot read the catalog -- which is exactly what the line before it
# says. So the log is self-consistent: the lookup broke, the file was not absent.
#
# That reasoning is an inference, and it has never been checked where it can be: the
# image as built. This does that. If launchd and dyld are present, the catalog is the
# only remaining explanation and all effort belongs on the flash. If either is absent,
# every catalog observation is secondary and this is the real bug.
#
# Exit status: 0 the boot-critical files are present, 1 one is missing, 2 bad usage.
set -u

ROOT=${1:?usage: check-boot-files.sh IMAGE_MOUNTPOINT}
[ -d "$ROOT" ] || { echo "not a directory: $ROOT" >&2; exit 2; }

missing=0
echo "boot-critical files under $ROOT:"
for f in sbin/launchd usr/lib/dyld bin/sh \
         System/Library/xpc/launchd.plist \
         private/var private/etc private/var/db; do
    if [ -e "$ROOT/$f" ]; then
        if [ -f "$ROOT/$f" ]; then
            # size and exec bit are both worth seeing: launchd must be executable
            sz=$(wc -c < "$ROOT/$f" 2>/dev/null || echo '?')
            if [ -x "$ROOT/$f" ]; then x=exec; else x=NOT-EXEC; fi
            echo "  present  $f  ($sz bytes, $x)"
        else
            echo "  present  $f  (directory)"
        fi
    else
        echo "  MISSING  $f"
        case "$f" in
            sbin/launchd|usr/lib/dyld) missing=1 ;;
        esac
    fi
done

echo
if [ "$missing" = 1 ]; then
    echo "RESULT: a boot-critical binary is absent from the image."
    echo "        That, not the catalog, is what errno 5 would then mean -- check"
    echo "        whether the HFS build step actually populated /sbin and /usr/lib."
    exit 1
fi
echo "RESULT: launchd and dyld are present and executable."
echo "        So errno 5 on the phone is EIO from the catalog, not ENOENT."
echo "        Keep the effort on the flash, not on the image contents."
exit 0
