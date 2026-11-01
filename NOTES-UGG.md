# iOS 16 on ugg (Redmi Note 5A, MSM8937) — working notes

> 本文件镜像上游 NOTES.md 的 handoff 规范：每次里程碑后更新最新 handoff，区分事实与猜测。

## Agent handoff / active work (2026-11-01, latest)

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

