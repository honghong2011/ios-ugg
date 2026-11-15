/*
 * RGB0 pipe report -- deliberately does NOT change it.
 *
 * WHY READ-ONLY. Twice now this file has written SRC_FORMAT trying to force
 * 32 bpp, and twice the panel came out sheared. The evidence is consistent:
 *
 *   - a 24 bpp console is readable and a 32 bpp one is not (photographed),
 *   - the photograph of the colour self-test showed a 2160/2880 = 0.75
 *     vertical compression and a 540-pixel per-line horizontal shift, which is
 *     exactly "we wrote 4 bytes per pixel, the panel scanned 3",
 *   - writing SRC_FORMAT = 0x000236ff (mido's value, measured on ITS panel)
 *     did NOT make 32 bpp work here.
 *
 * So the pipe stays whatever LK left it in, and everything draws 24 bpp. The
 * kernel's video console cannot paint 24 bpp, which is a separate problem that
 * is not solved by guessing at SSPP registers.
 *
 * Reading the registers is safe and is the first thing to look at when the
 * screen is wrong, so this keeps reporting ADDR / FMT / UNPACK / STRIDE / SIZE
 * and states the verdict.
 */
#include <stdint.h>
#include "console.h"
#include "mido_compat.h"
#include "board.h"
#include "fb32.h"

#define MDSS_BASE   0x01a00000UL
#define MDP_RGB0    (MDSS_BASE + 0x15000UL)

static inline uint32_t md_rd(uintptr_t a) { return *(volatile uint32_t *)a; }

void
shim_fb_report(void)
{
	uint32_t addr   = md_rd(MDP_RGB0 + 0x14);
	uint32_t fmt    = md_rd(MDP_RGB0 + 0x30);
	uint32_t unpack = md_rd(MDP_RGB0 + 0x34);
	uint32_t stride = md_rd(MDP_RGB0 + 0x24);
	uint32_t size   = md_rd(MDP_RGB0 + 0x0c);

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
	 * State the conclusion instead of making the reader do the arithmetic:
	 * the console writes width*3 bytes per row, so a STRIDE of exactly that
	 * is the case that draws correctly today.
	 */
	if (stride == (uint32_t)FB_W * 3u) {
		con_puts(" 24bpp matches\n");
	} else if (stride == (uint32_t)FB_W * 4u) {
		con_puts(" panel is 32bpp, console 24 -> shear\n");
	} else {
		con_puts(" unexpected stride\n");
	}
}
