/* Render the console layout on the host: ./out/host_test && view out/host.ppm */
#include <stdio.h>
#include "console.h"

static uint32_t host_fb[FB_H * FB_STRIDE / 4];

int main(void)
{
	con_fb = host_fb;
	con_clear(RED);
	con_str("SHIM", "sweet milestone 2");
	con_hex("MMFR0", 0x0000000000101122ULL);
	con_hex2("PSCI", "ver=", 0x10001, "smccc=", 0x10002);
	con_hex2("CPU7", "ret=", 0, "mpidr=", 0x81000700);
	con_clear(BLUE);
	con_str("PANIC", "sync exception");
	con_hex("ESR", 0x96000010);
	FILE *f = fopen("out/host.ppm", "wb");
	fprintf(f, "P6 %d %d 255\n", FB_W, FB_H);
	for (int y = 0; y < FB_H; y++)
		for (int x = 0; x < FB_W; x++) {
			uint32_t p = host_fb[y * (FB_STRIDE / 4) + x];
			unsigned char px[3] = { p >> 16, p >> 8, p };
			fwrite(px, 1, 3, f);
		}
	fclose(f);
	return 0;
}
