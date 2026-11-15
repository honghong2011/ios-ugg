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

/* ------------------------------------------------------------------ *
 * 32 bpp end to end
 *
 * The console above is 24 bpp and proven on the panel. XNU cannot stay
 * there: SweetFramebuffer::start() rejects fRowBytes < fWidth * 4, so the
 * GUI can never attach at 24 bpp, and upstream video_console has no 24 bpp
 * painter at all (ours is custom code we would have to keep alive).
 *
 * mido, on the same MDP5 family, has run XNU at 32 bpp from the start and
 * reached the home screen, so this follows its register sequence exactly,
 * with this board's geometry substituted:
 *
 *   LK leaves RGB0 in BGR888 (3 B/px, SRC_FORMAT 0x0002243f) at stride
 *   720*3. Switch it to BGRX8888 (0x000236ff), unpack B,G,R,X
 *   (0x03020001), stride 720*4, and flush CTL0 bit 3 so the change is
 *   latched at the next vsync.
 *
 * Staging and committing are separate on purpose: register writes are
 * readable immediately but nothing changes on the panel until the flush,
 * so the result can still be printed on the (24 bpp) console and read in a
 * photograph before the screen is replaced.
 * ------------------------------------------------------------------ */

#define MDP_CTL0    (MDSS_BASE + 0x2000UL)
#define CTL_FLUSH   0x18
#define CTL_FLUSH_RGB0   (1u << 3)

#define FMT_BGR888      0x0002243fu     /* LK's 24 bpp state (measured) */
#define FMT_BGRX8888    0x000236ffu     /* 4 B/px, 4 components, 8 bpc, alpha off */
#define UNPACK_BGRX     0x03020001u     /* memory order B, G, R, X */

static void
fb_delay_ms(uint32_t ms)
{
	uint64_t freq, t0, ticks;

	if (ms == 0) {
		return;
	}
	__asm__ volatile("mrs %0, cntfrq_el0" : "=r"(freq));
	__asm__ volatile("mrs %0, cntpct_el0" : "=r"(t0));
	ticks = (freq / 1000u) * (uint64_t)ms;
	for (;;) {
		uint64_t t1;
		__asm__ volatile("mrs %0, cntpct_el0" : "=r"(t1));
		if (t1 - t0 >= ticks) {
			break;
		}
	}
}

/* Fill the whole 32 bpp frame with one word. Done before the switch latches. */
static void
fb_fill32(uint32_t word)
{
	volatile uint32_t *p = (volatile uint32_t *)FB_PHYS;

	for (uint32_t i = 0; i < (uint32_t)FB_W * (uint32_t)FB_H; i++) {
		p[i] = word;
	}
	__asm__ volatile("dsb sy" ::: "memory");
}

/*
 * Program the pipe for 32 bpp but do not latch it. Returns 1 when every
 * register reads back what was written.
 */
int
shim_fb_stage_32bpp(void)
{
	uint32_t before = md_rd(MDP_RGB0 + SSPP_SRC_FORMAT);
	uint32_t stride = md_rd(MDP_RGB0 + SSPP_STRIDE_A);

	/* Start from a black frame so the switch never shows stale 24 bpp bytes. */
	fb_fill32(0x00000000u);

	md_wr(MDP_RGB0 + SSPP_SRC_FORMAT, FMT_BGRX8888);
	md_wr(MDP_RGB0 + SSPP_UNPACK, UNPACK_BGRX);
	md_wr(MDP_RGB0 + SSPP_STRIDE_A, (uint32_t)FB_W * 4u);

	con_puts("RGB0 FMT ");
	con_hex(before, 8);
	con_puts(" -> ");
	con_hex(md_rd(MDP_RGB0 + SSPP_SRC_FORMAT), 8);
	con_putc('\n');
	con_puts("RGB0 STRIDE ");
	con_hex(stride, 8);
	con_puts(" -> ");
	con_hex(md_rd(MDP_RGB0 + SSPP_STRIDE_A), 8);
	con_putc('\n');
	con_puts("RGB0 UNPACK -> ");
	con_hex(md_rd(MDP_RGB0 + SSPP_UNPACK), 8);
	con_putc('\n');

	return md_rd(MDP_RGB0 + SSPP_SRC_FORMAT) == FMT_BGRX8888 &&
	       md_rd(MDP_RGB0 + SSPP_UNPACK) == UNPACK_BGRX &&
	       md_rd(MDP_RGB0 + SSPP_STRIDE_A) == (uint32_t)FB_W * 4u;
}

void
shim_fb_commit_32bpp(void)
{
	md_wr(MDP_CTL0 + CTL_FLUSH, CTL_FLUSH_RGB0);
	fb_delay_ms(50);        /* more than two frames at 60 Hz */
}

/*
 * Six solid bars plus a one-pixel frame, drawn with 32-bit stores.
 *
 * This is the shape that answers "is the scan chain right?" in a single
 * photograph: solid bars mean the format, the unpack order and the stride
 * all agree with what is written; stripes, a missing frame or a frame that
 * is not flush with the edges means they do not. Text cannot answer that,
 * because an 8x16 font on a 720p panel is below what a camera resolves.
 */
void
shim_fb_bars32(uint32_t hold_ms)
{
	static const uint32_t bar[6] = {
		0x00ff0000u,     /* red   */
		0x0000ff00u,     /* green */
		0x000000ffu,     /* blue  */
		0x00ffffffu,     /* white */
		0x00808080u,     /* grey  */
		0x00000000u      /* black */
	};
	volatile uint32_t *p = (volatile uint32_t *)FB_PHYS;
	const uint32_t w = (uint32_t)FB_W;
	const uint32_t h = (uint32_t)FB_H;
	const uint32_t bw = w / 6u;

	for (uint32_t y = 0; y < h; y++) {
		for (uint32_t x = 0; x < w; x++) {
			uint32_t i = x / bw;
			if (i > 5u) {
				i = 5u;
			}
			p[y * w + x] = bar[i];
		}
	}
	/* Frame: proves the buffer is scanned with exactly FB_W x FB_H. */
	for (uint32_t y = 0; y < h; y++) {
		p[y * w + 0] = 0x00ffffffu;
		p[y * w + (w - 1u)] = 0x00ffffffu;
	}
	for (uint32_t x = 0; x < w; x++) {
		p[0 * w + x] = 0x00ffffffu;
		p[(h - 1u) * w + x] = 0x00ffffffu;
	}
	__asm__ volatile("dsb sy" ::: "memory");
	fb_delay_ms(hold_ms);
}

/* Blank the frame so XNU starts from a clean 32 bpp buffer. */
void
shim_fb_black32(void)
{
	fb_fill32(0x00000000u);
}

