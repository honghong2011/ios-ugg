/*
 * Milestone 4: act as iBoot for xnu.
 *
 * mkpayload.py already resolved the kernel's chained fixups and built the
 * ADT, so this only has to: find the payload in the ABL ramdisk, copy the
 * segments to phys_base + (vmaddr - virt_base), place the ADT and
 * boot_args behind the kernel, and jump to the entry point with the MMU
 * and caches off, x0 = boot_args (physical).
 */
#include <stdint.h>
#include "console.h"
#include "fdt.h"
#include "loader.h"
#include "mmu.h"
#include "emmc.h"
#include "fb32.h"

#define rsr(r) ({ uint64_t _v; __asm__ volatile("mrs %0, " r : "=r"(_v)); _v; })
#define wsr(r, v) __asm__ volatile("msr " r ", %0" : : "r"((uint64_t)(v)))

#define BOOT_LINE_LENGTH	608
/*
 * Hardware page size for the boot_args placement. sweet is a 16K kernel;
 * ugglite's Cortex-A53 has no 16K granule, so its kernel pages are 4K and
 * boot_args/topOfKernelData must be aligned to that.
 */
#if defined(BOARD_UGGLITE) || defined(BOARD_UGG)
#define BOOT_PAGE		0x1000UL
#else
#define BOOT_PAGE		0x4000UL
#endif

struct payload_seg {
	uint64_t vmaddr, vmsize, file_off, file_size;
};

struct payload {
	char magic[8];
	uint32_t version, nsegs;
	uint64_t virt_base, entry_va, adt_off, adt_size, kernel_end;
	uint64_t phys_base, mem_size;
	char cmdline[BOOT_LINE_LENGTH];
	struct payload_seg segs[];
};

/* pexpert/pexpert/arm64/boot.h, Revision/Version 2 */
struct boot_video {
	uint64_t v_baseAddr, v_display, v_rowBytes, v_width, v_height, v_depth;
};

struct boot_args {
	uint16_t Revision, Version;
	uint64_t virtBase, physBase, memSize, topOfKernelData;
	struct boot_video Video;
	uint32_t machineType;
	uint64_t deviceTreeP;
	uint32_t deviceTreeLength;
	char CommandLine[BOOT_LINE_LENGTH];
	uint64_t bootFlags, memSizeActual;
};

_Static_assert(__builtin_offsetof(struct payload, segs) == 0x2a8, "payload header layout");
_Static_assert(__builtin_offsetof(struct boot_args, Video) == 40, "boot_args layout");
_Static_assert(__builtin_offsetof(struct boot_args, CommandLine) == 108, "boot_args layout");
_Static_assert(sizeof(struct boot_args) == 736, "boot_args layout");

/* MMU off: everything is Device memory, so copy in aligned 8-byte words. */
static void copy64(uintptr_t dst, uintptr_t src, uint64_t n)
{
	volatile uint64_t *d = (volatile uint64_t *)dst;
	volatile const uint64_t *s = (volatile const uint64_t *)src;
	for (uint64_t i = 0; i < (n + 7) / 8; i++)
		d[i] = s[i];
}

static void zero64(uintptr_t dst, uint64_t n)
{
	volatile uint64_t *d = (volatile uint64_t *)dst;
	for (uint64_t i = 0; i < n / 8; i++)
		d[i] = 0;
}

/* Search the payload's command line for a flag, without libc. */
static int
cmdline_has(const char *cmd, const char *needle)
{
	for (int i = 0; i < BOOT_LINE_LENGTH && cmd[i]; i++) {
		int k = 0;
		while (needle[k] && i + k < BOOT_LINE_LENGTH && cmd[i + k] == needle[k]) {
			k++;
		}
		if (!needle[k]) {
			return 1;
		}
	}
	return 0;
}

/* Busy-wait on the architected counter; the shim has no timers yet. */
static void
loader_delay_ms(uint32_t ms)
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

static int magic_ok(const char *m)
{
	static const char want[] = "SWEETXNU";
	for (int i = 0; i < 8; i++)
		if (m[i] != want[i])
			return 0;
	return 1;
}

typedef void (*xnu_entry_t)(uint64_t boot_args_pa);

const char *loader_boot(uintptr_t dtb)
{
	uint64_t rd_start, rd_end;

	if (!fdt_chosen_u64(dtb, "linux,initrd-start", &rd_start) ||
	    !fdt_chosen_u64(dtb, "linux,initrd-end", &rd_end)) {
		/*
		 * ugglite's lk does not report the ramdisk in /chosen and does
		 * not place it at the header's ramdisk_addr (measured), so the
		 * payload is appended to the kernel image instead and found
		 * relative to the shim's own load address.
		 */
		extern uintptr_t sweet_payload_addr(void);
		uintptr_t pa = sweet_payload_addr();

		if (!pa)
			return "no payload after shim";
		rd_start = pa;
		rd_end = pa + 0x2000000;	/* 32 MiB ceiling; size comes from the header */
	}
	con_hex2("INITRD", "lo=", rd_start, "hi=", rd_end);

	const struct payload *p = (const struct payload *)rd_start;
	if (!magic_ok(p->magic))
		return "no SWEETXNU payload";
	if (p->version != 1 || (p->adt_off & 7) || (rd_start & 7))
		return "bad payload header";

	uint64_t pa_of_va_base = p->phys_base - p->virt_base;	/* pa = va + this */
	con_hex2("PHYS", "base=", p->phys_base, "size=", p->mem_size);
	con_hex("VIRT", p->virt_base);
	con_hex("ENTRY", p->entry_va);

	/* The payload must not overlap where the kernel goes. */
	if (rd_end > p->phys_base && rd_start < p->phys_base + p->mem_size)
		return "ramdisk overlaps kernel memory";

	for (uint32_t i = 0; i < p->nsegs; i++) {
		const struct payload_seg *s = &p->segs[i];
		uintptr_t dst = s->vmaddr + pa_of_va_base;
		copy64(dst, rd_start + s->file_off, s->file_size);
		if (s->vmsize > s->file_size)
			zero64(dst + ((s->file_size + 7) & ~7UL), s->vmsize - ((s->file_size + 7) & ~7UL));
	}
	con_hex2("SEGS", "n=", p->nsegs, "end=", p->kernel_end + pa_of_va_base);

	/* ADT, then boot_args, behind the kernel; everything below topOfKernelData is ours. */
	uintptr_t adt_pa = p->kernel_end + pa_of_va_base;
	copy64(adt_pa, rd_start + p->adt_off, p->adt_size);
	uintptr_t ba_pa = (adt_pa + p->adt_size + BOOT_PAGE - 1) & ~(BOOT_PAGE - 1);
	uintptr_t top = ba_pa + BOOT_PAGE;

	zero64(ba_pa, BOOT_PAGE);
	volatile struct boot_args *ba = (volatile struct boot_args *)ba_pa;
	ba->Revision = 2;
	ba->Version = 2;
	ba->virtBase = p->virt_base;
	ba->physBase = p->phys_base;
	ba->memSize = p->mem_size;
	ba->topOfKernelData = top;
	/*
	 * 32 bpp, 4 bytes per pixel, stride 720*4.
	 *
	 * The shim's own console above is 24 bpp and stays that way: it is proven
	 * on this panel. But XNU must be told 32 bpp, because the pipe is switched
	 * to BGRX8888 just before the jump (shim_fb_stage_32bpp), and because
	 * SweetFramebuffer::start() refuses fRowBytes < fWidth * 4 -- at 24 bpp the
	 * GUI can never attach. mido runs the same way on the same MDP5 family.
	 */
	ba->Video.v_baseAddr = FB_PHYS;
	ba->Video.v_display = 1;
	ba->Video.v_rowBytes = (uint64_t)FB_W * 4u;
	ba->Video.v_width = FB_W;
	ba->Video.v_height = FB_H;
	ba->Video.v_depth = 32;
	ba->deviceTreeP = adt_pa - pa_of_va_base;	/* xnu reads it with the MMU on: a VA */
	ba->deviceTreeLength = (uint32_t)p->adt_size;
	for (int i = 0; i < BOOT_LINE_LENGTH; i++)
		ba->CommandLine[i] = p->cmdline[i];
	ba->memSizeActual = p->mem_size;
	con_hex2("BOOTARG", "pa=", ba_pa, "top=", top);

	uintptr_t entry_pa = p->entry_va + pa_of_va_base;
	/*
	 * Prove the copy landed: read the first word back from the entry point
	 * and from phys_base. If these do not match the payload's bytes, the
	 * destination is not writable RAM (an XPU carve-out, or the wrong base),
	 * which is a very different failure from a bad entry address.
	 */
	con_hex("WROTE", *(volatile uint32_t *)entry_pa);
	con_hex("EXPECT", *(const uint32_t *)(rd_start +
	    (p->segs[2].file_off + (p->entry_va - p->segs[2].vmaddr))));
	con_hex("JUMP", entry_pa);
	con_str("XNU", "jumping (fbcon clears screen)");

	/*
	 * Flush the console log here, not only at the end of the eMMC probe.
	 *
	 * Everything above -- INITRD, PHYS, ENTRY, SEGS, BOOTARG, WROTE, EXPECT,
	 * JUMP -- is printed after the probe's flush, so a dump taken from the
	 * cache partition would end before the most useful lines of the boot. This
	 * is the last point where the shim still controls the CPU, so it is the
	 * last chance to persist what happened.
	 */
	ugg_emmc_flush_log();

	/* Everything was written with the MMU and caches off; drop any stale I-cache lines too. */
	/*
	 * Enter XNU with the MMU ON and its RAM mapped Normal write-back.
	 * With the MMU off every fetch is Device-nGnRnE, and instruction fetch
	 * from Device memory is constrained-unpredictable; on this A53 the
	 * branch to the entry point then produced no output at all. XNU's own
	 * start.s reprograms the MMU from scratch, so the mapping only has to
	 * be sane for the first few instructions.
	 */
	/*
	 * Leave the MMU OFF, as on sweet. The previous attempt to enter with it
	 * on was a hypothesis that did not help, and it also risked unmapping
	 * the shim's own code mid-flight.
	 */
	/*
	 * Keep the shim's exception vectors installed across the jump.
	 *
	 * XNU sets VBAR_EL1 early (before it has mapped the vectors' address), so
	 * any fault in its first instructions vectors into unmapped memory and
	 * the machine simply stops with no output - exactly what we see. Pointing
	 * VBAR_EL1 back at the shim's table means such a fault lands in
	 * exc_handler(), which prints ESR/ELR/FAR on the panel and tells us which
	 * instruction failed.
	 */
	{
		extern char vectors[];
		uintptr_t vb = (uintptr_t)vectors;

		__asm__ volatile("msr vbar_el1, %0" : : "r"(vb) : "memory");
		__asm__ volatile("isb" ::: "memory");
	}

	/*
	 * Arm a one-shot watchdog before entering XNU: GICv2 distributor and CPU
	 * interface enabled, virtual timer PPI unmasked, CNTV firing once about
	 * a second from now. If XNU hangs in a loop (no exception, so the vector
	 * table never runs) this interrupt still lands in the shim's handler,
	 * which prints the interrupted PC. XNU masks interrupts itself early on,
	 * so this only helps before that point - which is exactly where it hangs.
	 */
#if GIC_IS_V2
	{
		volatile uint32_t *gicd = (volatile uint32_t *)GICD_BASE;
		volatile uint32_t *gicc = (volatile uint32_t *)GICC_BASE;
		uint32_t ctfrq = (uint32_t)rsr("cntfrq_el0");

		gicd[0x000 / 4] = 1;			/* GICD_CTLR enable */
		gicd[0x080 / 4] = 0xffffffff;		/* IGROUPR0: all Group 1 */
		gicd[0x100 / 4] = (1u << VTIMER_INTID);	/* ISENABLER0 */
		gicd[0x400 / 4] = 0xa0a0a0a0;		/* IPRIORITYR0 */
		gicc[0x004 / 4] = 0xff;			/* PMR */
		gicc[0x000 / 4] = 1;			/* CTLR enable */

		wsr("cntv_tval_el0", ctfrq);		/* ~1 s */
		wsr("cntv_ctl_el0", 1);			/* enable, unmask */
		__asm__ volatile("isb" ::: "memory");
	}
#endif

	/*
	 * The one-shot armed above fires about a second from now, and everything
	 * below holds the screen for seconds (the colour-bar selftest holds it
	 * indefinitely). Disarm it here and re-arm it immediately before the jump,
	 * so the watchdog still guards XNU's entry and nothing else.
	 */
	wsr("cntv_ctl_el0", 0);
	__asm__ volatile("isb" ::: "memory");

	__asm__ volatile("dsb sy; ic iallu; dsb sy; isb" ::: "memory");

	/*
	 * Last shim step: hand the pipe over in the format XNU expects, show a
	 * shape that can actually be photographed, then jump.
	 *
	 * Everything the shim printed above is 24 bpp, and it stays visible until
	 * the flush because nothing changes on the panel before it. Register
	 * read-backs are printed first for exactly that reason: they are readable
	 * on the 24 bpp console even if the 32 bpp picture turns out wrong.
	 *
	 * Command line flag ugg_fbtest=1 holds the read-back and the bars long
	 * enough to photograph both; a normal boot only flashes them briefly.
	 */
	{
		int fbtest = cmdline_has(p->cmdline, "ugg_fbtest=1");
		int ok32 = shim_fb_stage_32bpp();

		con_str("RGB0 32BPP", ok32 ? "staged (registers read back)" : "REFUSED");
		con_hex("VIDEO rowbytes", ba->Video.v_rowBytes);
		con_hex("VIDEO depth", ba->Video.v_depth);
		/* give the read-back a chance to be photographed */
		loader_delay_ms(fbtest ? 6000u : 0u);

		shim_fb_commit_32bpp();
		shim_fb_bars32(fbtest ? 3000u : 1200u);
		if (fbtest) {
			/*
			 * Hold the bars forever: this boot exists only to photograph
			 * them. A colour bar either survives the scan chain or it does
			 * not, and that answer needs no kernel.
			 */
			for (;;) {
				__asm__ volatile("wfi");
			}
		}
		shim_fb_black32();
	}

	/* Re-arm the one-shot watchdog as the last thing before hand-off. */
#if GIC_IS_V2
	wsr("cntv_tval_el0", (uint64_t)(uint32_t)rsr("cntfrq_el0"));
	wsr("cntv_ctl_el0", 1);
	__asm__ volatile("isb" ::: "memory");
#endif

	((xnu_entry_t)entry_pa)(ba_pa);

	/*
	 * Reached only if XNU returns (it should never) or if the call faults
	 * back into the shim. Paint green over the bottom of the panel so the
	 * difference from a hang is visible on screen.
	 */
	{
		volatile uint8_t *fb = (volatile uint8_t *)FB_PHYS;
		for (int y = 0; y < 32; y++)
			for (int x = 0; x < FB_W; x++) {
				volatile uint8_t *q = fb + (uintptr_t)(FB_H - 48 + y) * FB_STRIDE
				    + (uintptr_t)x * FB_BPP;
#if FB_BPP == 4
				*(volatile uint32_t *)q = 0xff00ff00u;
#else
				q[0] = 0x00; q[1] = 0xff; q[2] = 0x00;
#endif
			}
	}
	return "xnu returned";
}

/*
 * Where is the payload?
 *
 * On sweet, ABL reports linux,initrd-start/end in /chosen and loader_boot()
 * uses that. ugglite's lk does not: its stock DTB's chosen node has only
 * bootargs, and measurement showed the ramdisk is not placed at the boot image
 * header's ramdisk_addr either (0x81000000 read back as unrelated data, and a
 * 64 KiB test ramdisk was not found there either). lk does reliably load and
 * decompress the KERNEL, so shim/build.sh appends the payload to the kernel
 * image and the shim looks for it relative to its own load address.
 *
 * The image is linked at 0, so `&_end` is the offset of the byte just past
 * the shim within the loaded image; the payload follows at a 16K boundary.
 */
uintptr_t
sweet_payload_addr(void)
{
	extern char _end[];
	/* Position independent: _end's address is base + its link-time offset. */
	uintptr_t self_end = (uintptr_t)_end;
	uintptr_t cand = (self_end + 0x3fff) & ~(uintptr_t)0x3fff;

	/*
	 * Check the version as well as the magic: the string "SWEETXNU" also
	 * appears in this file (magic_ok's own comparison), so the magic alone
	 * is not enough to identify a payload.
	 */
	for (int i = 0; i <= 8; i++) {
		uintptr_t a = cand + (uintptr_t)i * 0x4000;
		const struct payload *p = (const struct payload *)a;

		if (magic_ok(p->magic) && p->version == 1 &&
		    p->nsegs > 0 && p->nsegs < 64)
			return a;
	}
	return 0;
}
