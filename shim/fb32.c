/*
 * Switch LK's RGB0 pipe from 24 bpp (3 B/px) to 32 bpp (4 B/px), which is the
 * format the XNU framebuffer driver and the ADT advertise.
 *
 * Why this has to happen in the shim and not in XNU: pexpert/pexpert/arm64/
 * SWEET.h says so -- "the shim switches MDP RGB0 to 32 bpp, so a frame is
 * 720*4*1280 = 3.7 MiB". UGG_FB_STRIDE is 2880, i.e. 720 * 4. If the pipe is
 * still scanning out LK's 3-byte pixels, the kernel's frames are read with the
 * wrong stride and the panel shows diagonal garbage.
 *
 * The register values were measured on this phone family (mdp5, MDP HWVER
 * 0x10100000). Like mido's fb_to_32bpp(), this refuses to touch the pipe
 * unless it finds the exact LK state first: writing SSPP registers on a pipe
 * in an unexpected state can blank the panel permanently for this boot.
 *
 * MDP5 SSPP (RGB0 at MDSS+0x15000):
 *   +0x14  SRC0_ADDR
 *   +0x24  SRC_YSTRIDE0
 *   +0x30  SRC_FORMAT        3 B/px tight = 0x0002243f, 4 B/px = 0x000236ff
 *   +0x34  SRC_UNPACK_PATTERN
 * CTL0 +0x18 = CTL_FLUSH, bit 3 = RGB0; it latches at the next vsync.
 */
#include <stdint.h>
#include "console.h"
#include "mido_compat.h"
#include "board.h"

#define MDSS_BASE   0x01a00000UL
#define MDP_RGB0    (MDSS_BASE + 0x15000UL)
#define MDP_CTL0    (MDSS_BASE + 0x2000UL)

#define FMT_24BPP   0x0002243fUL     /* what LK leaves behind */
#define FMT_32BPP   0x000236ffUL     /* 4 B/px, 4 components, 8 bpc, alpha off */
#define UNPACK_BGRX 0x03020001UL     /* memory order B, G, R, X */
#define FLUSH_RGB0  (1UL << 3)

static uint64_t
shim_ticks(void)
{
	uint64_t v;
	__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(v));
	return v;
}

/* 19.2 MHz system counter on this SoC. */
static void
shim_delay_ms(unsigned ms)
{
	uint64_t end = shim_ticks() + 19200ULL * ms;
	while (shim_ticks() < end) {
		__asm__ volatile("yield");
	}
}

static inline uint32_t md_rd(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline void md_wr(uintptr_t a, uint32_t v) { *(volatile uint32_t *)a = v; }

void
shim_fb_to_32bpp(void)
{
	uint32_t addr = md_rd(MDP_RGB0 + 0x14);
	uint32_t fmt = md_rd(MDP_RGB0 + 0x30);
	uint32_t stride = md_rd(MDP_RGB0 + 0x24);

	con_puts("MDP RGB0: ADDR=");
	con_hex(addr, 8);
	con_puts(" FMT=");
	con_hex(fmt, 8);
	con_puts(" STRIDE=");
	con_hex(stride, 8);
	con_putc('\n');

		if (fmt != FMT_24BPP) {
		/*
		 * Either already switched, or a pipe state we did not measure. The
		 * console is compiled for 32 bpp, so if the pipe is left in another
		 * format the screen will be unreadable -- say so, because this line is
		 * the only clue that the display is not the kernel's fault.
		 */
		con_puts(fmt == FMT_32BPP ? "MDP: already 32bpp\n"
		                          : "MDP: unexpected FMT, pipe untouched (screen may be unreadable)\n");
		return;
	}
	/*
	 * Clear the whole 32 bpp frame first so the switch does not show whatever
	 * bytes were in the extra 1 B/px slot. FB_REGION_SIZE is the splash
	 * carve-out (20 MiB on ugg), comfortably larger than one frame.
	 */
	for (uintptr_t a = FB_PHYS; a < FB_PHYS + (uintptr_t)FB_W * 4u * FB_H; a += 4) {
		*(volatile uint32_t *)a = 0xff000000u;
	}

	md_wr(MDP_RGB0 + 0x30, FMT_32BPP);
	md_wr(MDP_RGB0 + 0x34, UNPACK_BGRX);
	md_wr(MDP_RGB0 + 0x24, (uint32_t)FB_W * 4u);
	md_wr(MDP_CTL0 + 0x18, FLUSH_RGB0);
	shim_delay_ms(50);                       /* > 2 frames at 60 Hz: the flush latched */

	con_puts("MDP RGB0 -> FMT=");
	con_hex(md_rd(MDP_RGB0 + 0x30), 8);
	con_puts(" STRIDE=");
	con_hex(md_rd(MDP_RGB0 + 0x24), 8);
	con_puts(" (32 bpp)\n");
}
