/*
 * Qualcomm MSM APSS watchdog (qcom,wdt@b017000, compatible "qcom,msm-watchdog")
 * and the IMEM restart reason word.
 *
 * WHY THIS FILE EXISTS
 *
 * The boot resets itself a number of seconds after the jump into the kernel,
 * which destroys exactly the evidence needed: the kernel's early console
 * exists only on the panel, so a reset before it can be photographed loses the
 * whole boot. On Qualcomm boards the APSS watchdog is armed by the bootloader
 * (LK) before it hands over, and from then on it is only kept alive by whoever
 * pets it. Linux ships drivers/watchdog/msm_wdt.c, whose probe both reprograms
 * the timeouts and pets the counter; XNU has no such driver, so nothing pets it
 * again and the phone resets on a fixed schedule.
 *
 * REGISTER MAP -- read from the upstream driver for THIS compatible string,
 * not from memory. An earlier version of this file used the qcom-wdt.c / KPSS
 * layout (contiguous CTRL/LOAD/VAL/CTRL1 at 0x00/0x04/0x08/0x0c) and was
 * wrong for msm-watchdog:
 *
 *   drivers/watchdog/msm_wdt.c (KonstaT/sailfishos_kernel_jolla_msm8909,
 *   msm8909/8937 family; identical map in the msm-3.18 tree):
 *
 *     #define WDT_RST        0x04   // write 1 = reload the counter ("pet")
 *     #define WDT_EN         0x08   // bit0 = enable
 *     #define WDT_STS        0x0C   // bit0 = status
 *     #define WDT_BARK_TIME  0x10
 *     #define WDT_BITE_TIME  0x14
 *     #define WDT_HZ         32768
 *
 * The difference matters in the worst possible way: under the KPSS map offset
 * 0x04 looks like "LOAD", but here it is WDT_RST and writing it is what PETS
 * the dog. Using the wrong map would have written tick counts into WDT_RST and
 * WDT_EN -- re-arming the watchdog with garbage instead of stopping it.
 *
 * UNITS. WDT_HZ is 32768 and the counters hold ticks, so the driver writes
 * 10 * WDT_HZ for "10 s". The device tree for this board gives
 * qcom,bark-time = 0x3a98 (15000 ms) and qcom,pet-time = 0x2710 (10000 ms),
 * so the firmware left bark 15 s / bite 18 s programmed in ticks. Note that
 * WDT_MAXTIMEOUT (0x3fff) is a limit in SECONDS for the watchdog core, not a
 * bound on the register contents, so it must not be used to validate a
 * register read.
 *
 * WRITES. Nothing is written unless the registers first read back as a
 * plausible msm-watchdog: EN must be exactly 0 or 1 (it is a single bit) and
 * BITE must not be below BARK. That gate is what keeps a wrong offset guess
 * from ever reaching the hardware.
 */
#include <stdint.h>
#include "console.h"
#include "mido_compat.h"
#include "board.h"
#include "wdt.h"

#ifndef WDT_PHYS
#define WDT_PHYS	0x0b017000UL
#endif

/* drivers/watchdog/msm_wdt.c -- the layout for "qcom,msm-watchdog". */
#define WDT_RST		0x04
#define WDT_EN		0x08
#define WDT_STS		0x0c
#define WDT_BARK_TIME	0x10
#define WDT_BITE_TIME	0x14

#define WDT_ENABLE	1u
#define WDT_HZ		32768u

/* 32 bit registers: anything a sane driver writes shifts left of here. */
#define WDT_TICKS_LIMIT	0x7fffffffu

static inline uint32_t
wdt_rd(uint32_t off)
{
	return *(volatile uint32_t *)(WDT_PHYS + off);
}

static inline void
wdt_wr(uint32_t off, uint32_t v)
{
	*(volatile uint32_t *)(WDT_PHYS + off) = v;
	__asm__ volatile("dsb sy" ::: "memory");
}

/* ticks -> milliseconds, without a 64 bit divide by 32768. */
static uint64_t
ticks_to_ms(uint32_t ticks)
{
	return (uint64_t)ticks * 1000u / WDT_HZ;
}

static int
wdt_looks_sane(uint32_t en, uint32_t bark, uint32_t bite)
{
	if (en != 0u && en != WDT_ENABLE) {
		return 0;			/* EN is one bit */
	}
	if (bark == 0u || bite == 0u) {
		return 0;
	}
	if (bark > WDT_TICKS_LIMIT || bite > WDT_TICKS_LIMIT) {
		return 0;
	}
	if (bite < bark) {
		return 0;			/* bite fires after bark */
	}
	return 1;
}

void
shim_wdt_report(const char *tag)
{
	uint32_t en = wdt_rd(WDT_EN);
	uint32_t sts = wdt_rd(WDT_STS);
	uint32_t bark = wdt_rd(WDT_BARK_TIME);
	uint32_t bite = wdt_rd(WDT_BITE_TIME);

	con_puts(tag);
	con_puts(" WDT EN=");
	con_hex(en, 8);
	con_puts(" STS=");
	con_hex(sts, 4);
	con_puts(en & WDT_ENABLE ? " ARMED\n" : " off\n");

	con_puts(tag);
	con_puts(" WDT BARK=");
	con_hex(bark, 6);
	con_puts("ms=");
	con_dec(ticks_to_ms(bark));
	con_puts(" BITE=");
	con_hex(bite, 6);
	con_puts("ms=");
	con_dec(ticks_to_ms(bite));
	con_putc('\n');

	if (!wdt_looks_sane(en, bark, bite)) {
		con_puts(tag);
		con_puts(" WDT IMPLAUSIBLE: not msm-watchdog, will not write\n");
	}
}

uint32_t
shim_wdt_disable(void)
{
	uint32_t before = wdt_rd(WDT_EN);

	if (!(before & WDT_ENABLE)) {
		/*
		 * Not armed. Write nothing. If the phone still resets by itself
		 * after this, the watchdog is provably not the cause -- which is
		 * itself the answer we need.
		 */
		con_puts("WDT not armed, nothing written\n");
		return 0;
	}

	if (!wdt_looks_sane(before, wdt_rd(WDT_BARK_TIME), wdt_rd(WDT_BITE_TIME))) {
		con_puts("WDT SKIP: registers implausible\n");
		return before;
	}

	/*
	 * msm_wdt_disable(), verbatim:
	 *     __raw_writel(1, msm_wdt_base + WDT_RST);
	 *     __raw_writel(0, msm_wdt_base + WDT_EN);
	 * Pet first so the counter reloads even if the enable clear is ignored.
	 */
	wdt_wr(WDT_RST, 1);
	wdt_wr(WDT_EN, 0);
	__asm__ volatile("dsb sy" ::: "memory");

	uint32_t after = wdt_rd(WDT_EN);
	con_puts("WDT STOP en was=");
	con_hex(before, 8);
	con_puts(" now=");
	con_hex(after, 8);
	con_puts((after & WDT_ENABLE) ? " STILL ARMED\n" : " ok\n");
	return before;
}

/*
 * Why the previous boot ended. ABL/LK leaves a reason word in IMEM; a
 * watchdog bite, a user power cycle and a clean reboot all differ there.
 * Printed raw because the encoding is board specific and reading beats
 * guessing.
 */
uint64_t
shim_reset_reason(void)
{
#ifdef IMEM_RESTART_REASON
	if (IMEM_RESTART_REASON) {
		return *(volatile uint32_t *)(uintptr_t)IMEM_RESTART_REASON;
	}
#endif
	return 0;
}
