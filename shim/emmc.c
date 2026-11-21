/*
 * eMMC probe for the ugg shim: SDHCI-MSM read path, GPT parse, guarded write
 * of the console log ring into the "cache" partition.
 *
 * The driver itself (sdhc.c) and the RPM / SPMI helpers come from the mido
 * port, where they were verified on hardware. What is ugg-specific here is
 * only the partition policy: ugg keeps Android on the internal eMMC and must
 * never touch user data, so this file
 *
 *   - reads LBA0 / LBA1 and prints the signatures,
 *   - walks the GPT and prints every partition it finds,
 *   - and only ever allows writes inside a partition whose name matches
 *     "cache" AND whose first LBA it printed. Nothing else is writable.
 *
 * If there is no "cache" partition the probe still reports the read path,
 * which is all the XNU eMMC driver needs; the log ring is a convenience.
 */
#include <stdint.h>
#include "console.h"
#include "mido_compat.h"
#include "sdhc.h"

#define LOG_SECTORS 128            /* 64 KiB of console log */

/* The console log lives at the end of the shim image (see console.c). */
extern uintptr_t con_log_phys(void);

static uint32_t blk[128];
static uint64_t cache_first;
static uint64_t cache_sectors;
static uint64_t userdata_first;
static uint64_t userdata_sectors;
static int      write_ok;
static int      emmc_code;

/* One 128-byte GPT entry, little endian, name at offset 56 as UTF-16LE. */
static int
name_eq(const uint32_t *e, const char *want)
{
	const uint16_t *n = (const uint16_t *)((const uint8_t *)e + 56);
	for (int i = 0; want[i]; i++) {
		if (n[i] != (uint16_t)(unsigned char)want[i]) {
			return 0;
		}
	}
	return n[(int)0] != 0 ? 1 : 0;
}

static void
gpt_walk(void)
{
	uint64_t ent_lba = (uint64_t)blk[18] | ((uint64_t)blk[19] << 32);
	uint32_t n = blk[20], esz = blk[21];
	if (esz != 128 || n == 0 || n > 256) {
		con_puts("GPT BAD ESZ/N\n");
		emmc_code = 5;
		return;
	}
	con_puts("GPT ENTRIES=");
	con_dec(n);
	con_putc('\n');
	uint32_t used = 0;
	for (uint32_t i = 0; i < n; i++) {
		if (i % 4 == 0 && sdhc_read(ent_lba + i / 4, blk)) {
			con_puts("GPT READ E\n");
			emmc_code = 5;
			return;
		}
		const uint32_t *ent = blk + (i % 4) * 32;
		/* A zero type GUID means an unused entry: skip it silently. */
		if (ent[0] == 0 && ent[1] == 0 && ent[2] == 0 && ent[3] == 0) {
			continue;
		}
		uint64_t first = (uint64_t)ent[8] | ((uint64_t)ent[9] << 32);
		uint64_t last = (uint64_t)ent[10] | ((uint64_t)ent[11] << 32);
		used++;
		/*
		 * Only the partitions the boot cares about are printed.
		 *
		 * A full dump listed all 48 entries, which scrolled the panel so far
		 * that the interesting lines (INITRD, JUMP, XNU jumping) had already
		 * left the screen by the time a photograph could be taken. The
		 * addresses are still recovered for the ones that matter, and the
		 * count keeps the rest observable.
		 */
		if (name_eq(ent, "cache")) {
			cache_first = first;
			cache_sectors = last - first + 1;
			con_puts("GPT cache  F=");
			con_dec(first);
			con_puts(" N=");
			con_dec(last - first + 1);
			con_putc('\n');
		} else if (name_eq(ent, "userdata")) {
			userdata_first = first;
			userdata_sectors = last - first + 1;
			con_puts("GPT userdat F=");
			con_dec(first);
			con_puts(" N=");
			con_dec(last - first + 1);
			con_putc('\n');
		} else if (name_eq(ent, "boot")) {
			con_puts("GPT boot   F=");
			con_dec(first);
			con_puts(" N=");
			con_dec(last - first + 1);
			con_putc('\n');
		}
	}
	con_puts("GPT used=");
	con_dec(used);
	con_putc('\n');
	if (cache_first == 0) {
		con_puts("NO CACHE PARTITION, WRITES OFF\n");
		return;
	}
	con_puts("CACHE F=");
	con_dec(cache_first);
	con_puts(" N=");
	con_dec(cache_sectors);
	con_putc('\n');
	if (cache_sectors >= LOG_SECTORS) {
		sdhc_allow_writes(cache_first, cache_first + LOG_SECTORS);
		write_ok = 1;
		con_puts("LOG TO CACHE ENABLED\n");
	} else {
		con_puts("CACHE TOO SMALL, WRITES OFF\n");
	}
}

void
ugg_emmc_flush_log(void)
{
	if (!write_ok) {
		return;
	}
	/*
	 * The log is written while the console keeps appending to it, so the
	 * message below lands in the ring and shows up in the NEXT flush. That is
	 * harmless (the ring is the source of truth) but worth knowing when
	 * reading the dump: the last line of a dump is one flush behind.
	 */
	int e = 0;
	int bad = -1;
	for (int i = 0; i < LOG_SECTORS; i++) {
		e = sdhc_write(cache_first + i, (const void *)(con_log_phys() + 512UL * i));
		if (e) {
			bad = i;
			break;
		}
	}
	if (e) {
		emmc_code = 8;
		/*
		 * Print the code. "LOG WRITE E" alone said a write failed but not
		 * whether it was the command (the number is the CMD24 error) or the
		 * programming timeout, and those need different fixes. The sector
		 * says whether the window is right: a failure at sector 0 means the
		 * write path never worked, a failure part way in means it ran out.
		 */
		con_puts("LOG WRITE E=");
		con_dec((uint64_t)e);
		con_puts(" SEC=");
		con_dec((uint64_t)bad);
		con_putc('\n');
		return;
	}
	int ok = !sdhc_read(cache_first, blk) &&
	    blk[0] == *(volatile uint32_t *)con_log_phys();
	con_puts(ok ? "LOG VERIFY OK\n" : "LOG VERIFY FAIL\n");
	if (!ok) {
		emmc_code = 9;
	}
}


/*
 * Read the first sector of "userdata" and say whether it holds an HFS+ volume
 * header.
 *
 * This answers the question the kernel cannot: XNU only reports an errno from
 * vfs_mountroot(), and the boot-loop scrolled it away every time. The shim can
 * read the same bytes the kernel will read, before the kernel exists, and say
 * plainly whether the image that was flashed is actually there.
 *
 * An HFS+ volume header lives at offset 1024 of the volume, so it is the
 * third 512-byte sector, and it starts with the signature 'H+' (0x482B) or,
 * for HFSX (case sensitive), 'HX' (0x4858). The iOS root built by mkiosroot.sh
 * is created with mkfs.hfsplus -s, i.e. HFSX, so 'HX' is the expected value.
 *
 * Reads only. Nothing here can write.
 */
void
ugg_emmc_check_userdata(void)
{
	if (userdata_first == 0 || userdata_sectors == 0) {
		con_puts("USERDATA MISSING\n");
		return;
	}
	con_puts("USERDATA F=");
	con_dec(userdata_first);
	con_puts(" N=");
	con_dec(userdata_sectors);
	con_putc('\n');

	/*
	 * Sector 0 first: it tells "blank" from "some other filesystem" from
	 * "the HFS+ header is here but at offset 0". Read it before anything
	 * else clobbers the shared block buffer.
	 */
	if (sdhc_read(userdata_first, blk)) {
		con_puts("USERDATA READ FAILED\n");
		return;
	}
	uint32_t s0 = blk[0];
	uint32_t s0_1 = blk[1];
	con_puts("USERDATA s0=");
	con_hex(s0, 8);
	con_puts(" ");
	con_hex(s0_1, 8);
	con_putc('\n');

	/*
	 * HFS+ puts its volume header at offset 1024 of the volume, i.e. the
	 * third 512-byte sector. Read it into its own buffer: the shared one is
	 * only one block wide and the comparisons below need both sectors.
	 *
	 * BYTE ORDER. The signature is the two bytes 'H' '+' (0x48 0x2B) read as
	 * a big-endian 16-bit value at the start of the header. blk[] is a
	 * little-endian uint32_t, so those two bytes appear as 0x2B48, NOT 0x482B
	 * -- and 'HX' (0x48 0x58) as 0x5848. The first version of this check got
	 * that wrong and reported "NOT HFS+" for a correct image.
	 */
	static uint32_t vh[128];
	uint32_t sig1024 = 0;
	if (sdhc_read(userdata_first + 2, vh) == 0) {
		sig1024 = vh[0];
	}

	con_puts("USERDATA sig@0=");
	con_hex(s0, 8);
	con_puts(" sig@1024=");
	con_hex(sig1024, 8);
	con_putc('\n');

	/*
	 * A sparse image that fastboot did NOT expand starts with the magic
	 * 0xED26FF3A, which is written little endian (bytes 3A FF 26 ED), so a
	 * little-endian uint32 read gives exactly 0xED26FF3A.
	 */
	if (s0 == 0xed26ff3au) {
		con_puts("USERDATA SPARSE IMAGE NOT EXPANDED -- fastboot wrote the .simg header\n");
		return;
	}

	if (sig1024 == 0x2b48u) {
		con_puts("USERDATA HFS+ at 1024 -- image present\n");
	} else if (sig1024 == 0x5848u) {
		con_puts("USERDATA HFSX at 1024 -- image present, case sensitive\n");
	} else if (s0 == 0x2b48u) {
		con_puts("USERDATA HFS+ at 0 -- image present but at the wrong offset\n");
	} else if (s0 == 0 && sig1024 == 0) {
		con_puts("USERDATA BLANK -- nothing was flashed here\n");
	} else {
		/*
		 * Neither signature matched. Dump enough of the 1024 sector to
		 * identify what is actually there (an ext4/f2fs superblock, a
		 * truncated write, ...) instead of only saying "no".
		 */
		con_puts("USERDATA NOT HFS+ -- vh words:");
		for (int i = 0; i < 8; i++) {
			con_putc(' ');
			con_hex(vh[i], 8);
		}
		con_putc('\n');
	}
}

void
ugg_emmc_probe(void)
{
	int r = sdhc_init();
	if (r) {
		emmc_code = -r;
		con_puts("EMMC INIT FAILED\n");
		return;
	}
	int e = sdhc_read(0, blk);
	con_puts("LBA0 E=");
	con_dec((uint64_t)(unsigned)e);
	con_puts(" SIG=");
	con_hex(blk[127] >> 16, 4);
	con_puts(blk[127] >> 16 == 0xaa55 ? " OK\n" : " BAD\n");
	if (e || blk[127] >> 16 != 0xaa55) {
		emmc_code = 3;
		return;
	}
	e = sdhc_read(1, blk);
	int gpt = !e && blk[0] == 0x20494645 && blk[1] == 0x54524150;    /* "EFI PART" */
	con_puts("LBA1 E=");
	con_dec((uint64_t)(unsigned)e);
	con_puts(gpt ? " GPT OK\n" : " NO GPT\n");
	if (!gpt) {
		emmc_code = 4;
		return;
	}
	gpt_walk();
	/*
	 * Prove what is actually on userdata before the kernel tries to mount it.
	 * A photograph of this decides whether the next step is "flash the image"
	 * or "the image is there and something else is wrong".
	 */
	ugg_emmc_check_userdata();
	ugg_emmc_flush_log();
}
