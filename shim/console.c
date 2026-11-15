/*
 * Minimal text console on the ABL splash framebuffer. With the MMU off
 * every access is Device memory, so stay aligned (-mstrict-align).
 *
 * The panel format differs per board: sweet leaves a 32 bpp a8r8g8b8 splash
 * at 0x9c000000, ugglite a 24 bpp RGB888 one at 0x90001000. Pixel writes go
 * through con_put() so the 24 bpp path only touches three aligned bytes.
 */
#include "console.h"
#include "font.h"

#define SCALE		FB_SCALE
#define CH_W		(8 * SCALE)
#define CH_H		(16 * SCALE)
#define MARGIN		24
#define LABEL_COLS	8

volatile uint32_t *con_fb = (volatile uint32_t *)FB_PHYS;

/* ---------------- console text log ring ----------------
 *
 * The panel is the only output on this phone and a photo of it is lossy, so
 * every console character is also appended to a plain-text ring in RAM that
 * the shim can write to the eMMC "cache" partition. A host then reads it with
 * one dd. Layout: "UGGSHIM\0" magic, u32 length at +8, text from +16.
 *
 * The buffer sits inside reserved-memory/wcnss_fw_region@0
 * (0x8e300000 + 0x700000 = 0x8e300000..0x8ea00000), which the kernel never
 * uses and which is above every region LK loads us into.
 */
#ifndef CON_LOG_PHYS
#define CON_LOG_PHYS 0x8e800000UL
#endif
#ifndef CON_LOG_SIZE
#define CON_LOG_SIZE 0x10000UL          /* 64 KiB, matches the 128-sector ring */
#endif

static unsigned con_log_len;

uintptr_t
con_log_phys(void)
{
	return CON_LOG_PHYS;
}

void
con_log_init(void)
{
	static const char m[8] = { 'U', 'G', 'G', 'S', 'H', 'I', 'M', 0 };
	for (int i = 0; i < 8; i++) {
		*(volatile char *)(CON_LOG_PHYS + (uintptr_t)i) = m[i];
	}
	con_log_len = 0;
	*(volatile uint32_t *)(CON_LOG_PHYS + 8) = 0;
}

static void
con_log_putc(char c)
{
	if (con_log_len + 16 < CON_LOG_SIZE) {
		*(volatile char *)(CON_LOG_PHYS + 16 + con_log_len) = c;
		con_log_len++;
		*(volatile uint32_t *)(CON_LOG_PHYS + 8) = con_log_len;
	}
}

static uint32_t con_bg;
static int row;

/*
 * Write one pixel. The framebuffer is Device memory and we run with the MMU
 * off, so only naturally aligned accesses are used: for 24 bpp that is the
 * three bytes at fb + y*stride + x*3 (byte stores, always aligned to 1).
 */
static inline void con_put(int x, int y, uint32_t c)
{
	volatile uint8_t *p = (volatile uint8_t *)con_fb + (uintptr_t)y * FB_STRIDE + x * FB_BPP;

#if FB_BPP == 4
#if FB_SWAP_RB
	/* Colour constants are 0xAARRGGBB; this panel stores 0xAABBGGRR. */
	c = (c & 0xff00ff00U) | ((c & 0x00ff0000U) >> 16) | ((c & 0x000000ffU) << 16);
#endif
	*(volatile uint32_t *)p = c;
#else
	/* 0xRRGGBB in the low 24 bits; r8g8b8 means byte order R,G,B. */
	p[0] = (uint8_t)(c >> 16);
	p[1] = (uint8_t)(c >> 8);
	p[2] = (uint8_t)c;
#endif
}

void con_clear(uint32_t bg)
{
	for (int y = 0; y < FB_H; y++)
		for (int x = 0; x < FB_W; x++)
			con_put(x, y, bg);
	/* Mirror the background into every other frame the panel may scan out. */
	for (int f = 1; f < FB_FRAMES; f++) {
		volatile uint32_t *dst = (volatile uint32_t *)((volatile uint8_t *)con_fb
							       + (uintptr_t)f * FB_FRAME_BYTES);
		uint32_t c = bg;
#if FB_BPP == 4 && FB_SWAP_RB
		c = (c & 0xff00ff00U) | ((c & 0x00ff0000U) >> 16) | ((c & 0x000000ffU) << 16);
#endif
		for (int i = 0; i < FB_FRAME_BYTES / 4; i++)
			dst[i] = c;
	}
	con_bg = bg;
	row = 0;
}


/*
 * Scroll the text area up by one row.
 *
 * Without this the console silently stops drawing: put_char_in() returns as
 * soon as the glyph would fall past FB_H, but 'row' keeps incrementing, so
 * every subsequent line is dropped. That is why a boot could print 36 lines of
 * eMMC detail and then show nothing at all -- not even 'XNU jumping', let alone
 * kernel text. The transfer below is byte-granular because the panel is 24 bpp
 * and a row is 2160 bytes, which is not a multiple of a 32-bit word.
 */
static void con_scroll(void)
{
	uintptr_t shift = (uintptr_t)CH_H * FB_STRIDE;
	uintptr_t total = (uintptr_t)FB_H * FB_STRIDE;

	for (int f = 0; f < FB_FRAMES; f++) {
		volatile uint8_t *base = (volatile uint8_t *)con_fb + (uintptr_t)f * FB_FRAME_BYTES;
		/*
		 * 8-byte chunks where the geometry allows it (2160*32 is a multiple
		 * of 16, and the base is page aligned), bytes otherwise.
		 */
		if ((shift % 8u) == 0u && (total % 8u) == 0u) {
			volatile uint64_t *d = (volatile uint64_t *)base;
			uintptr_t n = (total - shift) / 8u;
			for (uintptr_t i = 0; i < n; i++) {
				d[i] = d[i + shift / 8u];
			}
		} else {
			for (uintptr_t i = 0; i + shift < total; i++) {
				base[i] = base[i + shift];
			}
		}
		/*
		 * Clear the row that just scrolled into view.
		 *
		 * This has to write the background colour the same way put_char_in()
		 * does. Writing only (con_bg & 0xff) was a bug: red is 0xffff0000, so
		 * that byte is zero and the freshly cleared row came out BLACK against
		 * a red console. The photograph of the first scrolling build shows
		 * exactly that -- the last few lines sat on a dark band.
		 */
		for (uintptr_t i = total - shift; i < total; i += FB_BPP) {
#if FB_BPP == 4
			*(volatile uint32_t *)(base + i) = con_bg;
#else
			base[i + 0] = (uint8_t)(con_bg >> 16);
			base[i + 1] = (uint8_t)(con_bg >> 8);
			base[i + 2] = (uint8_t)con_bg;
#endif
		}
	}
}

/* Keep 'row' inside the drawable area, scrolling when it would leave it. */
static void con_ensure_row(void)
{
	int rows = (FB_H - MARGIN) / CH_H;
	if (row < rows) {
		return;
	}
	con_scroll();
	row = rows - 1;
}

/*
 * Draw one character into one frame. `base` is the frame's start; frame 0 is
 * con_fb itself.
 */
static void put_char_in(volatile uint8_t *base, int col, char ch, uint32_t fg)
{
	if (ch < 0x20 || ch > 0x7e)
		ch = '?';
	const unsigned char *g = font8x16[ch - 0x20];
	int x0 = MARGIN + col * CH_W, y0 = MARGIN + row * CH_H;

	if (x0 + CH_W > FB_W || y0 + CH_H > FB_H)
		return;
	for (int gy = 0; gy < 16; gy++)
		for (int gx = 0; gx < 8; gx++) {
			uint32_t c = (g[gy] & (0x80 >> gx)) ? fg : con_bg;
#if FB_BPP == 4 && FB_SWAP_RB
			c = (c & 0xff00ff00U) | ((c & 0x00ff0000U) >> 16) |
			    ((c & 0x000000ffU) << 16);
#endif
			for (int sy = 0; sy < SCALE; sy++)
				for (int sx = 0; sx < SCALE; sx++) {
					volatile uint8_t *p = base +
					    (uintptr_t)(y0 + gy * SCALE + sy) * FB_STRIDE +
					    (uintptr_t)(x0 + gx * SCALE + sx) * FB_BPP;
#if FB_BPP == 4
					*(volatile uint32_t *)p = c;
#else
					/* 24 bpp: three bytes, never a 32-bit store. */
					p[0] = (uint8_t)(c >> 16);
					p[1] = (uint8_t)(c >> 8);
					p[2] = (uint8_t)c;
#endif
				}
		}
}

/* Every glyph is drawn into all frames, so whichever one scans out shows it. */
static void put_char(int col, char ch, uint32_t fg)
{
	con_ensure_row();
	con_log_putc(ch);
	for (int f = 0; f < FB_FRAMES; f++)
		put_char_in((volatile uint8_t *)con_fb + (uintptr_t)f * FB_FRAME_BYTES,
			    col, ch, fg);
}

static int put_str(int col, const char *s, uint32_t fg)
{
	while (*s)
		put_char(col++, *s++, fg);
	return col;
}

static void fmt_hex(char *buf, uint64_t v, int digits)
{
	static const char hex[] = "0123456789ABCDEF";
	for (int i = 0; i < digits; i++)
		buf[i] = hex[(v >> (4 * (digits - 1 - i))) & 0xf];
	buf[digits] = 0;
}

void con_skip(void)
{
	row++;
}

void con_str(const char *label, const char *s)
{
	put_str(0, label, YELLOW);
	put_str(LABEL_COLS, s, WHITE);
	row++;
}

void con_hex(const char *label, uint64_t v)
{
	char buf[17];
	fmt_hex(buf, v, 16);
	con_str(label, buf);
}

void con_hex2(const char *label, const char *a, uint32_t va, const char *b, uint32_t vb)
{
	char buf[9];
	int col = put_str(0, label, YELLOW);
	col = col < LABEL_COLS ? LABEL_COLS : col + 1;
	col = put_str(col, a, YELLOW);
	fmt_hex(buf, va, 8);
	col = put_str(col, buf, WHITE);
	if (b) {
		col = put_str(col + 1, b, YELLOW);
		fmt_hex(buf, vb, 8);
		put_str(col, buf, WHITE);
	}
	row++;
}
