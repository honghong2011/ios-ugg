/*
 * Console compatibility layer for the drivers ported from the mido shim.
 *
 * The ugg console is a fixed 45x40 cell grid driven by con_str(); mido's is a
 * scrolling text console with con_puts()/con_putc(). Rather than rewriting the
 * ported drivers (which would make them diverge from the versions verified on
 * mido hardware), this file turns the mido calls into a running text line and
 * flushes that line through con_str() whenever a newline arrives.
 */
#include <stdint.h>
#include "console.h"
#include "mido_compat.h"

#define MIDO_LINE 44

static char line[MIDO_LINE + 1];
static int  len;
static unsigned long skip_rows;   /* con_skip() is not used by the ported code */

static void
flush_line(void)
{
	line[len] = 0;
	if (len) {
		con_str("", line);
	}
	len = 0;
}

void
mido_con_putc(char c)
{
	if (c == '\n') {
		flush_line();
		return;
	}
	if (c == '\r') {
		len = 0;
		return;
	}
	if (len >= MIDO_LINE) {
		flush_line();
	}
	line[len++] = c;
}

void
mido_con_puts(const char *s)
{
	while (*s) {
		mido_con_putc(*s++);
	}
}

void
mido_con_hex(uint64_t v, int digits)
{
	static const char hex[] = "0123456789abcdef";
	if (digits <= 0 || digits > 16) {
		digits = 16;
	}
	for (int i = digits - 1; i >= 0; i--) {
		mido_con_putc(hex[(v >> (4 * i)) & 0xf]);
	}
}

void
mido_con_dec(uint64_t v)
{
	char b[21];
	int n = 0;
	if (v == 0) {
		mido_con_putc('0');
		return;
	}
	while (v && n < 20) {
		b[n++] = '0' + (char)(v % 10);
		v /= 10;
	}
	while (n) {
		mido_con_putc(b[--n]);
	}
}

void
mido_con_kv(const char *k, uint64_t v)
{
	mido_con_puts(k);
	mido_con_puts("=");
	mido_con_hex(v, 16);
}
