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
1. `shim/console.h`：FB_BASE=0x90000000，FB_W=720，FB_H=1280，stride 2880。
2. `shim/shim.c`：GICv3 探测段 → GICv2 探测（GICC/GICD 最小初始化 + vtimer INTID 20 + IAR 读取）；
   删除 ufs.c 探测调用（RAM 阶段无存储）；PSCI/SMP 段保留（8 核双簇 MPIDR 表换成 0x0-3/0x100-103）。
3. `shim/build.sh`：mkbootimg 改 `--header_version 0`（本机 LK 只认 v0，实机 boot.img 已验证），
   且 v0 无 --dtb 参数（DTB 由 LK 经 x0 传给 shim，fdt.c 现成）；删掉 ufs.c 编译项。
4. 新增 `.github/workflows/shim-ugg.yml`：ubuntu runner（gcc-aarch64-linux-gnu + mkbootimg + cpio），
   产出 shim-boot.img artifact，供 `fastboot boot` 上机。
5. 上机测试：异常画彩屏（沿用 shim 现有 panic 屏），成功标志 = vtimer 中断计数跳动 + 8 核 CPU_ON 全 rc=0。

### 待验证 / 风险
- 8937 LK 是否真的把 FDT 指针放 x0 传给内核入口（标准 qcom 行为，未实测）——U1 第一屏就打印 x0 验证。
- GICv2 与 TZ 的 Group 0/1 划分：qgic2 在 8937 上 TZ 占 Group 0（与 SM7150 相同思路），须实测确认。
- RAM 布局：低 bank 0x10000000-0x7FFFFFFF 里散布 XPU 保留区（qseecom/secure/modem/adsp 等），
  mkadt-ugg.py 生成时内核可用 RAM 必须避开（实况 FDT 的 reserved-memory reg 是运行时值，以解析结果为准）。
- 4GB RAM + 16K 页：完整 iOS 根卷（3-4GB）放不进 RAM——U3 用裁剪根卷，完整根卷等 U6 eMMC 驱动。

### 本地资产（不入 git）
- 实机设备树 tar + 解包（device-dumps/dt/）、aboot.img、boot-head.bin。
- 设备序列号 32da6a6b；TWRP root shell 可用。

### 会话记录
- 2026-11-01：探测 + 分诊 + 本分支骨架（docs/ugg/*、NOTES-UGG.md、shim CI workflow）。
