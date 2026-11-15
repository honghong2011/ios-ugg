/*
 * RGB0 pipe report -- deliberately does NOT change it.
 *
 * History: this file used to switch the pipe from LK's BGR888 (3 B/px) to
 * 32 bpp, because the kernel was built for 32 bpp. On the phone that switch did
 * not take effect (SRC_FORMAT did not match the value mido measured), while the
 * console was compiled for 32 bpp anyway -- so every scanline was drawn at the
 * wrong pitch and the boot text was unreadable. Diagnosing a display fault you
 * cannot see is not possible.
 *
 * Everything now writes 24 bpp, which is what LK leaves, so there is nothing to
 * switch. What is still valuable is the reading: SRC_FORMAT and SRC_YSTRIDE say
 * whether the pitch we assume is the pitch the panel scans.
 *
 * Reading the registers is safe. Writing them without knowing the exact
 * expected value is how the screen got stolen in the first place.
 */
#include <stdint.h>
#include "console.h"
#include "mido_compat.h"
#include "board.h"
#include "fb32.h"

#define MDSS_BASE   0x01a00000UL
#define MDP_RGB0    (MDSS_BASE + 0x15000UL)
#define MDP_CTL0    (MDSS_BASE + 0x2000UL)

static inline uint32_t md_rd(uintptr_t a) { return *(volatile uint32_t *)a; }

void
shim_fb_report(void)
{
	uint32_t addr = md_rd(MDP_RGB0 + 0x14);
	uint32_t fmt = md_rd(MDP_RGB0 + 0x30);
	uint32_t unpack = md_rd(MDP_RGB0 + 0x34);
	uint32_t stride = md_rd(MDP_RGB0 + 0x24);
	uint32_t size = md_rd(MDP_RGB0 + 0x0c);

	/*
	 * One line, and every field matters when the screen is wrong:
	 *   ADDR    must be inside the splash carve-out
	 *   FMT     low bits are the element format; 3 B/px vs 4 B/px lives here
	 *   STRIDE  must equal width * bytes-per-pixel
	 *   SIZE    panel width in the low half, height in the high half
	 */
	con_puts("RGB0 ADDR=");
	con_hex(addr, 8);
	con_puts(" FMT=");
	con_hex(fmt, 8);
	con_puts(" UNPACK=");
	con_hex(unpack, 8);
	con_putc('\n');
	con_puts("RGB0 STRIDE=");
	con_hex(stride, 8);
	con_puts(" SIZE=");
	con_hex(size, 8);

	/*
	 * State the conclusion rather than making the reader do the arithmetic:
	 * the console writes width*3 bytes per row, so a STRIDE of exactly that is
	 * the case we can draw correctly today.
	 */
	if (stride == (uint32_t)FB_W * 3u) {
		con_puts(" -> 24 bpp, matches the console\n");
	} else if (stride == (uint32_t)FB_W * 4u) {
		con_puts(" -> 32 bpp (console is 24 bpp: expect a sheared screen)\n");
	} else {
		con_puts(" -> unexpected stride\n");
	}

	/*
	 * The blob: does it point where the ADT expects the frame?
	 * 24 bpp frame = 720*3*1280 = 2,764,800 bytes, inside the 20 MiB carve-out.
	 */
	con_puts("FB  " );
	con_hex(FB_PHYS, 8);
	con_puts(" frame ");
	con_hex((uint64_t)FB_W * 3u * FB_H, 8);
	con_puts(" bytes\n");
}
