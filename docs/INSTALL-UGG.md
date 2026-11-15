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
| `shim-boot-0082-mido.img` | 仓库根目录，最新构建 | 8.2 MB |
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
fastboot boot shim-boot-0082-mido.img
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

## 5. 把 iOS 根镜像写进去

**关键：目标分区是 `userdata`，不是 `system`。**

### 5.1 方式 A：fastboot（推荐，最快）

```bash
# 手机先进 fastboot
adb reboot bootloader

# 分块刷，避免一次传 12 GB 被 USB 缓冲打断
fastboot -S 256M flash userdata ios16-root.img
```

`-S 256M` 是**必须**的：不分块时 fastboot 会一次性把整个文件读进内存，
12 GB 会直接失败。

### 5.2 方式 B：TWRP 里 dd（fastboot 不行时用）

把镜像放 U 盘，插 OTG，然后 TWRP 终端：

```bash
ls /usb_otg/                      # 确认真实挂载点
dd if=/usb_otg/ios16-root.img of=/dev/block/bootdevice/by-name/userdata bs=4M
sync
```

`dd` 会跑很久（10-30 分钟）。**中途绝对不能拔线或断电。**

### 5.3 确认写对了

```bash
# TWRP 终端
dd if=/dev/block/bootdevice/by-name/userdata bs=512 count=2 2>/dev/null | hexdump -C | head
```

看最后两字节是不是 `55 aa`（MBR/GPT 保护标记）或者能看到 `HFS`/`APFS` 字样。

---

## 6. 启动进 iOS

```bash
fastboot boot shim-boot-0082-mido.img
```

**这一次和主动试跑的区别**：现在 `userdata` 里有真的 iOS 根卷了，
XNU 的 `bsd_init` 应该能找到 `IOMedia/Apple_HFS` 根设备，不再无限等待。

### 6.1 预期顺序

```
shim 红底控制台（滚动，比试跑时短）
XNU jumping
黑屏 1-3 秒
内核文字开始滚动（现在是 24bpp，能画出来了）
bsd_init: ...
IOMedia/Apple_HFS 挂载成功
launchd 启动
苹果 logo / 白屏
桌面
```

### 6.2 如果卡在 `Waiting on <dict ... IOMedia ... Apple_HFS>`

这是"找不到根设备"。检查：

1. 第 5.3 步的确认做了吗？头两字节对吗？
2. `userdata` 是不是被格式化成了 ext4 而**没有写入镜像**？（顺序错了）
3. shim 控制台里 `GPT userdat F=... N=...` 的数字，是不是和你刷的分区一致？

---

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
fastboot boot shim-boot-0082-mido.img

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
fastboot boot shim-boot-0082-mido.img
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
