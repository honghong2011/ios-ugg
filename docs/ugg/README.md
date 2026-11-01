# iOS 16 on Redmi Note 5A（ugg / MSM8937）

把 [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet) 的 iOS 16.7.16 + XNU (xnu-8796) 移植到
Redmi Note 5A Prime（代号 **ugg**，高通 MSM8937 / 骁龙 430 级，4GB+64GB eMMC）。

目标：`fastboot boot` 纯内存启动，先在 RAM 盘上点亮内核和用户空间（不碰任何分区），逐步推进到锁屏。
不追求 GPU 和日常可用。

上游 sweet 机型是 Redmi Note 10 Pro（SM7150，GICv3，GENI I²C，UFS）；本移植的差异与新增工作见
[PATCH-TRIAGE.md](PATCH-TRIAGE.md)。

## 设备关键事实（全部经实机只读探测确认，2026-11-01）

| 项 | 值 |
|---|---|
| SoC | MSM8937，8× Cortex-A53 双簇（MPIDR 0x0-3 @1.4GHz / 0x100-103 @1.1GHz），ARMv8.0-A + crypto，无 PAC |
| 内存 | bank1 0x10000000+0x70000000，bank2 0x80000000+0x80000000（共 3.75GB，另有一批 XPU 保留区） |
| 帧缓冲 | splash region **0x90000000 / 20MB**（ABL 运行时重定位，FDT 节点名 @83000000 是旧值），720×1280×4 |
| 中断控制器 | **qcom,msm-qgic2（GICv2 类）：GICD @ 0x0B000000，GICC @ 0x0B002000**（上游全部是 GICv3——本移植最大新增工作） |
| 虚拟定时器 | cp15 arch timer，19.2MHz；FDT PPI 序 (sec=2, phys=3, virt=4, hyp=1) → **CNTV = INTID 20**（SM7150 是 19，勿照抄） |
| 存储 | 64GB eMMC（SanDisk HCG8a4）；RAM 盘阶段完全绕开；后期 SDHCI 驱动挂 userdata/SD |
| 触屏 | Goodix GT917D @ BLSP QUP I²C（0x78b7000，地址 0x5d，IRQ GPIO 65）；sweet 是 GT9897@GENI |
| PMIC | 老一代 RPM（非 RPMh），触屏供电轨道后期处理 |
| 引导 | LK bootloader（2017 世代），BL 已解锁不验签，`max-download-size ≈ 511MB`，boot header **v0**（上游用 v2） |
| 日志 | `/proc/last_kmsg` 可用（跨重启取内核日志）；帧缓冲控制台可 `adb exec-out dd if=/dev/graphics/fb0` 截取 |

完整探测记录、路线决策和调试手册见工作区 README（本地保留，含设备数据，不入 git）。

## 方法论（沿用上游 AGENTS.md）

- 每个里程碑更新 `NOTES-UGG.md` 的 active handoff；区分观测事实与猜测。
- 每次上机用临时 `fastboot boot` 镜像，重启即回 Android；**破坏性操作先确认**；data 分区只读。
- 设备 dump、序列号、苹果下载物一律不入 git。
- XNU 内核走 GitHub Actions macOS runner（public 仓库免费）；shim 交叉编译走 ubuntu runner（本机无工具链）。

## 里程碑

| # | 内容 | 验收 |
|---|---|---|
| U1 | shim 探测镜像：FB 控制台 + CPU/PSCI 报告 + 8 核 CPU_ON + GICv2 虚拟定时器中断 | 定时器中断计数跳动，8 核上线 |
| U2 | UGG 板级配置编译 XNU（GICv2 + mkadt-ugg），shim 加载跳转 | 内核控制台输出 |
| U3 | mockfs RAM 盘根 + launchd（上游 0021/0022/0024 现成） | 守护进程拉起 |
| U4 | IOSurface/IOMFB + 720×1280 帧缓冲 | SpringBoard 出画面 |
| U5 | BLSP I²C + GT917D + RPM 轨道 | 触摸可用 |
| U6 | SDHCI eMMC/SD 驱动，完整 iOS 根卷 | 完整用户空间 |
| U7 | Adreno 505 GPU | 悬置（不追求） |
