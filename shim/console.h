#pragma once
#include <stdint.h>

/*
 * ugg: the live FDT (msm8940-mtp) has cont_splash_region at 0x90000000,
 * size 0x1400000; panel otm1901a_720p_video is 720x1280. The MDP pads the
 * line stride to 128 bytes: 720*4 = 2880 -> 2944 (read back from fb0).
 * The console can be re-pointed at other bpp/stride combinations for the
 * display probe.
 */
#define FB_BASE		0x90000000UL
#define FB_W		720
#define FB_H		1280
#define FB_STRIDE	2944

/* Default framebuffer; con_fb starts NULL so .data stays relocation-free. */
#define CON_FB		((volatile uint32_t *)(uintptr_t)FB_BASE)

extern volatile uint32_t *con_fb;

/* colours are 32bpp ARGB words (memory order B,G,R,A on little endian) */
#define RED	0xffff0000U
#define GREEN	0xff00ff00U
#define BLUE	0xff0000ffU
#define WHITE	0xffffffffU
#define YELLOW	0xffffff00U
#define BLACK	0xff000000U

void con_setup(volatile void *base, uint32_t stride, uint32_t bpp);
void con_clear(uint32_t bg);
void con_rect(int x, int y, int w, int h, uint32_t color);
void con_skip(void);
void con_str(const char *label, const char *s);
void con_hex(const char *label, uint64_t v);
/* label, then "a=xxxxxxxx b=xxxxxxxx" style pairs of 32-bit values */
void con_hex2(const char *label, const char *a, uint32_t va, const char *b, uint32_t vb);
