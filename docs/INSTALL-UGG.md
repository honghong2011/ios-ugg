# 在 UGG 上安装 iOS 16 —— 从 TWRP 清理到进入桌面（完整手册）

本文件是**给操作者看的步骤书**，不是移植笔记（那些在 `NOTES-UGG.md`）。
按顺序做，每一步都写了"怎么确认它生效了"和"失败了怎么办"。

> ⚠️ 下面第 5 步会**彻底抹掉这台手机的 Android 系统**。做完不可逆。
> 如果你还想留着 Android 双系统，看第 9 节，但 RAM 启动路线不支持双启动。

---

## 0. 先看清楚现状（2 分钟）

| 项目 | UGG 实际值 | 说明 |
|---|---|---|
| 机型 | Redmi Note 5A Prime（`ugg`） | 全名 `Redmi Note 5A Prime` |
| SoC | MSM8940 / 骁龙 435 | 8×Cortex-A53，**ARMv8.0，无 LSE** |
| 屏幕 | 720×1280，**24 bpp**（行宽 2160 字节） | 已由照片两次确认 |
| MDP 扫描地址 | **0x90001000**（不是 0x90000000） | 本轮照片读出的关键值 |
| 触摸 | Goodix GT917x @ i2c-3 0x5d | 驱动在 `ugg_input.c` |
| 存储 | **eMMC**（`sdhci@7824900`） | 不是 UFS |
| 内存 | 3 / 4 GB | 影响根卷大小选择 |

**关键区别（和 mido 不一样的地方）**

- mido 是 1080×2400 @32bpp / stride 4320；我们是 720×1280 @**24bpp** / stride 2160。
- mido 的 shim 不碰 MDP；我们**必须**在 shim 里把 RGB0 指到 0x90000000，
  因为它默认扫 0x90001000，差 4096 字节会让整屏错位。
- mido 是 UFS；我们是 eMMC，XNU 侧走 `sweet_ufs.c` 的 eMMC 分支。

---

## 1. 你需要准备的东西

### 1.1 电脑侧

- Windows + **platform-tools**（要 `fastboot` 和 `adb`）
- 至少 **20 GB 空闲磁盘**（根镜像解压后约 12 GB，还要留余量）
- 一个能跑 `fastboot` 的 USB 口，**用原装或好线**

### 1.2 手机侧

- 已解锁 bootloader（`fastboot oem device-info` 里 `Device unlocked: true`）
- 已刷入 **TWRP**（或 OrangeFox）
- 电量 **> 60%**

### 1.3 文件

| 文件 | 从哪来 | 大小 |
|---|---|---|
| `shim-boot-0105-touch.img` | 工作区根目录，最新构建（含触摸修复） | 8.2 MB |
| `ios16-root.img` | GitHub Actions artifact `ios16-root-parts`，需自己拼 | ~12 GB |

**根镜像怎么拿到并拼起来**

artifact 是分卷的，下载后按 `part00, part01, ...` 顺序拼：

```bash
# Linux / macOS / MSYS bash
cat ios16-root.img.part* > ios16-root.img
sha256sum ios16-root.img      # 和仓库记录的哈希对比
```

> artifact 有**过期时间**。如果下载 404，说明已过期，需要重新跑
> `.github/workflows/build-root.yml` 生成（约 1 小时）。

---

## 2. 确认分区表（**必做，不是可选项**）

在做任何破坏性操作前，先把真实分区表读出来存档：

```bash
adb shell "cat /proc/partitions"
adb shell "ls -l /dev/block/bootdevice/by-name/"
```

把输出**存成文件**。之后如果刷错，这是唯一的恢复依据。

本机应看到（名字可能略有差异）：

```
boot         ~64 MB
recovery     ~64 MB
system       ~2.5 GB
vendor       ~1 GB
cache        256 MB - 1 GB     <- 日志分区，我们会写它
userdata     ~10-24 GB         <- iOS 根卷放这里
```

**记录 userdata 的确切大小**：

```bash
fastboot getvar partition-size:userdata
```

如果 `userdata` 小于根镜像大小，**停下来**，不要继续（见第 8 节）。

---

## 3. 先验证 iOS 能不能起来（RAM 启动，不破坏任何东西）

**这一步一定要先做。** 它不改磁盘，只是把镜像放进内存跑一次。

```bash
fastboot boot shim-boot-0105-touch.img
```

### 3.1 屏幕上应该看到什么

红底控制台，从上到下：

```
RGB0 was=90001000 now=90000000 ok     <- 管道基址已纠正
SHIM ugg loader + board probe
RGB0 FMT=... UNPACK=...
RGB0 STRIDE=00000870 SIZE=...
RGB0 stride matches the console
WDT EN=00000000 ... WDT not armed
GPT cache   F=... N=...
GPT userdat F=... N=...
GPT used=NN
EMMC ...
```

然后**继续滚动**（关键！以前到这里就停了）：

```
INITRD / PHYS / ENTRY / SEGS / BOOTARG
WROTE / EXPECT / JUMP
XNU jumping (fbcon clears screen)
```

### 3.2 判读

| 现象 | 含义 | 下一步 |
|---|---|---|
| 出现 `XNU jumping` 且屏变黑/出内核字 | ✅ 真突破，继续第 4 步 | 4 |
| `RGB0 was=90001000 now=90000000 ok` | ✅ 基址修好了 | — |
| `RGB0 ... REFUSED` | MDP 不接受写入 | 见 7.1 |
| 到 GPT 就停住不动 | 滚动仍未生效 | 告诉我，附照片 |
| 出现 `PANIC` + ESR/ELR/FAR | XNU 崩了，**这张照片极其重要** | 拍下来发我 |
| 自动重启 | 不应该再发生 | 若发生，拍重启前最后画面 |

**手机不会自己重启了。** 卡住或崩溃都会停在屏幕上等你长按电源键。
这是本轮专门改的——以前崩溃后会立刻重启，把证据全抹掉。

---

## 4. 试跑通过后，才动磁盘

### 4.1 进 TWRP

```bash
adb reboot recovery
```

### 4.2 备份（**唯一一次机会**）

在 TWRP 里：`Backup` → 勾选 `Boot`、`System`、`Vendor`、`Data` →
备份到 **外部 SD 卡或 OTG U 盘**（不要放内部存储，下面要格式化它）。

至少必须备份 `boot` 和 `modem`/persist 类分区。**丢了 modem 会没信号，且不可恢复。**

或者用命令（TWRP 内置终端）：

```bash
dd if=/dev/block/bootdevice/by-name/boot of=/external_sd/boot-backup.img
dd if=/dev/block/bootdevice/by-name/modem of=/external_sd/modem-backup.img
```

### 4.3 清理 Android（你要的那一步）

在 TWRP 里依次做：

1. `Wipe` → `Advanced Wipe`
2. 勾选：`Dalvik / ART Cache`、`System`、`Data`、`Internal Storage`、`Cache`
3. `Swipe to Wipe`
4. **不要**勾 `Vendor`、`Modem`、`Persist`、`EFS`（勾了可能变砖）

等价的命令行做法：

```bash
# 在 TWRP 终端里
mke2fs -t ext4 -L IOSROOT /dev/block/bootdevice/by-name/userdata
```

> 为什么只格式化 `userdata` 就够：iOS 根卷整个放进 `userdata`，
> 不需要单独的 `system` 分区。格式化 `userdata` 同时会清掉 Android 的
> 用户数据和加密头，这是必须的（否则 iOS 会看到 ext4/f2fs 的残留超级块）。

### 4.4 确认清理结果

```bash
adb shell "blkid /dev/block/bootdevice/by-name/userdata"
```

应该是 `TYPE="ext4"` 且 **LABEL 为空或 IOSROOT**，容量等于分区大小。

---

> **需要另一台电脑？** 见 [`ROOT-IMAGE-OTHER-PC.md`](ROOT-IMAGE-OTHER-PC.md)：
> 那台机器上怎么装 `gh`、下哪 7 个分片、怎么校验拼合、
> 以及 CI 里各步骤在干什么，全部逐条写好了。
> 镜像已构建好躺在 GitHub 上（run `43644714094`，**2026-11-19 到期**），
> 不需要本地重新构建。
## 5. 把 iOS 根镜像写进去

**关键：目标分区是 `userdata`，不是 `system`。**

> # ⛔ 先读这一段：写 userdata 是被禁止的
>
> `ugg/AGENTS.md` 和 `README.md` 都明确写着：**data/userdata 分区只读、绝不触碰**，
> 清空时机由用户自己负责；2026-10-15 那次授权针对的是 *sweet*，**不是 ugg**。
>
> 所以下面这些 `flash userdata` / `erase userdata` 命令是**破坏性**的，
> 只能由用户在自己决定的时机执行。**不要照抄执行。**
>
> 符合约束的路线是 **SD 卡**：用 SDHCI-msm 驱动挂 SD 卡上的完整 iOS 根，
> 完全不碰 userdata（`README.md` 早已把它列为 U6）。那条线还没做。
>
> 本节保留，是因为它记录了 mido 的刷写方式与踩过的坑，仍是有效的技术资料。

> **只刷 `.simg`，一条命令。** 这一节 2026-11-22 重写过：
> 之前的版本让你先 `simg2img` 转 raw、再用自写的分块脚本一点点 dd 进去 ——
> 那条路在本机从来没成功过（`adb exec-in dd` 静默不写、`/sdcard`
> 就住在 userdata 上塞不进 16 GiB、TWRP 的 dd 不接受 `1M` 后缀），
> 相关脚本已删除。

### 5.1 存档：mido 的写法（**破坏性，需用户自行授权**）

```bash
# 手机先进 fastboot
adb reboot bootloader

# 直接刷稀疏镜像。mido 用的就是这条，24-25 片，约 5-8 分钟。
fastboot -S 512M flash userdata ios16-root.simg
```

为什么是 `.simg` 而不是 raw：

| | `.simg`（推荐） | raw `.img` |
|---|---|---|
| 文件大小 | 11.1 GiB | 16.0 GiB |
| USB 传输量 | 只有 RAW chunk，约 11.15 GiB | 全部 16 GiB |
| 空块 | FILL / DONT_CARE，设备端直接填零 | 传 16 GiB 的零 |
| mido 验证过 | **是** | 否 |

> **「11 GiB 变 16 GiB 是不是脚本坏了？」不是。**
> Android sparse 是**压缩描述**格式：FILL 块（一段全零或全同一字节）和
> DONT_CARE 块只占几字节头，展开后才成为完整的 16 GiB。
> `simg2img.py` 的输出尺寸**必须**等于 sparse 头里的 `total_blks * blk`，
> 那个脚本会校验这一条。11 → 16 GiB 是**正确展开**，不是撑坏。

`-S 512M` 是分块大小。不分块时 fastboot 会试图把整个文件读进内存。

### 5.2 刷之前：确认分区够大

```bash
fastboot getvar partition-size:userdata
```

要 ≥ `0x1AC4BFB000`（约 107 GB 的字节数）。实际 userdata 有 52.99 GiB 可用。

### 5.3 刷完立刻验证（**不要先后启动**）

```bash
adb push ugg/tools/verify-flash.sh /tmp/
adb shell sh /tmp/verify-flash.sh
```

它会从**卡上**读回四个关键的 HFS 目录节点，并打印期望值。四个全对上才算写成功。

**为什么要这一步**：2026-11-22 之前的几轮，都是先启动、再从内核日志里
发现数据不对，白白浪费启动和排查。直接读卡 30 秒出结果。

如果对不上，可以再带一个块号参数去验证"4 GiB 回绕"假设：

```bash
adb shell sh /tmp/verify-flash.sh 686351
```

### 5.4 大刷之后 fastboot 会挂住（正常现象）

小米 ABL 在刷完大分区后，下一次 `fastboot boot` 会卡在 `Sending` 不动。
**这不是故障**：手动按住 **电源 + 音量下** 重新进 fastboot 即可。
不要对挂住的 ABL 重试命令，也**不要拔线**（曾有一次 25/25 时中断，只能整盘重刷）。

---

## 6. 启动进 iOS

```bash
fastboot boot shim-boot-01NN-xxx.img
```

**这一次和"只试跑内核"的区别**：现在 `userdata` 里有真的 iOS 根卷，
XNU 的 `bsd_init` 能找到根设备并挂载。

### 6.1 判读

```
hfs: mounted iOSRoot on device b(1, 0)      根卷挂上了
bsd_init: done                              内核初始化完成
load_init_program: attempting to load /sbin/launchd
```

**只要出现 `hfs_swap_BTNode: invalid forward link`，就是卡上数据仍然不对**，
不要去调内核 —— 回到 5.3 验证卡上字节。

### 6.2 完整预期顺序

```
shim 红底控制台（滚动，比试跑时短）
XNU jumping
黑屏 1-3 秒
内核文字开始滚动
bsd_init: ...
hfs: mounted iOSRoot on device b(1, 0)
load_init_program: attempting to load /sbin/launchd
苹果 logo / 白屏
桌面
```

### 6.3 排错

| 现象 | 含义 | 怎么办 |
|---|---|---|
| `hfs_swap_BTNode: invalid forward link` | **卡上数据不对**，不是内核问题 | 回到 5.3 读卡验证，然后重刷 |
| `cannot mount root` 反复重试 | 根设备找到了但卷读不出来 | 5.3 验证卷头 `48 58`（HFSX） |
| `Waiting on <dict ... IOMedia ... Apple_HFS>` | 根本没找到根设备 | 检查 `rd=ufsroot0` 与分区大小 |
| `failed loading /sbin/launchd: errno 5` | 目录树节点坏了 | 同上，回到 5.3 |

---

## 取内核日志（TWRP + ADB，3 步）

**不需要改代码、不需要刷任何东西。** 内核本来就把控制台日志写在
**userdata 的最后 4 MiB + 4 KiB**，这是为「屏幕拍不清」准备的。

### 前提

- 手机进 **TWRP**（或 OrangeFox）
- 电脑装了 **adb**（platform-tools）
- TWRP 里 **Mount → 勾选 Data**（如果 data 加密了就跳过这步，用下一节的 raw 方式）

### 方式一：raw dd（最稳，不依赖挂载）

```bash
# 1. 看分区表，找到 userdata 的最后一个扇区
adb shell fdisk -l /dev/block/mmcblk0
```

输出里找 `userdata` 那行，记下 **Start** 和 **Sectors**（单位 512 字节）。

```bash
# 2. 把数字填进去算 skip（4K 块单位）
#    skip = (Start + Sectors)/8 - 1025
adb shell dd if=/dev/block/mmcblk0 bs=4096 skip=<skip> count=1025 of=/sdcard/sweetlog.bin

# 3. 拉出来
adb pull /sdcard/sweetlog.bin
```

### 方式二：让 shell 自己算（省事）

```bash
adb shell 'D=/dev/block/bootdevice/by-name/userdata; \
  SZ=$(blockdev --getsz $D); \
  SK=$(( SZ/8 - 1025 )); \
  dd if=$D bs=4096 skip=$SK count=1025 of=/sdcard/sweetlog.bin'
adb pull /sdcard/sweetlog.bin
```

### 解码

```bash
python tools/sweet-log.py sweetlog.bin out.txt
```

成功的话第一行会告诉你版本和刷写序号：

```
# version 1, ring 4194304, total 123456 bytes, flush #7
```

然后 `out.txt` 就是完整的内核控制台输出——包括 panic 原文。

**如果报 `no SWEETLOG header`**：说明日志线程一次都没跑起来（例如死在
挂载之前）。这时文件全是 0，直接告诉我，我换别的办法。

### 现在的改进：失败时会主动刷一次

本轮加了 `sweet_ufs_flush_log_now()`，在 `cannot mount root` panic **之前**
**同步**写一次日志。所以即使日志线程从来没启动，只要 eMMC 能写，
日志也一定在分区末尾。这比等 10 秒一次的线程可靠得多。

## 7. 故障排查

### 7.1 `RGB0 ... REFUSED`

MDP 拒绝改基址。临时办法：把 `ugg/shim/board.h` 里的
`FB_PHYS` 改成 `0x90001000`（跟着面板走），重新编译 shim。

### 7.2 屏幕花屏/条纹

说明写入位宽和面板扫描位宽不一致。本机必须是 **24bpp / stride 2160**。
检查 `board.h` 的 `FB_BPP == 3`，且没有代码去改 `SRC_FORMAT`。

### 7.3 自动重启

不应该发生。如果发生了，说明还有 `reset()` 路径没清掉：
```bash
grep -n "PSCI_SYSTEM_RESET\|IMEM_RESTART_REASON" ugg/shim/*.c
```
应该只有宏定义，没有调用。

### 7.4 触摸没反应

触摸驱动在 `bsd/dev/ugg_input.c`，i2c-3 @0x5d。先确认 shim 的
`input_setup()` 有没有打印成功。桌面能显示但点不动，是 i2c 时序问题，
不是驱动没编进去。

### 7.5 想看日志但屏幕不配合

shim 的日志会写进 `cache` 分区（看到 `LOG TO CACHE ENABLED` 就是开了）。
在 TWRP 里取：

```bash
dd if=/dev/block/bootdevice/by-name/cache of=/external_sd/shimlog.bin bs=4096 count=16
```

---

## 8. userdata 太小怎么办

如果 `fastboot getvar partition-size:userdata` 小于根镜像：

1. 不要硬刷（会截断，启动必然失败）
2. 在 TWRP 里把 `system` + `cache` 合并进 `userdata`（改分区表，风险高）
3. 或者用**压缩根卷**（去掉不需要的 .app / 语言包）后再刷

先量，再决定。**不要跳过第 2 节。**

---

## 9. 想保留 Android（双系统）

**当前不支持。** iOS 根卷占满 `userdata`，Android 的 data 也在 `userdata`，
两者冲突。

真要双系统，唯一干净的做法是把 iOS 根卷放到 **SD 卡**：
但这条路线在 ugg 上已放弃（SD 控制器在 XNU 里没有可用驱动）。
所以：**本机不做双系统。**

---

## 10. 一页速查

```bash
# 1. 备份分区表
adb shell "cat /proc/partitions" > partitions.txt

# 2. 试跑（不破坏）
fastboot boot shim-boot-0105-touch.img

# 3. 备份 boot/modem
adb reboot recovery
#   TWRP -> Backup -> Boot, Modem -> 外部SD

# 4. 清 Android
#   TWRP -> Wipe -> Advanced -> Dalvik/System/Data/Internal/Cache
#   保留 Vendor/Modem/Persist/EFS

# 5. 格式化 userdata 为 ext4
mke2fs -t ext4 -L IOSROOT /dev/block/bootdevice/by-name/userdata

# 6. 刷根卷
adb reboot bootloader
fastboot -S 256M flash userdata ios16-root.img

# 7. 启动
fastboot boot shim-boot-0105-touch.img
```

---

## 附：本轮代码改动一览（对应"为什么这次不一样"）

| 问题 | 位置 | 影响 |
|---|---|---|
| 管道基址差 4096 字节 | `fb32.c` 新增 `shim_fb_claim()` | 整屏错位 1365 像素 |
| 控制台不滚动 | `console.c` 新增 `con_scroll()` | **填满后所有输出被丢弃** |
| GPT 刷屏 48 行 | `emmc.c` 只打印关键分区 | 把重要行挤出屏幕 |
| 崩溃后自动重启 | `shim.c` `reset()` 改停机 | 证据被抹掉 |
| 内核无 24bpp 绘制 | `video_console.c` 补齐 24 分支 | 内核文字一个像素都不画 |
