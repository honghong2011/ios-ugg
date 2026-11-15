#pragma once

/* Report the RGB0 pipe registers without changing them. Reading is safe;
 * the previous version switched the pipe and stole the screen when its
 * assumption about the current value was wrong. */
void shim_fb_report(void);
