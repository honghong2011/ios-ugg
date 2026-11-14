# UGG × MIDO 移植计划与执行记录（2026-11-14 夜）

> **路线切换**：推翻 UGG 自研 `0082-0098`，改为照抄 `tarodib/ios-mido` 分支 `mido`（HEAD `d0e4cd1`）。
> **目标**：进入 iOS 桌面 + 触屏可用。GPU 合成 / 零拷贝显示明确跳过。存储 = eMMC。
> **CI**：`MACHINE_CONFIG=SWEET`（不是 UGG），板级差异全部走 `-DUGG_*` 编译宏 —— 与 mido 完全同构。

---

## 0. 三条已核实的关键事实

### 0.1 mido 的补丁链 = 上游原版 + 一个补丁

| 检查 | 结果 |
|---|---|
| `ios-sweet/xnu/patches` vs `mido-src/xnu/patches` 的 `0001-0081` | `same=84 diff=0`（**逐字节完全相同**） |
| mido 新增补丁 | 只有 `0100-mido-board.patch`（3730 行 / 31 文件 / +2889 −22） |

⇒ mido 的全部板级改动**集中在一个补丁**，这正是我们该照抄的形态。

### 0.2 我们旧路的病根已确定

`ugg/xnu/patches` 里 41 个 `0001-0081` 补丁被改成了 `SWEET_FAMILY` 版本（原版是 `ARM64_BOARD_CONFIG_SWEET`），且 `0082-0098` 是自己从零摸 pmap。这导致：
- 基线无法与上游对齐（`patch` 只应用一部分，产生假 hunk）；
- 卡在 `SWEET FAULT esr 0x9600004f`，永远到不了 `pmap_bootstrap done`。

### 0.3 干净基线已重建成功（今晚完成）

`
xnu-src  重置到 xnu-8796.141.3
  + 跑 3 个 staging 脚本（libpthread / BearSSL / HFS）
  + 按序 apply 0001-0081
=> applied=81  failed=0

再对 mido 的 0100 做 git apply --check：
=> 31 files, +2889/-22, 零冲突, 全部 Checking patch 通过
`

**这是本轮最重要的验证**：说明 mido 的改动可以完整落到我们的树上。

---

## 1. UGG 硬件常量（全部来自本机 DTB，非推测）

`
SoC            MSM8940 (Snapdragon 435), 8x Cortex-A53, ARMv8.0
               model = "Qualcomm Technologies, Inc. MSM8940-PMI8937 MTP"
               compatible = qcom,msm8940-mtp
CPU MPIDR      0x000-0x003, 0x100-0x103   (与 mido 同型, Aff1:Aff0)
Timer          arch_timer 19.2 MHz (0x124f800), virt timer INTID 20
GIC            GICD 0x0b000000, GICC 0x0b002000  (qcom,msm-qgic2, GICv2)
RAM            bank1 0x10000000+0x70000000, bank2 0x80000000+0x80000000
  最后占用       splash 0x90000000+0x1400000 (20 MiB)
  -> XNU 用     phys_base 0xA0000000, size 0x60000000 (1.5 GiB, 与 mido 同策略)
Framebuffer    splash 0x90000000, 720x1280
eMMC           sdhci@7824900: hc 0x7824900+0x500, core 0x7824000+0x800,
               cmdq 0x7824e00+0x200, IRQ SPI 123 (hc) / 138 (pwr)
               bus-width 8, HS400/HS200/DDR 支持, nonremovable
SD (留着不用)  sdhci@7864900: hc 0x7864900, IRQ SPI 1/2, bus-width 4, cd-gpios 67
GCC            0x01800000
TLMM           0x01000000
PMIC           PMI8937 (SID 1), 老 RPM (非 RPMh)
Touch          goodix@5d on i2c@78b7000 (QUP v1, qcom,i2c-msm-v2, 400kHz)
               irq-gpio 65, reset-gpio 64, power_ldo-gpio 47
               vdd_ana = regulator-l10 (2.85 V)   <-- 与 mido 完全一致
               vcc_i2c = regulator-l6  (1.8 V)    <-- 与 mido 完全一致
               compatible = goodix,gt9xx, family-id 9, product-id "9111"
               另有一个 focaltech@38 节点 (同总线, 未焊/备用)
Buttons        vol_up = gpio_keys (TLMM), power = PON KPDPWR
RPM            qcom,rpm-smd, cid 4, SMEM 0x86300000 legacy TOC (与 mido 同)
Battery        qcom,battery-data 在 DTB 内
`

### 与 mido 的差异清单（决定要改的常量）

| 项 | mido | ugg | 影响 |
|---|---|---|---|
| SoC | MSM8953 / 625 | MSM8940 / 435 | CPU 频率档位 |
| 面板 | 1080×1920 @0x90001000 | **720×1280 @0x90000000** | fb 基址/尺寸/stride |
| 触控 IC | FocalTech FT5435 | **Goodix GT9xx** | 驱动寄存器序列 |
| 触控电源 | L10 + L6 | **L10 + L6** | 一致，RPM 可照抄 |
| eMMC 基址 | 0x07824900 | **0x07824900** | 一致 |
| 用户态身份 | iPhone 8 Plus (10,5/D211) | **iPhone 8 (10,4/D20)** | 面包板尺寸、/product |
| MPIDR | 0x000-3 / 0x100-3 | 同 | 一致 |
| GICv2 | 0x0b000000 | 同 | 一致 |

---

## 2. 执行步骤（P0 已完成，P1 进行中）

### P0 重建干净基线 ✅ 完成

| # | 动作 | 结果 |
|---|---|---|
| P0.1 | `ugg/xnu/patches` 恢复上游原版 `0001-0081` | `same=84 diff=0` ✅ |
| P0.2 | 旧 `0082-0098` 归档到 `build-m1/old-ugg-patches/` | 84 个补丁在册 ✅ |
| P0.3 | `xnu-src` 重置 + 跑 3 个 staging 脚本 + apply `0001-0081` | `applied=81 failed=0` ✅ |
| P0.4 | 对 mido `0100` 做 `git apply --check` | 31 文件零冲突 ✅ |

### P1 生成 `0082-ugg-board.patch`（照抄 0100，换常量）

按 mido 的 31 个文件逐项处理：

| # | mido 文件 | UGG 处理 |
|---|---|---|
| 1 | `makedefs/MakeInc.def` | `-DMIDO_*` → `-DUGG_*`；保留 `-mcpu=cortex-a53+crc+crypto`；保留 iOS VA 布局 |
| 2 | `pexpert/pexpert/arm64/SWEET.h` | 新增 UGG 段：no 16K、HAS_GIC_V2、vtimer 20、fb 0x90000000/720×1280 |
| 3 | `pexpert/arm/pe_fiq.c` | GICv2 路径照抄 |
| 4 | `osfmk/arm/arm_init.c` | 16K VM 默认 + `ugg_vm4k=1` 回退 |
| 5 | `osfmk/arm/pmap/pmap.c` | `text_leaf_index &= ~(PAGE_RATIO-1)` |
| 6 | `osfmk/arm64/arm_vm_init.c` | early fb alias（720×1280 只需 1 个 2MB 块） |
| 7 | `osfmk/arm64/start.s` | stage-0 白带 + UGG_MARK |
| 8 | `osfmk/arm64/sleh.c` | EL0 LSE 模拟器（必须，860 处） |
| 9 | `osfmk/arm64/sweet_early.c` | fb 基址/行数 |
| 10 | `osfmk/kern/{zalloc,startup}.c` | zone map 24G/8G |
| 11 | `osfmk/vm/{vm_kern,vm_compressor}.c` | compressor 4× mem |
| 12 | `osfmk/mach/arm/vm_param.h` | `MACH_VM_MAX_ADDRESS 0xFC0000000` |
| 13 | `osfmk/arm/commpage/commpage_asm.s` | PFZ casa → LDAXR/STXR |
| 14 | `iokit/Kernel/arm/SweetCPU.cpp` | IONameMatch `arm,cortex-a53`；MPIDR `&~0x103` |
| 15 | `iokit/Kernel/arm/SweetFramebuffer.cpp` | canvas 750×1334 → 面板 720×1280 |
| 16 | `iokit/Kernel/arm/SweetSurface.cpp/.h` | 照抄 |
| 17 | `bsd/dev/sweet_ufs.c` | SDHCI PIO 传输层（换 SDCC 基址） |
| 18 | `bsd/dev/ugg_input.c`（新） | Goodix GT9xx over QUP v1 I2C |
| 19 | `iokit/Kernel/arm/hid/SweetHID.cpp` | 720×1280 归一化 |
| 20 | `bsd/conf/files`, `iokit/conf/files.arm64`, `iokit/KernelConfigTables.cpp` | 挂钩 |
| 21 | `mido_gpu.c` / `MidoGPU.cpp` | **不抄** |
| 22 | `bsd/kern/{bsd_init,kern_exec,sweet_amfi}.c` | 照抄 |

**门禁**：CI `patch-report` 的 `applied` = 82，`skipped` 不含 `0082`；`kscan` 真 LSE = 0。

### P2 shim 移植

| mido 文件 | UGG 处理 |
|---|---|
| `shim/sdhc.c` (557) | eMMC 读写/GPT/受限写/读回 —— 拷贝换常量 |
| `shim/rpm.c` (222) | RPM client —— **几乎原样**（L10/L6 一致） |
| `shim/input.c` (302) | 改 Goodix GT9xx |
| `shim/perf.c` (208) | CPU PLL 升频 —— 方法照抄，档位换 8940 |
| `shim/console.c`, `shim.c` | 拷贝，fb 0x90000000 + 720×1280 |
| `shim/gpu.c` (798) | **跳过** |
| `shim/build.py` | 换 toolchain 路径 + ugg DTB |

### P3 根卷（需 Linux，单独交付 `.sh`）

### P4 上机

---

## 3. 里程碑

| 里程碑 | 判据 |
|---|---|
| M1 | shim 出图 + eMMC 读写 + GPT 校验 |
| M2 | XNU 起动，`Still waiting for root device` |
| M3 | HFS+ root 读写挂载 |
| M4 | `Early boot complete` → 锁屏 |
| M5 | **桌面 + 触屏** |

---

## 4. 不做

- GPU（`gl/*`、`mido_gpu.c`、`MidoGPU.cpp`）
- MDP VIG0 零拷贝
- SD 卡驱动
- UGG 旧 `0082-0098` 诊断代码

---

## 6. P0/P1 执行记录（2026-11-14 夜，实际完成）

### 6.1 干净基线（已完成并 commit）

`
xnu-src  git checkout -- . && git clean -fdq          -> 0 modified
         跑 3 个 staging 脚本（libpthread / BearSSL / HFS）
         for p in 0001..0081: git apply                   -> applied=81 failed=0
         git commit -m baseline                          -> 2bbcef0
`

> `xcrun` 在 Windows 上不存在，libpthread/HFS 的 staging 会跳过最后一行的
> `cp $SDK/usr/include/TargetConditionals.h`；**不影响 CI**（macOS 上有 xcrun）。
> 本地只用于生成 diff，CI 会重跑这两个脚本拿到完整结果。

### 6.2 补丁 0082-ugg-board.patch（已生成并验证）

`
来源     mido 的 0100-mido-board.patch（31 文件 +2889/-22）
手法     git apply 原样落地 -> 机械重命名 MIDO->UGG -> 只改真正不同的常量
结果     28 文件 +2089/-22，2914 行
验证     GIT_INDEX_FILE=<temp> git read-tree HEAD && git apply --cached --check
         -> CHECK-OK（零冲突）
`

### 6.3 相对 mido 的实质改动（不只是改名）

| 文件 | mido | ugg | 原因 |
|---|---|---|---|
| `SWEET.h` | fb 0x90001000, 1920 高, stride 4320 | **0x90000000, 1280, stride 2880** | UGG DTB splash_region |
| `SWEET.h` | — | 新增 `UGG_FB_WIDTH` / `UGG_FB_BLOCKS 2` | 720x1280x4 = 3.7 MB = 2 个 2MB 块 |
| `sweet_early.c` | 硬编码 1080/1920/4320 | 从 board header 取 | 一块代码两个板 |
| `arm_vm_init.c` | 4 个 L2 块 | `UGG_FB_BLOCKS` (=2) | 同上 |
| `SweetFramebuffer.cpp` | canvas 1242x2208, 458 ppi | **750x1334, 326 ppi** | iPhone 8 D20AP |
| `SweetHID.cpp` | 1080x1920 归一化 | 720x1280 | 面板尺寸 |
| `bsd/dev/ugg_input.c` | FT5435（8 位寄存器） | **Goodix GT9xx（16 位寄存器）** | UGG 实际触控 IC |
| `mido_gpu.c` / `MidoGPU.cpp` | 完整 GPU 驱动 | **删除** | 用户明确跳过 GPU |
| `SweetSurface.cpp` | 场景池走 GPU BO 分配 | 删除池路径 | 无 GPU 时用普通 IOBuffer |
| `sweet_ufs.c` | 启动时调 `mido_gpu_init()` | 删除该调用 | 同上 |
| `tools/mkadt_ugg.py` | 新建，iPhone10,4/D20AP 750x1334 | | 身份 + 面板 |

### 6.4 Goodix GT9xx 驱动要点（bsd/dev/ugg_input.c，469 行）

| 项 | 值 | 来源 |
|---|---|---|
| 总线 | BLSP1 QUP3 `0x078b7000`，QUP **v1** FIFO I2C，400 kHz | DTB `i2c@78b7000` |
| 地址 | `0x5d` | DTB `goodix@5d/reg` |
| 寄存器 | **16 位大端**地址（FT5435 是 8 位）| GT9xx 数据手册 |
| 状态 | `0x814e` bit7 = 缓冲就绪，bits[3:0] = 点数 | 同上 |
| 坐标 | `0x814f` 起每点 8 字节：id / x[15:0] / y[15:0] | 同上 |
| 分辨率 | `0x8048` (max_x) / `0x804a` (max_y)，**运行时读取** | 配置块 |
| 产品 ID | `0x8140` 4 字符，期望 "9111" | DTB `goodix,product-id` |
| 电源 | L10 2.85 V（vdd_ana）+ L6 1.8 V（vcc_i2c） | DTB phandle 解析 |
| GPIO | irq 65、reset 64、power_ldo 47 | DTB |
| 按键 | power = PON KPDPWR、vol+ = TLMM gpio85、vol- = PON RESIN | DTB |

**关键设计**：坐标不从 DT 的 `display-coords` 硬编码，而是**启动时读配置块的 max_x/max_y**，
再按比例缩放到 720x1280。这样即使这批 UGG 用了不同规格的 GT9xx 也能自适应。
`uggtouchswap=1` 可强制交换 x/y（若面板装反）。

### 6.5 CI 配置修正（两个必须的改动）

| # | 问题 | 修正 |
|---|---|---|
| 1 | `MACHINE_CONFIG` 默认是 `UGG` | 改回 **SWEET**。3 个 staging 脚本用 `[[ "$MACHINE_CONFIG" == SWEET ]] \|\| exit 0` 门控，UGG 会让它们全部跳过，导致 libpthread/HFS/BearSSL 缺失、编译失败。板级差异全部由 `-DUGG_BOARD` 承载 |
| 2 | 原来用 `sed` 把 libfirehose 改成多架构 arm64 | 换成 mido 的 `ci/patch_dxb.py`：**只编 arm64 一个切片**，且加 `-mcpu=cortex-a53+crc+crypto`。libfirehose 由 xcodebuild 构建，**看不到 MACHINE_FLAGS**，否则会残留 11 处 LSE 指令，A53 上直接 undefined instruction panic |

### 6.6 已提交

| 项 | 值 |
|---|---|
| commit | `b6afa4b` `port: switch to the mido route (0082-ugg-board.patch)` |
| 推送 | `origin/ugg-port` ✅ |
| CI | `gh workflow run xnu.yml -R honghong2011/ios-ugg --ref ugg-port -f machine_config=SWEET` |

> **踩坑**：`gh workflow run` 不带 `-R` 时会用 `upstream` 远程（dipa-studio/ios-sweet），
> 报 `HTTP 403: Must have admin rights`。必须显式 `-R honghong2011/ios-ugg`。

---

## 7. P2 shim 移植（已完成，CI 编译通过）

### 7.1 移植进来的文件（全部来自 mido，硬件上验证过）

| 文件 | 行数 | UGG 适配 |
|---|---|---|
| `shim/sdhc.c` | 558 | **零改动**。HC `0x07824900` / CORE `0x07824000` / GCC SDCC1 RCG `0x01842004` / PM8953 L5(1.8V)+L8(2.9V) —— 与 UGG 的 DTB 逐项一致 |
| `shim/spmi.c` | 49 | 零改动 |
| `shim/rpm.c` | 223 | 零改动。cid 4 / SMEM `0x86300000` legacy TOC 一致 |
| `shim/perf.c` | 222 | CPU PLL 升频**默认关闭**（见 7.3） |
| `shim/input.c` | 302 | **重写**：FT5435 → Goodix GT9xx |
| `shim/mido_compat.h` + `shim/mido_console.c` | 36 + 91 | **新写**：mido 的 `con_puts/con_hex(v,n)` → UGG 的 `con_str` 单元网格 |
| `shim/emmc.c` + `emmc.h` | 163 | **新写**：UGG 自己的 GPT 策略 |
| `shim/console.c` | +49 | 新增纯文本日志环 `0x8e800000` |
| `shim/ufs.c` | — | **移出构建**（UGG 是 eMMC，不是 UFS） |
| `shim/gpu.c` | — | **不移植**（用户明确跳过 GPU） |

### 7.2 三个必须自己写的东西

#### (a) console 兼容层 `mido_compat.h` / `mido_console.c`

mido 的 console 是滚动文本（`con_puts(s)`、`con_hex(v,digits)`、`con_putc`、`con_dec`），
UGG 的是固定 45x40 单元网格（`con_str(label,s)`、`con_hex(label,v)`）。

选择**加适配层**而不是改 mido 的驱动代码，理由：让移植过来的驱动与被硬件验证过的版本**逐字节相同**，将来 mido 更新可以直接覆盖。

#### (b) eMMC GPT 策略 `emmc.c`

mido 的硬编码是它的 cache 分区 `LBA 7471104`。UGG 的 GPT 不同，所以改成：

`
读 LBA0 -> 检查 0xAA55
读 LBA1 -> 检查 "EFI PART"
遍历 GPT，打印每一个分区（#号 / F= / N= / 名字）
只有名字恰好是 "cache" 的分区才允许写
userdata 只打印名字，绝不写
`

**屏上会直接看到 UGG 的真实分区表** —— 这对后面刷 userdata 是必须的信息。

#### (c) 纯文本日志环 `console.c`

`
物理地址  0x8e800000   (reserved-memory/wcnss_fw_region@0 = 0x8e300000+0x700000 内)
大小      64 KiB
布局      +0  "UGGSHIM\0" 魔数
          +8  u32 当前长度
          +16 文本
`

每个字符同时进像素和这个环；然后写进 cache 分区。这样**不用拍照**就能从电脑 `dd` 出来。

### 7.3 为什么要关掉 CPU 升频

mido 的 `perf_sweep()` 表是 `{73, 88, 94, 102, 105}` = 1401/1689/1804/1958/2016 MHz，**这是 MSM8953（骁龙 625）的档位**。
UGG 是 MSM8940（骁龙 435），A53 分档和 APC 轨电压都不同，且**没有任何一档在 UGG 上验证过**。
在未验证的电压轨上升频，风险是启动中途不可恢复地挂死。
所以默认 `#if !defined(PERF_SWEEP_ENABLE)` 直接返回 0（保持 LK 的时钟），等实测后再开。

### 7.4 CI 验证

| 项 | 结果 |
|---|---|
| `shim-ugg` workflow | **success**（run 43612347343） |
| 修过的问题 1 | `input.c:151/294` `NULL` 未声明（freestanding 无 libc）→ 改成 `0` |
| 修过的问题 2 | `xnu` 的 `ugg_input.c:224` `unknown type name 'atic'`（我编辑时损坏了 `static`） |

### 7.5 shim_main 的新 bring-up 路径

无 payload 时（bring-up 模式）依次执行：

`
ugg_emmc_probe()    读 GPT、打印分区、写日志环到 cache
input_setup()       RPM L10 + QUP3 时钟 + gpio10/11/64/65 引脚
perf_boost()        目前是 no-op
保持 3 分钟后自动重启
`

`input_setup()` 的电源/引脚状态**会保留到 XNU**，所以 XNU 里的 GT9xx 驱动不需要重新上电。

---

## 8. P3 根卷构建（已交付脚本，等 Linux 电脑）

### 8.1 交付物

`ugg/build-root.sh` —— **174 行，bash -n 语法通过，一条命令跑完**。

`
./build-root.sh [WORKDIR]        # 默认 ~/ugg-root
`

它做的事：

| 步 | 动作 | 细节 |
|---|---|---|
| 0 | pre-flight | 检查 7 个工具 + ≥40 GB 空闲，缺什么直接告诉你 apt 命令 |
| 1 | 下载 IPSW | `iPhone10,4` / iOS `16.7.16` / `20H392`，约 5-6 GB |
| 2 | 解三个 dmg | 从 `BuildManifest.plist` **按角色**找 OS / Cryptex1,SystemOS / Cryptex1,AppOS，不硬编码文件名（Apple 每次改名） |
| 3 | 合成 HFS+ | 调 `mkiosroot.sh` → 16 GiB 大小写敏感、日志式卷 |
| 4 | 打移植补丁 | 挂载 + `sweet-root-tweaks.py` + 卸载 |
| 5 | 转 sparse | `img2simg` → 约 12 GB 的 `.simg` |

### 8.2 需要 Linux 电脑的原因（不是可以绕过的）

| 步骤 | 为什么必须 Linux |
|---|---|
| `apfs-fuse` | 读 IPSW 里的 APFS dmg；Windows/macOS 都没有可用实现 |
| `mount -t hfsplus` | 需要内核 hfsplus 支持。**WSL2 默认没编**（`CONFIG_HFSPLUS_FS` unset），mido 踩过这个坑 |
| `fsck.hfsplus` | hfsprogs 只有 Linux/BSD 版 |

**GitHub Actions 编不下**：root 镜像需要 6 GB IPSW + 16 GB 镜像 + 12 GB sparse ≈ 34 GB，
而且要先装 apfs-fuse（编译）。ubuntu runner 的磁盘是 14 GB 可用，装不下；
即使用 LFS/artifact 分段也超过免费额度。所以这条路**必须走你找的 Linux 电脑**。

### 8.3 复制进来的工具（来自 mido，已在其硬件上验证）

| 文件 | 行数 | 作用 |
|---|---|---|
| `tools/mkiosroot.sh` | 135 | APFS dmg → 单个 HFS+ 卷；保留属主/权限/符号链接/硬链接 |
| `tools/sweet-root-tweaks.py` | 153 | 跳过设置向导、种激活状态、关崩溃守护进程、给 SpringBoard 关 watchdog |
| `tools/remotezip.py` | 115 | 用 HTTP Range 只从 IPSW 取 `DeviceTree.d20ap.im4p`，不下整个 5 GB |

### 8.4 打完补丁后的产物要给我什么

`
1. fsck 输出（应含 "volume iOSRoot appears to be OK"）
2. ios16-root.img 和 ios16-root.simg 的字节数
3. fastboot getvar partition-size:userdata 的输出
`

拿到这三样我就能算清分包策略和刷写时间。

---

## 9. 我认为你该知道的判断（不是描述，是取舍）

### 9.1 关于「推翻之前做的东西」

你让我推翻，我确实推翻了 `0082-0098`。但推翻的**不是全部**：

| 保留的 | 为什么 |
|---|---|
| `shim/` 的 MMU、loader、fdt、console | UGG 特有的 LK 行为（ramdisk 位置、DTB bundle、32bpp 切换）已经趟明白，mido 的 shim 没有这些 |
| `tools/pack-ugg.py` / `mkuggboot.py` / `mkpayload.py` | mido 用的是 own `bootimg.py` + `build.py`，但我们这套已经验证过 UGG 的 LK |
| `device-dumps/` | UGG 的真实 DTB，全部硬件常量的来源，不可再生 |

### 9.2 关于「直接抄」

mido 的 `0100-mido-board.patch` 我是**原样 git apply**，然后机械改名 `MIDO→UGG`，
**只改真正不同的常量**。这样 mido 的每一个已知修复都自动带过来，包括我们之前卡死的 pmap。

改动清单（28 文件第 3 节表格）：framebuffer 尺寸、iPhone 8 画布、GT9xx 触控、删 GPU、关 CPU 升频。
除此之外**一行逻辑都没动**。

### 9.3 关于 GitHub Actions 能不能编

| 产物 | Actions 能不能 | 结论 |
|---|---|---|
| XNU 内核 | **能**，macos-15-intel 约 15-20 分钟 | ✅ 走 Actions |
| shim | **能**，ubuntu 约 1 分钟 | ✅ 走 Actions |
| **16 GB 根卷** | **不能** | ❌ 必须 Linux 电脑（见 8.2） |

所以**只有根卷这一件事需要你找电脑**，其余全自动。和你猜的一致。

### 9.4 关于「先跳过 GPU」

mido 的移植日志写得很清楚：**run #22 锁屏、run #25 桌面，都还没有 GPU**，
GPU（run #26 之后）和零拷贝显示是最后才加的。所以跳过 GPU 到桌面**是 mido 自己验证过的路径**，不是赌博。

CPU 渲染代价：720x1280 每帧坐标变换，比 mido 的 1080x1920 少 47% 像素，且我们用 750x1334 画布缩放比 0.96（mido 是 0.87）。**理论上比 mido 更快**。

### 9.5 剩余风险（诚实列出）

| 风险 | 概率 | 缓解 |
|---|---|---|
| MSM8940 的 eMMC 时钟/电压与 8953 有细微差别 | 低 | 地址/轨位完全一致（已从 DTB 核对），mido 的序列带失败回退 |
| GT9xx 的 QUP v1 时序 | 中 | shim 里已能读 product id 和分辨率；读不到会打印错误码 |
| iPhone 8 用户态在某处依赖 GPU | 低 | mido 已用 iPhone X 用户态无 GPU 跑到桌面 |
| EL0 LSE 模拟器在 cpus=1 下性能 | 中 | mido 实测「0 次模拟」——iPhone 8 用户态几乎不触发 |
| 根卷的 daemon 裁剪不够 | 中 | mido 的 `sweet-root-tweaks.py` 直接复用 |

### 9.6 下一步（等 CI）

`
1. xnu CI 出内核 -> 下载 -> docs 里的校验三件套（applied/skipped/LSE）
2. make-image.sh 出 shim-boot-ugg.img
3. fastboot boot  -> 看屏显：
   - 出 SWEET FB 说明 XNU 起来了
   - "Still waiting for root device" = M2 达成
4. 你找 Linux 电脑跑 build-root.sh -> 给我三个数
5. 刷 userdata -> 再 boot -> 目标桌面
`

---

## 10. CI 迭代记录（每一轮的真实结果，照实记）

### 10.1 轮次表

| 轮 | 提交 | applied/skipped | 结果 | 错误 |
|---|---|---|---|---|
| 1 | `b6afa4b` | — | **cancelled** | 并发组被手动 dispatch 抢掉，不是代码问题 |
| 2 | `b6afa4b` | `applied=86 skipped=4` ✅ | **失败** | `ugg_input.c:224` `unknown type name 'atic'` |
| 3 | `275ecb1` | `applied=86 skipped=4` ✅ | **失败** | 3 个：`THREAD_CONTINUE_0`、`SweetSurface.cpp` 未闭合 `#if`、`ugg_mdp_hold_mode` 未声明 |
| 4 | `5101a2c` | 待 | 待 | — |

`skipped=4` 全部是 dxb 自带的**外来补丁**（iobuffermemd_monterey / skywalk_sonoma / syntax_checker_sonoma / TrustCache），
与我们的 `0082` **无关**。CI 的 `ours_skipped` 过滤器确认 `patches-skipped` 注解**没有出现**。

**这是本轮最重要的门禁：0082 第一次真正被应用了。**

### 10.2 三个错误的根因（都是我引入的，不是 mido 的）

| # | 文件 | 错误 | 根因 |
|---|---|---|---|
| 1 | `bsd/dev/ugg_input.c:306` | `use of undeclared identifier 'THREAD_CONTINUE_0'` | 我为了修 freestanding 的 `NULL`，粗暴地把整个 xnu 侧的 `ugg_input.c` 里所有 `NULL` 替换成 `0`，误伤了 `THREAD_CONTINUE_NULL` |
| 2 | `iokit/Kernel/arm/SweetSurface.cpp:30` | `unterminated conditional directive` | 删 GPU 场景池时，把 `#if defined(UGG_BOARD)` 的配对 `#endif` 一起删了（那个 `#endif` 原本在池代码块尾部） |
| 3 | `iokit/Kernel/arm/SweetFramebuffer.cpp:368` | `use of undeclared identifier 'ugg_mdp_hold_mode'` | 这个函数定义在第 560 行，但第 371 行就用了；mido 原版能过是因为它定义得更早，我的 `_UGG_FB_BLOCKS` 改动不影响，是我删 GPU 时连带调整了顺序 |

### 10.3 教训（写下来避免再犯）

1. **不要全局替换 `NULL`**。freestanding 的 shim 需要，但 xnu 侧的代码有 `NULL` 定义，且 `*_NULL` 这类宏名会被误伤。
   正确做法：只在 shim 目录里替换，或 `#include <stddef.h>`。
2. **删 `#if` 块必须成对删**。删完立刻数 `#if` 与 `#endif` 的个数。
3. **本仓库没法本地编译 xnu**（需要 macOS SDK + Xcode）。所以每次推 CI 前，
   至少要跑这三个静态检查：

`
# a) 预处理配平
for f in <所有改动文件>; do
  a=$(grep -c '^#if' $f); b=$(grep -c '^#endif' $f)
  [ "$a" = "$b" ] || echo "IMBALANCE $f $a $b"
done

# b) 补丁能零冲突应用
GIT_INDEX_FILE=<tmp> git read-tree <baseline> && \
  git apply --cached --check <patch>

# c) 新标识符有定义
grep -rn '<new_ident>(' --include='*.c' --include='*.cpp' . | grep -v extern
`

4. **本地 grep 出来的宏名要用词边界**。之前用 `grep -oE 'MIDO_?[A-Z0-9_]*'` 把 `DEBUGGER` 里的 `UGGER` 也逮到，虚惊一场。

---

## 11. 文件清单（谁该看哪个）

| 文件 | 行数 | 作用 |
|---|---|---|
| `ugg/docs/MIDO-PORT-PLAN.md` | 492 | **本文件**。计划 + 执行记录 + CI 迭代 + 判断 |
| `ugg/NOTES-UGG.md` | 923 | 活跃交接（顶部 68 行是 baru 的路线说明，下面全是旧记录） |
| `ugg/xnu/patches/0082-ugg-board.patch` | 2906 | **核心产物**。28 文件 +2089/-22，零冲突 |
| `ugg/xnu/patches/0001-0081` | 84 个 | 上游 ios-sweet 原版，逐字节一致 |
| `ugg/shim/sdhc.c` | 558 | eMMC 驱动（照抄 mido，零改动） |
| `ugg/shim/emmc.c` | 163 | UGG 的 GPT 策略（新写） |
| `ugg/shim/input.c` | 302 | GT9xx 触控（重写） |
| `ugg/shim/mido_console.c` / `mido_compat.h` | 91 / 36 | console API 兼容层（新写） |
| `ugg/build-root.sh` | 174 | **交给 Linux 电脑跑的那一个文件** |
| `ugg/make-image.sh` | 82 | 内核 → 可启动镜像，一条命令 |
| `ugg/tools/mkadt_ugg.py` | 216 | UGG 的 Apple Device Tree |
| `ugg/ci/patch_dxb.py` | 24 | 让 libfirehose 按 Cortex-A53 编（无 LSE） |
| `build-m1/old-ugg-patches/` | 14 个 | 作废的 0082-0098，归档留证 |

### 11.1 一句话验收标准

`
能进桌面 = 屏上出现 iPhone 锁屏（时钟/日期），上滑后有 App 图标网格，
        手指在屏上滑动时 SpringBoard 有反应。
`

### 11.2 从零复现的完整命令

`
# 内核（CI，免费）
gh workflow run xnu.yml -R honghong2011/ios-ugg --ref ugg-port -f machine_config=SWEET
gh run download <RUN_ID> -R honghong2011/ios-ugg -n xnu-kernel -D ci-out

# shim（CI，免费，push 即触发）
gh run download <SHIM_RUN> -R honghong2011/ios-ugg -n shim-ugg -D shim-out

# 组装（本机）
./ugg/make-image.sh ci-out/kernel.development.ugg shim-out/Image

# 上机（不上电刷写）
fastboot boot build/img/shim-boot-ugg.img

# 根卷（Linux 电脑）
./ugg/build-root.sh /path/with/40GB
`

---

## 12. ★ 内核编译成功（2026-11-15 00:18，本轮里程碑）

### 12.1 结果

`
run      43613955911  (commit 5101a2c)
结果     **success**
产物     kernel.development.sweet
大小     17,140,032 B
sha256   0d8ed3eda477dc7ee0e0279e83b40bbb83452b7612e7e2035ad123a087d83094
`

### 12.2 三项硬门禁

| # | 门禁 | 期望 | 实际 | 结论 |
|---|---|---|---|---|
| 1 | `applied` 计数 | 86（含 0082） | `applied=86` | ✅ |
| 2 | `patches-skipped` 不含 0082 | 无 | 注解**未出现**（只有 `patches-skipped-foreign`） | ✅ |
| 3 | 内核含 0082 的标记 | `sweet_early_mark` / `sweet_gic_ack` | 两者都在 | ✅ |

`skipped=4` 全部是 dxb 自带的外来补丁：
`
iobuffermemd_monterey.patch
skywalk_sonoma.patch
syntax_checker_sonoma.patch
TrustCache.patch
`
这些与我们的补丁链无关，mido 的 CI 也是同样 4 个。

### 12.3 一个注解的坑（别被它骗）

`kernel-machine-configs` 注解显示 `ARM64_ADR ARM64_RET ...` 而**没有** `ARM64_BOARD_CONFIG_SWEET`。

**这不是问题。** 复查旧内核（0098 那版，CI success）得到完全相同的 4 个字符串：
`ARM64_ADR ARM64_GRANULE_ALLOW_BLOCK ARM64_RET ARM64_RETAB`。
原因：`-DARM64_BOARD_CONFIG_SWEET` 只影响 `#if defined(...)` 的分支选择，
**宏名本身不会作为字符串进内核**。这个注解的 `re.findall(rb'ARM64_[A-Z0-9_]+')` 只能捞到
别处恰好含这些字母的数据。这个检查项本身设计有问题，不是构建出错。

**判断 0082 是否真的生效，正确的方法是查它引入的符号**（见 12.2 第 3 项），
或者在 `build.log` 里看 `Applying patch: 0082-ugg-board.patch`。

### 12.4 内核大小变化说明什么

| 版本 | 大小 | 说明 |
|---|---|---|
| 0098 那版 | 17,711,296 B | 含 UGG 自研的 0082-0098 诊断代码 |
| **新版** | **17,140,032 B** | 含 mido 的 31 文件改动（+2889 行）+ 我们的 UGG 适配 |

新版**更小**是合理的：旧版塞了 14 个补丁的 fault-report / 双读数区 / 栈扩容等诊断代码，
新版是干净的 mido 移植 + 少量 UGG 适配。

---

## 13. ★★ 可启动镜像已生成（2026-11-15 00:31）

### 13.1 交付物

`
文件    build/img/shim-boot-ugg-0082.img
大小    8,169,472 B
sha256  7a97fee7a10275996bfcd04423867bfc64d4641732308e5ab7b75d3c3cb10af9
`

### 13.2 结构校验（全部通过）

| 项 | 值 | 判断 |
|---|---|---|
| Android boot magic | `ANDROID!` | ✅ |
| header_version | `0` | ✅ v0，LK 要的就是这个 |
| page_size | `2048` | ✅ |
| kernel_addr | `0x80008000` | ✅ 与库存 boot.img 一致 |
| tags_addr | `0x80000100` | ✅ |
| product name | `ugg-shim` | ✅ |
| kernel section | 8,166,776 B | ✅ |
| gzip 成员解压 | 6,013,634 → **16,724,960 B** | ✅ |
| gzip 之后的残留 | 2,153,142 B，魔数 `d00dfeed` | ✅ 就是 DTB bundle |
| 第一个 DTB 大小 | 247,516 B | ✅ |
| 解压后 arm64 头 | `ARMd` | ✅ |
| shim Image 大小 | 184,320 B（text_offset 0，image_size 0x2d000） | ✅ 自洽 |
| SWEETXNU 魔数 | 在解压区偏移 `0x77b3` | ✅ payload 在 |

### 13.3 payload 的关键参数

`
XNU 链接地址  0xfffffff007004000      <- **iOS VA 布局**（不是 -2TB 的 macOS 布局）
入口          0xfffffff00742a488
kernel_end    0xfffffff0084b4000
payload 大小  16,528,352 B
`

链接地址是这一版最重要的自检项：mido 的移植日志里，**链接到 -2TB 会让 MMU 开起来后静默挂死**
（build #2 的教训）。`0xfffffff007004000` 说明 `MakeInc.def` 对 SWEET 家族保留 iOS 布局这条生效了。

### 13.4 引导参数（CPU 渲染路线）

`
debug=0xc serial=3 cpus=1 keepsyms=1 -v -enable_kprintf_spam -noprogress
rd=ufsroot0 ufsrw=1 rootrw=1
unentitled_ios_sim_launch=1 ignition_level=1
wdt_test=no_user_checkin wdt=-1 launchd_unsecure_cache=1
sweetfb_noconsole=1 sweetfb_hz=15
`

| 参数 | 为什么这样设 |
|---|---|
| `cpus=1` | mido 明确写了：EL0 LSE 模拟器**不是多核原子的**，在做出 stop-the-world 之前用户态必须单核 |
| `rd=ufsroot0` | 沿用 mido/sweet 的变量名，底层是我们的 SDHCI eMMC 传输层 |
| `sweetfb_noconsole=1` | 不让内核文字盖住 GUI，日志走持久环 |
| `sweetfb_hz=15` | mido 实测 30 Hz 会把单核 A53 压满导致 eMMC 超时、触摸延迟数分钟 |
| `wdt=-1` | 关硬件看门狗，慢启动不能被它杀掉 |
| 没有 `midogpu=1` | 我们删了 GPU |

---

## 14. ★★★ 根卷不再需要你的 Linux 电脑（2026-11-15 00:45）

### 14.1 我之前的判断是错的，已用实测推翻

之前我写「根卷必须 Linux 电脑，GitHub Actions 编不下」。**这个结论是错的**，原因是我用的是
「ubuntu runner 只有 14 GB」这个流传的说法，**没有实测**。

新加的 `probe-rootenv.yml` 把六个前提全部实测了一遍，**六个全部通过**：

| # | 前提 | 实测结果 |
|---|---|---|
| 1 | 磁盘空间 | **86 GB 可用**（`/dev/root 145G，用了 59G`），不是 14 GB |
| 2 | `modprobe hfsplus` | **MODPROBE OK**（ubuntu-24.04 上是模块，能加载） |
| 3 | `mkfs.hfsplus` | **MKFS OK** |
| 4 | `mount -t hfsplus -o loop,force` | **MOUNT OK** |
| 5 | `fsck.hfsplus -fy` | **FSCK OK** |
| 6 | `apfs-fuse` 源码构建 | **cmake rc=0, ninja rc=0**，50/50 目标全部链接完成 |

> 唯一一个 FAILED 是 `touch /mnt/hfstest/hello` 用了普通用户权限（挂载点是 root 所有），
> 不是文件系统问题 —— 后面用 `sudo touch` 复测是 **HFS+ read-write OK**。

### 14.2 顺带确认了 WSL2 到底差在哪

| 项 | ubuntu-24.04 runner | WSL2 |
|---|---|---|
| `CONFIG_HFSPLUS_FS` | 有（模块） | **没有**（mido 踩过的坑） |
| 能不能 `modprobe` | ✅ | ❌ 没有模块可加载 |

所以「WSL2 不行」是真的，但「Actions 也不行」是我没验证的臆断。

### 14.3 新增 `build-root.yml`（189 行，11 步）

| 步 | 动作 |
|---|---|
| 1 | 清掉 runner 上预装的大工具链（dotnet/android/ghc/boost），腾出空间 |
| 2 | 装工具链 + **验证 hfsplus 能 mount 能写**（不通过就早失败） |
| 3 | 源码构建 `apfs-fuse` 并 `cmake --install` |
| 4 | 下载 IPSW（可用 `ipsw` 自动解析，也可手填`ipsw_url`） |
| 5 | 从 `BuildManifest.plist` **按角色**找 OS / Cryptex1,SystemOS / Cryptex1,AppOS |
| 6 | `mkiosroot.sh` 合成 16 GiB HFS+ |
| 7 | 挂载 + `sweet-root-tweaks.py` + 卸载 + fsck |
| 8 | `img2simg` 转 sparse |
| 9 | **按 1.8 GB 切片**（GitHub 单个 artifact 文件上限 10 GB） |
| 10 | 生成 `SHA256SUMS` |
| 11 | 上传 `ios16-root-parts` artifact |

### 14.4 你要做的变成两步

`
# 1. 触发根卷构建（免费，约 1-2 小时）
gh workflow run build-root.yml -R honghong2011/ios-ugg --ref ugg-port

# 2. 下载 + 拼回 + 校验（本机）
gh run download <RUN_ID> -R honghong2011/ios-ugg -n ios16-root-parts -D parts
cd parts && sha256sum -c SHA256SUMS
cat ios16-root.simg.part* > ../ios16-root.simg
`

### 14.5 诚实标注风险

| 风险 | 说明 |
|---|---|
| IPCC 下载 5-6 GB | 从 Apple CDN 下载，runner 网络快，但如果 Apple 改 URL 会失败 → 可用 `ipsw_url` 手填 |
| 16 GiB HFS+ 合成耗时 | mido 本地 20-60 分钟；runner 磁盘快，预计 30-50 分钟 |
| 总时长 | 预计 60-90 分钟，workflow 超时设 350 分钟，够 |
| 免费额度 | public 仓库的 Actions 分钟数免费且不限量 |

---

## 15. 本轮（第 7 轮）新增与结论

### 15.1 三件事

| # | 事情 | 结果 |
|---|---|---|
| 1 | **推翻「根卷必须 Linux 电脑」的判断** | 六项前提在 ubuntu runner 上全部实测通过，已写 `build-root.yml` |
| 2 | **QEMU 早期启动验证** | `tools/qemu-ugg.py` + `mkadt_ugg.py --qemu`，第一次放错 job（macOS 上没有 apt-get）已修正 |
| 3 | 修正 `build-root.yml` 的两个必错点 | 嵌套 sudo（无 tty）、`./ugg/` 路径（仓库根就是 ugg） |

### 15.2 QEMU 验证为什么重要

这一轮之前，判断内核是否活着**只能靠屏摄**。QEMU 把这件事变成自动的：

`
CI: build (macOS)  ->  kernel artifact
    qemu  (ubuntu)  ->  下载 kernel，用 -M virt,gic-version=2 -cpu cortex-a53 启动
                    ->  解码帧缓冲文字
                    ->  报里程碑：start.s / arm_init / pmap / VM bootstrap /
                       platform expert / SWEET FB / waiting for root device
`
**这正好覆盖旧路线卡死的整段路径**（start.s → MMU → pmap → bsd_init）。
如果 QEMU 能走到 `VM bootstrap done` 甚至 `SWEET FB`，就证明 0082 的
16K-VM-over-4K 方案是对的，之前那个 `esr 0x9600004f` 已经不存在。

### 15.3 QEMU 的局限（不能吹）

| 能验 | 不能验 |
|---|---|
| start.s / MMU / pmap / boot_args 契约 | UGG 的真实 MMIO（GICD 0x0b000000、eMMC、面板） |
| EL1 异常向量 / 早期控制台 | RPM/SPMI 电源 |
| 内存布局与 physmap | 触摸 |

所以 QEMU 通过 ≠ 真机能进桌面。它只是把「内核逻辑对不对」和「硬件对不对」分开。

### 15.4 根卷这条线的关键数字

| 项 | 值 |
|---|---|
| runner 可用磁盘 | **86 GB** |
| IPSW | 约 5-6 GB |
| HFS+ 镜像 | 16 GiB |
| sparse 产物 | 约 12 GB |
| 切片大小 | 1.8 GB × 7 片（artifact 单文件上限 10 GB） |
| 预计耗时 | 60-90 分钟 |
| 成本 | public 仓库免费 |

---

## 16. QEMU 第一次结果与随之发现的真 bug

### 16.1 QEMU 第一轮：blank_screen

`
qemu-verdict     kernel stopped early
qemu-milestones  reached: (none)
qemu-result      {"status": "blank_screen", "unknown_glyphs": 0}
harness          phys_base=0x50000000 boot_args=0x514b7000 entry=0x5042a488
`

连 `SWEET EARLY` 都没出现 —— 说明内核在**打印第一个字符之前**就停了。

### 16.2 顺藤摸出的四个真 bug（不是 QEMU 特有的，真机同样会中）

 | # | 位置 | mido 的值 | ugg 实际 | 后果 |
|---|---|---|---|---|
| 1 | `start.s` `UGG_MARK` | `0x90001000 + 1888*4320`，stride `4320` | `0x90000000 + 1272*2880`，stride `2880` | **写越界** |
| 2 | `start.s` stage-0 白带 | `0x90001000 + 1888*4320`，stride `4320` | `0x90000000 + 1248*2880` | **写越界** |
| 3 | `sweet_early.c` 早期控制台 | 已改用 `UGG_FB_*` | ✅ 早已修好 | — |
| 4 | `SweetFramebuffer.cpp` MDP 回退 | `0x90001000` / `4320` | `0x90000000` / `720*4` | 错地址 |

### 16.3 越界计算（这是关键证据）

mido 的 `UGG_MARK` 在 ugg 上的写入范围：

`
起点  0x90001000 + 1888*4320            = 0x911D4480
高度  32 行，每行加 4320
终点  0x911D4480 + 32*4320 + 64*4      = 0x9146F100
splash_region 是 0x90000000 + 0x1400000
                                  终点 0x91400000
`

**超出 splash_region 末尾 0x6F100 字节。**

在真机上这是写进下一个 reserved-memory 区域；在 QEMU 上这是内核执行的**第一件事**
（stage-0，还没有栈、没有页表、没有任何输出），所以表现为纯黑屏。

### 16.4 这是本轮最有价值的产出

如果没有 QEMU，这个 bug 只会在真机上表现为**黑屏**，然后我会误以为是 pmap 或更后面的问题，
又浪费几轮。QEMU 把它提前暴露成「0 个里程碑」，直接指向最早的那几条指令。

### 16.5 修复后

| 项 | 值 |
|---|---|
| `UGG_MARK` | `0x90000000 + 1272*2880`，8 行（不再是 32） |
| stage-0 白带 | `0x90000000 + 1248*2880`，stride `2048+832` |
| MDP 回退 | `0x90000000` / `720*4` |
| 补丁 | 2924 行，28 文件，`git apply --cached --check` 通过 |

> 注：`stride 2880` 不能作为 ARM 的 add 立即数，代码里拆成 `#2048 + #832`，
> 与 mido 处理 4320 的方式（`#4096 + #224`）同一手法。

---

## 17. ★★★ QEMU 的真结论：不是内核挂了，是我喂了错的内存大小

### 17.1 从 1.16 GB 的 qemu.log 里读出来的事实

`
Taking exception 3 [Prefetch Abort] on CPU 0    <-- 第一条，根因
...with ESR 0x21/0x8600000e
...with FAR 0x5042c5e4
...with ELR 0x5042c5e4

之后是 4000 条（日志上限）Undefined Instruction：
Taking exception 1 [Undefined Instruction]
...with ELR 0xfffffff007426458
`

`FAR = ELR = 0x5042c5e4` —— 这是一个**物理地址**（phys_base 0x50000000 之后 0x42c5e4）。

换算成 VA：

`
0x5042c5e4 - 0x50000000 + 0xfffffff007000000 = 0xfffffff00742c5e4
符号化：common_start + 0x198
`

**`common_start` 就是 commpage 的起点。** 内核跳到了 commpage 的**物理地址**去执行，
当然取指失败；随后的 Undefined Instruction 是异常处理器自己的连锁反应。

（补一句：`0x00ad0a04` 不是 LSE，是 `stp` 存对指令。我一开始按 ESR 猜 LSE，扫内核却只找到
1 处真 LSE，说明猜错了 —— 用 FAR/ELR 换算成符号才对上。）

### 17.2 真正的根因：QEMU 的内存大小让内核走了错误的页大小分支

`arm_init.c` 的选择逻辑：

`
if (args->memSize > 1 GiB)   PAGE_SHIFT_CONST = PAGE_MAX_SHIFT;   // 16K VM 页
else                         硬件页粒度                            // 4K
`

| 环境 | memSize | 走的路径 |
|---|---|---|
| **真机 ugg** | 1.5 GiB（0xA0000000..0x100000000） | **16K VM over 4K granule** |
| **QEMU（我之前设的）** | **512 MiB** | **4K VM** ← 错 |

**所以 QEMU 之前测的根本不是真机的那条路径。** 4K VM 下 commpage 的
`PAGE_RATIO = 1`，mido 的 `text_leaf_index &= ~(PAGE_RATIO - 1)` 变成空操作，
commpage 的地址计算与 PTE 布局对不上，于是跳到了物理地址。

### 17.3 修正

`
QEMU_MEM_SIZE  0x20000000 (512 MiB)  ->  0x60000000 (1.5 GiB)
`

和真机的 `PHYS_BASE=0xA0000000 / MEM_SIZE=0x60000000` 完全一致，
这样 QEMU 才真的在测手机跑的那条路径。

### 17.4 这轮的教训（值得写下来）

1. **QEMU 的价值不是「能启动」，而是「用和真机一样的参数启动」。** 内存大小差一个字，
   走的页大小分支就完全不同，测出来的结论毫无意义。
2. **不要用 ESR 猜指令类别。** `0x1fe00000` 看着像 LSE，实际是异常处理器在
   「prefetch abort 之后」自己崩掉的表现。正确做法：用 FAR/ELR 换算成符号。
3. **1.16 GB 的日志是线索不是噪音。** 4000 条重复异常说明陷入了异常风暴，
   而风暴的**第一条**（Prefetch Abort，只出现 1 次）才是根因。

---

## 18. QEMU 的精确诊断（1.5 GiB 配置下依然复现，但根因已定位到符号级）

### 18.1 事实

| 项 | 值 |
|---|---|
| 内存 | 已改 1.5 GiB（与真机一致），`X24=0x5fefc000` 证明生效 |
| 第一条异常 | **Prefetch Abort**，只有 1 次 |
| `FAR` = `ELR` | **0x5042c5e4**（物理地址） |
| 换算成 VA | 0xfffffff00742c5e4 = **`common_start + 0x198`** |
| 第二条及以后 | 4000 条 `Undefined Instruction`，`ELR = fleh_dispatch64 + 0x3c` |

### 18.2 因果链（不是猜测）

`
1. 内核把 commpage 的 **物理地址**（0x5042c5e4）当成 VA 去取指
2. -> Prefetch Abort（FAR = 那个物理地址）
3. -> 跳到异常向量 0xfffffff007425000
4. -> 异常分发器 fleh_dispatch64+0x3c 自己又触发 Undefined Instruction
5. -> 循环 4000 次（qemu.log 1.16-1.44 GB 全是这个）
`

**第 1 步才是根因，第 2-5 步都是连锁反应。**

### 18.3 为什么这指向 commpage_populate

`common_start` 是 commpage 文本区的符号。内核**只有在
`vm_commpage_init → vm_commpage_text_init → pmap_create_commpages → commpage_populate`
这条链上才会碰它。而 `pmap_create_commpages` 正是 mido 打过补丁的地方：

`
#if defined(UGG_BOARD)
    text_leaf_index &= ~(PAGE_RATIO - 1);   /* VM-page 对齐 */
#endif
`

这个补丁要求 `PAGE_RATIO > 1`（即 16K VM over 4K granule）。如果实际跑的是 4K VM
（`PAGE_RATIO == 1`），该补丁是空操作，commpage 的 leaf index 没有按 VM 页对齐，
PTE 写到了错误的位置 —— 与观测完全吻合。

### 18.4 需要确认的一件事

QEMU 里实际生效的 `PAGE_RATIO` 是多少。已知：

| 条件 | 来源 |
|---|---|
| `-DUGG_4K_VM` 已定义 | MakeInc.def 第 70 行 |
| 它影响 `MACH_VM_MAX_ADDRESS` 和 zalloc/compressor 的尺寸 | vm_param.h:136, zalloc.c:163, vm_kern.c:3592/3680, vm_compressor.c:833 |
| 它**不影响** `PAGE_SHIFT_CONST` | arm_init.c 只看 `memSize > 1 GiB` |

所以 1.5 GiB 时 `PAGE_SHIFT_CONST = PAGE_MAX_SHIFT = 14`，`PAGE_RATIO = 4`，
补丁**应当**生效。那问题在别处 —— 需要下一轮在
`pmap_create_commpages` 里加打印才能定位。

### 18.5 我的判断

这个问题**只在 QEMU 暴露**，真机可能根本走不到（真机连 stage-0 白带都还没验证过）。
继续在 QEMU 深挖的性价比不高，**优先让真机跑一次**，用真实屏显判断卡在哪。
