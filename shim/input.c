/*
 * ugg input bring-up (shim only): touch power/clock/pinmux, then a short
 * poll of the Goodix GT9xx and the power / volume keys so the hardware can be
 * verified before XNU exists.
 *
 * Hardware from ugg's own device tree:
 *   goodix@5d on i2c@78b7000 (BLSP1 QUP3, qcom,i2c-msm-v2, 400 kHz)
 *       irq gpio 65, reset gpio 64, power_ldo gpio 47
 *       vdd_ana = RPM L10 2.85 V      (verified: mido's L10 vote works here too)
 *       vcc_i2c = RPM L6  1.8 V
 *   gpio_keys vol_up, PMI8937 PON KPDPWR / RESIN
 *
 * The power and pinmux sequence is the one the mido port verified on hardware;
 * only the touch register protocol differs (GT9xx uses 16-bit register
 * addresses, and its ID lives at 0x8140). input_setup() runs before every XNU
 * jump: the RPM vote and the pad state persist into the kernel.
 */
#include <stdint.h>
#include "console.h"
#include "mido_compat.h"
#include "spmi.h"
#include "rpm.h"
#include "input.h"

#define TLMM_CFG(n)  (TLMM_BASE + 0x1000u * (uint32_t)(n))
#define TLMM_IO(n)   (TLMM_BASE + 0x1000u * (uint32_t)(n) + 4u)
#define GCC_BLSP1_AHB_CBCR   0x01800008UL
#define GCC_QUP3_I2C_CBCR    0x01847024UL
#define GCC_APCS_CLK_VOTE    0x0180001cUL

#define QUP_PA        0x078b7000u
#define Q_CONFIG      0x000
#define Q_STATE       0x004
#define Q_IO_MODE     0x008
#define Q_SW_RESET    0x00c
#define Q_OPER        0x018
#define Q_MX_OUT_CNT  0x100
#define Q_OUT_FIFO    0x110
#define Q_MX_WR_CNT   0x150
#define Q_MX_IN_CNT   0x200
#define Q_MX_RD_CNT   0x208
#define Q_IN_FIFO     0x218
#define Q_I2C_CLK     0x400
#define Q_I2C_STATUS  0x404
#define ST_VALID      (1u << 2)
#define OP_OUT_NOT_EMPTY (1u << 4)
#define OP_IN_NOT_EMPTY  (1u << 5)
#define I2C_ERR_MASK  0x38000fcu
#define T_START       (1u << 8)
#define T_STOP        (3u << 8)
#define T_REC         (4u << 8)

#define GT_ADDR       0x5d
#define GT_REG_CONFIG 0x8047
#define GT_REG_PRODUCT 0x8140
#define GT_REG_STATUS 0x814e
#define GT_REG_POINT0 0x814f

static uint32_t last_status, last_oper;

static uint64_t now(void)
{
	uint64_t v;
	__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(v));
	return v;
}

static void delay_ms(unsigned ms)
{
	uint64_t end = now() + 19200ULL * ms;
	while (now() < end) {
		__asm__ volatile("yield");
	}
}

static inline uint32_t qrd(uintptr_t o) { return *(volatile uint32_t *)(QUP_PA + o); }
static inline void qwr(uintptr_t o, uint32_t v) { *(volatile uint32_t *)(QUP_PA + o) = v; }

static int qup_state(uint32_t s)
{
	uint64_t end = now() + 19200ULL * 10;
	while (now() < end) {
		uint32_t v = qrd(Q_STATE);
		if ((v & ST_VALID) && (v & 3) == s) {
			return 0;
		}
		if (v & ST_VALID) {
			qwr(Q_STATE, s);
		}
	}
	return -1;
}

static int qup_xfer(const uint16_t *tags, int ntags, uint8_t *in, int nread)
{
	qwr(Q_SW_RESET, 1);
	uint64_t end = now() + 19200ULL * 10;
	while (!(qrd(Q_STATE) & ST_VALID) && now() < end) {
	}
	if (qup_state(0)) {
		return -10;
	}
	qwr(Q_I2C_CLK, (3u << 8) | 21u);
	qwr(Q_MX_OUT_CNT, 0);
	qwr(Q_MX_WR_CNT, (uint32_t)ntags);
	qwr(Q_MX_IN_CNT, 0);
	qwr(Q_MX_RD_CNT, (uint32_t)nread);
	qwr(Q_CONFIG, (2u << 8) | 15u | (nread ? 0 : (1u << 7)));
	qwr(Q_IO_MODE, (1u << 14) | (1u << 15));
	qwr(Q_OPER, 0xff0);
	qwr(Q_I2C_STATUS, 0xfffffc);
	if (qup_state(1)) {
		return -11;
	}
	for (int i = 0; i < ntags; i += 2) {
		qwr(Q_OUT_FIFO, tags[i] | (i + 1 < ntags ? (uint32_t)tags[i + 1] << 16 : 0));
	}
	int got = 0;
	end = now() + 19200ULL * 20;
	while (now() < end) {
		last_status = qrd(Q_I2C_STATUS);
		last_oper = qrd(Q_OPER);
		if (last_status & I2C_ERR_MASK) {
			qup_state(0);
			return -3;
		}
		while (got < nread && (last_oper & OP_IN_NOT_EMPTY)) {
			uint32_t v = qrd(Q_IN_FIFO);
			in[got++] = (uint8_t)v;
			if (got < nread) {
				in[got++] = (uint8_t)(v >> 16);
			}
			last_oper = qrd(Q_OPER);
		}
		if (got >= nread && !(last_oper & OP_OUT_NOT_EMPTY) && !(last_status & (1u << 8))) {
			break;
		}
	}
	qup_state(0);
	return got < nread ? -4 : 0;
}

/* GT9xx: 16-bit big-endian register address, then read from the pointer. */
static int gt_read(uint16_t reg, uint8_t *buf, int n)
{
	uint16_t w[3] = {
		(uint16_t)(T_START | (GT_ADDR << 1)),
		(uint16_t)(reg >> 8),
		(uint16_t)(T_STOP | (reg & 0xff)),
	};
	int e = qup_xfer(w, 3, 0, 0);
	if (e) {
		return e;
	}
	uint16_t r[2] = { (uint16_t)(T_START | (GT_ADDR << 1) | 1), (uint16_t)(T_REC | (unsigned)n) };
	return qup_xfer(r, 2, buf, n);
}

/*
 * Prepare the touch rail, the I2C clocks and the pads. Called before every
 * XNU jump; returns 0 when the RPM accepted the L10 vote.
 */
int
input_setup(void)
{
	int e = rpm_ldo_enable(10, 2850000, 40);              /* touch vdd_ana (2.85 V) */
	/*
	 * vcc_i2c too. ugg's device tree gives goodix@5d vcc_i2c-supply =
	 * regulator-l6 (1.8 V), and without it the QUP3 pull-ups have no rail,
	 * so the bus reads 0xFF no matter what the protocol does.
	 * The return value is ignored: if the RPM refuses, the driver still
	 * reports the touch IC id and the failure is visible in the log.
	 */
	int e6 = rpm_ldo_enable(6, 1800000, 40);              /* vcc_i2c (1.8 V) */
	*(volatile uint32_t *)GCC_APCS_CLK_VOTE |= (1u << 10);
	*(volatile uint32_t *)GCC_QUP3_I2C_CBCR |= 1u;
	delay_ms(2);
	*(volatile uint32_t *)TLMM_CFG(10) = 2u << 2;         /* blsp_i2c3 = func 2 */
	*(volatile uint32_t *)TLMM_CFG(11) = 2u << 2;
	*(volatile uint32_t *)TLMM_CFG(65) = 3u;              /* touch irq: input, pull-up */
	*(volatile uint32_t *)TLMM_CFG(85) = 3u;              /* vol+: input, pull-up */
	*(volatile uint32_t *)TLMM_CFG(64) = (1u << 9) | (1u << 6);  /* touch reset: output */
	*(volatile uint32_t *)TLMM_IO(64) = 0;
	delay_ms(10);
	*(volatile uint32_t *)TLMM_IO(64) = 2;                /* release: fw boots ~200 ms */
	uint32_t ahb = *(volatile uint32_t *)GCC_BLSP1_AHB_CBCR;
	uint32_t core = *(volatile uint32_t *)GCC_QUP3_I2C_CBCR;
	con_puts("INPUT SETUP: RPM L10 E=");
	con_dec((uint64_t)(int64_t)e);
	con_puts(" L6 E=");
	con_dec((uint64_t)(int64_t)e6);
	con_puts(" CLK ");
	con_puts(((ahb | core) & (1u << 31)) ? "OFF" : "ON");
	con_putc('\n');
	return e;
}

void
input_test(unsigned seconds)
{
	con_puts("\nINPUT TEST (Goodix GT9xx)\n");
	{
		int ch = spmi_find_chan(0x149);
		uint8_t st = 0;
		for (int i = 0; i < 100 && ch >= 0; i++) {
			spmi_read(ch, 0x08, &st);
			if (st & 0x80) {
				break;
			}
			delay_ms(1);
		}
		con_puts(" L10 CH=");
		con_dec((uint64_t)(int64_t)ch);
		con_puts(" ST=");
		con_hex(st, 2);
		con_puts((st & 0x80) ? " VREG OK\n" : " NOT OK\n");
	}
	delay_ms(250);

	/* The DT node is goodix@5d on this bus; confirm by reading its product id. */
	uint8_t pid[4] = { 0, 0, 0, 0 };
	int e = gt_read(GT_REG_PRODUCT, pid, 4);
	con_puts(" GT9xx E=");
	con_dec((uint64_t)(int64_t)e);
	con_puts(" ID=");
	for (int i = 0; i < 4; i++) {
		con_putc(pid[i] >= 0x20 && pid[i] < 0x7f ? (char)pid[i] : '.');
	}
	con_puts(" ST=");
	con_hex(last_status, 8);
	con_putc('\n');

	uint8_t cfg[4] = { 0, 0, 0, 0 };
	if (gt_read(GT_REG_CONFIG + 1, cfg, 4) == 0) {
		unsigned mx = (unsigned)cfg[0] | ((unsigned)cfg[1] << 8);
		unsigned my = (unsigned)cfg[2] | ((unsigned)cfg[3] << 8);
		con_puts(" GT9xx RES ");
		con_dec(mx);
		con_putc('x');
		con_dec(my);
		con_putc('\n');
	}

	int pon = spmi_find_chan(0x008);
	con_puts(" PON CH=");
	con_dec((uint64_t)(int64_t)pon);
	con_puts("\n TOUCH THE SCREEN AND PRESS POWER / VOL+\n");

	uint64_t end = now() + 19200000ULL * seconds;
	unsigned lines = 0, points = 0;
	while (now() < end && lines < 30) {
		uint8_t rt = 0;
		if (pon >= 0) {
			spmi_read(pon, 0x10, &rt);
		}
		unsigned keys = (rt & 1) | ((rt & 2) ? 4 : 0) |
		    ((*(volatile uint32_t *)TLMM_IO(85) & 1u) ? 0 : 2);
		static unsigned last_keys = 0xff;
		if (keys != last_keys) {
			con_puts(" KEYS: PWR=");
			con_dec(keys & 1);
			con_puts(" VOL+=");
			con_dec((keys >> 1) & 1);
			con_puts(" VOL-=");
			con_dec((keys >> 2) & 1);
			con_putc('\n');
			last_keys = keys;
			lines++;
		}
		if (e == 0) {
			uint8_t st = 0;
			if (gt_read(GT_REG_STATUS, &st, 1) == 0 && (st & 0x80)) {
				unsigned n = st & 0x0f;
				uint8_t b[8 * 5];
				if (n > 5) {
					n = 5;
				}
				if (n && gt_read(GT_REG_POINT0, b, (int)(8 * n)) == 0) {
					con_puts(" TOUCH N=");
					con_dec(n);
					for (unsigned t = 0; t < n; t++) {
						const uint8_t *p = b + 8 * t;
						unsigned id = p[0] & 0x0f;
						int x = (int)((unsigned)p[1] | ((unsigned)p[2] << 8));
						int y = (int)((unsigned)p[3] | ((unsigned)p[4] << 8));
						con_puts(" [");
						con_dec(id);
						con_putc(' ');
						con_dec((uint64_t)(int64_t)x);
						con_putc(',');
						con_dec((uint64_t)(int64_t)y);
						con_puts("]");
					}
					con_putc('\n');
					points++;
					lines++;
				}
				/* acknowledge the latch */
				uint16_t w[3] = {
					(uint16_t)(T_START | (GT_ADDR << 1)),
					(uint16_t)(GT_REG_STATUS >> 8),
					(uint16_t)(T_STOP | (GT_REG_STATUS & 0xff)),
				};
				qup_xfer(w, 3, 0, 0);
			}
		}
		delay_ms(100);
	}
	con_puts("INPUT TEST DONE (points=");
	con_dec(points);
	con_puts(")\n");
}
