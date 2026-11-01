#pragma once
#include <stdint.h>

/*
 * ugg: the live FDT (msm8940-mtp) has cont_splash_region at 0x90000000,
 * size 0x1400000; panel otm1901a_720p_video is 720x1280, stride 2880.
 * Not 0x9c000000/1080x2400 like sweet.
 */
#define FB_BASE		0x90000000UL
#define FB_W		720
#define FB_H		1280
#define FB_STRIDE	(FB_W * 4)	/* a8r8g8b8, matches mainline simplefb */

/* Default framebuffer; con_fb starts NULL so .data stays relocation-free. */
#define CON_FB		((volatile uint32_t *)(uintptr_t)FB_BASE)

extern volatile uint32_t *con_fb;

#define RED	0xffff0000U
#define BLUE	0xff0000a0U
#define WHITE	0xffffffffU
#define YELLOW	0xffffff00U
#define GREEN	0xff00ff00U

void con_clear(uint32_t bg);
void con_skip(void);
void con_str(const char *label, const char *s);
void con_hex(const char *label, uint64_t v);
/* label, then "a=xxxxxxxx b=xxxxxxxx" style pairs of 32-bit values */
void con_hex2(const char *label, const char *a, uint32_t va, const char *b, uint32_t vb);
