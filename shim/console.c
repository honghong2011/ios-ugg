/*
 * Minimal text console on the bootloader framebuffer. With the MMU off
 * every access is Device memory, so stay aligned (-mstrict-align).
 * The pixel format is configurable so the same renderer can probe 16/24/32
 * bpp and different strides.
 */
#include "console.h"
#include "font.h"

#define SCALE		2	/* 720 px wide: 45 columns, 40 rows */
#define CH_W		(8 * SCALE)
#define CH_H		(16 * SCALE)
#define MARGIN		24
#define LABEL_COLS	8

/*
 * NULL-initialised (.bss) so the image carries no absolute pointer in
 * .data; con_clear() latches the default framebuffer unless a host test
 * or con_setup() already provided one.
 */
volatile uint32_t *con_fb;
static volatile uint8_t *base;
static uint32_t stride = FB_STRIDE;
static uint32_t bpp = 32;
static uint32_t con_bg;
static int row;

void con_setup(volatile void *fb, uint32_t s, uint32_t b)
{
	base = (volatile uint8_t *)fb;
	stride = s;
	bpp = b;
	row = 0;
}

static void ensure_base(void)
{
	if (!base)
		base = (volatile uint8_t *)(con_fb ? con_fb : CON_FB);
}

static void put_px(int x, int y, uint32_t c)
{
	volatile uint8_t *p = base + (uint32_t)y * stride;

	if (bpp == 32) {
		((volatile uint32_t *)p)[x] = c;
	} else if (bpp == 16) {
		uint32_t r = (c >> 16) & 0xff, g = (c >> 8) & 0xff, b = c & 0xff;
		((volatile uint16_t *)p)[x] =
			(uint16_t)(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3));
	} else {
		volatile uint8_t *q = p + 3 * x;
		q[0] = c >> 16;	/* R */
		q[1] = c >> 8;	/* G */
		q[2] = c;	/* B */
	}
}

void con_clear(uint32_t bg)
{
	int npx;

	ensure_base();
	con_bg = bg;
	row = 0;
	npx = (int)(stride / (bpp / 8));
	for (int y = 0; y < FB_H; y++) {
		volatile uint8_t *p = base + (uint32_t)y * stride;

		if (bpp == 32) {
			volatile uint32_t *q = (volatile uint32_t *)p;
			for (int x = 0; x < npx; x++)
				q[x] = bg;
		} else if (bpp == 16) {
			uint32_t r = (bg >> 16) & 0xff, g = (bg >> 8) & 0xff, b = bg & 0xff;
			uint16_t v = (uint16_t)(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3));
			volatile uint16_t *q = (volatile uint16_t *)p;
			for (int x = 0; x < npx; x++)
				q[x] = v;
		} else {
			for (int x = 0; x < npx; x++) {
				p[3 * x + 0] = bg >> 16;
				p[3 * x + 1] = bg >> 8;
				p[3 * x + 2] = bg;
			}
		}
	}
}

void con_rect(int x, int y, int w, int h, uint32_t color)
{
	ensure_base();
	for (int yy = y; yy < y + h; yy++) {
		if (yy < 0 || yy >= FB_H)
			continue;
		for (int xx = x; xx < x + w; xx++)
			if (xx >= 0 && xx < FB_W)
				put_px(xx, yy, color);
	}
}

static void put_char(int col, char ch, uint32_t fg)
{
	if (ch < 0x20 || ch > 0x7e)
		ch = '?';
	const unsigned char *g = font8x16[ch - 0x20];
	int x0 = MARGIN + col * CH_W, y0 = MARGIN + row * CH_H;
	if (x0 + CH_W > (int)FB_W || y0 + CH_H > FB_H)
		return;
	for (int gy = 0; gy < 16; gy++)
		for (int gx = 0; gx < 8; gx++) {
			uint32_t c = (g[gy] & (0x80 >> gx)) ? fg : con_bg;
			for (int sy = 0; sy < SCALE; sy++)
				for (int sx = 0; sx < SCALE; sx++)
					put_px(x0 + gx * SCALE + sx, y0 + gy * SCALE + sy, c);
		}
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
	ensure_base();
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
	int col;
	ensure_base();
	col = put_str(0, label, YELLOW);
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
