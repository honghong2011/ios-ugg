#pragma once

/*
 * Point the MDP RGB0 pipe at the frame the shim draws (FB_PHYS) and report the
 * result. Must be called before the first pixel is written, because the panel
 * may be scanning a different address than the one assumed.
 * Returns 1 when the pipe ends up at FB_PHYS.
 */
int  shim_fb_claim(void);

/* Report FMT / UNPACK / STRIDE / SIZE and whether the stride suits the console. */
void shim_fb_report(void);

/*
 * Switch the RGB0 pipe from LK's BGR888 to BGRX8888 at stride FB_W*4, the
 * format XNU's own 32 bpp paths and SweetFramebuffer require.
 *
 * stage: program the registers and report what they read back, without any
 *        visible change, so the (24 bpp) console can still print the result.
 * commit: flush CTL0 so the panel latches it at the next vsync.
 */
int  shim_fb_stage_32bpp(void);
void shim_fb_commit_32bpp(void);

/* Solid colour bars + a one-pixel frame, then hold: the scan-chain selftest. */
void shim_fb_bars32(uint32_t hold_ms);

/* Blank the 32 bpp frame so XNU starts from a clean buffer. */
void shim_fb_black32(void);
