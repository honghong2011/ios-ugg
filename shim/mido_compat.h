#pragma once
/*
 * Compatibility shim: the eMMC / RPM / input / perf sources below were taken
 * from the mido port, which has its own console API (con_puts/con_dec/
 * con_putc/con_hex(value,digits)/con_kv). The ugg shim console is cell based
 * (con_str/con_hex(label,value)). This header maps the former onto the
 * latter so the ported drivers stay byte-identical to the versions that were
 * verified on mido's hardware.
 */
#include <stdint.h>
#include "console.h"

void mido_con_puts(const char *s);
void mido_con_putc(char c);
void mido_con_hex(uint64_t v, int digits);
void mido_con_dec(uint64_t v);
void mido_con_kv(const char *k, uint64_t v);

#define con_puts   mido_con_puts
#define con_putc   mido_con_putc
#define con_dec    mido_con_dec
#define con_kv     mido_con_kv
/* con_hex has a different signature, so it cannot be a macro: the ported
 * sources call it as con_hex(value, digits). */
#define con_hex(v, digits) mido_con_hex((v), (digits))

/* mido colours, used by the ported console output only */
#ifndef C_NAVY
#define C_NAVY   0x002050
#endif
#ifndef C_RED
#define C_RED    0x800000
#endif
#ifndef C_GREEN
#define C_GREEN  0x005000
#endif
