#pragma once
#include <stdint.h>

/*
 * ugg shim eMMC probe: SDHCI-MSM read path, GPT parse, and a guarded write of
 * the console log into the "cache" partition. Prints every partition it finds.
 * Never writes outside a partition literally named "cache".
 */
void ugg_emmc_probe(void);
