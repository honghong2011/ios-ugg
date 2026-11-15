/*
 * Qualcomm APSS watchdog (qcom,wdt@b017000, "qcom,msm-watchdog") and the
 * IMEM restart reason word.
 *
 * Why this matters. On this board the phone resets itself some seconds after
 * the boot image starts, which destroys exactly the evidence we need: the
 * kernel's early console is only on the panel, so a reset before it can be
 * photographed loses the whole boot. Two candidates explain a spontaneous
 * reset and only the registers tell them apart:
 *
 *   1. The APSS watchdog. LK arms it before handing over and stops petting it.
 *      Linux has the driver that disables it; XNU does not. Contract from
 *      device-dumps/dt/base/soc/qcom,wdt@b017000:
 *        reg            = <0xb017000 0x1000>
 *        qcom,bark-time = 0x3a98 (15000 ms, bark interrupt)
 *        qcom,pet-time  = 0x2710 (10000 ms, pet interval)
 *      Register map, from Linux drivers/watchdog/qcom-wdt.c:
 *        0x00 CTRL (bit0 EN)   0x04 LOAD   0x08 VAL   0x0c CTRL1
 *        0x10 STATUS           0x14 RESET (writing bit0 resets the SoC!)
 *        0x1c BARK_TIME        0x20 BITE_TIME
 *
 *   2. Something in the kernel path calling a reset.
 *
 * This file is READ-ONLY by default. It reports CTRL/CTRL1/LOAD/VAL/BARK/BITE/
 * STATUS and the IMEM restart reason, and only stops the watchdog when CTRL
 * says it is actually armed -- if it is disarmed there is nothing to change
 * and nothing is written at all. That keeps a diagnostic boot from being the
 * thing that resets the phone. Writes are also limited to the registers
 * qcom-wdt.c itself touches; RESET (0x14) is never written.
 */
#include <stdint.h>
#include "console.h"
#include "mido_compat.h"
#include "board.h"
#include "wdt.h"

#ifndef WDT_PHYS
#define WDT_PHYS	0x0b017000UL
#endif

#define WDT_CTRL	0x00
#define WDT_LOAD	0x04
#define WDT_VAL		0x08
#define WDT_CTRL1	0x0c
#define WDT_STATUS	0x10
#define WDT_BARK_TIME	0x1c
#define WDT_BITE_TIME	0x20

#define CTRL_EN		(1u << 0)

/* qcom-wdt.c: the counter runs from the 32 kHz sleep clock. */
#define WDT_HZ		32764u
#define WDT_MAX_TICKS	0xffffu

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

static uint32_t
ms_to_ticks(uint32_t ms)
{
	uint64_t t = (uint64_t)ms * WDT_HZ / 1000u;
	return t > WDT_MAX_TICKS ? WDT_MAX_TICKS : (uint32_t)t;
}

void
shim_wdt_report(const char *tag)
{
	uint32_t ctrl = wdt_rd(WDT_CTRL);

	con_puts(tag);
	con_puts(" WDT CTRL=");
	con_hex(ctrl, 8);
	con_puts(" C1=");
	con_hex(wdt_rd(WDT_CTRL1), 8);
	con_puts(" ST=");
	con_hex(wdt_rd(WDT_STATUS), 4);
	con_puts(ctrl & CTRL_EN ? " ARMED\n" : " off\n");

	con_puts(tag);
	con_puts(" WDT LOAD=");
	con_hex(wdt_rd(WDT_LOAD), 8);
	con_puts(" VAL=");
	con_hex(wdt_rd(WDT_VAL), 8);
	con_puts(" BARK=");
	con_hex(wdt_rd(WDT_BARK_TIME), 8);
	con_puts(" BITE=");
	con_hex(wdt_rd(WDT_BITE_TIME), 8);
	con_putc('\n');
}

uint32_t
shim_wdt_disable(void)
{
	uint32_t before = wdt_rd(WDT_CTRL);

	if (!(before & CTRL_EN)) {
		/*
		 * Not armed: write nothing. If the phone still resets by itself
		 * after this, the watchdog is provably not the cause, which is
		 * itself the answer we need.
		 */
		return 0;
	}

	/*
	 * Armed. Raise every timeout first so that even a half-effective
	 * disable buys minutes instead of the firmware's 15 s, then clear EN
	 * the way Linux's stop path does.
	 */
	wdt_wr(WDT_BARK_TIME, ms_to_ticks(120000));
	wdt_wr(WDT_BITE_TIME, ms_to_ticks(300000));
	wdt_wr(WDT_LOAD, ms_to_ticks(120000));
	wdt_wr(WDT_CTRL, before & ~CTRL_EN);

	uint32_t after = wdt_rd(WDT_CTRL);
	con_puts("WDT STOP was=");
	con_hex(before, 8);
	con_puts(" now=");
	con_hex(after, 8);
	con_puts((after & CTRL_EN) ? " STILL ARMED\n" : " ok\n");
	return before;
}

/*
 * Why the previous boot ended. ABL/LK leaves a reason word in IMEM; a
 * watchdog bite, a user power cycle and a clean reboot all differ. Printed
 * raw because the encoding is board specific and reading it beats guessing.
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
