/*
 * ugg U1 (MSM8940 / Redmi Note 5A Prime): one boot answers the questions
 * that decide the XNU port.
 *   - does LK hand us a DTB in x0, and does /chosen carry an initrd?
 *   - CPU feature registers: XNU needs the 16K translation granule
 *   - PSCI version and SMP: CPU_ON for the 7 secondaries (MPIDR 0x0-3/0x100-103)
 *   - GICv2 (qcom,msm-qgic2 at 0xb000000): do Group 1 IRQs work at all, and
 *     which timer PPI fires (virtual is INTID 20 here, not sweet's 19)?
 * Any unexpected exception paints a blue panic screen.
 */
#include <stdint.h>
#include "console.h"
#include "mmu.h"
#include "loader.h"

#define IMEM_RESTART_REASON	0x0860065cUL	/* qcom,msm-imem@8600000 restart_reason@65c */
#define RESTART_BOOTLOADER	0x77665500U
#define PSHOLD			0x004ab000UL	/* soc/restart@4ab000 pshold-base */

/* GICv2: GIC-400, distributor + CPU interface, no redistributors */
#define GICD_BASE		0x0b000000UL
#define GICC_BASE		0x0b002000UL

#define GICD_CTLR		0x000
#define GICD_TYPER		0x004
#define GICD_IIDR		0x008
#define GICD_IGROUPR		0x080
#define GICD_ISENABLER		0x100
#define GICD_ICENABLER		0x180
#define GICD_ISPENDR		0x200
#define GICD_ISACTIVER		0x300
#define GICD_IPRIORITYR		0x400
#define GICD_ITARGETSR		0x800
#define GICD_ICFGR		0xc00
#define GICD_SGIR		0xf00

#define GICC_CTLR		0x000
#define GICC_PMR		0x004
#define GICC_BPR		0x008
#define GICC_IAR		0x00c
#define GICC_EOIR		0x010
#define GICC_HPPIR		0x014
#define GICC_IIDR		0x0fc
#define GICC_DIR		0x1000

/*
 * DT: <GIC_PPI 2 ..> secure phys, <3> non-secure phys, <4> virtual, <1> hyp.
 * So the virtual timer XNU uses is INTID 16 + 4 = 20 (sweet's SM7150 has 19).
 */
#define VTIMER_INTID		20
#define PTIMER_INTID		19
#define SGI_INTID		1

#define GICD_CTLR_ENABLEGRP1	0x1

#define PSCI_VERSION		0x84000000UL
#define PSCI_CPU_SUSPEND	0xc4000001UL
#define PSCI_CPU_OFF		0x84000002UL
#define PSCI_CPU_ON		0xc4000003UL
#define PSCI_SYSTEM_RESET	0x84000009UL
#define PSCI_FEATURES		0x8400000aUL
#define SMCCC_VERSION		0x80000000UL

#define NR_CPUS			8

#define rsr(r) ({ uint64_t _v; __asm__ volatile("mrs %0, " r : "=r"(_v)); _v; })
#define wsr(r, v) __asm__ volatile("msr " r ", %0" : : "r"((uint64_t)(v)))
#define isb() __asm__ volatile("isb" ::: "memory")

static inline uint32_t rd32(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline uint64_t rd64(uintptr_t a) { return *(volatile uint64_t *)a; }
static inline void wr32(uintptr_t a, uint32_t v) { *(volatile uint32_t *)a = v; }
static inline void wr8(uintptr_t a, uint8_t v) { *(volatile uint8_t *)a = v; }

extern char secondary_entry[];

static const char *stage;	/* set at runtime: no absolute pointers in data */
static const uint64_t cpu_mpidr[NR_CPUS] = {
	0x0, 0x1, 0x2, 0x3, 0x100, 0x101, 0x102, 0x103
};
static volatile uint64_t sec_mpidr[NR_CPUS];
static volatile uint32_t sec_up[NR_CPUS];
static volatile uint32_t irq_count, irq_other, irq_last;
static volatile int irq_src;

static uint64_t smc(uint64_t fn, uint64_t a1, uint64_t a2, uint64_t a3)
{
	register uint64_t x0 __asm__("x0") = fn;
	register uint64_t x1 __asm__("x1") = a1;
	register uint64_t x2 __asm__("x2") = a2;
	register uint64_t x3 __asm__("x3") = a3;
	__asm__ volatile("smc #0"
			 : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3)
			 :
			 : "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11",
			   "x12", "x13", "x14", "x15", "x16", "x17", "memory");
	return x0;
}

static uint64_t now(void)
{
	isb();
	return rsr("cntpct_el0");
}

static void delay_ms(unsigned ms)
{
	uint64_t frq = rsr("cntfrq_el0");
	uint64_t end = now() + frq / 1000 * ms;
	while (frq && now() < end)
		;
}

static void __attribute__((noreturn)) reset(unsigned after_s)
{
	con_skip();
	con_str("RESET", after_s > 20 ? "in 40s (then fastboot)" : "in 20s");
	delay_ms(after_s * 1000);
	wr32(IMEM_RESTART_REASON, RESTART_BOOTLOADER);
	__asm__ volatile("dsb sy" ::: "memory");
	smc(PSCI_SYSTEM_RESET, 0, 0, 0);
	wr32(PSHOLD, 0);
	for (;;)
		__asm__ volatile("wfe");
}

/* ---- exceptions ---- */

static void irq_handler(void)
{
	uint32_t iar = rd32(GICC_BASE + GICC_IAR);
	uint32_t id = iar & 0x3ff;

	if (id >= 1020)
		return;	/* spurious: do not EOI */
	irq_last = id;
	if (id == (uint32_t)irq_src)
		irq_count++;
	else
		irq_other++;
	if (id == VTIMER_INTID)
		wsr("cntv_tval_el0", rsr("cntfrq_el0") / 100);	/* 10 ms */
	else if (id == PTIMER_INTID)
		wsr("cntp_tval_el0", rsr("cntfrq_el0") / 100);
	wr32(GICC_BASE + GICC_EOIR, iar);	/* EOImode 0: also deactivates */
	isb();
}

void exc_handler(uint64_t slot, uint64_t *regs)
{
	if (slot == 5) {	/* IRQ from current EL, SPx */
		irq_handler();
		return;
	}
	con_clear(BLUE);
	switch (slot & 3) {
	case 0: con_str("PANIC", "SYNC"); break;
	case 1: con_str("PANIC", "IRQ"); break;
	case 2: con_str("PANIC", "FIQ"); break;
	default: con_str("PANIC", "SERROR"); break;
	}
	con_hex2("SLOT", "n=", slot, "cpu=", rsr("mpidr_el1"));
	con_str("STAGE", stage);
	con_hex("ESR", rsr("esr_el1"));
	con_hex("ELR", rsr("elr_el1"));
	con_hex("FAR", rsr("far_el1"));
	con_hex("SPSR", rsr("spsr_el1"));
	con_hex("X0", regs[0]);
	con_hex("X1", regs[1]);
	con_hex("X30", regs[31]);	/* x29/x30 were stashed just above the frame */
	reset(40);
}

/* ---- SMP ---- */

void secondary_main(uint64_t idx)
{
	if (idx < NR_CPUS) {
		sec_mpidr[idx] = rsr("mpidr_el1");
		__asm__ volatile("dsb sy" ::: "memory");
		sec_up[idx] = 1;
	}
	__asm__ volatile("dsb sy" ::: "memory");
	smc(PSCI_CPU_OFF, 0, 0, 0);
	for (;;)
		__asm__ volatile("wfe");
}

static void test_smp(void)
{
	uint64_t self = rsr("mpidr_el1") & 0xffffff;
	int32_t rc[NR_CPUS];
	uint32_t on0 = 0, on1 = 0, rc0 = 0, rc1 = 0;

	stage = "smp";
	for (int i = 0; i < NR_CPUS; i++) {
		rc[i] = -1;
		if (cpu_mpidr[i] == self) {
			rc[i] = 1;	/* boot cpu */
			continue;
		}
		rc[i] = (int32_t)smc(PSCI_CPU_ON, cpu_mpidr[i],
				     (uintptr_t)secondary_entry, (uint64_t)i);
	}
	delay_ms(500);
	for (int i = 0; i < NR_CPUS; i++) {
		uint32_t up = (sec_up[i] &&
			       (sec_mpidr[i] & 0xffffff) == cpu_mpidr[i]) ? 1 : 0;
		if (i < 4) {
			on0 |= up << i;
			rc0 |= ((uint32_t)rc[i] & 0xff) << (8 * i);
		} else {
			on1 |= up << (i - 4);
			rc1 |= ((uint32_t)rc[i] & 0xff) << (8 * (i - 4));
		}
	}
	con_hex2("SMP0", "on=", on0, "rc=", rc0);
	con_hex2("SMP1", "on=", on1, "rc=", rc1);
}

/* ---- GICv2 + timer ---- */

/* SGI to the calling CPU: GICv2 GICD_SGIR, TargetListFilter 2 = self */
static void send_sgi(unsigned id)
{
	wr32(GICD_BASE + GICD_SGIR, (2U << 24) | id);
	isb();
}

/*
 * Run one interrupt source for ~300 ms and report what the GIC saw.
 * IRQs are masked while the first period elapses, so the pending/active
 * state can be sampled without racing the handler.
 */
static void irq_window(const char *label, int src)
{
	uint64_t f = rsr("cntfrq_el0");
	uint32_t pend, hppi, ist;

	irq_count = irq_other = 0;
	irq_last = 0x3ff;
	irq_src = src;
	if (src == VTIMER_INTID) {
		wsr("cntv_tval_el0", f / 100);
		wsr("cntv_ctl_el0", 1);
	} else if (src == PTIMER_INTID) {
		wsr("cntp_tval_el0", f / 100);
		wsr("cntp_ctl_el0", 1);
	}
	isb();
	uint64_t t = now() + f / 50;
	while (now() < t)
		;
	if (src == SGI_INTID)
		send_sgi(SGI_INTID);
	isb();
	ist = src == PTIMER_INTID ? rsr("cntp_ctl_el0") : rsr("cntv_ctl_el0");
	pend = rd32(GICD_BASE + GICD_ISPENDR);
	hppi = rd32(GICC_BASE + GICC_HPPIR) & 0x3ff;

	__asm__ volatile("msr daifclr, #2" ::: "memory");
	t = now() + f * 3 / 10;
	uint64_t next = now() + f / 100;
	for (int sent = 1; now() < t;) {
		if (src == SGI_INTID && sent < 10 && now() >= next) {
			send_sgi(SGI_INTID);
			sent++;
			next += f / 100;
		}
	}
	__asm__ volatile("msr daifset, #2" ::: "memory");
	wsr("cntv_ctl_el0", 0);
	wsr("cntp_ctl_el0", 0);
	isb();

	con_hex2(label, "n=", irq_count, "other=", irq_other);
	if (src == VTIMER_INTID)
		con_hex2(" pre", "pend=", pend, "hppi=", hppi);
	con_hex2(" pre", "tctl=", ist, "last=", irq_last);
}

static void test_gic(void)
{
	stage = "gic ids";
	con_hex2("GICD", "iidr=", rd32(GICD_BASE + GICD_IIDR),
		 "typer=", rd32(GICD_BASE + GICD_TYPER));
	con_hex2("GICC", "iidr=", rd32(GICC_BASE + GICC_IIDR),
		 "ctlr=", rd32(GICC_BASE + GICC_CTLR));

	stage = "gic ctlr";
	uint32_t dctlr = rd32(GICD_BASE + GICD_CTLR);
	uint32_t cctlr = rd32(GICC_BASE + GICC_CTLR);
	/* NS view: bit0 is EnableGrp1 (TrustZone owns Group 0) */
	wr32(GICD_BASE + GICD_CTLR, dctlr | GICD_CTLR_ENABLEGRP1);
	for (int i = 0; i < 1000000 && (rd32(GICD_BASE + GICD_CTLR) & (1U << 31)); i++)
		;
	wr32(GICC_BASE + GICC_CTLR, cctlr | GICD_CTLR_ENABLEGRP1);
	wr32(GICC_BASE + GICC_PMR, 0xff);
	wr32(GICC_BASE + GICC_BPR, 0);
	isb();
	con_hex2("GICDCTL", "was=", dctlr, "now=", rd32(GICD_BASE + GICD_CTLR));
	con_hex2("GICCCTL", "was=", cctlr, "now=", rd32(GICC_BASE + GICC_CTLR));

	stage = "gic config";
	uint32_t grp = rd32(GICD_BASE + GICD_IGROUPR);
	uint32_t en = rd32(GICD_BASE + GICD_ISENABLER);
	for (int id = 0; id < 32; id++)
		wr8(GICD_BASE + GICD_IPRIORITYR + id, 0xa0);
	/* level-sensitive PPIs: clear both config bits for INTID 19 and 20 */
	uint32_t cfg = rd32(GICD_BASE + GICD_ICFGR + 4);
	cfg &= ~((3U << 6) | (3U << 8));
	wr32(GICD_BASE + GICD_ICFGR + 4, cfg);
	wr8(GICD_BASE + GICD_ITARGETSR + SGI_INTID, 1);
	wr32(GICD_BASE + GICD_ISENABLER,
	     (1U << VTIMER_INTID) | (1U << PTIMER_INTID) | (1U << SGI_INTID));
	isb();
	con_hex2("IGROUP", "ppi=", grp >> 16, "sgi=", grp & 0xffff);
	con_hex2("ISET", "was=", en, "now=", rd32(GICD_BASE + GICD_ISENABLER));

	stage = "gic vtimer";
	irq_window("VTIMER", VTIMER_INTID);
	stage = "gic ptimer";
	irq_window("PTIMER", PTIMER_INTID);
	stage = "gic sgi";
	irq_window("SGI1", SGI_INTID);
	wr32(GICD_BASE + GICD_ICENABLER, 0xffffffff);
	isb();
}

/* ---- main ---- */

void shim_main(uint64_t dtb)
{
	struct mmu_info mi;

	stage = "banner";
	con_clear(RED);
	con_str("SHIM", "ugg U1: GICv2 / timer / SMP probe");
	con_skip();
	con_hex2("DTB", "at=", (uint32_t)dtb,
		 "magic=", dtb ? __builtin_bswap32(rd32(dtb)) : 0);

	/* xnu payload? For U1 the ramdisk is empty, so this just validates
	 * that /chosen parses (and prints the initrd the LK passed). */
	stage = "loader";
	const char *why = loader_boot(dtb);
	con_str("LOADER", why);
	con_skip();

	stage = "cpu";
	uint64_t mmfr0 = rsr("id_aa64mmfr0_el1");
	con_hex2("CPU", "midr=", (uint32_t)rsr("midr_el1"),
		 "mmfr0=", (uint32_t)mmfr0);
	con_hex2("CPU", "tg16=", (mmfr0 >> 20) & 0xf,
		 "tg64=", (mmfr0 >> 24) & 0xf);
	con_hex2("CPU", "parange=", mmfr0 & 0xf,
		 "pfr0lo=", (uint32_t)rsr("id_aa64pfr0_el1"));
	con_hex2("TIME", "frq=", rsr("cntfrq_el0"),
		 "cnt=", (uint32_t)rsr("cntpct_el0"));
	con_skip();

	stage = "psci";
	con_hex2("PSCI", "ver=", smc(PSCI_VERSION, 0, 0, 0),
		 "smccc=", smc(SMCCC_VERSION, 0, 0, 0));
	con_skip();

	test_gic();
	con_skip();

	test_smp();
	con_skip();

	/*
	 * The MMU test only runs when the CPU advertises the 16K granule:
	 * enabling it otherwise would fault before the vector can be fetched.
	 */
	stage = "mmu";
	if (((mmfr0 >> 20) & 0xf) != 0) {
		con_str("MMU", "no 16K granule: XNU blocker");
	} else if (mmu_enable(&mi)) {
		con_str("MMU", "setup failed");
	} else {
		con_hex2("MMU", "l3=", mi.n_l3, "ttbr=", (uint32_t)mi.ttbr);
		con_hex2("PAR", "img=", mmu_probe((uintptr_t)shim_main),
			 "fb=", mmu_probe(FB_PHYS + 0x1000));
		con_hex2("PAR", "gic=", mmu_probe(GICD_BASE),
			 "12G=", mmu_probe(0x300000000UL));
	}

	stage = "done";
	reset(40);
}
