#pragma once

/*
 * Force the MDP RGB0 pipe to 32 bpp, the only format XNU's video console can
 * paint and the only one its GUI path accepts. Returns 1 when the pipe ends up
 * in 32 bpp, 0 when the hardware refused the write.
 */
int shim_fb_set_32bpp(void);

/* Reading only (still forces 32 bpp; use shim_fb_set_32bpp for the verdict). */
void shim_fb_report(void);
