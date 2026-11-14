# iOS 16 on ugg (Redmi Note 5A, MSM8937) — working notes

## ★★★★★ 最新（2026-11-15 06:10，第 17 轮）-- /product 已打通；文件已修复

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1653 行，权威且无损）。

### 先说我修坏的东西（已恢复）

上一轮末尾本机 **Windows 虚拟内存耗尽**（`os error 1455`），我用有读取上限的工具做
整文件重写，把本文件从 **1956 行截断到 1430 行**。

**已从 git 对象库完整恢复**（blob `99d49f9d`，64,168 字节，1956 行），并核对了首尾。

### 本轮实质进展：`/product` 节点已打通

mido 的日志说 `/product` 只对 userland 必需，缺了它的后果是 backboardd 崩溃循环
（`attachImage: surface b3a8 ... format failed`）。我的 ADT 一直没有这个节点。

| 环节 | 状态 |
|---|---|
| 从 IPSW 抽 `DeviceTree.d20ap.im4p` | ✅ `tools/ipsw_adt.py` |
| 解 DER/IM4P + **LZFSE**（三级回退） | ✅ |
| CI 实跑（run 43644714094） | ✅ **全部 15 步 success** |
| ADT 自动带 `/product` | ✅ 9896 → 10124 字节，22 节点 |
| Apple 固件不入库 | ✅ `.gitignore` 加 `*.im4p` / `*d20ap.adt` |

该 run 的完整步骤链：

`
Free up runner disk → Install toolchain → Build apfs-fuse → Fetch the IPSW
→ Extract the three system images → Extract the device tree for /product ✅
→ Build the HFS+ root ✅ → Apply the bring-up tweaks → Convert to sparse and split
`

**注意**：设备树步骤现在是 `continue-on-error`，它失败也不会再阻断根卷构建
（上一轮它曾把 20 分钟的根卷产物整个 skip 掉）。

### 我修掉的三个自己的错误

1. 误以为 ADT 是 FDT（检查 `d00dfeed` 魔数）—— **ADT 没有魔数**，改用 `adt.parse()` 验证
2. 自动发现路径从 `ugg/tools` 往上找了三级（应为两级）
3. 可选步骤失败阻断主流程（已改 `continue-on-error` + 内部软失败）

### 镜像（不变）

`
shim-boot-0082-mido.img  8,169,472 B
sha256 3fa935772411dadfdda6d14ac1fbcd0126fa6e252bcb9be1b5550ee119f453a4
`

`
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
`

### 根卷（两个成功的 artifact）

| run | 大小 | 分片 |
|---|---|---|
| 43634756880 | 11,970,598,900 B | 7 片 |
| 43644714094 | 同上规格（本轮含 device tree） | 7 片 |

**有效期到 11/19**。需 20 GB 空闲盘：`./ugg/flash-root.sh /path/with/20GB`

---


## ★★★★★ 最新（2026-11-15 05:40，第 15 轮）-- 关键结论：QEMU 到 M2，eMMC 必须真机验

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1582 行）。

### QEMU 已经跑通到 M2（上一轮），这轮搞清了它证明了什么

**已证明**（38 行屏幕完整解码）：

```
bsd_init: calling loopattach → ether_family_init → net_init_run
        → inittodr → setconf
Waiting on <dict ... IOMedia ... Apple_HFS>
```

| 已证明 |
|---|
| start.s → MMU → pmap → VM bootstrap 全通 |
| IOKit / platform expert |
| `bsd_init` 全部子系统（kauth/MAC/buffer/socket/domain/skywalk/net） |
| **旧路线卡死点 A1 不存在了** —— 16K VM over 4K granule 有效 |

**没证明**（必须真机）：

| 项 | 为什么 |
|---|---|
| eMMC 驱动 | QEMU 没有 eMMC 硬件，`SWEET UFS` 行根本不出现 |
| GT9xx 触摸 | 同上 |
| RPM 电源 | 同上 |

### 一个修正了的判读预期（重要）

`iokit/bsddev/IOKitBSDInit.cpp:778`：

```c
int ufs_error = sweet_ufs_rootdev(root);
if (ufs_error) {
    panic("IOFindBSDRoot: SWEET UFS root %s unavailable: %d", rdBootVar, ufs_error);
}
```

**eMMC 驱动失败 = 直接 panic，不是「等待根设备」。**

| 真机现象 | 含义 | 下一步 |
|---|---|---|
| `panic: IOFindBSDRoot: SWEET UFS root ufsroot0 unavailable: N` | eMMC 驱动失败（N=errno） | 把 N 告诉我 |
| `Still waiting for root device` | eMMC OK 但**没刷根卷** | 去刷根卷 |
| 苹果 logo → 锁屏 | 成功 | 恭喜 |

**好消息**：`serial_console.c:286` 的 `if (sweet_console_muted && !panic_active())` 意味着
**panic 时一定会重新绘制到屏幕**，即使 `sweetfb_noconsole=1`。两种结局都能看到。

### CI 门禁升级

QEMU 检查从「能画字就算过」升级为：

- 统计 6 个 `bsd_init` 阶段
- 识别 QEMU 特有的是 `Waiting on ... IOMedia ... Apple_HFS`（这是它在这块板上的最好结果）
- 明确输出 `PASS: bsd_init complete ... (M2)` 或 `FAIL: kernel panicked`

已用真实屏幕文本回放验证：`of 6 stages: 4 reached` + `PASS ... (M2)`。
以后任何改动让 pmap/IOKit/bsd_init 退化，都会立刻可见。

### 镜像（不变）

```
shim-boot-0082-mido.img  8,169,472 B
sha256 3fa935772411dadfdda6d14ac1fbcd0126fa6e252bcb9be1b5550ee119f453a4
```

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

### 根卷（不变，已就绪）

artifact `ios16-root-parts`（run 43634756880），11,970,598,900 B，7 片，**有效期到 11/19**。
需 20 GB 空闲盘：`./ugg/flash-root.sh /path/with/20GB`

---


## ★★★★★ 最新（2026-11-15 05:30，第 14 轮）-- QEMU 跑通到 M2，真机应同样

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1505 行）。

### 重大进展：内核在 QEMU 里跑到了「等待根设备」

```
qemu-verdict  kernel is drawing text on the early console
qemu-text     38 行非空，38 行含字母数字
```

屏幕解码出的末尾（内核实际顺序）：

```
bsd_init: calling inittodr
bsd_init: calling setconf
Waiting on <dict ID="0"><key>IOProviderClass</key><string ID="1">IOMedia</string>
             <key>Content</key><string ID="2">Apple_HFS</string></dict>
```

**这就是 M2。** pmap、VM bootstrap、IOKit、`bsd_init` 全部跑完，停在找 HFS 分区。

### 根因：`phys_base` 落在不同的 1 GiB L1 区（不是内核 bug）

`start.s` 把 framebuffer 的 4 个 L2 block 写进「第一个 L2 页」，
**假设 RAM 和 fb 共享同一个 L1 条目**。

| 环境 | phys_base | RAM 的 L1 索引 | fb 的 L1 索引 | |
|---|---|---|---|---|
| 真机 | `0xA0000000` | 2 | 2 | ✅ 相同 |
| QEMU（之前） | `0x50000000` | **1** | **2** | ❌ 不同 |

不同索引 ⇒ 那 4 个 block 写进了 RAM 的 L2 表里 fb 的槽位 —— 表错了，fb 没映射，
内核一开 MMU 就取指失败。与日志完全吻合（FAR 是物理地址、该处是 `isb`、前面是 `msr SCTLR_EL1`）。

**修复**：`QEMU_PHYS_BASE` 改为 `0xA0000000`（真机的值）。

### 为什么这个结果对真机有参考价值（已实测确认）

| 项 | 真机 payload | QEMU payload |
|---|---|---|
| phys_base | `0xa0000000` | `0xa0000000` |
| mem_size | `0x5ff00000` | `0x5ff00000` |
| entry | `0xfffffff00742a488` | 同 |
| kernel_end | `0xfffffff0084b4000` | 同 |
| **段表** | 10 段 | **完全相同** |

两者**只差 ADT 里的 GIC 地址（0x0b000000 vs 0x08000000）和时基（19.2 vs 62.5 MHz）**，
那是硬件差异，不影响内核被加载到哪里。

**⇒ QEMU 能跑到 M2，真机没有理由跑不到。**

### 这也说明前几轮修的 bug 是对的

前几轮修的 framebuffer 地址、mark 越界、MDP 32bpp、eMMC 初始化、L6 电源，
**都不是 QEMU 黑屏的原因**，但它们都是真 bug —— 现在内核能在正确的地址布局下
跑完全程，说明这些修复没有引入回归。

### 镜像（不变，仍然是这个）

```
shim-boot-0082-mido.img  8,169,472 B
sha256 3fa935772411dadfdda6d14ac1fbcd0126fa6e252bcb9be1b5550ee119f453a4
```

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

预期：**停在 `Still waiting for root device`（M2）** —— 因为还没刷根卷。

### 根卷（不变，已就绪）

artifact `ios16-root-parts`（run 43634756880），11,970,598,900 B，7 片，**有效期到 11/19**。
需 20 GB 空闲盘：`./ugg/flash-root.sh /path/with/20GB`

---


## ★★★★★ 最新（2026-11-15 05:20，第 13 轮完）-- 刷这个镜像

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1432 行）。

### 镜像

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

```
8,169,472 B
sha256 3fa935772411dadfdda6d14ac1fbcd0126fa6e252bcb9be1b5550ee119f453a4
```

### 这版改了什么

**去掉 `-enable_kprintf_spam`。** mido 的日志（PORTING_LOG 574-576）明确写：

> 「`-enable_kprintf_spam` 的行在 mute 之后仍然绘制，所以去掉这个启动参数」

去掉之后它才进了苹果 logo 和锁屏。我的 cmdline 一直带着这个参数。

### 启动参数现在与 mido 对齐

| 参数 | mido | ugg |
|---|---|---|
| `sweetfb_hz` | 30 | **30** ✓ |
| `-enable_kprintf_spam` | 无 | **无** ✓ |
| 其余 13 项 | — | 全部一致 ✓ |
| `-v` | 无 | **有**（有意：现在需要看打印） |
| `cpus` | 6 | **1**（有意：LSE 模拟器非多核原子） |

### 内核门禁复核通过（实测）

对内核二进制逐项检查：

| 检查 | 结果 |
|---|---|
| `UGG LSE` / `emulating` / `LDADD` 字符串 | 全部 FOUND |
| `handle_uncategorized` / `sleh_synchronous` / `arm_fast_fault` | 全部 FOUND |
| `__TEXT_EXEC` 里的真 LSE 指令 | **0 条** |

唯一被扫出的一条在 `K256 + 0xe4`（`0x78a5636f`）—— 那是 **SHA-256 常量表**，
数据里的字面量恰好命中 LSE 掩码，与 mido 的 `kscan.py` 记录同一个假阳性。

**⇒ EL0 LSE 模拟器完整可用，内核代码无真 LSE。**

### 屏显预期

```
SHIM    ugg loader + board probe
MDP RGB0: ADDR=90000000 FMT=0002243f STRIDE=00000870
MDP RGB0 -> FMT=000236ff STRIDE=00000b40 (32 bpp)
EMMC HC_MODE=00000001
 BUS POWER ON: PWRREQ=..
LBA0 E=0 SIG=AA55 OK
LBA1 E=0 GPT OK
#25 F=... N=... cache          <- 你的真实分区表
LOG TO CACHE ENABLED / LOG VERIFY OK
INPUT SETUP: RPM L10 E=0 L6 E=0 CLK ON
LOADER  <原因>
```

| 看到 | 含义 |
|---|---|
| `FB32 FAILED: not booting XNU` | 管道状态异常，已拒绝启动 → **拍照** |
| `EMMC INIT FAILED` / `BUS POWER STILL OFF` | eMMC 没起来 → **拍照** |
| `LBA1 ... GPT OK` + 分区列表 | **eMMC 通了** ✅ |
| `Still waiting for root device` | 没根卷（预期，M2） |
| `panic:` / 苹果 logo / 锁屏 | 拍照 / 等 / **目标达成** |

### 根卷（不变）

artifact `ios16-root-parts`（run 43634756880），11,970,598,900 B，7 片，**有效期到 11/19**。
需 20 GB 空闲盘：`./ugg/flash-root.sh /path/with/20GB`

---


## ★★★★★ 最新（2026-11-15 05:10，第 12 轮完）-- 刷这个镜像

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1373 行）。

### 镜像

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

```
8,169,472 B
sha256 9149b117ffaae6d19e44e792c046e807f59dec1485bd36de7207b14fd29359fa
```

### 这版新增：启动门禁（照抄 mido）

mido 不是无条件跳 XNU，而是：

```c
if (fb == 0) {   /* XNU needs the 32 bpp framebuffer; never boot it on LK's 24 bpp */
    loader_boot(dtb);
}
```

我的 shim 之前是无条件跳。这很危险：**如果 MDP 切换失败，XNU 会在 24bpp 面板上
按 32bpp 渲染，屏幕不可读 —— 那就无法区分「显示故障」和「内核故障」**，
而刷小镜像的唯一目的就是读屏。

现在 `fb32 != 0` 时：

```
FB32    FAILED: not booting XNU (see MDP line above)
HOLD    POWER to reboot
```

屏上留下的是 shim 自己可读的输出。

### 累计已修的 5 个「shim 欠 XNU 的步骤」

| XNU 侧 | 依赖 shim | 轮次 |
|---|---|---|
| `sweet_ufs.c` | eMMC 初始化到 transfer state | 10 ✅ |
| `ugg_input.c` | L10 + L6 电源 | 10 ✅ |
| `ugg_input.c` | QUP3 时钟、gpio10/11/64/65 | 原有 ✅ |
| `SWEET.h` | MDP RGB0 → 32bpp | 11 ✅ |
| mido `shim_main` | **32bpp 失败则不跳 XNU** | **12 ✅** |

### 屏显预期（从上到下）

```
SHIM    ugg loader + board probe
MDP RGB0: ADDR=90000000 FMT=0002243f STRIDE=00000870
MDP RGB0 -> FMT=000236ff STRIDE=00000b40 (32 bpp)
EMMC HC_MODE=00000001
 PRES=... HCTL=... CLK=... HCTL2=...
 BUS POWER ON: PWRREQ=..
LBA0 E=0 SIG=AA55 OK
LBA1 E=0 GPT OK
#25 F=... N=... cache        <- 你的真实分区表
CACHE F=... N=...
LOG TO CACHE ENABLED
LOG VERIFY OK
INPUT SETUP: RPM L10 E=0 L6 E=0 CLK ON
LOADER  <原因>
```

| 看到 | 含义 | 动作 |
|---|---|---|
| `MDP: unexpected FMT` + `FB32 FAILED: not booting XNU` | 管道状态异常，已拒绝启动 | **拍照**（屏或许还能看清） |
| `EMMC INIT FAILED` / `BUS POWER STILL OFF` | eMMC 没起来 | **拍照** |
| `LBA1 ... GPT OK` + 分区列表 | **eMMC 通了** ✅ | 继续 |
| `Still waiting for root device` | 没根卷（预期，M2） | 刷根卷 |
| `panic:` | — | **拍照** |
| 苹果 logo | 根卷挂载成功 | 等锁屏 |

### 根卷（不变）

artifact `ios16-root-parts`（run 43634756880），11,970,598,900 B，7 片，**有效期到 11/19**。
本机 C: 只剩 7.3 GB，需在 20 GB 空闲的机器上：`./ugg/flash-root.sh /path/with/20GB`

---


## ★★★★★ 最新（2026-11-15 05:05，第 11 轮完）-- 刷这个镜像

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1322 行）。

### 镜像

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

```
8,169,472 B
sha256 f65d72194abf50588c467d3b7f14f200207cf91cae3e9fdbbb981c2a7eded03d
```

### 这版比上一版多了 MDP 32bpp 切换

`SWEET.h` 里写着「the shim switches MDP RGB0 to 32 bpp」，但 ugg 的 shim
**完全没有 MDP 代码**。RGB0 还是 LK 的 24bpp（stride 2160），而 shim 控制台和
XNU 都按 32bpp 写（stride 2880）⇒ **每行错位，屏幕会是斜条纹**。

新增 `shim/fb32.c`：验证 LK 状态 → 切 `SRC_FORMAT=0x000236ff` /
`UNPACK=0x03020001` / `stride=2880` → flush RGB0。`FB_BPP` 3→4。

### 「shim 欠 XNU 的步骤」清单（4 条，全部已补）

| XNU 侧 | 依赖 shim | 轮次 |
|---|---|---|
| `sweet_ufs.c` | eMMC 初始化到 transfer state | 第 10 轮 ✅ |
| `ugg_input.c` | L10 + L6 电源 | 第 10 轮 ✅ |
| `ugg_input.c` | QUP3 时钟、gpio10/11/64/65 | 原有 ✅ |
| `SWEET.h` | MDP RGB0 → 32bpp | **第 11 轮 ✅** |

### 屏显判读（更新）

```
MDP RGB0: ADDR=90000000 FMT=0002243f STRIDE=00000870
MDP RGB0 -> FMT=000236ff STRIDE=00000b40 (32 bpp)     <-- 成功
EMMC HC_MODE=00000001
 BUS POWER ON: PWRREQ=..
LBA0 E=0 SIG=AA55 OK
LBA1 E=0 GPT OK
#25 F=... N=... cache
LOG VERIFY OK
INPUT SETUP: RPM L10 E=0 L6 E=0 CLK ON
```

| 看到 | 含义 | 动作 |
|---|---|---|
| `MDP: unexpected FMT ... screen may be unreadable` | 管道状态不是预期的 | **拍照**（屏可能看不清，尽量拍） |
| `MDP RGB0 -> FMT=000236ff` | 32bpp 切换成功 | 继续 |
| `EMMC INIT FAILED` / `BUS POWER STILL OFF` | eMMC 没起来 | **拍照** |
| `LBA1 ... GPT OK` + 分区列表 | **eMMC 通了** ✅ | 继续 |
| `Still waiting for root device` | 没根卷（预期，M2） | 刷根卷 |
| `panic:` | — | **拍照** |

### 根卷（不变）

artifact `ios16-root-parts`（run 43634756880），11,970,598,900 B，7 片，**有效期到 11/19**。
下载需 20 GB 空闲盘：`./ugg/flash-root.sh /path/with/20GB`

---


## ★★★★★ 最新（2026-11-15 04:55，第 10 轮完）-- 刷这个镜像

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1258 行）。

### 镜像

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

```
8,169,472 B
sha256 2b435f5b189849d28f809162c6e00e18faa51523f21d048ce9ec9c2608b93edc
```

### 这版修了什么（比之前所有版本都关键）

**1. shim 现在会初始化 eMMC（之前完全没做）**

`shim_main()` 原本把 `loader_boot()` 放第一条语句，eMMC 初始化只在「无 payload」
分支里跑。所以手机带 payload 启动时**卡从未被初始化**。

XNU 自己的代码就是证据（`bsd/dev/sweet_ufs.c`）：

```c
printf("UGG EMMC: card not in transfer state after the shim (%d)\n", e);
```

**「after the shim」** —— 它假设 shim 已经把卡初始化好，自己只调超时计数器。

| 不修会怎样 |
|---|
| `Still waiting for root device` 永远不出来 |
| **即使刷了 16 GB 根卷也读不到 GPT** |
| 会被误判成根卷问题 |

**2. 补上 L6 电源（vcc_i2c 1.8 V）**

`ugg_input.c` 注释说 shim 会准备 L10 + **L6** 两路，实际只投了 L10。
UGG 的 DTB：`goodix@5d` 的 `vcc_i2c-supply` = `regulator-l6`（1.8 V）。
没这路电，I2C 上拉无源，总线恒读 0xFF。

### 屏上现在会多出这些行（判读用）

```
EMMC HC_MODE=00000001
 PRES=... HCTL=... CLK=... HCTL2=...
 BUS POWER ON: PWRREQ=..
LBA0 E=0 SIG=AA55 OK
LBA1 E=0 GPT OK
#25 F=... N=... cache
CACHE F=... N=...
LOG TO CACHE ENABLED
LOG VERIFY OK
INPUT SETUP: RPM L10 E=0 L6 E=0 CLK ON
```

**关键判读**：

| 看到 | 含义 | 动作 |
|---|---|---|
| `EMMC INIT FAILED` | shim 阶段 eMMC 就没起来 | **拍照给我** |
| `BUS POWER STILL OFF - ABORT` | 电源握手失败 | **拍照给我** |
| `LBA0 ... BAD` / `NO GPT` | 读到了但内容不对 | **拍照给我** |
| `LBA1 ... GPT OK` + 分区列表 | **eMMC 通了** ✅ | 继续看后面 |
| `Still waiting for root device` | eMMC OK 但没根卷（预期） | 去刷根卷 |
| `panic:` | **拍照给我** | |

这次屏上会直接列出**你的真实分区表**（`#25 F=... N=... cache` 这样的行），
那本身就是 eMMC 驱动工作的证明。

### 根卷（不变）

| 项 | 值 |
|---|---|
| artifact | `ios16-root-parts`，run 43634756880 |
| 大小 | 11,970,598,900 B，7 片 |
| 有效期 | **到 2026-11-19** |

下载：`./ugg/flash-root.sh /path/with/20GB`（本机 C: 只有 7.3 GB，需换盘）

---


## ★★★★★ 最新（2026-11-15 04:45，第 10 轮）-- 找到一个会让根卷白刷的 bug

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1258 行）。

### 这轮找到的根因（比之前所有 bug 都关键）

**`shim_main()` 把 `loader_boot(dtb)` 放在第一条语句**，而 eMMC 初始化只在
「没有 payload」的分支里跑。所以**手机带 payload 启动时 eMMC 从未被初始化**。

证据是 XNU 自己的代码注释（`bsd/dev/sweet_ufs.c` 的 `ugg_take_over()`）：

```c
int e = ugg_card_ready(500);
if (e) {
    printf("UGG EMMC: card not in transfer state after the shim (%d)\n", e);
    return ENXIO;
}
```

**「after the shim」** —— XNU 假设 shim 已经把卡初始化到 transfer state，
它自己只调超时计数器，不跑 CMD0/1/2/3/7、不开 bus power、不配 SDCC1 RCG。

| 后果 | 说明 |
|---|---|
| `Still waiting for root device` 永远不出来 | 卡没进 transfer state，所有读盘失败 |
| **即使刷了 16 GB 根卷也一样** | 读不到 GPT，找不到 `userdata` |
| 会误判成根卷问题 | 实际是 shim 少一步 |

已修：bring-up 移到跳转前无条件执行。

### 第二个同类问题

`ugg_input.c` 注释说 shim 会准备 **L10 + L6 两路电源**，但 shim 只投了 L10。
UGG 的 DTB 明确 `goodix@5d` 的 `vcc_i2c-supply` = `regulator-l6`（1.8 V）。
没有这路电，I2C 上拉无源，总线恒读 0xFF。已补。

### 一条值得记住的排查方法

**在 XNU 驱动里搜 `after the shim` / `the shim left` / `the shim` 这类注释**，
每一条都对应 shim 里必须有的一步。已知三条，全部已满足：

| XNU 侧 | 依赖 shim 做的 | 状态 |
|---|---|---|
| `sweet_ufs.c` | eMMC 初始化到 transfer state | ✅ 本轮修 |
| `ugg_input.c` | L10 + L6 电源 | ✅ 本轮修 |
| `ugg_input.c` | QUP3 时钟、gpio10/11/64/65 | ✅ 原有 |

### 当前镜像状态

⚠️ **工作区里的 `shim-boot-0082-mido.img` 还是上一版（sha256 `4b787b…`），不含本次修复。**
等 shim CI 出新的 `Image` 后我会重建并给你新的 sha256。**先别刷那个旧的。**

### 根卷（不变，已就绪）

| 项 | 值 |
|---|---|
| artifact | `ios16-root-parts`，run 43634756880 |
| 大小 | 11,970,598,900 B，7 片 |
| 有效期 | 到 2026-11-19 |
| 校验 | 每片 sha256，`sha256sum -c` 全过 |

下载：`./ugg/flash-root.sh /path/with/20GB`（需要 20 GB 空闲，本机 C: 只有 7.3 GB）

---


## ★★★★★ 最新（2026-11-15 04:30，第 9 轮）-- 新镜像 + 根卷已验证内容

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1175 行）。

### 请刷这个新镜像

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

```
8,169,472 B
sha256 4b787b060111b7ddec43532158616079c6598386ae51c1d375bbc4665605ab2b
```

**与上一版的唯一区别：`sweetfb_hz` 从 15 改成 30。**

依据是 mido 的实测 A/B（PORTING_LOG 第 981-982 行）：

| 设置 | mido 观察 |
|---|---|
| `sweetfb_hz=60` | App 启动了（exec Preferences、MobileSMS，无崩溃无磁盘错误）但**不显示** |
| `sweetfb_hz=30` | **App 正常打开** |
| 结论 | 「Use 30 Hz」——60 Hz 的面板拷贝把 CPU 饿死 |

我之前用 15 Hz 没有依据（只是偏保守）。15 虽然不至于像 60 那样严重，但没有验证过，
而 **30 Hz 是 mido 进桌面时用的值**。

### 根卷内容已验证（不只是「构建成功」）

从 CI 日志确认移植补丁**真的生效**：

| 项 | 证据 |
|---|---|
| launchd | `7 _PanicOnCrash renamed, 2 CommCenter jobs removed` |
| containers | `Bundle` / `Data/System` / `Shared/SystemGroup` / `Temp` 四目录已建 |
| 音频 | `VirtualAudio.plugin disabled` |
| MediaToolbox | `StartRecorderServer off` × 3 path |
| 偏好 | `com.apple.migration` / `springboard` / `purplebuddy` 已写 |
| dyld 缓存 | `dyld_shared_cache_arm64` + `.symbols` 已硬链接 |
| 大小/校验 | 16 GiB / 11.15 GiB sparse / fsck OK |

### QEMU 的结论（已停止投入，但要记录）

用符号精确定位到：故障 FAR = `common_start + 0x194`，那里是 **`isb`**，前一条是 **`msr SCTLR_EL1`**
= **打开 MMU 的那一瞬间**。计算出 TTBR1（T1SZ=25）只覆盖 `0xffffff80_00000000` 以上，
而 commpage base `0x0FC0000000` **不在覆盖内** —— 这是 `UGG_4K_VM`（36 位 VA 布局的 iOS 值）
与 39 位 TTBR1 的不自洽。

**mido 从未用过 QEMU**（移植日志里 0 次提及），它靠真机屏显直接到桌面。
所以 QEMU 保留为回归检查，**不阻塞主线**。

### 你的两步

**1. 刷新镜像看屏显**（不需要根卷）

预期停在 `Still waiting for root device`（M2）。

**2. 在有 20 GB 空闲的机器上下载并刷根卷**

```
./ugg/flash-root.sh /path/with/20GB
```

然后：

```
fastboot -S 256M flash userdata ios16-root.simg     # 10-15 分钟
fastboot boot shim-boot-0082-mido.img               # 首启 4-8 分钟
```

### 屏显判读

| 看到 | 含义 |
|---|---|
| 左下角白带 / 底部绿色方块（数个数） | stage-0 / 早期阶段号 |
| `SWEET EARLY NN: 标签` | 早期控制台 |
| `panic:` | **拍照给我** |
| `Still waiting for root device` | **M2**（未刷根卷的正常终点） |
| 苹果 logo | 根卷挂载成功 |
| 锁屏 / 桌面 | **目标达成** |

---


## ★★★★★ 最新（2026-11-15 04:20，第 8 轮）-- 根卷已构建出来，可以刷了

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1114 行）。

### 现在的状态：所有构建产物都齐了

| 产物 | 状态 | 位置 |
|---|---|---|
| XNU 内核 | ✅ | CI run 43629928191，17,140,032 B |
| shim | ✅ | CI run 43614156236，184,320 B |
| **boot.img** | ✅ | **工作区根目录 `shim-boot-0082-mido.img`，8,169,472 B** |
| **iOS 根卷** | ✅ | **CI run 43634756880，11,970,598,900 B，7 个分片** |

### 你要做的三步

**1. 刷 boot.img 看屏显（可先做，不依赖根卷）**

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

```
sha256 e91b0d5fb2d40800f7fe374822860019b3bfaf3377de9cdcbba947139e46ec0e
```

没刷根卷 ⇒ **正常应停在 "Still waiting for root device"**（M2 达成）。

**2. 下载并校验根卷**

⚠️ **注意磁盘**：本机 C: 只剩 7.3 GB，装不下 11.2 GB 的镜像。
请在有 20 GB 以上空闲空间的机器/盘上做：

```
./ugg/flash-root.sh /path/with/20GB
```

或者手动：

```
gh run download 43634756880 -R honghong2011/ios-ugg -n ios16-root-parts -D parts
cd parts && sha256sum -c SHA256SUMS
cat ios16-root.simg.part* > ../ios16-root.simg
stat -c%s ../ios16-root.simg     # 必须是 11970598900
```

**3. 刷入并启动**

```
fastboot getvar partition-size:userdata    # 确认够大
fastboot -S 256M flash userdata ios16-root.simg
fastboot boot shim-boot-0082-mido.img
```

会清空 Android 数据（你已批准）。刷 10-15 分钟，首启 4-8 分钟。

### 根卷的实测数据（不是估计）

| 项 | 值 |
|---|---|
| HFS+ 镜像 | 17,179,869,184 B（16 GiB） |
| fsck | 三次全部 `The volume iOSRoot appears to be OK.` |
| sparse 镜像 | 11,970,598,900 B |
| 分片 | 6 × 1,887,436,800 + 1 × 645,978,100 = 7 片 |
| 校验 | 每片 sha256，`sha256sum -c` 全过 |
| CI 步骤 | **11/11 success** |
| 合成耗时 | 不到 3 分钟（比 mido 本地快得多） |

### 屏显判读

| 看到 | 含义 |
|---|---|
| 左下角 64×32 白带 | stage-0 跑到了 |
| 底部绿色方块（数个数） | `sweet_early_mark` 的阶段号 |
| `SWEET EARLY 01..NN: 标签` | 早期控制台工作 |
| `panic:` | **拍照给我** |
| `Still waiting for root device` | **M2**（没刷根卷时的正常终点） |
| 苹果 logo | 根卷挂载成功，进 M3/M4 |
| 锁屏 / 桌面 | **目标达成** |

---


## ★★★★★ 最新（2026-11-15 03:30）-- 镜像已更新，请刷这个

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1002 行）。

### 你的那一步

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

```
8,169,472 B
sha256 e91b0d5fb2d40800f7fe374822860019b3bfaf3377de9cdcbba947139e46ec0e
```

**这个镜像和上一版不同**：修掉了 5 个 framebuffer 地址 bug（见下），务必刷这个新的。

### 本轮修掉的 5 个真 bug（真机同样会中）

| # | 位置 | 问题 | 后果 |
|---|---|---|---|
| 1 | `start.s` UGG_MARK | `0x90001000 + 1888*4320`，stride 4320 | 写越界 0x6F100 字节，超出 splash_region |
| 2 | `start.s` stage-0 白带 | 同上 | 同上 |
| 3 | `sweet_early.c` `sweet_early_mark` | `stage*48` 到 `(stage+1)*48`，stage 最大 20 ⇒ x 到 **1008** | **超出 720 宽 288 像素**，绕行后越出 framebuffer |
| 4 | `SweetFramebuffer.cpp` MDP 回退 | `0x90001000` / `4320` | 错地址 |
| 5 | `mkadt_ugg.py` QEMU 模式 | 512 MiB ⇒ 实际测 4K VM 路径 | QEMU 测的不是真机路径 |

bug 3 尤其严重：mido 的面板 1080 宽能放 22 个 48px 方块，ugg 只有 720 宽只能放 15 个，
而 stage 能到 20 —— **只要有 stage>=15 就必然越界写**。

### 另外两件重要的事

**1. 根卷不需要 Linux 电脑了**

`probe-rootenv.yml` 在免费 ubuntu runner 上实测六项全过：
86 GB 磁盘 / hfsplus 可加载 / mkfs / mount / fsck / apfs-fuse 源码构建成功。
`build-root.yml` 一条命令出 16 GB 根卷，切 1.8 GB 片上传。

**2. QEMU 早期启动验证已上线，但尚未通过**

已排除：内存大小、framebuffer 地址、mark 越界、commpage 补丁。
诊断埋点已加（`UGG PMAP: commpage ...`），但这行**没出现** ⇒ 故障在 `arm_vm_init` 更早处。
判断：QEMU 转为回归检查，不阻塞真机。真机屏显才是判据。

### 屏显判读

| 看到 | 含义 |
|---|---|
| 左下角 64x32 白带 | stage-0 跑到了 |
| 底部一排（或两排）绿色方块 | `sweet_early_mark` 在工作，数字越大越靠后 |
| `SWEET EARLY 01..NN: 标签` | 早期控制台 + 阶段名 |
| `panic:` / 白字滚动 | **拍照给我**，最有价值 |
| `Still waiting for root device` | **M2 达成** |
| 黑屏但有背光，等 3 分钟 | 可能已进 XNU |

---


## ★★★★★ 最新（2026-11-15 02:20，第 7 轮）

> 全部记录：`docs/MIDO-PORT-PLAN.md`（898 行）。本文件下方是历次交接。

### 三件已完成的事

| # | 事情 | 结论 |
|---|---|---|
| 1 | **根卷不需要 Linux 电脑** | `probe-rootenv.yml` 实测六项全过（86 GB 磁盘 / hfsplus 可加载 / mkfs / mount / fsck / apfs-fuse 源码构建成功），`build-root.yml` 在 CI 里做 |
| 2 | **QEMU 早启验证上线** | `-M virt,gic-version=2 -cpu cortex-a53`，解码帧缓冲，报里程碑 |
| 3 | **修掉四个真实 framebuffer bug** | mido 的 `0x90001000 + 1888*4320` 在 ugg 上**写越界 0x6F100 字节**（超出 splash_region） |

### QEMU 那条「内核挂了」是假警报，已查明

1.16 GB 的 `qemu.log` 里只有**一条** Prefetch Abort，后面 4000 条都是它的连锁反应：

`
FAR = ELR = 0x5042c5e4          <- 物理地址
0x5042c5e4 - 0x50000000 + virt_base = 0xfffffff00742c5e4
符号 = common_start + 0x198     <- commpage
`

**根因**：`arm_init.c` 只在 `memSize > 1 GiB` 时选 16K VM 页；我给 QEMU 的是 512 MiB，
于是它测的是 4K VM 路径 —— 而真机是 1.5 GiB / 16K VM。**QEMU 之前测的路径和真机不同。**
已改成 `QEMU_MEM_SIZE = 0x60000000`，与真机一致。

### 你的那一步（没变）

`
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
8,169,472 B   sha256 7a97fee7a10275996bfcd04423867bfc64d4641732308e5ab7b75d3c3cb10af9
`

**只进内存。** 没刷根卷 ⇒ **正常应停在 "Still waiting for root device"**（M2）。

| 屏上看到 | 含义 |
|---|---|
| 左下角一条 64x32 白带 | stage-0 跑到了（mido 移植标记） |
| `SWEET EARLY` 01..NN | 早期控制台工作 |
| `panic:` / 白字滚动 | **拍照给我**，最有价值 |
| `Still waiting for root device` | **M2 达成** |
| 黑屏但有背光，等 3 分钟 | 可能已进 XNU |

---


## ★★★★★ 现在的真实状态（2026-11-15 01:50，第 7 轮末）

> 完整计划/记录：`docs/MIDO-PORT-PLAN.md`（830 行）。本轮全部提交已推送 `ugg-port`。

### 三件事，按重要性

#### 1. 你又少了一件要准备的事：根卷在 CI 里做

我说过「必须 Linux 电脑」，**错了**，没实测就下的结论。`probe-rootenv.yml` 在 ubuntu
runner 上把六个前提全测过，全通：

| 前提 | 实测 |
|---|---|
| 磁盘 | **86 GB 可用**（不是传闻的 14 GB） |
| `modprobe hfsplus` / `mkfs` / `mount` / `fsck` | 全 OK |
| `apfs-fuse` 源码构建 | **cmake rc=0 / ninja rc=0** |

所以 `build-root.yml` 已在仓库里，一条命令出 16 GB 根卷（切 1.8 GB 片）。

#### 2. QEMU 抓到了四个真 bug（**真机同样会中**）

第一次 QEMU 启动：`blank_screen`，**零个里程碑**，连 `SWEET EARLY` 都没打出来。
这指向最早的那几条指令，而不是 pmap。查出来的原因：

| # | 位置 | mido 的值（ugg 上错的） |
|---|---|---|
| 1 | `start.s` `UGG_MARK` | `0x90001000 + 1888*4320`，stride `4320` |
| 2 | `start.s` stage-0 白带 | 同上 |
| 3 | `SweetFramebuffer.cpp` MDP 回退 | `0x90001000` / `4320` |
| 4 | `sweet_early.c` 早期控制台 | 已改（早先修的） |

**越界证据**（这是判断的关键，不是猜）：

`
mido 的 UGG_MARK 写到  0x911D4480 + 32*4320 + 64*4 = 0x9146F100
splash_region 末尾                             = 0x91400000
超出                                           = 0x6F100 字节
`

这些写入发生在**有栈、有页表、有控制台之前**，所以在手机上只会表现为黑屏，
很容易被误判成 pmap 问题。QEMU 把它提前暴露成「0 个里程碑」。

修复后 QEMU 从 `blank_screen` 变成 **`incomplete_decode`，出现 4 个字形** —— 
**内核确实开始画字了**，几何修对了。

#### 3. 解码器也在修

`????` 是因为解码器按 sweet 的 2400 行面板算，且把空白格子也算成「未知字形」，
所以只要屏上有空白就永远判定不通过。已改成按 ugg 的 720x1280（45 列 x 39 行）解码，
空白当空格。

### 你的那一步没变

`
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
`

`
8,169,472 B   sha256 7a97fee7a10275996bfcd04423867bfc64d4641732308e5ab7b75d3c3cb10af9
`

**只进内存。** 没刷根卷，所以**正常应停在 "Still waiting for root device"**（那是 M2）。

### 屏显判读（和之前一样）

| 看到 | 含义 |
|---|---|
| 屏底部左下一条白带（64x32） | stage-0 跑到了 ✅ 这是 mido 移植的标记 |
| `SWEET EARLY` 01..NN | 早期控制台工作 |
| `panic:` / 白字 | **拍照给我**，最有价值 |
| `Still waiting for root device` | **M2 达成** |
| 黑屏但有背光，等 3 分钟 | 可能已进 XNU |

---


## ★★★★ 最新状态（2026-11-15 01:10，第 7 轮）

> 本章取代下面所有内容。计划与全部记录：`docs/MIDO-PORT-PLAN.md`（772 行）。

### 两件大事（本轮）

**1. 你不需要找 Linux 电脑了。**

我之前说「根卷必须 Linux 电脑」，**那是错的**，我没实测就下了结论。新加的
`probe-rootenv.yml` 在 ubuntu runner 上把六个前提全测了，全过：

| 前提 | 实测 |
|---|---|
| 磁盘 | **86 GB 可用**（不是传闻的 14 GB） |
| `modprobe hfsplus` | OK |
| `mkfs.hfsplus` | OK |
| `mount -t hfsplus` | OK |
| `fsck.hfsplus` | OK |
| `apfs-fuse` 源码构建 | **cmake rc=0 / ninja rc=0** |

所以 `build-root.yml` 已经写好，**在 CI 里构建 16 GB 根卷**，切 1.8 GB 片上传。

**2. 内核早期启动有了自动化验证（QEMU）。**

不再只能靠屏摄判断内核死没死：CI 里加了一个 ubuntu job，用
`-M virt,gic-version=2 -cpu cortex-a53` 启动真内核，解码帧缓冲文字，
报告走到了哪个里程碑（start.s / arm_init / pmap / VM bootstrap / SWEET FB / waiting for root）。

> 这正好覆盖旧路线卡死的整段路径。注意它**不能**验 UGG 的真实 MMIO、eMMC、面板。

### 现在完全由你决定的只有一步

`
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
`

`
文件    shim-boot-0082-mido.img   8,169,472 B
sha256  7a97fee7a10275996bfcd04423867bfc64d4641732308e5ab7b75d3c3cb10af9
`

**只进内存，不刷任何分区。** 还没刷根卷，所以**正常应该停在 "Still waiting for root device"**
—— 那就是 M2，不是失败。

### 屏显判读

| 看到 | 含义 | 动作 |
|---|---|---|
| 2 分钟内回 fastboot + `LOADER:` 原因 | shim 拒绝 payload | 拍照 |
| `SWEET EARLY` 1..4 | XNU 在跑 | 继续看 |
| `panic:` / 白字滚动 | **最有价值** | 拍照 |
| `Still waiting for root device` | **M2 达成** | 告诉我，进入下一步 |
| 黑屏但有背光，等 3 分钟 | 可能已进 XNU | 拍照 |

### 下一步（M2 之后）

`
gh workflow run build-root.yml -R honghong2011/ios-ugg --ref ugg-port
# 约 60-90 分钟，产出 ios16-root-parts（7 个 1.8 GB 分片）
gh run download <RUN_ID> -R honghong2011/ios-ugg -n ios16-root-parts -D parts
cd parts && sha256sum -c SHA256SUMS && cat ios16-root.simg.part* > ../ios16-root.simg
fastboot -S 256M flash userdata ../ios16-root.simg     # 会清空 Android 数据（你已批准）
fastboot boot shim-boot-0082-mido.img
`

---


## ★★★ 现在这一步：镜像已就绪，等你刷机（2026-11-15 00:35）

> 本章是最新状态，取代下面的「路线已切换」章节。

### 你要做的（一条命令）

`
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
`

`
文件    shim-boot-0082-mido.img
大小    8,169,472 B
sha256  7a97fee7a10275996bfcd04423867bfc64d4641732308e5ab7b75d3c3cb10af9
`

**这是 `fastboot boot`，只进内存，不刷任何分区。** 断电即恢复 Android。

### 屏上该看到什么（判读指南）

| 现象 | 含义 | 下一步 |
|---|---|---|
| 2 分钟内自动回到 fastboot | shim 拒绝了 payload，屏上会写原因（`LOADER:` 开头） | 拍照给我 |
| 屏上 3 色带 + `SWEET EARLY` 1..4 | shim 跑通，XNU 的 start.s 在跑 | ✅ 继续看 |
| 出现 `panic:` 或白字滚动 | XNU 起来了但中途挂 | **拍照给我**，这是最有价值的 |
| 停在 `Still waiting for root device` | **M2 达成** | 下一步做根卷 |
| 屏一直黑但有背光 | 可能已经进 XNU 但 fb 没接管 | 等 3 分钟再拍照 |
| 苹果 logo | **M3/M4 达成** | 继续等锁屏 |
| 锁屏 / 桌面 | **目标达成** | 告诉我，录一段触控 |

**注意**：如果刷了根卷后第一次启动，mido 实测要 **4-8 分钟**才出苹果 logo。你现在还没刷根卷，
所以这一版应该走到 `Still waiting for root device` 就停住（因为 userdata 现在还是 Android 的 ext4）。
**这正是 M2 的判据。**

### 已经做完的完整链条

| # | 步骤 | 状态 | 证据 |
|---|---|---|---|
| 1 | 恢复上游原版补丁链 `0001-0081` | ✅ | `same=84 diff=0` |
| 2 | 重建干净基线 | ✅ | `applied=81 failed=0`，commit `2bbcef0` |
| 3 | 移植 mido 的 `0100` 为 `0082-ugg-board.patch` | ✅ | 28 文件 +2089/-22，零冲突 |
| 4 | 修掉 4 轮 CI 发现的错误 | ✅ | run 43613955911 **success** |
| 5 | 内核 `applied=86`，skipped 无 0082 | ✅ | annotation 确认 |
| 6 | shim 移植（eMMC/RPM/GT9xx）+ CI 编译 | ✅ | run 43614156236 success |
| 7 | 生成 UGG ADT（iPhone10,4 / 750x1334） | ✅ | 9896 B |
| 8 | 打包并校验 boot.img | ✅ | 结构 12 项全过 |
| 9 | 交付根卷构建脚本 | ✅ | `ugg/build-root.sh` 174 行，`bash -n` 通过 |

### 唯一还没做的：根卷

需要你找一台 **Linux 电脑**（原生优先，WSL2 的 hfsplus 没编），磁盘 ≥ 40 GB 空闲，跑：

`
cd 任意目录
git clone https://github.com/honghong2011/ios-ugg ugg-src   # 或者直接用你现在这份
./ugg-src/ugg/build-root.sh ~/ugg-root
`

跑完给我三个数：

`
1. fsck 输出（应含 volume iOSRoot appears to be OK）
2. ios16-root.img 与 ios16-root.simg 的字节数
3. fastboot getvar partition-size:userdata 的输出
`

### 为什么根卷必须走 Linux（不是偷懒）

| 步骤 | Windows/macOS 能做吗 |
|---|---|
| `apfs-fuse` 读 IPSW 的 APFS dmg | ❌ 没有可用实现 |
| `mkfs.hfsplus` / `fsck.hfsplus` | ❌ 只有 Linux/BSD 版 |
| `mount -t hfsplus -o loop` | ❌ Windows 无 loop 设备 |

GitHub Actions 也不行：需要 6 GB IPSW + 16 GB 镜像 + 12 GB sparse ≈ 34 GB，ubuntu runner 只有 14 GB。

---


## ★★ 路线已切换：照抄 ios-mido（2026-11-14 深夜）

> **本章取代下面所有旧内容。** 旧的 `0082-0098` 自研补丁路线**已全部作废并归档**。
> 完整计划与执行记录见 **`docs/MIDO-PORT-PLAN.md`**（441 行，最新、必读）。

### 一句话现状

**XNU 补丁 `0082-ugg-board.patch` 已生成并验证零冲突；shim 已移植并 CI 编译通过；正在等最后一轮 xnu CI。**

### 已经做完的（有提交、有 CI、有验证）

| # | 事情 | 证据 |
|---|---|---|
| 1 | 发现旧路病根：`ugg/xnu/patches` 里 41 个 `0001-0081` 被改成 `SWEET_FAMILY` 版本，导致 `patch` 只应用一部分 → 假 hunk → 0093/0095/0098 被 CI 跳过 | `same=84 diff=0` 对比上游 |
| 2 | 恢复上游原版 `0001-0081`（逐字节） | 84 个补丁全部一致 |
| 3 | 重建干净基线：reset + 3 个 staging 脚本 + apply `0001-0081` | `applied=81 failed=0`，commit `2bbcef0` |
| 4 | 验证 mido `0100-mido-board.patch` 可在本基线零冲突应用 | 31 文件 `git apply --check` 全过 |
| 5 | 生成 `0082-ugg-board.patch` | 28 文件 +2089/-22，`git apply --cached --check` 通过 |
| 6 | 移植 shim（sdhc/rpm/spmi/perf/input + 新写 emmc.c/兼容层/日志环） | shim-ugg CI **success** run 43612347343 |
| 7 | 生成 UGG ADT（`tools/mkadt_ugg.py`，iPhone10,4/D20AP 750x1334） | 9896 B |
| 8 | 交付根卷构建脚本 `build-root.sh`（Linux 用，174 行） | `bash -n` 通过 |

### UGG 真实硬件（已从本机 DTB 核实，推翻旧文档）

`
SoC        MSM8940（骁龙 435），**不是 8937**
           DTB: model = "Qualcomm Technologies, Inc. MSM8940-PMI8937 MTP"
eMMC       sdhci@7824900，HC 0x500 / core 0x800，IRQ SPI 123/138
           电源 L5=1.8V(vdd-io) L8=2.9V(vdd)  <- 与 mido 完全一致
GCC SDCC1  RCG 0x01842004                        <- 与 mido 完全一致
触控       goodix@5d on i2c@78b7000 (QUP **v1**)
           irq gpio65, reset gpio64, power_ldo gpio47
           vdd_ana = L10 2.85V, vcc_i2c = L6 1.8V  <- 与 mido 完全一致
面板       720x1280，splash 0x90000000 + 20 MiB
指纹       fpc1020 + goodix_fp（两个节点都在）
`

### 与 mido 的差异（全部已处理，见 MIDO-PORT-PLAN §6.3）

| 项 | mido | ugg |
|---|---|---|
| framebuffer | 0x90001000 / 1080x1920 / stride 4320 | **0x90000000 / 720x1280 / stride 2880**（2 个 2MB 块） |
| 呈现画布 | 1242x2208 / 458ppi（iPhone 8 Plus） | **750x1334 / 326ppi（iPhone 8）** |
| 触控 IC | FocalTech FT5435（8 位寄存器） | **Goodix GT9xx（16 位寄存器）** |
| GPU | 有（Adreno 506） | **删除**（用户明确跳过） |
| CPU 升频 | 1401–2016 MHz 五档 | **关闭**（435 档位未实测，风险不可恢复） |

### 下一步（严格按序）

`
1. 等 xnu CI（run 43612214819 之后的那个）-> 检查三件套：
   a. annotation 里 applied 计数 = 86（0082 已算在内）
   b. patches-skipped 里**不含** 0082
   c. kernel.development.ugg 比上版大（0082 加了 ~2000 行）
2. 下载内核 -> ./ugg/make-image.sh <kernel>  -> 出 shim-boot-ugg.img
3. fastboot boot shim-boot-ugg.img（**不刷任何分区**）
   屏显判读：出 "SWEET FB" = XNU 起来；"Still waiting for root device" = M2 达成
4. 用户找 Linux 电脑跑 ./ugg/build-root.sh，回传三个数：
   fsck 输出 / img+simg 字节数 / fastboot getvar partition-size:userdata
5. 刷 userdata（**这一步会清空 Android 数据，用户已批准**）-> 再 boot -> 目标桌面
`

### 归档位置

旧 `0082-0098` 补丁在 `build-m1/old-ugg-patches/`（14 个文件），不再使用。

---


> 本文件镜像上游 NOTES.md 的 handoff 规范：每次里程碑后更新最新 handoff，区分事实与猜测。

## ★ 先读这个：iOS 桌面目标的可行性核对（2026-11-14）

完整内容见 **`docs/ROADMAP-2026-11-14.md`**。这里只放最要紧的三条：

### 1. 「全程 RAM 进桌面」在此设备上走不通（已核实）

| 限制 | 数值 | 来源 |
|---|---|---|
| `fastboot boot` 载荷上限 | **511.0 MiB** | `README.md:45` 实机 getvar |
| 减去 shim + 内核后根镜像余量 | **494 MiB** | 实算 |
| iOS shared cache 需求 | **2.5 GiB**（去 .symbols） | `ugg/NOTES.md:184` 上游实测 |
| XNU 当前可见 RAM | 512 MiB | payload `mem_size` @0x38 |

**差 5 倍以上。** 上游撞到同一面墙，结论一致：要么存储驱动，要么极小 cache。

### 2. 上游 ios-sweet 跑在完全不同的 SoC 上

上游是 **A55 + UFS + RPMh + GT9896 + 1125×2436**，我们是 **A53 + eMMC + RPM + GT917D + 720×1280**。
它 2026-10-18 确实拿到了 SpringBoard 桌面，但**底层驱动几乎全部要重写**，只能复用用户态那半。

### 3. 唯一被上游验证成功的路线是存储驱动，而我们有 SD 卡

手机**已插 32GB SD 卡**。SD 卡驱动（SDHCI-msm）比 eMMC 简单，且**只读用户自己的卡**，
符合「不动 data 分区」的硬约束。这是 B 路线，比 E（写 eMMC 完整根卷）轻得多。

### 砍掉的步骤

| 阶段 | 结论 |
|---|---|
| B1 串口 | **砍掉**：本机无物理 UART，屏上输出已够用 |
| B3 RPM 电源 | **降级**：只在触摸不工作时才做 |
| E eMMC 完整根卷 | **砍掉**（难且需写分区），但 B 的 SD 卡驱动保留 |
| U7 GPU | 用户不追求 |

### 待用户确认

- **x86 Linux 那台的硬盘大小**（需 ≥40 GB 才能构建根镜像；2GB ARM 机因内存不够不可用）

## Agent handoff / active work (2026-11-12 深夜, latest)

### >>> M1 仍未通过；0092 已推送、CI 通过，待真机验证 <<<

**一句话：0089 的栈溢出已确认修好；0090/0091 暴露的两个「诊断代码自己炸」问题已在 0092 修掉。**
现在的失败点是**我自己的仪俪代码读系统寄存器被拒**，不是内核逻辑。

**1. 0090 真机结果（用户屏摄）**

- 旧的 `esr 9600004f`（写只读保护页）**完全消失** ⇒ 栈扩容生效。
- 但屏上出现**几百块**重复 `SWEET FAULT sync`，每块都停在 `istack:` 后。
- 定位：`pc` = `_sweet_early_fault+0x140`，指令是 `mrs x10, SP_EL0`；
  `sp` 每轮下移 ~1216 字节（848 frame + 368 分发）⇒ **打印函数自己重入死循环**。
- `esr 0x02000000` = EC 0（unknown reason）⇒ 异常处理已在半途又取异常。
- 仪表没显示：它画在文本第 38 行，而滚动文字也用第 38 行，最后一行覆盖了它。**设计 bug**。

**2. 0091 做了什么（只动早期控制台）**

- 预留第 38 行给仪表，滚动只用前 38 行（`EARLY_TEXT_ROWS`）。
- 仪表**总是**绘制，SP 不在启动栈时画 `????`。
- `sweet_early_fault()` 去掉 `_doprnt`、只报一次（`early_fault_reported`）。
- 加 `EARLY_LEFT_MARGIN`：首列留空（屏摄显示首列被边框切掉，`00000` 看成 `30000`）。

**3. 0091 真机结果（用户第二张屏摄）**

- 防重入**成功**：屏上只有**一条** `SWEET FAULT`，不再是几百条。
- 新故障 `pc ffffffe0007439f20` = `_sweet_early_mark+0x850`，机器码 `d5384114`
  = **`mrs x20, SP_EL0`** ⇒ **仪表自己**在抓异常。启动连标记 1 都没过。
- `sp ffffffe00080bfef0`，距 `_intstack_top` **272 字节**。
  **注意方向**：栈向下长 ⇒ 只用了 272 字节、**剩 65264 字节（99.6% 空）**。
  0089 那次 `sp` 在栈底**以下**，是真溢出；这次不是。**⇒ 0090 确实修好了溢出。**
- 第二条 panic `Synchronous exception taken while SP1 selected`：
  `pc` = `_current_percpu_base+0xc` = `ldr x0,[x0,#544]`，`esr 0x96000005`
  （data abort EL1, DFSC 5 translation fault L1），`x10` = `0x220` = 544。
  `current_thread_fast()` 就是 `mrs TPIDR_EL1`；**标记 1 时 TPIDR_EL1 还是 0**，
  解引用 NULL+544 就翻译失败。⇒ **这是第一条故障的后果，不是独立 bug。**

**4. 0092 做了什么**

- `sweet_early.c`：`sweet_early_sp_el0()`（`mrs SP_EL0`）→ `sweet_early_sp()`（`mov %0, sp`）。
  `sweet_early_mark()` 在 `arm_init()` 里跑，`SPSel=0`，所以 `sp` 与 `SP_EL0` **同值**，
  而读 `sp` 是普通通用寄存器搬移，**不可能抛异常**。数值不变，风险归零。
- `sleh.c`：`sleh_synchronous()` 与 `sleh_invalid_stack()` 原本在序言就先
  `thread = current_thread()`，在 SWEET 报告**之前** ⇒ TPIDR_EL1=0 时先炸，
  把真报告盖成误导性 panic。现改为**先打印、后取 thread**。

**5. 交付物 / 复现**

| 项 | 值 |
|---|---|
| commit | `eac43c7`(0091) `9d8669c`(notes) `08ba29f`(0092) |
| CI run | `43218229183`(0091) `43237805476`(0092) 均 **success** |
| patch-report | `applied=96 skipped=4`（4 条为外部 dxb 补丁） |
| 0091 kernel | 17,301,656 B，sha256 `fa715f77...c9b3b1b0` |
| 0092 kernel | 17,301,656 B，sha256 `264250a9...4fcabaa1` |
| 0091 镜像 | `build-m1/diag2/shim-boot-0091-faulthardened.img` sha256 `2b22fb6b...7e20631` |
| 0092 镜像 | `build-m1/diag2/shim-boot-0092-faultsafe.img`（见下） |
| 补丁校验 | 0090→0091→0092 顺序应用逐字节复现；均不可重复应用 |

**6. 审计结论（0092 顺带做的）**

对 0091 内核做全量系统寄存器扫描：早期路径（`sweet_early_*` + `arm_init`）里
**只有一处**风险系统寄存器读取，就是 `_sweet_early_mark+0x850` 的 `mrs x20, SP_EL0`，
**已被 0092 覆盖**。另扫描 ARMv8.1 LSE 原子指令（A53 是 ARMv8.0，LSE 会 UNDEF）：
早期函数中 **0 处**，所以 `esr 02000000` 确实就是那条 `mrs` 本身。

**7. 下一步**

`fastboot boot` 0092 镜像，看：
- 若不再有 `SWEET FAULT` 且标记递增 → **M1 前进，准备进 M2**；
- 左下角应出现 `stkXXXX`（剩余栈 ÷18 的十六进制）：`stk0e29` = 65,264 B 剩；
- 若仍有故障 → 这次是**真**故障，`pc/lr/sp/esr/far` 齐全且只报一条。

## 交付物：0098（当前最新，双 bank 读数，2026-11-14 夜）

| 项 | 值 |
|---|---|
| 镜像 | `build-m1/diag2/shim-boot-0098-twobank.img` |
| 大小 | 8,151,040 B |
| sha256 | `6d06b4b120a6ff3aacb69818af19b1b0f60cf79e73e4763ed09138f0383e2dec` |
| 内核 | `ci-xnu17/kernel.development.ugg`，17,711,296 B，sha256 `192b04f3...ef6b3ab` |
| 来源 CI | run `43599523442`（`9d64b3c`）**success**，`applied=102 skipped=4` |
| 构造脚本 | `build-m1/mk0099.py` |

**用法（RAM-only，不刷任何分区）**：

`
fastboot boot build-m1/diag2/shim-boot-0098-twobank.img
`

**四重门禁全过**：

| gate | 结果 |
|---|---|
| `patches-skipped` | **不含 0098** |
| `patch-report` | `applied=102`（上一轮 101） |
| bank A 标签（`ptovn/w.pa/w.va/w.len/w.end/raend`） | **全部存在** |
| bank B 标签（`zerva/zerolastva/...`） | **全部存在** |
| 两组共存于同一内核 | **True** |

### 屏幕布局（这次两批读数互不覆盖）

| 行 | 内容 |
|---|---|
| 0..17 | 滚动控制台（panic dump 在其内） |
| **18..27** | **bank A：ptov 值（0097 的内容，之前从未显示过）** |
| **28..37** | **bank B：pmap 值（0094 的内容）** |
| 38 | `stk` 仪表 |

### 两个 bank 分别看什么

**bank A（关键）**：

| 槽 | 标签 | 含义 |
|---|---|---|
| 0 | `ptovn` | 非空 ptov 窗口数量 |
| 1 | `w.pa` | 含 `avail_start` 的窗口起始 PA；**`ffffffffffffffff` = 不在任何窗口** |
| 2 | `w.va` | 该窗口 VA 基址 |
| 3 | `w.len` | 该窗口长度 |
| 4 | `w.end` | 该窗口 PA 结束 |
| 5 | `zerva` | `phystokv(avail_start)` 应解析到的 VA |
| 6 | `pstart` | `avail_start` |
| 7 | `pb` | `physmap_base` |
| 8 | `pe` | `physmap_end` |
| 9 | `raend` | `real_avail_end` |

**bank B**：pmap 表相关的十个值（已知正常，用于对照）。

## 交付物：0097（当前最新，ptov 诊断版，2026-11-14 晚）

| 项 | 值 |
|---|---|
| 镜像 | `build-m1/diag2/shim-boot-0097-ptovdiag.img` |
| 大小 | 8,151,040 B |
| sha256 | `dad085438047a43e1cbe6408a82b742a6ce05ca7d17e1bff85be67cd3bd901b1` |
| 内核 | `ci-xnu16/kernel.development.ugg`，17,694,912 B，sha256 `285b81e9...765362e8` |
| 来源 CI | run `43581971337`（`7a410cc`）**success**，`applied=101 skipped=4` |
| 构造脚本 | `build-m1/mk0098.py` |

**用法（RAM-only，不刷任何分区）**：

`
fastboot boot build-m1/diag2/shim-boot-0097-ptovdiag.img
`

**已验证诊断确实进了内核**（吸取 0093/0095 的教训）：

| gate | 结果 |
|---|---|
| `ptovn/w.pa/w.va/w.len/w.end/raend` 字符串 | **全部存在**（0x7a101 附近） |
| `zerva/zerolastva/physmapbase/physmapend` | 仍在（0x78756 附近） |
| `patches-skipped` | **不含 0097** |
| `patch-report` | `applied=101`（上一轮 99） |

### 屏幕布局

| 行 | 内容 |
|---|---|
| 28~37 | **0097 十个诊断值**（见下） |
| 38 | `stk` 栈仪表 |
| 0~27 | 滚动控制台（panic dump 在这里，不会覆盖诊断） |

### 十个值的含义

| 槽 | 标签 | 含义 |
|---|---|---|
| 0 | `ptovn` | 非空 ptov 窗口数量 |
| 1 | `w.pa` | 含 `avail_start` 的窗口起始 PA；**`ffffffffffffffff` = 不在任何窗口** |
| 2 | `w.va` | 该窗口 VA 基址 |
| 3 | `w.len` | 该窗口长度 |
| 4 | `w.end` | 该窗口 PA 结束 |
| 5 | `zerva` | `phystokv(avail_start)` 应解析到的 VA |
| 6 | `pstart` | `avail_start`（物理） |
| 7 | `pb` | `physmap_base` |
| 8 | `pe` | `physmap_end` |
| 9 | `raend` | `real_avail_end` |

## 交付物：0095（当前最新，256 KiB 启动栈，2026-11-14）

| 项 | 值 |
|---|---|
| 镜像 | `build-m1/diag2/shim-boot-0095-stack256k.img` |
| 大小 | 8,151,040 B |
| sha256 | `eaaf9fa43d9e95ec5dfebeab08868775f41f6d7b76de38f8c7cd59f7edcc370e` |
| 内核 | `ci-xnu15/kernel.development.ugg`，17,694,912 B，sha256 `53c1df06...40b7593` |
| 来源 CI | run `43553713449`（`01155e7`）**success**，`applied=99 skipped=4` |
| 构造脚本 | `build-m1/mk0096.py` |

**用法（RAM-only，不刷任何分区）**：

`
fastboot boot build-m1/diag2/shim-boot-0095-stack256k.img
`

**已验证（事实）**：

| 门禁 | 结果 |
|---|---|
| `_intstack` 大小 | **262,144 字节（256 KiB）** ✓ |
| `_excepstack` 大小 | **262,144 字节（256 KiB）** ✓ |
| `__BOOTDATA` 大小 | `0x64000` → **`0xc4000`（784 KiB）**，与预测一致 |
| shim | 与 0094 逐字节相同 |

### 为什么是 256 KiB（实测数据，不是估算）

0094 的固定行读数**证明 pmap 表全部正常**，随后从 panic 现场反推出真实缺口：

| 项 | 字节 |
|---|---|
| 故障前 `SP_EL0` | `0xfffffe00080b0180`（离栈底 384）|
| 已消耗（距栈顶）| 65,152 |
| 异常帧需求 | 848 |
| **合计需求** | **66,000** |
| 当时可用 | 65,536 |
| **缺口** | **464** |

64 KiB 差 464 字节。256 KiB 是实测需求的 **3.97 倍**。

### 代价

每 CPU 两栈共 512 KiB × 8 CPU = **4 MiB**，4 GiB 设备上可忽略。
`__BOOTDATA` 变大但会被 `ml_static_mfree()` 在真实 pmap 建立后释放。

## 交付物：0094（当前最新，固定行读数版，2026-11-14）

| 项 | 值 |
|---|---|
| 镜像 | `build-m1/diag2/shim-boot-0094-readoutband.img` |
| 大小 | 8,151,040 B |
| sha256 | `e5bef54878918eefda3574680c16b6080b3d3419a954c82116477c560c426b13` |
| 内核 | `ci-xnu14/kernel.development.ugg`，17,301,696 B，sha256 `d9b1050e...cf1edcfb` |
| 来源 CI | run `43541927223`（`b2b76cb`）**success**，`applied=98 skipped=4` |
| 构造脚本 | `build-m1/mk0095.py` |

**用法（RAM-only，不刷任何分区）**：

`
fastboot boot build-m1/diag2/shim-boot-0094-readoutband.img
`

**三重门禁已验证**：`_sweet_early_val` 存在、10 个 tag 字符串齐全、
`_pmap_data_bootstrap` 由 `0x300` 增至 `0x320`。shim 与 0093 逐字节相同。

### 0093 为什么没显示出数字（重要）

0093 的代码**确实进了内核**（门禁全过），但屏上一个数字都没有。
原因与 0091 的仪表**是同一类错误**：

- `sweet_early_val()` 用的是 `sweet_early_putc()`，即**加入滚动控制台**。
- 之后依次打印：SWEET FAULT(4 行) + panic 文本(4 行) + 寄存器 dump(~34 行) ≈ 42 行，
- 而滚动环只有 39 行 ⇒ **10 个数字被从头滚出屏幕**。

**教训：位置固定不够，必须落在滚动区之外。**

### 0094 的屏幕分区（三个互不重叠的带）

| 行 | 用途 | 宏 |
|---|---|---|
| 0..27 | 滚动控制台 | `EARLY_TEXT_ROWS = 28` |
| 28..37 | 10 个读数槽 | `EARLY_VAL_ROW = EARLY_ROWS - 11` |
| 38 | 栈仪表 | `EARLY_GAUGE_ROW` |

`early_row` 被 `EARLY_TEXT_ROWS` 约束，所以 `sweet_early_clear_row()` **只可能**擦掉控制台行，
永远碰不到读数槽和仪表。已核验无重叠：文字止于 27，读数始于 28，读数止于 37，仪表 38。

### 读数槽顺序（按诊断价值排）

| 槽 | 标签 | 含义 |
|---|---|---|
| 0 | `zerva` | 清零起始 VA |
| 1 | `zerolastva` | 清零末尾 VA ← 与 3 比较 |
| 2 | `physmapbase` | physmap 窗口起始 |
| 3 | `physmapend` | physmap 窗口结束 ← 若 1 > 3 则越界 |
| 4 | `zerolen` | memset 长度 |
| 5 | `mem_size` | XNU 认为的内存 |
| 6 | `realphys` | physmap 实际覆盖 ← 若 5 > 6 则不一致 |
| 7 | `pmapstart` | 物理起始 |
| 8 | `availstart` | 分配结束 |
| 9 | `gphysbase` | 物理基址 |

## 交付物：0093（当前最新，诊断版，2026-11-13 深夜）

| 项 | 值 |
|---|---|
| 镜像 | `build-m1/diag2/shim-boot-0093-physmapdiag.img` |
| 大小 | 8,151,040 B |
| sha256 | `4716e9bf7b8e7ac2def386e7ea01ac1ce958edd3498f6996d35742a2827fa815` |
| 内核 | `ci-xnu13/kernel.development.ugg`，**17,318,080 B**，sha256 `011b6c19...105570ba` |
| 来源 CI | run `43438611222`（`d659127`）**success**，`applied=97 skipped=4` |
| 构造脚本 | `build-m1/mk0094.py` |

**用法（RAM-only，不刷任何分区）**：

`
fastboot boot build-m1/diag2/shim-boot-0093-physmapdiag.img
`

**三重门禁已验证（事实，这是本次修复的证明）**：

| 门禁 | 结果 |
|---|---|
| `_sweet_early_val` 符号 | **存在** `0xfffffe000743a150` |
| 10 个诊断 tag 字符串 | **全部存在**（0x78776 附近连续） |
| `_pmap_data_bootstrap` 大小 | `0x300`（0092 是 `0x210`），**增长 240 字节** |
| shim 代码区 | 与 0092 / `shim-Image-CI.bin` **逐字节相同** |

**这次预期看到**（10 个数字，每行一个）：

`
pmapstruct    <pmap_struct_start 物理地址>
availstart    <分配结束位置>
zerolen       <memset 长度>
zerva         <清零起始虚拟地址>
mem_size      <XNU 认为的内存大小>
realphys      <physmap 实际覆盖大小>
gphysbase     <物理基址，应 0x91600000>
physmapbase   <physmap 窗口起始 VA>
physmapend    <physmap 窗口结束 VA>
zerolastva    <清零范围最后一个字节的 VA>
`

**判读**：

| 情况 | 含义 | 修法 |
|---|---|---|
| `zerolastva > physmapend` | 清零范围超出 physmap 窗口 | 扩大 physmap 映射 或 缩小表 |
| `zerva` 本身就在窗口外 | 分配器已越界 | 对齐 ADT memory 与 real_phys_size |
| `realphys < mem_size` | XNU 以为内存比映射的多 | 让 ADT memory 节点与实际一致 |
| 只差一页 | 表尺寸 off-by-one | 直接修边界 |

## 交付物：0092（当前最新，可直接 fastboot boot，2026-11-13）

| 项 | 值 |
|---|---|
| 镜像 | `build-m1/diag2/shim-boot-0092-faultsafe.img` |
| 大小 | 8,151,040 B |
| sha256 | `7c9aa5613feb5c3dfb2652c447a486408c029372309dbdb438c3838c04142a5b` |
| 内核 | `ci-xnu10/kernel.development.ugg`，17,301,656 B，sha256 `264250a9...4fcabaa1` |
| 来源 CI | run `43237805476`（`08ba29f`）**success** |
| 构造脚本 | `build-m1/mk0092.py` |

**用法（RAM-only，不刷任何分区）**：

`
fastboot boot build-m1/diag2/shim-boot-0092-faultsafe.img
`

**已在二进制里验证（事实）**：

- `_sweet_early_mark` 中 `mrs SP_EL0` 计数 = **0**（0091 里是 1，正是故障指令 `d5384114`）。
- shim 代码区 [32:196608] 与 0091、与 `shim-Image-CI.bin` **逐字节相同**，
  头部唯一差异字节为 0 —— 这次连长度字段都没变（两版内核大小相同）。
- 镜像**确定性可复现**：连续构建两次 sha256 一致。

**这次预期看到**：

| 现象 | 判断 |
|---|---|
| 无 `SWEET FAULT`，标记递增到 13+ | **M1 通过，可进 M2** |
| 左下角出现 `stkXXXX` | 剩余启动栈 ÷18；`stk0e29` = 65,264 B |
| 仍有一条 `SWEET FAULT` | 真故障，`pc/lr/sp/esr/far` 齐全，继续修 |

## 交付物：可以直接 fastboot boot 的镜像（2026-11-12）

| 项 | 值 |
|---|---|
| 镜像 | `build-m1/diag2/shim-boot-0090-stack64k.img` |
| 大小 | 8,151,040 B |
| sha256 | `46577dfe3fcd9a23d0681247d2c1cfefc62df85e4fc7d405bad244a8f1153579` |
| 内核 | `ci-xnu8/kernel.development.ugg`，17,301,624 B，sha256 `86d8963a823bb76f56b1fc7e40024cc3d2cf7c4137f860b90361ae9ba7431647` |
| 来源 CI | run `43178792316`（`c93bebd`）**success** |
| 构造脚本 | `build-m1/mk0090b.py`（复现：`python build-m1/mk0090b.py`） |

**用法（RAM-only，不刷任何分区）**：

`
fastboot boot build-m1/diag2/shim-boot-0090-stack64k.img
`

与 A/B 那两张屏摄用的是同一条链路、同一个 shim、同一份 ADT 形状
（dram-base 0x91600000 / 512 MiB），只有内核从 0089 换成 0090。

**已在二进制里逐符号验证（事实）**：从 ci-xnu8 内核符号表读出
`_intstack 0xfffffe00080b0000` / `_intstack_top 0xfffffe00080c0000`，
`INTSTACK size = 65536`、`EXCEPSTACK size = 65536`，
即 **16 KiB → 64 KiB 确实生效**（0089 同一符号是 16384）。
`__BOOTDATA` vmsize 从 `0x4c000` 变 `0x64000`，正好 +0x18000 = 98304，
与按 `data.s` 布局手算的增量一致；各段 gap 全为 0。

**下一轮读屏标准**：最后一行左下角固定位置会出现 `stkXXXX`
（`剩余启动栈字节 ÷ 18` 的 4 位十六进制）：`stk0e38`=64 KiB 全空、
`stk071c`=剩 32 KiB、`stk0024`=只剩 0.6 KiB。

1. **标记 13（`pmap_bootstrap done`）出现** ⇒ M1 通过，可以进 M2。
2. **仪表在某个标记处明显跳水** ⇒ 该标记之后的调用链是栈消耗大户。
3. **仪表一路很高但仍 panic** ⇒ 成因判断错了，此时屏上有
   `el0/ibase/itop/free` 整行可直接对账，不用猜。

无论哪种，**这次都不要再改 ADT**：A/B 已证明 ADT 形状不是变量。

**唯一变量保证（事实）**：新镜像与已上机跑过的 A 臂用的是**逐字节相同的 shim**。
把两个镜像的 kernel blob 解压后比对：偏移 32 之后的部分与 `build-m1/shim-Image-CI.bin`
的 32 之后部分**完全相同**，只有 arm64 Image 头的 `text_offset`(8..10) 与
`image_size`(16..18) 六个字节不同 —— 那正是 `pack-ugg.py` 故意改写的（声明
shim+payload 的总长）。所以本轮唯一变量就是内核：0089 → 0090。

本次重跑 `python build-m1/mk0090b.py` 得到的 sha256 与首次完全一致（确定性构建）。

## 6. 0090 真机结果与 0091（2026-11-12 晚，最新）

### 0090 的结果：旧故障消失，但诊断代码自己炸成了风暴

用户 `fastboot boot` 了 0090 镜像，屏上不再是上次那条 `esr 9600004f`，而是**几百块**同一结构：

`
SWEET FAULT sync
  pc 000000000743a160  lr 000000000743a148
  sp 0000000007b64120  esr 02000000
 istack:                 <- 永远停在这里
SWEET FAULT sync          <- 立刻下一条
`

**结论：0090 的栈扩容生效了（旧的 permission fault 不再出现），但新加的仪表代码在故障路径上又触发异常，形成重入死循环。**
三条独立证据指向同一结论：

1. 符号还原：`pc` = `_sweet_early_fault + 0x140`，`lr` = `+0x128` —— 故障发生在**打印函数自己内部**。
2. `pc` 那条指令是 `mrs x10, ...`，即读 `SP_EL0`，只有 `sweet_early_sp_el0()` 会这么干。
3. 每一块都停在 `istack:` 之后 —— 那正是调用 `sweet_early_stackinfo()` 之前的最后一句。

`sp` 每次下移约 **1216 字节**（= 848 的 ARM_CONTEXT + 368 的分发开销），说明每轮都往同一个栈再压一个 frame。
`esr 0x02000000` 的 EC = 0（unknown reason），与「异常处理机制已在半途又取异常」自洽。

### 仪表为什么没显示

仪表画在文本第 38 行，而滚动文字也用第 38 行，最后一行 `istack:` 每次都把它覆盖。
**这不是用户没找到，是设计 bug。**

另外屏摄暴露一个问题：**左边第一列被边框切掉了**，几行开头的 `00000` 显示成 `30000`，数值最高位不可信。

### 0091 改了什么（只动早期控制台，不碰内核逻辑）

| 改动 | 原因 |
|---|---|
| 预留第 38 行给仪表，滚动文本只用前 38 行（`EARLY_TEXT_ROWS`） | 文字再也覆盖不到读数 |
| 仪表**总是**绘制，SP 不在启动栈时画 `????` | 空白仪表与「没跑过」无法区分，白费一轮 |
| `sweet_early_fault()` 不再调 `_doprnt`、不再读 `SP_EL0`、只报一次 | 这是死循环的根因 |
| 加 `EARLY_LEFT_MARGIN`，首列留空；折行宽度跟着调整 | 数值最高位被边框切掉，地址有歧义 |

| 项 | 值 |
|---|---|
| commit | `eac43c7` |
| CI run | `43218229183` **success** |
| 校验 | 0090→0091 顺序应用逐字节复现工作文件；0091 单独可应用到 0090 之后；均不可重复应用 |
## Previous: 2026-11-07 及更早

### >>> U1 已在真机通过（700bfa6 镜像，用户实拍红屏报告）<<<

**读这里：U1 验收项全部通过，屏幕驱动正常，下一步 = U2（XNU 板级 + GICv2 驱动 + 跳转）。**
逐行读数（对照 shim.c 打印代码）：

| 屏上值 | 解读 |
|---|---|
| `DTB at=0x134000000 magic=0xd00dfeed` | **LK 把选中的 DTB 放 x0 传给内核入口——确认**。风险清单里那条"未验证"关闭。注意 DTB 在 0x134000000（bank2 高段），不在 bank1 |
| `LOAD 0x10081C10` | 解压加载 0x10080000（+页对齐偏移），与 TWRP /proc/iomem 观测一致 |
| `INITRD lo=0x13600000 hi=0x13600062` | **ugg 的 LK 会传 ramdisk 并写 chosen/linux,initrd-***（98 字节空 cpio）——与 ugglite 的 LK 行为不同。payload 仍用"追加进 Image"方案（fastboot boot 路径下不可依赖），但这条给了第二条可选通道 |
| `LOADER no SWEETXNU payload` | 预期内（还没放 XNU 载荷） |
| `CPU midr=0x410FD034` | Cortex-A53 r0p4 ×8；`mmfr0=0x1122`：**TGran16=0**（4K/64K only），64K=1、4K=1、PA=40bit（parange=2）。PAGE_RATIO(16K VM/4K hw) 路线确认 |
| `TIME frq=0x124F800 ok≠0` | 19.2MHz；**CNTCR.EN 修复生效**，CNTPCT 正常前进 |
| `PSCI ver=0x10000` | PSCI 0.1?——**读数注意**：值 = 0x00010000 = 主 0 次 1？打印把 (maj<<16\|min) 编码，实际是 **PSCI 1.0**（maj=0,min=1? 待复核；smccc 被屏幕黑斑遮挡。不影响 SMP 实测通过） |
| `GICD iidr=0x1070 typer=0x4EA` | ARM 0x43b GIC-400；ITLinesNumber=0x1A → **11 组 = 352 INTID**；LSPI=0（无 LPI，纯 GICv2） |
| `GICC iidr=0x20070 ctlr=1` | LK 已开 GICC（EnableGrp1=1） |
| `GICDCTL was=1 now=1` / `GICCCTL was=1 now=1` | NS 侧 Group1 使能成功（TZ 占 Group0，符合预期） |
| `IGROUP ppi=0 sgi=0` | 我们测的 SGI/PPI 全在 Group0（TZ 的），NS 视图下走 qgic2 的 Group1 使能路径即可投递 |
| `ISET was=0xFF now=0x1800FF` | INTID 19/20 使能成功 |
| `VTIMER n=30 other=0 last=0x14` | **CNTV = INTID 20 = 0x14，300ms 内 30 次中断**——核心验收通过 |
| `pre pend=0xA1500000 hppi=0xF0` | 采样窗口内 pending 含 19/20/28/31；hppi=240（spurious 界内）正常 |
| `PTIMER n=30 last=0x13` | CNTP = INTID 19 也通 |
| `SGI1 n=11 other=0` | SGI 自发自收 11/11 |
| `SMP0 on=0xF rc=0` | 核 0–3 CPU_ON 全 rc=0 全上线 |
| `SMP1 on=0xE rc=1` | 核 5–7 上线；rc 字节 1 = boot CPU 在索引 4（0x100）故 `on` 位 4 缺。**8 核全部上线**（boot 核 + 7 从核）。注意 boot CPU 落在簇 1（0x100），XNU 侧不能假设 boot 核是 CPU 0 |

**红底 = shim 完成态底色（con_clear 红色），不是 panic**。屏右上/中部的黑斑是屏幕物理坏点，不是渲染问题。

**U1 遗留（不阻塞 U2）**：PSCI 版本读数需复核打印编码；`INITRD` 通道留作后备。

### U2 补丁系列（2026-11-07，进行中）

xnu 侧开始做 UGG 板级。所有新补丁都在本地 xnu-8796.141.3 树上逐条验证「从干净源码应用
0001..N 全部补丁」，再 `git add -f` 进 `xnu/patches/`（`.gitignore` 忽略 `*.patch`，
必须 `-f`）。工作树副本在 `E:\ios-ugg\xnu-src`（**不入 git**，本地验证用）。

| 补丁 | 内容 | 状态 |
|---|---|---|
| （Phase A） | 81 个旧补丁的 `ARM64_BOARD_CONFIG_SWEET` 守卫 → 家族宏 `SWEET_FAMILY`（自动生成的 `tools/family-rename.py`，可重复执行）；0004 的 arm64e 导出闸门改为 `ifeq ($(filter $(CURRENT_MACHINE_CONFIG),SWEET UGG),)`；builtin pthread/bearssl/hfs 的 `Makefile.template` 闸门与 3 个 `stage-*.sh` 放行 `UGG` | ✅ `0e4e765` |
| 0082 | `UGG.h`（4K 粒度、GICv2、CNTV INTID 20、8×A53、`SWEET_SMP_MAX_CPUS 8`）、`board_config.h` 家族宏 + UGG 段、`MakeInc.def` 注册 `UGG` 与 `-mcpu=cortex-a53`（A53 无 LSE，`-march=armv8-a` 不够）、`config/MASTER.arm64.ugg`（**缺它 doconf 会静默丢掉 `nos_arm_asm`**，全内核汇编不编译 → 几百个未定义符号）、4K commpage 断言改用 iPhoneOS 的 `0x0fc0000000`、`commpage_asm.s` 两处 `casa` → LL/SC | ✅ `d813cf3` |
| 0083 | GICv2 驱动：从 DT `/arm-io/gic` 映射 GICD/GICC，ack/EOI 走 CPU 接口 MMIO，SGI 走 `GICD_SGIR`（**目标位用逻辑 CPU 号**：8937 的 8 个 CPU 接口按 DT 顺序而非 MPIDR）；`sweet_vtimer_intid` 移出 `HAS_GIC_V3` 块；`sleh_irq` 两块板共用访问器；宏名统一 `UGG_GIC_V2`（修掉 ugglite 0083 的 `SWEET_GIC_V2` 残留） | ✅ `d813cf3` |
| 0084 | `start.s` 两处 `msr OSLAR_EL1` 加 `#if !defined(SWEET)`（Apple 专属寄存器，A53 上 UNDEFINED → 第一条指令同步异常，即「JUMP 后黑屏」元凶） | ✅ `eb6f4ba` |
| 0085 | 早期控制台 24bpp：新增 `osfmk/arm64/ugg_early_board.h`（板级几何），`sweet_early.c`/`pe_serial.c` fbcon 改按字节寻址 + 每像素字节数（32 位写覆盖相邻像素 = 花屏雪花）；**顺带修一个真 bug**：marker 原来按 `stage*48` 铺开，720 宽屏上 stage>14 全跑到屏外（arm_init 用到 20），改成 17px 竖条、最多 40 段 | ✅ `0f85b1d` |
| 0086 | 4K 页几何（1/3）`proc_reg.h`：UGG 下 `T0SZ_BOOT=T1SZ_BOOT=16`（48 位 VA）、`ARM_TT_ROOT_*` 改指 L0 并新增 `ARM_TT_ROOT_LEVEL`、新增 `L0_TABLE_INDEX`/`L1_TABLE_VA` 辅助宏 | ✅ `908dd07` |
| 0087 | 4K 页几何（2/3）`start.s`：新增 `create_l0_table_entry` + `ugg_mark_bar` 宏；引导页表从 4 页扩到 8 页（V=P L0/L1、KVA L0/L1、L2 跟随）；`TTBR1=x25+2*PGBYTES`；帧缓冲按 2×2MiB Normal-NC 块映射到 0x90000000；预 C 三档 24bpp marker（白/品红/黄，x=600+17n） | ✅ `908dd07` |
| 0088 | 4K 页几何（3/3）`arm_vm_init.c`：新增 `arm_kva_to_l2_table()`（按 `ARM_TT_ROOT_LEVEL` 决定下降几级）；`arm_kva_to_tte`/`init_ptpages`（含为 L0 根补分配 L2）/两处 `va_l1` 循环全部改走 `ARM_TT_ROOT_*`；帧缓冲内核别名按整屏块数映射（1 块 2MiB 只到第 971 行，底部 marker 带会缺页 → 挂死） | ✅ `908dd07` |

**验证状态（2026-11-08）**：从干净 `xnu-8796.141.3` 一次性应用 **0001–0088 共 88 个补丁 = 86/88 干净通过**，
且 `git add -A` 后与自建树的 diff **完全为空**（即补丁链能逐字节重建工作树）。唯二失败的 0031/0041 是 hfs
补丁，依赖 CI 上 `0026-stage-hfs.sh` 摆放的 `bsd/sweet_hfs`（本地无法下载 hfs 源码），在 CI 上正常。

**关键决策：必须 4K 硬件粒度**。A53 实测 `ID_AA64MMFR0_EL1=0x1122`（TGran16 字段 = 0，不支持 16K 粒度），
而 iOS 16 用户态是 16K 页。xnu 的 `PAGE_RATIO` 机制（4K 硬件页 + `PAGE_SHIFT_CONST=14` → PAGE_RATIO=4）
给用户态 16K VM 页，这正是 A7/A8 的排布，也是 ugglite 走通的路。`proc_reg.h` 里 4K + `SUBPAGE_L1` 的
`T0SZ_BOOT=26`，但 start.s 的 L0 索引宏按 9 位（bits 47:39）建表，26 只有 38 位 VA → 索引对不上；
ugglite 的解法是 `T0SZ=T1SZ=16`，我们用同一结论。**注意 CI 构建用 `MACHINE_CONFIG=UGG` 默认值。**

**参照项目最新状态**（2026-11-08 复查）：ios-sweet 上游 `45263be`、ios-ugglite `48d7f9b` 均无新提交。

### >>> 2026-11-08 的重要新事实（读这里）<<<

**1. CI 终于跑通（第一块硬骨头不是代码，是 runner）。**
`macos-14` 对本账号不可用：GitHub 把它解析成 arm64 镜像 `macos-14-arm64-us-default`，
任务在创建后 1 秒内被 cancelled、runner 都没分到（`run_number 1` 那个 xnu 全是 cancelled）。
探测矩阵结论：`macos-13` 已退役（排队永不分配）、`macos-15` 是 arm64（官方提示排队慢）、
**`macos-15-intel` 可用**（x86_64）。代价：该镜像只有 Xcode 16.x/26.x（无上游要求的 15.x），
但**实测 iig 的 IORPC ABI 差异没有爆**，直接编过。`runs-on` 已改 `macos-15-intel`。

**2. 公开 fork 的 Action 日志/artifact 需仓库管理权限，匿名读不到。**
所以 workflow 里加了两步「把诊断写成 check annotation」——annotation 是匿名可读的。
每轮构建会汇报：补丁应用数、我们自己的补丁被跳过（=错误）、编译错误行、产物清单、
kernel 的 sha256、内核里出现的机器配置符号。**这是我能自己闭环迭代的关键**，不需要用户贴日志。
（注意：这两步必须在 `Collect` 之后，否则 `out/` 还不存在。）

**3. 第一次 UGG 内核构建成功（run #3 / `4c167e3`，18m48s，`applied=89 skipped=4`）。**
跳过的 4 个都是 darwin-xnu-build 自带的、给别的 macOS 版本用的补丁（上游同样跳过），**我们的 85 个全应用**。
产物 `xnu-kernel` 58.9MB，用户已下载并解压到 `E:\ios-ugg\xnu-kernel`。本机静态核对：

| 检查 | 结果 |
|---|---|
| 文件名 | **`kernel.development.ugg`** ← 机器配置后缀，证明 `MACHINE_CONFIG=UGG` 生效 |
| SHA256 | 本机重算 = CI 的 `SHA256SUMS` ✅ |
| Mach-O | arm64、`cpusubtype=0`（纯 arm64，非 arm64e）✅ |
| 链接地址 | `__TEXT` vmaddr = `0xfffffe0007004000` = 内核链接地址（印证 T1SZ 必须覆盖它）|
| UGG 专有符号 | `_sweet_gic_ack/_eoi/_send_sgi`、`_sweet_early_mark/_panic/_relocate`、`_sweet_fbcon_serial_functions`、`SweetCPU` 全部在，没被 dead-strip ✅ |
| `TCR_EL1` 立即数 | 从 `_sysreg_restore` 偏移 0 读出 `0x00000022a51a251a` → T0SZ=26 T1SZ=26 TG0=0 TG1=2 IPS=2（旧的 4K/38 位几何；0086 后应变成 `...a5102510`，即 16/16）|

**这条「读二进制静态验证」的手法值得沿用**（ugglite 用过 `sysreg_restore.tcr_el1`；
我用 python 解析 Mach-O nlist + `capstone` 反汇编，都在本地、不需要跑）。

**4. 残留风险：内核里还有 37 条 LSE 原子指令（A53 上 UNDEFINED）。**
反汇编 `__TEXT`/`__TEXT_EXEC`（243 万条指令）统计，除 37 条外 `-mcpu=cortex-a53` 都生效了
（`_lck_grp_reference` 现在是 `ldxr/add/stxr` 循环 ✅）。这 37 条集中在
`firehose_buffer_*` / `__firehose_merge_updates`（os_log 的环形缓冲）。来源**不是** xnu 源码，
是 `libfirehose_kernel.a`——由 darwin-xnu-build 从 apple-oss-distributions/libdispatch 现场编的，
而 workflow 的 sed 给它加了 `arm64` 架构后，它的 `-mkernel` 默认目标仍让编译器发了 LSE。
ugglite 也遇到同样问题，但误以为「闭源对象不能重编」而放弃；**实际是开源的，可以修**
（在该库的 `xcconfig` 的 `OTHER_CFLAGS` 前面插 `-mcpu=cortex-a53`，且只建 arm64 架构）。
它不在启动关键路径（ugglite 走到 `arm_vm_init` 都没碰到），但 `os_log` 一被用到就会炸。**待办。**

**5. ugglite 的 NOTES 是一份珍贵踩坑记录，我们直接受益于它的结论。**
它已经用同一条路线（同 mi8937、splash 同在 0x90000000、面板 720×1280/24bpp/stride 2160 完全一致）
在真机上跑到 `arm_vm_init`，记录并经硬件验证的三个致命点，正好是我们的 0086-0088：
① `T0SZ/T1SZ` 必须 =16（软件页表固定 9 位 L0 索引，23 会让硬件只用 2 位 → 首次取指 L0 fault）；
② start.s 的 marker 循环曾用 `w14` 当临时寄存器，**踩掉了 KVA 游标 x14**，导致内核链接区间没建映射
（我们的 `ugg_mark_bar` 只用 x0-x6，并且明确不放在两次 `create_bootstrap_mapping` 之间）；
③ 帧缓冲内核别名只映射 1 个 2MiB 块 → 只到第 971 行，底部 marker 带缺页 → 挂死（我们 0088 按整屏块数）。
另外它记录了 **dram base 必须 2MiB 对齐**（start.s 用 `ARM_TTE_BLOCK_L2_MASK` 掩码，未对齐会被静默取整）；
它给内核只喂 **554 MiB**（而非全部 RAM），因为 `BOOTSTRAP_TABLE_SIZE` 只有 8 页。
→ **我们的 ADT 计划：dram-base `0x91600000`（2MiB 对齐、在 splash carve-out 之上）+ 512 MiB。**

**6. run #4 的失败与修复（2026-11-08，0087 汇编错误 → 已修，`8be6da3`）。**
0086-0088 三补丁全部干净应用（`applied=92 skipped=4`，92 = 上次 89 + 新增 3；跳过的 4 个仍是
上游自带、给别的 macOS 版本的外来补丁，与 run #3 一致），但 `osfmk/arm64/start.s` 汇编报 12 条错，
`start.o` 挂 → bootstrap 中断 → `out/` 无 kernel（注解 `kernel-missing` / `SHA256SUMS 0` 是结果不是原因）。

12 条 = 3 组 × 4 条，正好对应我新加的三处 `ugg_mark_bar` 调用（x=600/617/634）→ **整次失败由这一个宏造成，
与页表几何方案无关**。根因（已读源码确认）：

- **宏声明了形参 `xoff, colour` 却用 `$0/$1` 位置引用。** 本树约定：位置引用只用于**无参数表**的宏；
  一旦有形参名就必须用 `\name`（`cswitch.s` 的 `\cpudatap`、`machine_routines_asm.s` 的 `\end_addr` 是 `\` 风格）。
  同文件 `create_l0_table_entry` 就是「无参表 + `$0..$5`」，本次构建中被调用两次且零报错 —— **这是该约定的现成反证**。
  于是 `$0/$1` 未替换，字面量进了指令：`add x0, x0, $0` → `expected compatible register, symbol or integer in range [0, 4095]`；
  `MOV32 w1, $1` 展开后立即数表达式含未定义符号 → `immediate must be an integer in range [0, 65535]`。
- **顺带查出第二个独立缺陷**：`add x0, x0, $0, lsl #1` 本身也非法 —— AArch64 的 ADD(立即数) 只允许 `lsl #0/#12`，
  没有 `lsl #1`。原意是 `x0 += 3*xoff`，改为一条常量加法 `add x0, x0, #(3 * $0)`。

修法：去掉宏参数表、保留 `$0/$1`（与 `create_l0_table_entry` 对齐），并同步修正因减少一行而偏移的后续 hunk 头。
洁净室复验：从纯净 tag `xnu-8796.141.3` 起应用全链，**86/88 干净通过**（仅 0031/0041 两个 hfs 相关的已知失败），
补丁为规范 diff、无 CRLF。**注意：本次在 start.o 中断，0086(proc_reg.h) 与 0088(arm_vm_init.c) 的 C 代码还没轮到编译，
下一次绿了才是它们的首次编译验证。**

**7. M1（内核上机）进展：shim/tools/ADT 已按最简方案做完，只差一次 shim 产物下载。**
目标：让内核在真机上跑起来（U2 的第一步）。做法是**直接抄 uglite 的 U2 shim**（它已在同家族真机跑到
`arm_vm_init`），来源 `E:\ios-ugg\ugglite\shim\`，加一个 `BOARD_UGG` 分支。

**决定性事实（uglite 实测，直接沿用）**：这条 LK **不把 payload 放到 boot header 的 ramdisk_addr**，
也不在 `/chosen` 报 initrd。它可靠地解压 kernel 并连续落盘，所以 payload 必须**追加在未压缩 Image 之后**，
shim 从自己 `_end` 往高地址按 16K 步长扫 magic（`loader.c: sweet_payload_addr()`）。
另：**DTB bundle 必需**（raw Image → `dtb not found` 或死挂），LK 按 `qcom,msm-id/qcom,board-id`
选一个 DTB 放进 x0；U1 已确认 LK 把 DTB 传进来了。

已改完（commit `0d3a711` + `2a10fb7`）：
- `shim/board.h`（新，抄 uglite）：`BOARD_UGG` 分支，常量取自 **ugg 真机 DT**（`device-dumps/dt`，
  "MSM8940-PMI8937 MTP"）：GICv2 `qcom,msm-qgic2` GICD 0xb000000/GICC 0xb002000、splash
  0x90000000+0x1400000（720x1280 RGB888，2160 字节/行）、CNTV INTID 20、PSHOLD 0x4ab000、
  IMEM restart_reason 0x860065c。
- `shim/{shim.c,loader.c,mmu.c,fdt.c,console.*,probe.c,ufs.c}`：抄 uglite；`loader.c`/`mmu.c` 的
  `BOARD_UGGLITE` 条件扩为 `|| defined(BOARD_UGG)`；`BOOT_PAGE=4K`、`v_depth=FB_BPP*8=24`。
- `shim/build.sh`：改为只产 `shim/out/Image`（CI 用交叉编译器编，产物 196608 字节）。
- `tools/mkpayload.py`：抄 uglite 的 `adt_page_and_block()`——GICv2 板 = 4K 页/2MB L2 块，
  GICv3 = 16K/32MB；`virt_base` 原硬编码 32MB 对齐是 ugg 上的**真错**（应 2MB）。
- `tools/mkadt.py`：新增 `--ugg`（GICv2 节点、8 核真实 MPIDR 0x0-3/0x100-103、boot 核 **0x100 = running**、
  `dram-base 0x91600000 + 512MiB`、24bpp fbcon 720x1280 stride 2160、无 pram/无 UFS）。已逐字段核对。
- `tools/pack-ugg.py`：新增 `--payload`（payload 追加到 Image、16K 对齐、写 arm64 头的
  `text_offset`(off 8) 与 `image_size`(off 16)）；`--ramdisk` 可选。
- `tools/mkuggboot.py`（新）：本地一条命令组装最终 boot image（shim + payload + gzip + DTB bundle + v0 头）。
- `.github/workflows/shim-ugg.yml`：只编译 shim + 校验 `out/Image`；编译错误写注解。

**本地已验证**（用假 shim 跑通组装链）：boot image 8.16MB（<768MB 限制）、v0/2048、
gzip 流后跟 DTB bundle、解压 16787936 = shim 196608 + payload 16591328、`image_size==text_offset==len`、
payload magic `SWEETXNU` 落在 0x30000。产物在 `E:\ios-ugg\build-m1\`（payload.bin / ugg.adt / 空 ramdisk）。

**卡点**：本机无 aarch64 编译器，shim 只能 CI 编；**产物下载需登录**（匿名 401），所以真 shim Image
要用户从网页下 `shim-ugg` artifact（10KB）。拿到后一条命令即出最终 `shim-boot.img`，然后 `fastboot boot`。

**M1 剩余**（上机后按实际挂点补）：A2 `SweetCPU.cpp` 的拓扑校验（`phys_id & 0xff != 0` 会 panic，
ugg 是双簇 Aff0=0-3；且它要求 boot phys_id==0，而 ugg boot 核是 0x100）；A4 若卡在 `arm_vm_init`
内部则加细分 early marker（uglite 在这一段卡过）。

### >>> 以下为 2026-11-01 的历史 handoff <<<

## Agent handoff / active work (2026-11-01)

### 已完成
- 实机只读探测完成（adb / fastboot / TWRP）：硬件事实全部固化在
  [docs/ugg/README.md](docs/ugg/README.md)，关键差异：GICv2（GICD 0x0B000000 / GICC 0x0B002000）、
  vtimer INTID 20、splash FB 0x90000000（20MB，720×1280）、8 核双簇 MPIDR、boot header v0、
  max-download-size 0x1ff00000、/proc/last_kmsg 可用。
- 81 个上游补丁逐个分诊完成：见 [docs/ugg/PATCH-TRIAGE.md](docs/ugg/PATCH-TRIAGE.md)。
  结论：52 直接复用 / 15 改造 / 4（UFS 组）RAM 阶段绕开 / 6 项全新编写。
- 本分支（ugg-port）建立，上游 remote 已加（dipa-studio/ios-sweet）。
- 实况设备树已从手机拉取并按大端解析（本地 device-dumps/dt/，不入 git）。

### 下一步（U1，shim 探测镜像）
1. `shim/console.h`：FB_BASE=0x90000000，FB_W=720，FB_H=1280，stride 2880。**已完成**
2. `shim/shim.c`：GICv3 探测段 → GICv2 探测（GICC/GICD 最小初始化 + vtimer INTID 20 + IAR 读取）；
   删除 ufs.c 探测调用；MPIDR 表 0x0-3/0x100-103；MMU 段仅在 TGran16 支持时才启用。**已完成**
3. `shim/build.sh`：改用 `tools/pack-ugg.py` 打 header v0（page 2048、kernel 0x80008000、
   ramdisk 0x81000000、tags 0x80000100），kernel 段 = gzip(shim) + 原厂 DT 捆绑包。**已完成**
4. 新增 `.github/workflows/shim-ugg.yml`：ubuntu runner 全量构建 + 布局自检 + artifact。**已完成**
5. 上机测试：`fastboot boot` 产物；成功标志 = vtimer 中断计数跳动 + 8 核 CPU_ON 全 rc=0。

### U1 新查明的打包事实（2026-11-01 实测）
- 本机是 **MSM8940**（SD435），实况 FDT model = `Qualcomm Technologies, Inc. MSM8940-PMI8937 MTP`。
- LK **不理会** boot header 里的加载地址：TWRP 的 `/proc/iomem` 显示解压后的内核在
  **0x10080000**（Kernel code 10080000-1179ffff / Kernel data 1184a000-11dccfff），
  ramdisk 在 **0x13600000**（`/proc/device-tree/chosen/linux,initrd-start`）。
  我们的 shim 因此运行在 0x10080000，和 0x90000000 的 splash FB 不冲突。
- boot.img＝header v0 + `Image.gz` **紧跟** 7 个 FDT（共 0x20DAB6 = 2,153,142 字节），
  7 个 DTB 首尾相接到 kernel_size 末尾：rolex / prada / **ugg(msm8940, 偏移 0x8EF57, 299,591B)** /
  riva / santoni / ugglite / land。无 dtb/dtbo 分区、无 QCDT 表；LK 扫/解压后按
  `qcom,msm-id`、`qcom,board-id` 选中并把 DTB 指针放 x0。
- 设备 RAM：0x10000000 起 1792MB + 0x80000000 起 2048MB（4GB）；reserved: modem 0x86800000、
  adsp 0x8D200000、wcnss 0x8E300000、splash 0x90000000(20MB)、venus 0x8F800000 等。
- IMEM restart_reason = **0x0860065C**（DT qcom,msm-imem@8600000 + 0x65c）；
  PSHOLD = **0x004AB000**（/proc/iomem 里 "pshold-base" 已确认）。
- splash FB 0x90000000、20MB；面板 `otm1901a_720p_video` = 720×1280，stride 2880。
- 原厂 gzip 内核 19.5MB → 解压 42.5MB，说明 LK 解压到固定地址而非原地。

### 待验证 / 风险
- **A53 的 16K 页粒度（已解，非阻塞）**：ugglite 真机实测 `ID_AA64MMFR0_EL1=0x1122`，
  TGran16=不支持（A53 只有 4K/64K；ugg 同为 A53，必然相同）。**但这不是阻塞**：
  xnu-8796 的 `PAGE_RATIO` 机制支持"VM 页 16K / 硬件页 4K"（`arm_init` 里 memSize>1GiB
  时取 PAGE_SHIFT_CONST=14，PAGE_RATIO=4，`TEST_PAGE_RATIO_4` 路径约 60 处）——
  正是 A7/A8 的排列，iOS 16 用户态要的 16K VM 页照给。UGG.h 不定义 `__ARM_16K_PG__`、
  `ARM_PGSHIFT=12` 即可。ugg 4GB>1GiB，同一分支成立。
- 8937 LK 是否真的把选好的 FDT 指针放 x0 传给内核入口——U1 第一屏打印 x0 与 magic 验证。
- LK 对“无 gzip”与“gzip+DT 捆绑包”两条路径的 DT 定位方式未公开；U1 按原厂结构复刻（gzip+7 DTB）。
- GICv2 与 TZ 的 Group 0/1 划分：qgic2 在 8937 上 TZ 占 Group 0，须实测确认
  （U1 打印 GICD_TYPER / IGROUPR / ISENABLER 前后值）。
- 4GB RAM + 16K 页：完整 iOS 根卷（3-4GB）放不进 RAM——U3 用裁剪根卷，完整根卷等 U6 eMMC 驱动。

### 本地资产（不入 git）
- 实机设备树 tar + 解包（device-dumps/dt/）、aboot.img、boot-head.bin。
- `device-dumps/boot-stock.img`（boot 分区 64MB 全量）、`msm8937-dtbundle.bin`（2.1MB DT 捆绑包）。
- `toolchain/`（xpack aarch64-none-elf-gcc，本地编译 shim 用）。
- 设备序列号 32da6a6b；TWRP root shell 可用。
- **注意：本地不编译**（用户明确要求，只走 GitHub Actions）；toolchain/ 已按用户要求删除，
  本地只做 artifact 下载 + `tools/pack-ugg.py` 打包（DT 捆绑包不入 git，不能在 CI 打）。

### 会话记录
- 2026-11-01：探测 + 分诊 + 本分支骨架（docs/ugg/*、NOTES-UGG.md、shim CI workflow）。
- 2026-11-01：U1 代码完成（GICv2/INTID20/SMP、720p 控制台、v0 打包器）；查清 LK 加载地址与
  DT 捆绑包结构，抽出 msm8937-dtbundle.bin；推送 e617e91，准备首次 `fastboot boot`。
- 2026-11-01：**首次上机（e09e93c 镜像）**：`fastboot boot` 成功（LK 装载后离开 fastboot，
  fastboot 设备消失），但屏幕白屏/花屏 + 底部隐约文字，3 分钟后**没有自动复位**，只能长按电源。
  结论：shim 已运行；显示格式假设错误；某步死循环。
- 2026-11-01：sweep（fd6ea51）上机：6 张候选全花屏，无自动复位。同日调研参照项目
  ios-ugglite（同家族 Note 5A/MSM8917，XNU 已到 arm_vm_init）：确认 splash =
  **24bpp RGB888 / stride 2160 / R,G,B / 0x90000000**（fb0 的 32bpp/2944 是 TWRP 重配，
  不是 LK splash）；LK 不传 ramdisk → payload 追加进未压缩 Image；还有 arm64e 反转、
  OSLAR_EL1、LSE、48 位 VA、SWEET_FAMILY 等 10 条 XNU 侧教训（详见上节）。
  console 切 24bpp、删 sweep、shim_main 直接跑 U1，推送 CI。

### 首次上机的结论与修正（2026-11-01 第二轮）
- 从 TWRP 读到真实 fb 参数：fb0 = `mdssfb_80000`，`virtual_size 720x2560`（双缓冲），
  **stride 2944**（MDP 按 128 字节对齐，2880→2944），**32bpp**，mode 720x1280p-60；fb1 = `mdssfb_a0000`。
  → `shim/console.h` 的 FB_STRIDE 已改为 2944，con_clear 按整 stride 填充。
- 怀疑死循环根因：**arch timer 计数器（CNTCR.EN）未被 bootloader 使能** → CNTPCT 不前进，
  `while (now() < t)` 永不退出。已加：启动时 `CNTCR.EN=1`（@0x0B120000，与 Linux 相同做法），
  所有等待改成带上限的 `wait_ticks()/delay_ms()` 回退（无计数器时用 spin_loop）。
  DT `timer@b120000/clock-frequency = 19200000`。
- 新增**不依赖屏幕的诊断通道**：IMEM 空闲区 `0x08600800` 写
  `0x00 magic "GUG1" / 0x04 seq / 0x08 stage id / 0x0c state(0运行 1完成 2异常)
   0x10..0x20 panic slot/esr/elr/far/spsr / 0x40.. result[0..31]`。
  跑完后在 TWRP 用 `dd if=/dev/mem skip=0x08600800` 读回（IMEM 不在 System RAM，应可读）。
- 下一步：CI 构建 52a51c0 → 下载 → 打包 → `fastboot boot` → 等 3 分钟（或长按电源）→
  TWRP 读 IMEM，得到 stage/结果，再决定是修 MMU 还是继续 GIC。

### 显示格式 sweep 的结论（2026-11-01 第三轮）+ 参照项目 ios-ugglite

**sweep 结果**：6 张候选（A 32bpp/2944 … E 24bpp/2160 … F 32bpp/2944）用户反馈"全是花屏，
有几张稍微好点但记不清哪张"。设备没有自动复位（需长按电源）。结论：不能再靠盲猜轮播。

**参照项目 [TheArchitectEngineer/ios-ugglite](https://github.com/TheArchitectEngineer/ios-ugglite)**
（已 clone 到本地 `E:\ios-ugg\ugglite`，295 commit = sweet 全部历史 + 最后约 40 个 ugglite 增量；
只作参考不照抄）。它是同一片 mi8937 家族的 Redmi Note 5A（MSM8917/SD425，4×A53，2GB），
**已把 XNU 跑到真机 `arm_vm_init`**（0088），领先我们一整段。它踩过的坑直接解答了我们的问题：

1. **显示（已解）**：mi8937 LK 的 splash **不是** fb0 的 32bpp/2944（那是 TWRP 用户态重配的），
   而是 **24bpp RGB888、stride 2160（720×3）、字节序 R,G,B、基址 splash_region 0x90000000**。
   它首次点亮的两个 bug 与我们完全同款：(a) 对 24bpp 缓冲做 32 位写 → "老电视雪花"花屏
   （实心填充走字节路径反而正常，所以更迷惑）；(b) 拿 fb0 几何当 splash 几何。
   画错 ±0x1000 子基址只让整帧平移 ~2 行（内容仍可读），**只有 bpp/stride 错才会剪切**。
   → 我们的 console 改为 24bpp/2160@0x90000000，sweep 删除，直接跑 U1。
2. **LK 不传 ramdisk**：ugglite 的 lk 既不写 `linux,initrd-*`，也不把 ramdisk 放 0x81000000。
   解决：**payload 直接追加在未压缩 Image 之后再 gzip**，LK 解压后紧邻 shim，shim 从
   `_end` 向后按对齐找 `SWEETXNU` magic（"SWEETXNU" 字符串也出现在 shim 里，须同时校验
   version/nsegs）。boot_args 对齐改为按板 4K/16K（`BOOT_PAGE`）。
   （我们 ugg 的 TWRP /chosen 里有 initrd 属性，但 fastboot boot 路径不可信，同样方案。）
3. **启动头**：同为 header v0 / page 2048 / Image.gz-dtb（gzip 流后面跟 DTB）。
   raw Image → `dtb not found` 或死挂；DTB 放 boot 段外 → 同样失败。
4. **arm64e 反转 bug（上游 sweet 也中招）**：上游补丁 0004 的 `ifneq` 条件写反，
   SWEET/UGGLITE 反而构建成 arm64e → 一堆 PAC/JOP 错误。必须改成 `ifeq`。
   我们的 fork 继承了同一个 0004，**接 XNU 时必须先修它**。
5. **OSLAR_EL1 是 Apple 专属寄存器**：`start_first_cpu` 开头 `msr OSLAR_EL1, xzr`
   在 A53 上 UNDEFINED → XNU 第一条指令就同步异常，"JUMP 后黑屏"的唯一元凶。
   两处（reset_vector、start_first_cpu）都要 `#if` 掉非 Apple 板。
6. **LSE 原子指令**：`-march=armv8-a` 不够，Apple clang 的 `__c11_atomic_*` 仍发射
   `ldadd/casal`；A53 是 ARMv8.0 没有 LSE。要 **`-mcpu=cortex-a53`**，commpage_asm.s 里
   两条 `casa` 换成 LL/SC。闭源对象（_firehose_*、K256）里残留 12 条 LSE 是后患。
7. **48 位 VA**：start.s 引导页表按 L0 索引 9 位（bits 47:39）建，但 T0SZ/T1SZ=23 只有
   41 位 VA → 索引对不上，MMU 一开就飞。**T0SZ=T1SZ=16（48 位）**。
   phys_base 必须 2MiB 对齐（start.s 按 2MiB block 掩码）。
8. **GICv2 内核驱动**：`pe_init_fiq()` 的非 GICv3 分支在 xnu 里是空壳 → 新写
   `#elif defined(SWEET_GIC_V2)`（GICD/GICC 两个 MMIO 帧、Group1 使能、PMR/BPR/CTLR、
   vtimer PPI 电平触发）；`sleh_irq` 改走 `sweet_gic_ack/eoi`；IPI 走 GICD_SGIR(0xf00)
   而非 ICC_SGI1R_EL1（0083）；`sweet_vtimer_intid` 要移出 `#if HAS_GIC_V3`。
9. **板级配置的十大构建坑**（10 次 CI 才过）：MASTER.arm64.ugglite 必须存在且与 sweet 的
   同步（0008 要同时改两份）、4K commpage static_assert 要对 iPhoneOS 的
   MACH_VM_MAX_ADDRESS、39 处 `#if defined(ARM64_BOARD_CONFIG_SWEET)` 改成 **`SWEET_FAMILY`
   且必须经 `-D` 编译旗标传递**（头文件宏 20+ 文件根本没 include board_config.h，编译成空壳）、
   三个 staging 脚本 `== SWEET` 要放宽、ifneq/ifeq 方向陷阱。
10. **他们的路线图对我们直接适用**：U2 = UGG.h + GICv2 驱动 + mkadt-ugg；存储是 eMMC/SDHCI
    （sweet 的 UFS 补丁 0028/0030/0034/0069 不适用，要新写 SDHCI）；USB 是 DWC3+
    qcom wrapper（0072-0077 可参考）；触屏 FT5x06@0x38 / GT911@0x5d 在 BLSP1 I2C3（ugg 以
    device-dumps/dt 为准）；设备身份用 iPhone 8（D20AP，750x1334）比 iPhone X 更贴 720p。
    遗留：arm_vm_init 内挂起（0089-0091 加了更细的 marker 和 L0 root walk，未公开结果）。

**对 U1 的改动**：console 固定 24bpp/2160@0x90000000（先一张黑底确认屏 8s，再进 U1 探测，
屏上保留 3 分钟），`shim_main` 直接调 `u1_probe`，删除 sweep。


## 8. M1 真机结果（2026-11-08）：屏通，内核卡在 pmap_bootstrap

**实机 `fastboot boot shim-boot-m1.img`（7,984 KB，Sending/Booting 均 OKAY，非破坏性）。**

- **成功**：shim 的 framebuffer 控制台起来了，屏上出现 `SWEET EARLY 9/10/11/12` 和底部彩色
  标记条 —— 显示链路和早期控制台**完全打通**。这比 uglite 公开的真机结果（只到 stage 7
  entering arm_vm_init）更靠前。
- **卡点**：标记 12 之后的 13（pmap_bootstrap done）不再出现，随后 panic
  `Invalid kernel stack pointer (probable corruption)`。寄存器 `pc` 落在
  `_get_threadtask_early`、`lr` 落在 `_sleh_synchronous+0xbc`、`esr=0x9600004f`
  （EL1 data abort），说明**真正的第一条异常发生在 pmap_bootstrap 内**，而异常处理函数
  自己的 prologue（task_vtimer_check -> current_thread -> get_threadtask_early）在早期
  启动栈上又踩了一脚，把病因掩盖成了误导性的「栈指针非法」。
- **本轮未触发的老坑**：GICv2 / OSLAR / LSE / 48 位 VA 全部走过；SweetCPU 的拓扑校验也
  没炸（boot 核 MPIDR 0x100 未触发 phys_id 检查 —— 条件是否编译进去待查）。
- **符号化工具**：本轮新增 `tools/symlook.py`（解析 Mach-O 符号表，把 panic 里的
  pc/lr 还原成函数名）。实测 pc=0xfffffe00073475c0 -> _get_threadtask_early、
  lr=0xfffffe000743dc5c -> _sleh_synchronous+0xbc。

### 0089 诊断补丁（xnu/patches/0089-ugg-early-fault-report.patch）

目的：在**第一条**同步异常进入 SLEH 时就把它打出来，不再被后续误报掩盖。

1. osfmk/arm64/sweet_early.c/.h：新增 `sweet_early_fault(tag, pc, lr, sp, esr, far)`，
   经 _doprnt 直接画到早期 framebuffer 控制台；并让 `sweet_early_putc` 处理 `\t`
   （panic 的寄存器 dump 用 tab 对齐，之前 tab 被当字形画出来，整行错位 —— 这正是首张
   实机 panic 照片看起来乱序的原因）。
2. osfmk/arm64/sleh.c：`sleh_synchronous` 在 task_vtimer_check **之前**调用上报器；
   `sleh_invalid_stack` 在 panic 之前也调用（tag 分别是 sync / badstack）。两个入口都
   只依赖异常帧，不需要线程状态。

补丁已用 `patch -p1 --dry-run` 和 `git apply --check` 验证，可在 0001-0088 之后的树上
干净应用。下一轮：CI 出内核 -> 本地 mkuggboot.py 重拼 -> 用户刷机拍屏，读屏上
`SWEET FAULT sync ... pc ... esr ... far ...` 即可把真实故障定位到 pmap_bootstrap 的具体行。

### M2 路线结论

- **纯 RAM（rd=md0）**：补丁链里 0021/0022/0024 的 mockfs/RAMDisk 根已具备，
  mkpayload.py --ramdisk 也已移植，**不需要新内核代码**；限制是 4GB RAM 装不下 4.7GB 的
  完整 iOS rootfs，只能跑裁剪版（够把 launchd/dyld 拉起来）。
- **eMMC（sdhci@7824900）**：全新驱动（SDHCI core + ADMA2 + GCC 时钟 + pinctrl/regulator），
  树里无同类可抄（sweet 只有 UFS），难度高一个量级；好处是能放完整 rootfs。
- **决定：M2 先走 RAM**，eMMC 留到需要完整系统时再做。
