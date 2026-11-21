#pragma once
#include <stdint.h>

/*
 * ugg shim eMMC probe: SDHCI-MSM read path, GPT parse, and a guarded write of
 * the console log into the "cache" partition. Prints every partition it finds.
 * Never writes outside a partition literally named "cache".
 */
void ugg_emmc_probe(void);

/*
 * Write the console log ring to the "cache" partition and verify it.
 *
 * The log has to be flushed more than once. The first flush happens at the end
 * of the eMMC probe, but by then the most valuable lines of the boot -- the
 * RGB0 pipe report, the loader's INITRD/PHYS/ENTRY and "XNU jumping" -- have
 * not been printed yet, so a single early flush persists a log that stops
 * exactly where the interesting part begins. Cheap enough to call again.
 *
 * No-op when there is no writable "cache" partition.
 */
void ugg_emmc_flush_log(void);

/*
 * Read the first sectors of the "userdata" partition and report whether they
 * hold an HFS+ / HFSX volume header. Read-only; it exists so a photograph can
 * prove the iOS root image is really on the partition, which the kernel's
 * vfs_mountroot errno never managed to show before the boot loop scrolled it
 * away.
 */
void ugg_emmc_check_userdata(void);
