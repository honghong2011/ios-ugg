/*
 * RGB0 pipe: take it over at the address the panel is actually scanning.
 *
 * THE BUG THIS FIXES. The on-device photograph of the console showed
 *
 *     RGB0 ADDR=90001000 FMT=... STRIDE=00000870 SIZE=056002d0
 *
 * while the shim was drawing at FB_PHYS = 0x90000000. STRIDE 0x870 = 2160 =
 * 720*3 confirmed 24 bpp, and ADDR was 0x1000 (4096 bytes) higher than assumed.
 * 4096 bytes is 1365.33 pixels, so every visible row was the tail of one
 * console line followed by the head of the next, which is exactly the odd
 * left-margin fragments ("UMP", "2d0", "TE=0") in the photograph.
 *
 * Rather than hard-code a second guess, read SRC0_ADDR out of the pipe and use
 * what it says. If it already matches FB_PHYS nothing is written; otherwise the
 * pipe is pointed at FB_PHYS so that one constant is correct for the shim's
 * console, XNU's early console and SweetFramebuffer alike. Either way the value
 * is read back, because a register that silently refuses is the reason the
 * earlier 32 bpp attempt was misdiagnosed for two rounds.
 */
#include <stdint.h>
#include "console.h"
#include "mido_compat.h"
#include "board.h"
#include "fb32.h"

#define MDSS_BASE   0x01a00000UL
#define MDP_RGB0    (MDSS_BASE + 0x15000UL)   /* qcom,mdss-pipe-rgb-off = 0x15000 */

#define SSPP_SRC0_ADDR  0x14
#define SSPP_STRIDE_A   0x24
#define SSPP_SRC_FORMAT 0x30
#define SSPP_UNPACK     0x34
#define SSPP_OUT_SIZE   0x0c

static inline uint32_t md_rd(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline void     md_wr(uintptr_t a, uint32_t v)
{
	*(volatile uint32_t *)a = v;
	__asm__ volatile("dsb sy" ::: "memory");
}

/* Returns 1 when the pipe now scans the frame the shim draws. */
int
shim_fb_claim(void)
{
	uint32_t addr = md_rd(MDP_RGB0 + SSPP_SRC0_ADDR);

	if (addr != (uint32_t)FB_PHYS) {
		md_wr(MDP_RGB0 + SSPP_SRC0_ADDR, (uint32_t)FB_PHYS);
		uint32_t back = md_rd(MDP_RGB0 + SSPP_SRC0_ADDR);
		con_puts("RGB0 was=");
		con_hex(addr, 8);
		con_puts(" now=");
		con_hex(back, 8);
		con_puts(back == (uint32_t)FB_PHYS ? " ok\n" : " REFUSED\n");
		return back == (uint32_t)FB_PHYS;
	}
	con_puts("RGB0 addr already ");
	con_hex(addr, 8);
	con_putc('\n');
	return 1;
}

void
shim_fb_report(void)
{
	con_puts("RGB0 FMT=");
	con_hex(md_rd(MDP_RGB0 + SSPP_SRC_FORMAT), 8);
	con_puts(" UNPACK=");
	con_hex(md_rd(MDP_RGB0 + SSPP_UNPACK), 8);
	con_putc('\n');
	con_puts("RGB0 STRIDE=");
	con_hex(md_rd(MDP_RGB0 + SSPP_STRIDE_A), 8);
	con_puts(" SIZE=");
	con_hex(md_rd(MDP_RGB0 + SSPP_OUT_SIZE), 8);
	con_putc('\n');

	/*
	 * The console writes width*3 bytes per row. A stride of exactly that is the
	 * case that draws correctly; anything else means the shapes on screen will
	 * be shifted, which is worth saying out loud rather than leaving to be
	 * inferred from a photograph.
	 */
	uint32_t stride = md_rd(MDP_RGB0 + SSPP_STRIDE_A);
	if (stride == (uint32_t)FB_W * FB_BPP) {
		con_puts("RGB0 stride matches the console\n");
	} else {
		con_puts("RGB0 STRIDE MISMATCH: console writes ");
		con_hex((uint32_t)FB_W * FB_BPP, 8);
		con_putc('\n');
	}
}
