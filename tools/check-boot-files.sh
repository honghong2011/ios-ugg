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
#
# A note on where this can be trusted: the mode check parses the octal mode from
# stat(1) instead of using 'test -x', because on MSYS (the Windows shell used to
# develop this) -x returns TRUE for a 644 file. That was not hypothetical -- it made
# this script report a non-executable launchd as fine. Windows filesystems also do not
# carry POSIX modes at all, so on that host the mode column is not meaningful and this
# script can only be validated for real on Linux, which is where CI runs it.
set -u

ROOT=${1:?usage: check-boot-files.sh IMAGE_MOUNTPOINT}
[ -d "$ROOT" ] || { echo "not a directory: $ROOT" >&2; exit 2; }

missing=0
echo "boot-critical files under $ROOT:"
# /bin is listed next to /bin/sh so the report can say whether the directory was
# never populated or just lacks this entry -- those are different faults, and
# "MISSING bin/sh" alone cannot tell them apart.
for f in sbin/launchd usr/lib/dyld bin bin/sh bin/bash \
         System/Library/xpc/launchd.plist \
         private/var private/etc private/var/db; do
    # Check for a SYMLINK first. iOS makes /bin/sh a link to /bin/bash, and the
    # kernel resolves that inside the mount while a userspace stat follows an
    # absolute target against the HOST root. So [ -e ] alone reports nonsense for
    # linked entries: it can say MISSING for a perfectly good image, or find the
    # runner's own /bin/bash and say present. A symlink counts as present; its
    # target is reported so the reader can judge it.
    if [ -L "$ROOT/$f" ]; then
        printf "  present  %-30s (symlink -> %s)\n" "$f" "$(readlink "$ROOT/$f")"
        continue
    fi
    if [ -e "$ROOT/$f" ]; then
        if [ -f "$ROOT/$f" ]; then
            # Size, mode and ownership all matter. mido's notes record the requirement
            # for these two as 'root:wheel 0755': launchd is executed as PID 1, so an
            # unexpected owner or a missing exec bit is a silent failure that looks
            # exactly like a filesystem problem later.
            sz=$(wc -c < "$ROOT/$f" 2>/dev/null || echo '?')
            # Do NOT use "test -x". On MSYS (this project's Windows shell) -x returns
            # true for a file with mode 644, so a launchd missing its exec bit would
            # pass silently -- the exact silent failure this check exists to catch.
            # Decide from the numeric mode, and treat unknown as unknown, not as fine.
            mode=$(stat -c '%a' "$ROOT/$f" 2>/dev/null || echo '')
            # ids first: names come from the host's group file and can be unmapped.
            owner=$(stat -c '%u:%g(%U:%G)' "$ROOT/$f" 2>/dev/null || echo '?')
            # Is this entry supposed to be executable? A plist at 644 is CORRECT, and
            # printing 'NOT-EXEC' next to it is noise that trains the reader to ignore
            # the column -- which is how a real NOT-EXEC gets missed.
            need_exec=0
            case "$f" in
                sbin/launchd|usr/lib/dyld) need_exec=1 ;;
            esac
            case "$mode" in
                '')     x='UNKNOWN-MODE' ;;
                *[1357]) x='exec' ;;
                *)      if [ "$need_exec" = 1 ]; then x='NOT-EXEC'; else x='data'; fi ;;
            esac
            echo "  present  $f  (${sz} bytes, mode ${mode}, $owner, ${x})"
            if [ "$need_exec" = 1 ] && [ "$x" = 'NOT-EXEC' ]; then
                echo "           ^ NOT EXECUTABLE: the kernel cannot exec this"
                missing=1
            fi
        else
            echo "  present  $f  (directory)"
        fi
    else
        echo "  MISSING  $f"
        case "$f" in
            sbin/launchd|usr/lib/dyld) missing=1 ;;
            bin/sh|bin/bash|bin/dash)
                # iOS removed bash at iOS 11, and on iOS launchd starts Mach-O
                # binaries from ProgramArguments -- not shell scripts. A missing
                # /bin/sh is therefore a property of iOS, not a defect, and it does
                # not stop launchd from running.
                #
                # This used to warn that "launchd runs daemons via /bin/sh", a
                # desktop-OS assumption that is wrong here. A warning that is wrong
                # trains the reader to ignore the warnings that are right.
                echo "           note: absent, as expected on iOS (launchd starts"
                echo "                 Mach-O binaries, not shell scripts)."
                ;;
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
