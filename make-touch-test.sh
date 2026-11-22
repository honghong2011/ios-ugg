#!/bin/sh
# make-touch-test.sh -- build a shim that actually powers the touch controller.
#
#   ./make-touch-test.sh OUT.bin
#
# Why this exists: ugg's shim ships with BOARD_TOUCH_RAIL=0, which compiles
# input_setup() OUT entirely. Nothing the kernel's touch driver does can work in
# that state, because the controller is never powered or released from reset --
# the I2C votes and the pinmux never happen. So evaluating a single line of the
# touch work (coordinates, L5/L10 rails, GT9xx protocol) requires an image built
# with the rail on.
#
# That is a TEST image, not a candidate for the default:
#   * the rail vote is the prime suspect for an SoC reset recorded in
#     NOTES-UGG (console stops at REOPEN, just before the L10 vote)
#   * but the same capture also shows a failed log write, so the suspect is not
#     convicted
#   * and board.h now documents that L10 IS ugg's real vdd_ana, which weakens the
#     original reason for turning it off in the first place
#
# So: boot it, watch whether the phone survives and whether the console prints
# "INPUT SETUP: RPM L10 E=.. L5 E=..", then read the GT9xx id.
#
# Requirements: the aarch64 cross toolchain (CI builds this; locally it is
# usually absent -- in that case run the shim-ugg workflow with the flag).
set -eu

OUT=${1:-shim-touch-test.bin}
HERE=$(cd "$(dirname "$0")" && pwd)

if ! command -v aarch64-linux-gnu-gcc >/dev/null 2>&1; then
    echo "aarch64-linux-gnu-gcc not found." >&2
    echo "" >&2
    echo "This machine has no aarch64 toolchain (that is why kernels and the shim" >&2
    echo "are built on GitHub Actions). To produce the touch test image, run the" >&2
    echo "shim-ugg workflow with BOARD_TOUCH_RAIL forced on, or build on a machine" >&2
    echo "with the toolchain:" >&2
    echo "" >&2
    echo "    EXTRA_CFLAGS=\"-DBOARD_TOUCH_RAIL=1\" ./shim/build.sh" >&2
    echo "" >&2
    exit 1
fi

echo "building shim with BOARD_TOUCH_RAIL=1"
EXTRA_CFLAGS="-DBOARD_TOUCH_RAIL=1" "$HERE/shim/build.sh"

cp "$HERE/shim/out/Image" "$OUT"
echo ""
echo "wrote $OUT"
echo ""
echo "Check it really contains the rail vote: the string only exists inside"
echo "input_setup, so its absence proves the switch did not take."
if grep -q 'INPUT SETUP: RPM L10 E=' "$OUT" 2>/dev/null; then
    echo "  OK: input_setup is compiled in"
else
    echo "  WARNING: 'INPUT SETUP' string not found -- the flag may not have applied"
fi
echo ""
echo "Then: fastboot boot <xnu image built with this shim>"
echo "Expect on the console: INPUT SETUP: RPM L10 E=0 L5 E=0 CLK ON"
