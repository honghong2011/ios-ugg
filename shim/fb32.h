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
