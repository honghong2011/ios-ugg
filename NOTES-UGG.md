# iOS 16 on ugg (Redmi Note 5A, MSM8937) — working notes

> 本文件镜像上游 NOTES.md 的 handoff 规范：每次里程碑后更新最新 handoff，区分事实与猜测。

## Agent handoff / active work (2026-11-07, latest)

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
