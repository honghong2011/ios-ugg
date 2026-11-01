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
- **A53 的 16K 页粒度**：shim 先打印 `ID_AA64MMFR0.TGran16`（0=支持，1=不支持）；
  只有支持时才开 MMU。若为 1，XNU 16K 页方案在本 SoC 上直接受阻，需重新评估。
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

### 会话记录
- 2026-11-01：探测 + 分诊 + 本分支骨架（docs/ugg/*、NOTES-UGG.md、shim CI workflow）。
- 2026-11-01：U1 代码完成（GICv2/INTID20/SMP、720p 控制台、v0 打包器）；查清 LK 加载地址与
  DT 捆绑包结构，抽出 msm8937-dtbundle.bin；推送 e617e91，准备首次 `fastboot boot`。
- 2026-11-01：**首次上机（e09e93c 镜像）**：`fastboot boot` 成功（LK 装载后离开 fastboot，
  fastboot 设备消失），但屏幕白屏/花屏 + 底部隐约文字，3 分钟后**没有自动复位**，只能长按电源。
  结论：shim 已运行；显示格式假设错误；某步死循环。

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

