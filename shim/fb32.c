/*
 * RGB0 pipe: put it in 32 bpp and prove the switch took effect.
 *
 * WHY. This board's panel and XNU disagree about everything except 32 bpp:
 *
 *   - osfmk/console/video_console.c vc_paint_char() handles v_depth 8, 16, 30
 *     and 32 only. A kernel told 24 draws NOTHING, which is why the screen
 *     went red after "XNU jumping" and never showed kernel text again.
 *   - SweetFramebuffer::start() rejects fRowBytes < fWidth * 4, so the GUI
 *     path cannot attach at 24 bpp either.
 *
 * mido runs 32 bpp end to end -- its shim console is a uint32_t * and its
 * frame stride is FB_W * 4 -- and it reached the home screen that way. So the
 * target is 32 bpp, and this file exists to get the pipe there.
 *
 * HISTORY, because it explains the shape of this code. An earlier attempt set
 * SRC_FORMAT to mido's value (0x000236ff) unconditionally and then drew at
 * 32 bpp; the screen came out sheared, so the switch was judged to have failed
 * and everything was moved to 24 bpp instead. That was the wrong call: the
 * shearing proves the pipe and the console disagreed, not that the pipe cannot
 * be switched. What was missing is verification.
 *
 * So: read SRC_FORMAT, write the 32 bpp value, read it back, and only report
 * success when the register actually changed. If it does not stick, say so
 * loudly -- the boot will then produce kernel text sheared or absent, and the
 * photograph should be read as "the pipe refused 32 bpp" rather than as a new
 * mystery.
 *
 * The value is mido's, measured on its own panel: 0x000236ff. The register is
 * the VIG/RGB source format word for the SSPP; the MDSS register offsets here
 * come from this board's device tree (qcom,mdss-pipe-rgb-off = 0x15000,
 * qcom,mdss-mdp at 0x1a00000), so RGB0 = 0x1b5000 as assumed everywhere else
 * in this port.
 */
#include <stdint.h>
#include "console.h"
#include "mido_compat.h"
#include "board.h"
#include "fb32.h"

#define MDSS_BASE   0x01a00000UL
#define MDP_RGB0    (MDSS_BASE + 0x15000UL)

/* SSPP source format: 32 bpp, 4 components, 8 bpc, alpha off (mido's value). */
#define SRC_FORMAT_32BPP	0x000236ffu

static inline uint32_t md_rd(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline void     md_wr(uintptr_t a, uint32_t v)
{
	*(volatile uint32_t *)a = v;
	__asm__ volatile("dsb sy" ::: "memory");
}

/*
 * Reports the pipe and, when asked, forces 32 bpp.
 *
 * Returns 1 when the pipe is in the 32 bpp format the console will use, 0
 * when it is not. The caller uses this to decide whether to keep going: with
 * a 32 bpp console and a 24 bpp pipe every line is sheared, which is exactly
 * the state that was misdiagnosed once already.
 */
int
shim_fb_set_32bpp(void)
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
	con_putc('\n');

	if (fmt == SRC_FORMAT_32BPP) {
		con_puts("RGB0 already 32 bpp\n");
		return 1;
	}

	/*
	 * Switch it. The unpack word goes with the format: mido's pair is
	 * 0x000236ff / 0x03020001, and a format without its unpack order puts
	 * the channels in the wrong place rather than failing outright.
	 */
	md_wr(MDP_RGB0 + 0x30, SRC_FORMAT_32BPP);
	md_wr(MDP_RGB0 + 0x34, 0x03020001u);
	/* A frame is 720*4 bytes per line now, not 720*3. */
	md_wr(MDP_RGB0 + 0x24, (uint32_t)FB_W * 4u);

	uint32_t fmt2 = md_rd(MDP_RGB0 + 0x30);
	uint32_t str2 = md_rd(MDP_RGB0 + 0x24);

	con_puts("RGB0 FMT now=");
	con_hex(fmt2, 8);
	con_puts(" STRIDE now=");
	con_hex(str2, 8);
	con_putc('\n');

	if (fmt2 != SRC_FORMAT_32BPP) {
		con_puts("RGB0 SWITCH REFUSED: pipe is not 32 bpp\n");
		return 0;
	}
	if (str2 != (uint32_t)FB_W * 4u) {
		con_puts("RGB0 STRIDE REFUSED\n");
		return 0;
	}
	con_puts("RGB0 SWITCHED to 32 bpp\n");
	return 1;
}

/* Kept for callers that only want the reading. */
void
shim_fb_report(void)
{
	(void)shim_fb_set_32bpp();
}
