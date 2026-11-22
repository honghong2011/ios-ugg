#!/bin/bash
# ---------------------------------------------------------------------------
# ugg: fetch the CI-built iOS root image and flash it.
#
#   ./flash-root.sh [WORKDIR]        default: $HOME/ugg-flash
#
# Steps:
#   1. download the 7-part artifact from the build-root workflow run
#   2. verify every part against the SHA256SUMS shipped with it
#   3. concatenate into ios16-root.simg and check the exact byte count
#   4. print the fastboot commands (it does NOT flash for you)
#
# Space needed: ~6 GB for the download + ~11.2 GB for the joined image,
# so use a drive with >= 20 GB free. Put it in WORKDIR.
#
# Flashing erases the phone's userdata partition -- that is the approved
# design for ugg (iOS takes over userdata; Android data is lost).
# ---------------------------------------------------------------------------
set -euo pipefail

WORK=${1:-$HOME/ugg-flash}
RUN=${RUN:-43634756880}          # build-root run that produced the 7 parts
EXPECTED=11970598900                # exact size of ios16-root.simg

say() { printf '\n=== %s\n' "$*"; }
die() { printf '\n!!! %s\n' "$*" >&2; exit 1; }

say 'pre-flight'
command -v gh >/dev/null || die 'gh (GitHub CLI) is required: https://cli.github.com'
gh auth status >/dev/null 2>&1 || die 'gh is not logged in; run: gh auth login'
mkdir -p "$WORK" && cd "$WORK"
free_gb=$(df -BG --output=avail . | tail -1 | tr -dc '0-9')
[ "$free_gb" -ge 20 ] || die "need >= 20 GB free here, have ${free_gb} GB"

say "downloading ios16-root-parts from run $RUN (about 5.8 GB)"
rm -rf parts
gh run download "$RUN" -R honghong2011/ios-ugg -n ios16-root-parts -D parts
ls -l parts | head -12

say 'verifying every part'
(cd parts && sha256sum -c SHA256SUMS)

say 'joining'
cat parts/ios16-root.simg.part* > ios16-root.simg
got=$(stat -c%s ios16-root.simg)
echo "ios16-root.simg: $got bytes (expected $EXPECTED)"
[ "$got" = "$EXPECTED" ] || die 'size mismatch: the download or the join is wrong, do not flash'

say 'done'
cat <<EOF

Image ready: $WORK/ios16-root.simg  ($EXPECTED bytes)

Check the partition is big enough, then flash:

  fastboot getvar partition-size:userdata
  fastboot -S 256M flash userdata "$WORK/ios16-root.simg"
  fastboot boot shim-boot-0082-mido.img

The flash takes about 10-15 minutes at 256 MB per packet (mido measured 507 s
for 24 packets at 512M). Do not unplug. If Xiaomi's fastboot hangs afterwards,
hold Power + Volume Down to get back to fastboot.

First boot: the Apple logo can take 4-8 minutes. Do not assume it is dead.
EOF
