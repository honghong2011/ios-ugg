# ios-sweet 81 个内核补丁分诊（面向 ugg / MSM8937 移植）

> 依据：ios-sweet 上游克隆（2026-11-01，dipa-studio/ios-sweet @ main）逐补丁阅读。
> 行数 = patch 文件行数（含 diff 上下文）。分类：**A 直接复用 / B 改造复用 / C 暂不需要 / D 全新编写**。

## A. 直接复用（52 个，与 SoC 无关）

### 工具链与构建
| 补丁 | 行数 | 说明 |
|---|---|---|
| 0001-new-clang-drop-removed-auto-var-init-flag | 12 | 新版 clang 兼容 |
| 0002-new-clang-backport-UIO_STACKBUF | 391 | 同上 |
| 0005-non-pac-build-fixes | 13 | 去 PAC——A53 本来就没有 PAC，条件原样成立 |
| 0006-sweet-master-config-open-source-asm-pmap | 120 | 用开源 pmap 汇编 |
| 0007-sweet-stub-apple-internal-headers | 88 | 桩掉苹果内部头文件 |
| 0008-sweet-fill-closed-lib-gaps-kpc-stub | 361 | KPC 桩 |
| 0009-sweet-drop-apple-soc-only-exports | 74 | 去苹果 SoC 专属导出 |

### 内核服务替代（开源组件内建）
| 补丁 | 行数 | 说明 |
|---|---|---|
| 0013/0014 | 97/292 | 无 corecrypto 的 kmem RNG / HMAC-PRNG |
| 0019/0020(stage)/0023/0026(stage) | 129/—/59/— | libpthread 内建 + staging 脚本 |
| 0020/0023/0027/0032/0033 | 258/59/131/125/125 | BearSSL 系（AES-CBC、SHA256、MD5、SHA1、SHA384/512）内建 |
| 0026/0041/0052 | 351/55/23 | 开源 HFS+ 内建、link notes、rename-swap |

### 根文件系统（RAM 盘路径，U3 的核心）
| 补丁 | 行数 | 说明 |
|---|---|---|
| 0021-mockfs-ramdisk-root | 54 | mockfs 内存根（XNU 自带 mockfs 打开） |
| 0022-ramdisk-root-without-iomedia | 27 | 无 IOStorageFamily 时跳过 IOMedia |
| 0024-mockfs-virtual-ramdisk-io | 30 | IOKit RAMDisk 虚拟内存盘走正常设备 IO |
| 0029/0031 | 24/46 | 未密封根卷、可写根 |
| 0037-config-bindfs | 11 | bindfs 配置 |

### 安全体系解除（AMFI/沙箱/激活）
| 补丁 | 行数 | 说明 |
|---|---|---|
| 0025/0035/0036 | 192/477/26 | AMFI 无 entitlements / 平台二进制 / CS 签名放宽 |
| 0038 | 251 | AppleKeyStore 桩 |
| 0050/0055/0057 | 66/72/11 | 沙箱策略、AKS 状态、无外部 resolver |
| 0015 | 93 | trust cache 运行时绕过 |

### 日志/崩溃/看门狗（实机调试的核心手段）
| 补丁 | 行数 | 说明 |
|---|---|---|
| 0042/0043/0044/0047/0048 | 17/105/16/157/70 | exec 日志、控制台崩溃日志、崩溃原因、持久控制台、devnull tee |
| 0040/0045 | 118/40 | IO 看门狗（防卡死屏） |
| 0049/0051/0053/0054/0066/0070 | 167/114/30/219/28/36 | IOKit trace、堆字符串、SpringBoard 扫描、进程采样、fault 区、pid 休眠 |
| 0039 | 24 | coredump 默认关 |

### HID 与身份（设备无关的胶水）
| 补丁 | 行数 | 说明 |
|---|---|---|
| **0058-hid-event-services** | **21309** | IOHIDFamily 用户客户端对接 iOS 16.7 用户空间的全部胶水——最大补丁但完全设备无关，整体复用 |
| 0059-iphone-identity | 53 | 伪装 iPhone X（iPhone10,3/D22AP） |
| 0064/0068 | 57/64 | priv work interval、surface lookup 缓存 |

### USB 网络调试（可选，推迟）
0072/0073/0074/0075/0076/0077/0080/0081（139/427/41/457/24/107/51/71 行）——USB ECM 网卡调试通道。RAM 阶段不需要，U3 之后如果嫌 FB 控制台 + last_kmsg 不够用再启用（DWC3 在 8937 上同样存在，改造点主要在控制器地址）。

## B. 改造复用（15 个，把 SWEET 的硬件参数换成 UGG 的）

| 补丁 | 行数 | 改造点 |
|---|---|---|
| **0004-machine-config** | 318 | ① 新建 `UGG.h` 板级头：`-march=armv8.0-a+crypto+crc`（A53 是 ARMv8.0，sweet 用 8.2）；MAX_CPUS=8、MAX_CPU_CLUSTERS=**2**（sweet 单簇）；**GICv2**（删 GICR/GICv3 定义，换 GICC/GICD MMIO 定义）；VTIMER_INTID=**20**。② sleh.c 的 SWEET 分支改为读 **GICC_IAR**（MMIO）而非 `ICC_IAR1_EL1` 系统寄存器。③ pe_init_fiq 的 GICR 初始化段整体换成 GICD/GICC 初始化（TMZ 占 Group 0 的思路照搬）。④ start.s / proc_reg.h 的缓存行（A53 = 64B，MMU_CLINE=6 同 sweet） |
| 0003/0010/0012 | 176/344/233 | FB 控制台三件套：帧缓冲地址换 0x90000000、分辨率 720×1280、stride 2880 |
| 0016-device-tree-platform-expert | 119 | 设备树平台专家：逻辑不变，核对 UGG ADT 节点结构（mkadt-ugg.py 产出对齐） |
| 0017-virtual-timer-irq | 81 | INTID 19 → 20 |
| 0018-boot-cpu-driver | 201 | 引导 CPU 驱动：核对 MPIDR/簇拓扑读取路径 |
| 0046-iosurface-iomfb | 1449 | IOSurface + IOMobileFramebuffer：FB 地址/尺寸/stride 换 ours，present 路径不变 |
| 0056/0079 | 82/78 | FB 节流 present、显示电源（MDP5 侧参数） |
| 0058 内嵌的显示尺寸 | — | 0061-iphone-x-display-size：谎报分辨率改为 720×1280（UI 仍按 iPhone X 手势逻辑） |
| 0060/0062/0063 | 788/938/310 | 按键+触屏+供电三件套：GT9897@GENI → **GT917D@BLSP QUP**（0x78b7000，地址 0x5d，IRQ GPIO 65）；供电轨道 RPMh → **RPM legacy**；Goodix 寄存器族相同（GT9xx），pack 格式改 BLSP |
| 0065-smp-psci | 415 | PSCI CPU_ON（SMC #0）逻辑照用；phys_id 换我们的 MPIDR 表（0x0-3 / 0x100-103）；补双簇调度 |
| 0078-smp-8-cores | 53 | 8 核全开，核数一致直接用 |

## C. 暂不需要（4 个，RAM 盘阶段整体绕开存储层）

| 补丁 | 行数 | 原因 |
|---|---|---|
| 0028-ufs-root-device | 580 | UFS 根设备——RAM 盘阶段无存储；U6 阶段用 SDHCI 驱动等价替换 |
| 0030-ufs-writes | 224 | 同上 |
| 0034-ufs-dma-above-4g | 43 | 同上（DMA 4GB 以上区段的特殊处理——我们高段 bank 0x80000000+2GB 到 0x100000000 边界，问题形态类似，写 SDHCI 时参考） |
| 0069-ufs-faster | 181 | 性能优化，延后 |

## D. 全新编写（8937 特有，sweet 没有的部分）

### D1. GICv2 中断控制器（~300-500 行）★ 最大新增工作
- 位置：`pexpert/arm/pe_fiq.c`（初始化）+ `osfmk/arm64/sleh.c`（分发）+ `UGG.h`（寄存器定义）
- 内容：GICC_CTLR/GICD_CTLR 使能（Group 1 NS，思路同 sweet：TZ 占 Group 0，全部中断走 IRQ）；GICC_IAR 读 → 分发（SGI=IPI / PPI=vtimer / SPI→`cdp->interrupt_handler`）→ GICC_EOIR 写；GICD_ISENABLER 使能 SPI；每核 CPU interface 初始化；GICD_TYPER 探测中断线数
- 比 GICv3 简单：无 redistributor、无 ITS、无 LPI/message-SPI，纯 MMIO
- GICD @ 0x0B000000，GICC @ 0x0B002000（实机 FDT 已确认）

### D2. mkadt-ugg.py（ADT 生成器，~1 天）
- 素材：`device-dumps/dt/`（实机 FDT）+ sweet 的 mkadt.py 模板
- 要点：双内存 bank（0x10000000+0x70000000、0x80000000+0x80000000）减去 reserved-memory 的 XPU 区（qseecom/secure/modem/adsp/wcnss/venus/other_ext）；FB=0x90000000/20MB/720×1280/stride 2880；GICD/GICC 地址；vtimer=20；timebase=19.2MHz；SOC_BASE 参照 sweet 取值；panic log carve（sweet 踩过的坑：没有它会卡死）；`/product` 节点从 iPhone X IPSW 的 D22AP 设备树拷贝（同 sweet 流程）
- ECID 等合成值参照 SWEET_ECID 做法

### D3. shim-ugg（引导器改造，~2-3 天）
- 基于 shim/：FDT 解析、MMU 建立、载荷加载逻辑全复用
- 改：FB 地址/分辨率（console.c）、GIC 探测段（shim.c 里 sweet 的 GICv3 probe → GICv2 probe：读 GICC_IAR 确认 vtimer 到来）、删除 UFS 探测（shim/ufs.c，RAM 阶段不需要）、PSCI/SMP 探测保留（8 核双簇）
- 打包：tools/mkpayload.py + boot header v0 兼容（本机 LK 只认 v0，已验证现有 boot.img 为 v0）

### D4. BLSP QUP I²C 驱动（U5 阶段，~3-5 天）
- sweet 用 GENI I²C（新平台），8937 是 BLSP QUP 老控制器；寄存器文档取自小米开源内核（msm-3.18/4.9，LINUX android）或 CAF
- 只需 basic master 模式读写（GT917D 初始化 + 中断读点）

### D5. RPM legacy 驱动（U5 阶段，~2-4 天）
- 目的：给触屏供电轨道上电（vdd/vddio）。RPM over SMD/glink 消息通道；bring-up 早期可先试 ABL 是否已把轨道留着供电（大概率已开——Android 内核 probe 触屏前轨道就绪），若已开则 D5 可推迟
- 参照：msm-3.18 rpm/smd 驱动

### D6. SDHCI-msm eMMC/SD 驱动（U6 阶段，~1-2 周）
- sdhci-msm-v4 @ 0x7824900（eMMC）/ 0x7864900（SD 卡槽），JESD84 + CAF 源码
- 等价替换 sweet 的 UFS 补丁组（0028/0030/0034），根卷挂 userdata 或 SD 卡

## 工作量与顺序总览

```
U1 shim 探测（D3 部分 + GICv2 probe）     ← 先决：GICv2 最小实现
U2 内核点亮（D1 完整 + B 类 0004/0016/0017/0018 + D2 mkadt-ugg）
U3 RAM 用户空间（A 类 0021/0022/0024 + 0025/0038/0050 等安全解除）
U4 画面（B 类 0046/0056/0061/0079）
U5 触摸（D4 + D5 + B 类 0060/0062/0063）
U6 存储（D6 替换 C 类）
```

预计 U1+U2 是成败关键（GICv2 正确性决定一切）；A 类补丁在 U2-U3 期间原样搬运即可，无需理解全部 21000 行的 0058。

## 构建管线（无 Mac 方案）

- XNU 内核：GitHub Actions **macOS runner（public 仓库免费）**，`.github/workflows/xnu.yml` 照抄 sweet，darwin-xnu-build pinned commit，MACOS_VERSION=13.5 → xnu-8796；产物 kernel.UGG.macho artifact
- shim/工具链：本地 WSL/Linux（clang aarch64 + python3 + make），shim 单文件交叉编译先本地验证再上 CI
- 遵循上游 AGENTS.md 方法论：每里程碑更新 NOTES.md handoff、单独 commit、破坏性操作先确认
