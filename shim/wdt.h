#pragma once
#include <stdint.h>

/*
 * Qualcomm APSS watchdog (qcom,wdt@b017000, "qcom,msm-watchdog") and the
 * IMEM restart reason word.
 *
 * Reading the registers is always safe. shim_wdt_disable() writes only when
 * CTRL says the watchdog is actually armed, and then only the registers
 * Linux's qcom-wdt.c stop path touches (RESET at 0x14 is never written).
 */
void shim_wdt_report(const char *tag);

/* Stops the watchdog if it is armed; returns the CTRL value seen before. */
uint32_t shim_wdt_disable(void);

/* The reason word ABL/LK left in IMEM for why the previous boot ended. */
uint64_t shim_reset_reason(void);
