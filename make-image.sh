#!/bin/bash
# ---------------------------------------------------------------------------
# ugg: assemble a bootable image from a CI kernel   (runs on Windows/MSYS or Linux)
#
#   ./make-image.sh KERNEL [SHIM_IMAGE] [OUT]
#
#   KERNEL       kernel.development.ugg downloaded from the xnu CI artifact
#   SHIM_IMAGE   shim/out/Image downloaded from the shim-ugg CI artifact
#                (default: fetch the newest one with gh)
#   OUT          default build/img/shim-boot-ugg.img
#
# Steps: regenerate the ugg ADT -> pack the payload (kernel + ADT + boot-args)
#        -> append the payload to the shim Image -> gzip -> append the DTB
#        bundle -> boot.img v0. Then print the size, the sha256 and the exact
#        fastboot command.
#
# The DTB bundle is a device dump and never lives in git: point DTBUNDLE at
# your own, or let it default to device-dumps/msm8937-dtbundle.bin.
# ---------------------------------------------------------------------------
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)

KERNEL=${1:?usage: make-image.sh KERNEL [SHIM_IMAGE] [OUT]}
SHIM=${2:-}
OUT=${3:-$ROOT/build/img/shim-boot-ugg.img}
DTBUNDLE=${DTBUNDLE:-$ROOT/device-dumps/msm8937-dtbundle.bin}

HERE2=$ROOT/ugg
mkdir -p $(dirname "$OUT") $ROOT/build/img

[ -f "$KERNEL" ] || { echo "no kernel at $KERNEL" >&2; exit 1; }
[ -f "$DTBUNDLE" ] || { echo "no DTB bundle at $DTBUNDLE (a device dump, not in git)" >&2; exit 1; }

# 1) Apple device tree for this board
echo "=== ADT"
python $HERE2/tools/mkadt_ugg.py $ROOT/build/img/ugg.adt

# 2) payload = kernel + ADT + boot-args
#    CPU rendering only: no GPU, no MDP zero copy. cpus=1 until the EL0 LSE
#    emulator has a stop-the-world (mido's note: the emulator is not atomic
#    against other cores).
CMDLINE="debug=0xc serial=3 cpus=1 keepsyms=1 -v"
# No -enable_kprintf_spam: mido found that its lines keep drawing over the
# GUI after the mute, so they dropped it before reaching the home screen.
CMDLINE="$CMDLINE -noprogress"
# ROOTRW=0 mounts the iOS root read-only. That suppresses the journal
# initialisation and every metadata write HFS would otherwise do at mount, so a
# boot that fails read-only cannot have been corrupted by our own write path.
CMDLINE="$CMDLINE rd=ufsroot0 ufsrw=1 rootrw=${ROOTRW:-1}"
CMDLINE="$CMDLINE unentitled_ios_sim_launch=1 ignition_level=1"
CMDLINE="$CMDLINE wdt_test=no_user_checkin wdt=-1 launchd_unsecure_cache=1"
# 30 Hz, not 60: mido A/B-tested it -- at 60 apps start but never appear,
# at 30 they open (the panel copy starves the CPU). See PORTING_LOG 981.
CMDLINE="$CMDLINE sweetfb_noconsole=1 sweetfb_hz=30"
# Draw the kernel console at 2x (16x32 cells, 45x40). The upstream cell is
# 8x16, i.e. one-pixel strokes on this 720p panel: legible on the glass, but
# not resolvable in a photograph, which is how every boot result is read here.
# ugg_vcscale=1 restores upstream geometry without a rebuild.
CMDLINE="$CMDLINE ugg_vcscale=2"
# EXTRA_CMDLINE lets one shim+kernel pair produce both a normal image and the
# display selftest image (EXTRA_CMDLINE=ugg_fbtest=1), which holds the colour
# bars on screen long enough to photograph.
CMDLINE="$CMDLINE ${EXTRA_CMDLINE:-}"
echo "=== payload"
python $HERE2/tools/mkpayload.py "$KERNEL" $ROOT/build/img/ugg.adt \
    $ROOT/build/img/payload.bin --cmdline "$CMDLINE"

# 3) shim Image: from the argument, else the newest shim-ugg artifact
if [ -z "$SHIM" ]; then
    RUN=$(gh run list -R honghong2011/ios-ugg --workflow=shim-ugg.yml \
        --limit 1 --status success --json databaseId --jq '.[0].databaseId' 2>/dev/null || true)
    if [ -n "$RUN" ]; then
        echo "=== fetching the shim from run $RUN"
        rm -rf $ROOT/build/img/shimdl && mkdir -p $ROOT/build/img/shimdl
        gh run download "$RUN" -R honghong2011/ios-ugg -n shim-ugg -D $ROOT/build/img/shimdl
        SHIM=$ROOT/build/img/shimdl/Image
    fi
fi
[ -n "$SHIM" ] && [ -f "$SHIM" ] || { echo 'no shim Image; pass one or let gh fetch it' >&2; exit 1; }

# 4) boot.img
echo "=== pack"
python $HERE2/tools/pack-ugg.py --kernel "$SHIM" --payload $ROOT/build/img/payload.bin \
    --dtbundle "$DTBUNDLE" --out "$OUT"

echo "=== result"
ls -l "$OUT"
command -v sha256sum >/dev/null && sha256sum "$OUT"
cat <<EOF

Boot it (RAM only, nothing is flashed):

  fastboot boot $OUT

If it comes back to fastboot within ~2 minutes, the shim refused the payload
and printed the reason on screen; if it stays away, XNU is running.
EOF
