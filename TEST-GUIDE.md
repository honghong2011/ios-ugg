# UGG 移植 —— 上机测试手册

> 生成时间：2026-11-15 07:45
> 状态：**所有离线可做的准备工作已完成，等你在真机上验证。**

---

## 0. 一句话现状

内核能在 QEMU 里跑完全部早期路径直到 `bsd_init` 结束（M2），
16 GB iOS 根卷已在 CI 构建出来，boot.img 已打包校验。
**但一次真机测试都还没做过** —— 现在需要你。

---

## 1. 准备：你需要的东西

| 项 | 说明 |
|---|---|
| 手机 | Redmi Note 5A Prime（ugg），bootloader 已解锁 |
| USB 线 + fastboot | 能执行 `fastboot devices` 看到设备 |
| 相机/另一台手机 | **拍照用，最关键** |
| 磁盘 | 刷根卷需要 **20 GB 空闲**（当前 C: 有 8 GB，不够） |

---

## 2. 第一步：只刷 boot.img（10 分钟）

**这一步不需要根卷，不写任何分区，纯 RAM 启动。**

```bash
cd C:\Users\Administrator\Desktop\ios-ugg
fastboot devices                    # 先确认能看到设备
fastboot boot shim-boot-0082-mido.img
```

镜像信息：

```
文件    shim-boot-0082-mido.img
大小    8,171,520 B
sha256  04fb64de8c78b5b5faf55bc3df1b1c2ba07b095c0551e0afab8bd5586fcd6db3
```

### 期望看到什么

屏上从上到下应该出现（约 10-30 秒内）：

```
SHIM    ugg loader + board probe
MDP RGB0: ADDR=90000000 FMT=0002243f STRIDE=00000870
MDP RGB0 -> FMT=000236ff STRIDE=00000b40 (32 bpp)
EMMC HC_MODE=00000001
 PRES=... HCTL=... CLK=... HCTL2=...
 BUS POWER ON: PWRREQ=..
LBA0 E=0 SIG=AA55 OK
LBA1 E=0 GPT OK
#25 F=... N=... cache         <- 你的真实分区表
CACHE F=... N=...
LOG TO CACHE ENABLED
LOG VERIFY OK
INPUT SETUP: RPM L10 E=0 L6 E=0 CLK ON
LOADER  <原因>
```

然后是内核启动，最终应该停在：

```
Still waiting for root device
```

**这就是 M2，是成功，不是失败** —— 因为你还没刷根卷。

---

## 3. 第二步：把屏幕拍下来发我

**这一步最重要。** 请拍 2 张：

| 照片 | 时机 | 我要看什么 |
|---|---|---|
| 1 | 刚启动 5-15 秒 | 开头那几行 MDP / EMMC / LBA0 / LBA1 |
| 2 | 稳定后（约 1-2 分钟） | 最后停在什么 |

### 怎么判读（你也可以自己看）

```
看到                                             含义
--------------------------------------------------------------------
MDP RGB0 -> FMT=000236ff (32 bpp)                显示管道切换成功
MDP: unexpected FMT ... screen may be unreadable 管道状态异常（拍照给我）
EMMC HC_MODE=00000001                            eMMC 控制器进入 HC 模式
BUS POWER ON: PWRREQ=..                          卡供电打开
LBA0 E=0 SIG=AA55 OK                             读到分区表签名
LBA1 E=0 GPT OK                                  读到 GPT 头
#NN F=... N=... cache                            你的分区表（关键证据）
EMMC INIT FAILED                                 eMMC 没起来 -> 拍照
BUS POWER STILL OFF - ABORT                      电源握手失败 -> 拍照
Still waiting for root device                    M2 达成，驱动 OK
panic: IOFindBSDRoot: ... unavailable: N         eMMC 驱动失败，N 是错误码
FB32 FAILED: not booting XNU                     显示故障，已拒绝启动
```

---

## 4. 第三步（可选，需要 20 GB 磁盘）：刷根卷

### 4.1 下载

根卷在 GitHub 上，**11.97 GB，7 个分片，有效期到 2026-11-19**。

因为本机 C: 只有 8 GB，需要换一个有空闲的盘：

```bash
cd C:\Users\Administrator\Desktop\ios-ugg\ugg
bash flash-root.sh D:\ugg-flash        # 换成你有 20GB 的盘
```

脚本会自动：下载 → 逐片校验 sha256 → 拼接 → **断言总字节数必须是 11970598900**。

> 如果脚本不能用，手动：
> ```
> gh run download 43644714094 -R honghong2011/ios-ugg -n ios16-root-parts -D parts
> cd parts && sha256sum -c SHA256SUMS
> cat ios16-root.simg.part* > ../ios16-root.simg
> stat -c%s ../ios16-root.simg      # 必须 = 11970598900
> ```

### 4.2 刷入（⚠️ 会清空 Android 数据）

```bash
fastboot getvar partition-size:userdata      # 记下这个值，应该 > 24571 MiB
fastboot -S 256M flash userdata D:\ugg-flash\ios16-root.simg
fastboot boot shim-boot-0082-mido.img
```

| 项 | 值 |
|---|---|
| 刷写耗时 | 10-15 分钟（每包 256 MB） |
| 首启耗时 | **4-8 分钟**（mido 实测；别以为挂了） |

### 4.3 期望看到

```
（前面同第一步）
SWEET UFS: "userdata" on LUN 0: first block 0x..., 24571 MiB, read-write
SWEET LOG: console log to the last 4100 KiB of the partition
hfs: Initializing the journal
BSD root: ufsroot0, major 1, minor 0
... launchd 启动 ... Early boot complete
```

然后：苹果 logo → 锁屏 → **桌面**。

---

## 5. 结果对照表

| 现象 | 含义 | 下一步 |
|---|---|---|
| 2 分钟内自己回到 fastboot | shim 拒绝启动 | 拍照给我 |
| 卡在 `LOADER` 之前的某行 | shim 阶段问题 | 拍照给我 |
| `panic: IOFindBSDRoot ... unavailable: N` | eMMC 驱动失败 | **告诉我 N 的值** |
| `Still waiting for root device`（未刷根卷） | **M2 达成** | 去刷根卷 |
| `Still waiting for root device`（已刷根卷） | 根卷没找到 | 拍照 + 告诉我分区大小 |
| 苹果 logo | M3 | 等 4-8 分钟 |
| 锁屏 | M4 | 上滑 |
| **桌面 + 触屏** | **目标达成** | 录个视频 |

---

## 6. 如果出问题，我需要什么信息

按重要性排序：

1. **屏幕照片**（最重要，一张顶几轮推测）
2. `fastboot getvar partition-size:userdata` 的输出
3. `fastboot getvar max-download-size` 的输出
4. 如果是 panic，**panic 文本的完整内容**

---

## 7. 附：一切从头重跑的命令

```bash
# 内核（CI，约 15 分钟）
gh workflow run xnu.yml -R honghong2011/ios-ugg --ref ugg-port -f machine_config=SWEET
gh run download <RUN_ID> -R honghong2011/ios-ugg -n xnu-kernel -D ci-out

# shim（CI，push 即触发，约 5 分钟）
gh run download <SHIM_RUN> -R honghong2011/ios-ugg -n shim-ugg -D shim-out

# 根卷 + device tree（CI，约 20 分钟）
#   推 .github/build-root-trigger 即可触发

# 组装镜像
./ugg/make-image.sh ci-out/kernel.development.sweet shim-out/Image
```

---

## 8. 已知的取舍（不是 bug）

| 项 | 值 | 原因 |
|---|---|---|
| `cpus=1` | 单核 | EL0 LSE 模拟器非多核原子；mido 在单核也到了锁屏 |
| `-v` | 保留 | 现在需要看内核打印诊断，稳定后会去掉 |
| 无 GPU | CPU 渲染 | 你的要求；mido 在无 GPU 时也到了桌面 |
| `sweetfb_hz=30` | 30 Hz | mido A/B 实测：60 Hz 时 App 启动但不显示 |
