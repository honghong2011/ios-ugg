/*
 * Display self-test: a pattern whose geometry is readable from a photograph.
 *
 * The early text console is useless for bring-up if the mapping between the
 * buffer we write and the pixels the panel scans out is wrong -- the text comes
 * out smeared and cannot be read at all. Colours can be read even then.
 *
 * What it draws, and what each part proves:
 *
 *   - a white frame 8 px wide around the whole 720x1280 frame
 *       closed on all four sides -> pitch and height both right
 *       open at the bottom       -> the panel scans fewer rows than we write
 *       skewed diagonally        -> pitch mismatch (the classic case)
 *   - four full-width bars: RED at y=0, GREEN y=100, BLUE y=200, WHITE y=1200
 *       the WHITE one is the informative bar: it is near the last row, so it
 *       moves or disappears first when the pitch is wrong
 *   - a vertical white line at x=360 from y=300 to y=1100
 *       straight -> horizontal mapping is 1:1
 *       slanted  -> horizontal scaling or a wrong source width
 *   - a MAGENTA block at x=672..719, y=1232..1279
 *       present -> the shim reached this point and the bottom rows are shown
 *       absent  -> the panel is not scanning that far
 *
 * Writes BGR888 (3 bytes/px), which is what LK leaves in RGB0. The pattern is
 * a fixed number of byte stores at a fixed pitch: no stack, no MMU, no console.
 */
#include <stdint.h>
#include "console.h"
#include "board.h"
#include "selftest.h"

#define W       FB_W
#define H       FB_H
#define PITCH   (FB_W * 3)      /* BGR888, the format RGB0 is actually in */

static inline void
px(unsigned x, unsigned y, uint32_t c)
{
	if (x < W && y < H) {
		volatile uint8_t *p = (volatile uint8_t *)(uintptr_t)
		    (FB_PHYS + (uintptr_t)y * PITCH + (uintptr_t)x * 3u);
		p[0] = (uint8_t)(c >> 16);
		p[1] = (uint8_t)(c >> 8);
		p[2] = (uint8_t)c;
	}
}

static void
fill(unsigned x0, unsigned y0, unsigned x1, unsigned y1, uint32_t c)
{
	for (unsigned y = y0; y < y1 && y < H; y++) {
		for (unsigned x = x0; x < x1 && x < W; x++) {
			px(x, y, c);
		}
	}
}

void
shim_display_selftest(unsigned hold_ms)
{
	/* 1: everything black, so the pattern is the only thing on screen */
	fill(0, 0, W, H, 0x00000000u);

	/* 2: frame, 8 px, all four sides */
	fill(0, 0, W, 8, 0x00ffffffu);
	fill(0, H - 8, W, H, 0x00ffffffu);
	fill(0, 0, 8, H, 0x00ffffffu);
	fill(W - 8, 0, W, H, 0x00ffffffu);

	/* 3: four bars */
	fill(0, 0, W, 48, 0x00ff0000u);            /* red   */
	fill(0, 100, W, 148, 0x0000ff00u);         /* green */
	fill(0, 200, W, 248, 0x000000ffu);         /* blue  */
	fill(0, 1200, W, 1248, 0x00ffffffu);       /* white */

	/* 4: vertical line, proves 1:1 horizontal mapping */
	fill(360, 300, 364, 1100, 0x00ffffffu);

	/* 5: magenta block, bottom right */
	fill(672, 1232, 720, 1280, 0x00ff00ffu);

	/* 6: hold so the screen can be photographed */
	for (unsigned ms = 0; ms < hold_ms; ms++) {
		for (volatile unsigned spin = 0; spin < 24000; spin++) {
		}
	}
}
