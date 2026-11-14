#pragma once

/* Switch LK's RGB0 pipe from 24 bpp to 32 bpp, which XNU expects.
 * Must run before the first console write: the console draws 32-bit pixels. */
void shim_fb_to_32bpp(void);
