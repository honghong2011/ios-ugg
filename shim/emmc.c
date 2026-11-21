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
	 * Trimmed signature match.
	 *
	 * The HFS+ volume header begins with a 16-bit signature: 'H' '+' = 0x482B
	 * (HFS+) or 'H' 'X' = 0x4858 (HFSX, what mkfs.hfsplus -s makes), followed
	 * by a 16-bit version (4 or 5). Read little endian as a uint32_t that is
	 * 0x00042B48 / 0x00052B48 / 0x00054858, so the signature is the LOW half
	 * and the version the HIGH half.
	 *
	 * Two earlier versions of this function got this wrong: first comparing
	 * against 0x482B (never matches little endian), then comparing the whole
	 * word against 0x2B48 (fails whenever the version half is non-zero). Both
	 * produced a false "NOT HFS+". Mask the low 16 bits and be done with it.
	 */
#define HFS_SIG(word)   ((uint32_t)(word) & 0xffffu)
#define HFS_VER(word)   ((uint32_t)(word) >> 16)
#define HFS_MAGIC_PLUS  0x2b48u         /* 'H' '+' little endian */
#define HFS_MAGIC_X     0x5848u         /* 'H' 'X' little endian */

	static uint32_t vh[128];
	uint32_t sig1024 = 0;

	/*
	 * A sparse image that fastboot did NOT expand starts with the magic
	 * 0xED26FF3A, written little endian, so a little-endian uint32 read gives
	 * exactly that value.
	 */
	if (s0 == 0xed26ff3au) {
		con_puts("USERDATA SPARSE IMAGE NOT EXPANDED -- fastboot wrote the .simg header\n");
		return;
	}

	if (sdhc_read(userdata_first + 2, vh) == 0) {
		sig1024 = vh[0];
	}

	con_puts("USERDATA sig@0=");
	con_hex(s0, 8);
	con_puts(" sig@1024=");
	con_hex(sig1024, 8);
	con_putc('\n');

	if (HFS_SIG(sig1024) == HFS_MAGIC_PLUS) {
		con_puts("USERDATA HFS+ at 1024 ver=");
		con_dec(HFS_VER(sig1024));
		con_puts(" -- image present\n");
		return;
	}
	if (HFS_SIG(sig1024) == HFS_MAGIC_X) {
		con_puts("USERDATA HFSX at 1024 ver=");
		con_dec(HFS_VER(sig1024));
		con_puts(" -- image present\n");
		return;
	}
	if (HFS_SIG(s0) == HFS_MAGIC_PLUS || HFS_SIG(s0) == HFS_MAGIC_X) {
		con_puts("USERDATA signature at 0 -- image present but at the wrong offset\n");
		return;
	}
	if (s0 == 0 && sig1024 == 0) {
		con_puts("USERDATA BLANK -- nothing was flashed here\n");
		return;
	}

	/*
	 * Nothing valid where the header belongs. Identify what IS there.
	 *
	 * A bare signature is not enough to call it a volume header: the 16-bit
	 * version that follows must be 4 (HFS+) or 5 (HFSX). The 0087 run showed
	 * bytes 48 2B at +1028 with version 0x4C78, i.e. the signature alone would
	 * have matched while the header cannot possibly be valid -- a coincidence,
	 * not a filesystem. So every candidate is checked for a sane version.
	 */
	int found = 0;
	for (uint32_t sec = 0; sec < 64 && !found; sec++) {
		if (sdhc_read(userdata_first + sec, vh)) {
			break;
		}
		for (int w = 0; w < 127; w++) {
			uint32_t sig = HFS_SIG(vh[w]);
			uint32_t ver = HFS_VER(vh[w]);
			if ((sig == HFS_MAGIC_PLUS && ver == 4) ||
			    (sig == HFS_MAGIC_X && ver == 5)) {
				con_puts("USERDATA VALID ");
				con_puts(sig == HFS_MAGIC_X ? "HFSX" : "HFS+");
				con_puts(" at byte ");
				con_dec((uint64_t)sec * 512u + (uint64_t)w * 4u);
				con_putc('\n');
				found = 1;
				break;
			}
		}
	}
	if (found) {
		return;
	}

	/*
	 * Still nothing. Say what the two decisive places actually contain, and
	 * check the three filesystems that could plausibly be sitting here
	 * instead: ext4/f2fs (Android leftovers) and an unexpanded sparse image.
	 *
	 * The byte dump is printed as four 32-bit words, so a reader can decode
	 * any of them by hand without another round trip.
	 */
	if (sdhc_read(userdata_first, vh) == 0) {
		con_puts("USERDATA b0:");
		for (int i = 0; i < 4; i++) {
			con_putc(' ');
			con_hex(vh[i], 8);
		}
		con_putc('\n');
	}
	if (sdhc_read(userdata_first + 2, vh) == 0) {
		con_puts("USERDATA b1024:");
		for (int i = 0; i < 4; i++) {
			con_putc(' ');
			con_hex(vh[i], 8);
		}
		con_putc('\n');

		/* ext4 magic 0xEF53 lives at offset 1024 + 56; f2fs magic right at 1024. */
		if (vh[0] == 0x1020f5f2u) {              /* f2fs superblock, magic 0xF2F52010 LE */
			con_puts("USERDATA f2fs -- Android userdata still here\n");
			return;
		}
		if ((vh[14] & 0xffffu) == 0xef53u) {     /* ext4 s_magic at +56 */
			con_puts("USERDATA ext4 -- Android userdata still here\n");
			return;
		}
	}
	con_puts("USERDATA NO FILESYSTEM -- the image is not on this partition\n");
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
