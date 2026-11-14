#pragma once

/* Switch LK's RGB0 pipe from 24 bpp to 32 bpp, which XNU expects.
 * Must run before the first console write: the console draws 32-bit pixels. */
/* 0 = the pipe is in 32 bpp (switched now or already), -1 = it is in a state
 * we did not measure and was left alone, so the screen will be unreadable. */
int shim_fb_to_32bpp(void);
