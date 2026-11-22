#!/bin/sh
# make-both-images.sh -- build the two boot images the phone tests need.
#
#   ./make-both-images.sh KERNEL_DIR [SHIM_TOUCH] [SHIM_PLAIN]
#
# Produces, in the workspace root:
#
#   shim-boot-0105-touch.img   default shim: BOARD_TOUCH_RAIL=0, i.e. touch driver
#                              compiled but the controller never powered. Use this to
#                              reproduce the current "root mounts, launchd fails" state.
#   shim-boot-0106-touchon.img the touch TEST image: BOARD_TOUCH_RAIL=1, so
#                              input_setup() actually votes the RPM rails, releases
#                              the controller from reset and muxes the I2C pads.
#
# Why both: 0106 is an experiment, not a new default. board.h explains that the rail
# vote is still the prime (unproven) suspect for an SoC reset, so the default image
# must keep it off -- but without 0106 no line of the touch work can be evaluated at
# all, because input_setup() is compiled out in the default.
#
# Fetch the shims from CI:
#   gh run download <run> -R honghong2011/ios-ugg -n shim-ugg -D shim-plain
#   gh workflow run shim-ugg.yml -R honghong2011/ios-ugg --ref ugg-port -f touch_rail=true
#   gh run download <run> -R honghong2011/ios-ugg -n shim-ugg -D shim-touch
set -eu

KERNEL_DIR=${1:?usage: make-both-images.sh KERNEL_DIR [SHIM_TOUCH] [SHIM_PLAIN]}
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)

KERNEL="$KERNEL_DIR/kernel.development.sweet"
[ -f "$KERNEL" ] || { echo "no kernel at $KERNEL" >&2; exit 1; }

SHIM_TOUCH=${2:-$ROOT/shim-touch/Image}
SHIM_PLAIN=${3:-$ROOT/build/img/shimdl7/Image}

for s in "$SHIM_TOUCH" "$SHIM_PLAIN"; do
    [ -f "$s" ] || { echo "no shim at $s" >&2; exit 1; }
done

# The two shims must differ, and only the touch one may contain input_setup's
# strings. Checking this catches the classic mistake of swapping the arguments.
if cmp -s "$SHIM_TOUCH" "$SHIM_PLAIN"; then
    echo "ERROR: the touch and plain shims are the same file." >&2
    echo "       The touch build needs -DBOARD_TOUCH_RAIL=1 (workflow input touch_rail)." >&2
    exit 1
fi
if ! grep -q 'INPUT SETUP: RPM L10 E=' "$SHIM_TOUCH"; then
    echo "ERROR: $SHIM_TOUCH does not contain input_setup's strings," >&2
    echo "       so BOARD_TOUCH_RAIL was not 1 when it was built." >&2
    exit 1
fi
if grep -q 'skipped: RPM LDO vote resets this SoC' "$SHIM_TOUCH"; then
    echo "ERROR: $SHIM_TOUCH still contains the 'skipped' message," >&2
    echo "       so BOARD_TOUCH_RAIL was 0 when it was built." >&2
    exit 1
fi

echo "kernel : $KERNEL"
echo "plain  : $SHIM_PLAIN"
echo "touch  : $SHIM_TOUCH"
echo

touch_and_plain() {
    _out=$1; _shim=$2
    ( cd "$HERE" && ./make-image.sh "$KERNEL" "$_shim" "$_out" >/dev/null ) \
        || { echo "make-image.sh failed for $_out" >&2; exit 1; }
    echo "built $_out"
    sha256sum "$_out"
}

touch_and_plain "$ROOT/shim-boot-0105-touch.img" "$SHIM_PLAIN"
touch_and_plain "$ROOT/shim-boot-0106-touchon.img" "$SHIM_TOUCH"

echo
echo "0105 = default (touch compiled out of the power path); 0106 = touch test."
echo "Boot the test image with:  fastboot boot shim-boot-0106-touchon.img"
