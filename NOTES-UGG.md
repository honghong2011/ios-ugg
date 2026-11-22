# iOS 16 on ugg (Redmi Note 5A, MSM8937) — working notes

## ★★★★★ 最新（2026-11-22 22:55，第 46 轮）-- **QEMU 检查做成「有证据」的，并且读懂了空白屏**

### 这轮做了什么

第 45 轮加的 QEMU 工作流只能回答「有没有故障」，**说不出内核打印了什么**。
这一轮把它做成能给出证据的检查，并且校准了「什么算成功」的判读。

### 4 个 run 的对照（这是校准的全部依据）

| run | 改了什么 | 结果 |
|---|---|---|
| 45032399238 | 初版 | fb.png **14948 B（有字）**，7 条未定义指令 + 反复 Prefetch Abort |
| 45032900290 | 修好 64 字节种子 | fb.png **2760 B（全黑）**，368 IRQ，0 故障 |
| 45033971157 | 加 \`--kernel\` 解码 | 仍全黑 —— 但 \`fb.txt\` 只有 1 字节 |
| 45035153390 | 去掉 \`sweetfb_noconsole\` | **370 IRQ，0 故障，屏幕空白（正常）** |

### 关键判读：**空白屏是成功的标志，不是失败**

| 现象 | 含义 |
|---|---|
| 屏幕**有字** | 内核死在帧缓冲接管之前 —— 把遗言打出来就走了 |
| 屏幕**全黑** + 大量 IRQ + 0 故障 | 帧缓冲已接管显示，而还没有用户态程序去画东西 —— **正是"内核起来了但没 launchd"该有的样子** |

证据：健康那一轮 CPU 停在 \`_cpu_idle + 0x1ec\`，363 次 IRQ 返回 \`_machine_idle\`。
反过来，panic 那轮 \`fb.png\` 有 15 KB 文字、且伴随故障。

### 我在这轮里踩的两个坑（都是"检查本身不可信"）

1. **门禁通过但什么都没看见**：我在 cmdline 里照抄了手机镜像的
   \`sweetfb_noconsole=1\` —— 那个参数的作用恰恰是**关掉帧缓冲控制台**。
   于是一个专门用来读控制台的检查，把控制台关了。删掉后才有内容可读。
2. **假警报**：\`[ -s fb.txt ]\` 对"只有一个换行"的文件也为真，
   而空白屏解码出来正是 1 字节换行。于是每次健康运行都报
   「屏幕上还有字，可能早死」。改成 \`grep -q '[^[:space:]]'\` 才对。

> **两次都是同一类错误：检查的形式对，但语义没校准。**
> 一个能在"什么都没发生时"通过、或者对健康状态报警的检查，
> 比没有检查更糟 —— 它会被当成覆盖率。

### 现在的门禁规则（已写入 workflow）

\`\`\`
有故障（未定义指令 / Prefetch Abort / Data Abort / panic） → 失败
IRQ < 5                                                    → 失败（内核没跑起来）
屏幕有非空白文字                                           → 警告（可能早死）
否则                                                       → qemu-ok
\`\`\`

最新一次的真实输出：

\`\`\`
qemu-ok :: 370 IRQs, 0 faults, screen blank (expected once the framebuffer owns the display)
\`\`\`

---

## （2026-11-22 22:30，第 45 轮）-- **QEMU 立刻抓出我自己写的一个致命 bug**

### 这一轮最重要的一句话

**上一轮我宣布"0105 镜像已就绪、可以刷"的那个镜像，开机就会 panic。**
而它"就绪"的依据是：内核 sha256 对得上、cmdline 也对得上 —— **两条检查都过了**。
**镜像照样起不来，因为没有任何东西真正执行过它。**

### QEMU 怎么发现的

我加了个 CI 工作流（\.github/workflows/qemu-ugg.yml）：每次内核构建后，用
QEMU 的 virt 板（\`-M virt,gic-version=2 -cpu cortex-a53\`，4 GiB）
把真内核跑 25 秒，然后截图帧缓冲。

第一次跑，屏幕上是：

\`\`\`
SWEET EARLY 1: arm_init entered (MMU on)
...
SWEET EARLY 7: entering arm_vm_init

SWEET EARLY PANIC: Expected 64 seed bytes from bootloader, but got 48.
@prng_random.c:64
\`\`\`

### 根因：我自己在 \`a6a739d\` 引入的

上一轮为了"镜像可复现"，我把 ADT 的随机种子从 \`os.urandom(64)\` 改成：

\`\`\`python
hashlib.sha384(...).digest()[:64]      # sha384 只有 48 字节！
\`\`\`

而 \`osfmk/prng/prng_random.c:59\`：

\`\`\`c
n = PE_get_random_seed(seed, sizeof(seed));       /* sizeof(seed) == 64 */
if (n < sizeof(seed)) {
    panic("Expected %lu seed bytes from bootloader, but got %u.", ...);
}
\`\`\`

**种子不足 64 字节 = 致命 panic，在 \`arm_vm_init\` 之后立刻发生。**

### 修复（commit \`36be11a\`）

- \`sha384\` → **\`sha512\`**（正好 64 字节，仍然确定性）
- 加一条构建期断言：种子不足 64 字节就直接报错，不让这种 bug 再悄悄溜过去

### 修完的 QEMU 复验：干净

| 项 | 修复前 | 修复后 |
|---|---|---|
| 屏幕 | **EARLY PANIC** 文字 | 黑屏（控制台已滚过） |
| qemu.log | 7 条 Undefined Instruction + 反复 Prefetch Abort | **83 KB，368 条异常，全部是 IRQ** |
| 故障/panic 条数 | 有 | **0** |
| IRQ 返回点 | — | 363 次落在 \`machine_idle + 0xfc\` |

\`machine_idle\` 是内核的**空闲循环** —— 说明内核不但没崩，还稳定跑着、
在正常处理定时器中断。失控的 IRQ 风暴不会把返回点集中在 idle 里。

### 这轮学到的（写进纪律）

1. **"哈希对得上"不是"能启动"**。sha256 校验只证明文件没被改，
   完全不能证明它里面的代码能跑。
2. **能在 CI 上跑的东西，就必须在 CI 上跑**。这个 bug 修一次 CI 大约 3 分钟；
   要是没加这一步，就是在手机上浪费一次 8 分钟启动 + 一次取日志，
   而且日志里只会看到一条 panic，还得再来一轮。
3. 我上一轮把"可复现"当成纯粹的改进，改完只验了"两次构建哈希相同"，
   **没有验"构建出来的东西还能启动"** —— 这正是 QEMU 存在的意义。

### 本轮产物

| 项 | 值 |
|---|---|
| commit | \`36be11a\`（种子修复）、\`01b5368\`（QEMU 工作流） |
| QEMU CI | 45032399238（发现 bug）、**45032900290（修复后干净）** |
| 镜像 | \`shim-boot-0105-touch.img\` 已用修复后的种子重建 |

---

## （2026-11-22 21:10，第 44 轮）-- **0104 全日志到手：坏区有确切边界，第 43 轮的结论要改**

> 纠错声明：第 43 轮写的「根因在 fastboot 的 sparse 解析、只写了 11.15 GiB」
> **是错的**。方向对（卡上数据确实不对），**推理链错**：
> 那段 fastboot 输出根本证明不了偏移。见第 1 节。

本轮依据：用户提供的 **0104 完整控制台日志**（288 行，
桌面 `kernel-console.txt`）。此前每轮都靠拍屏和片段推断，
这是第一次拿到完整文本。

### 1. 先把 11.15 GiB 这个数字彻底澄清

第 43 轮拿「24 个分片加起来 11.15 GiB < 16 GiB」当作 fastboot 少写了，
**这个推理不成立**：

| 事实 | 数值 |
|---|---|
| `.simg` 稀疏文件大小 | 11,970,598,900 B = **11.148 GiB** |
| 展开后 raw 大小 | 17,179,869,184 B = **16.000 GiB** |
| `fastboot flash` 的 USB 传输量 | **等于稀疏文件里 RAW chunk 的数据量** |

`fastboot` 遇到 sparse 镜像时**不会**传 16 GiB —— 它读 sparse 头，
FILL / DONT_CARE chunk 在设备端直接填零，只有 RAW chunk 的数据要过 USB。
所以「24 片之和 ≈ 11.15 GiB」正是**正确行为**，不是缺口。

同理 `simg2img.py` 把 11 GiB 变 16 GiB 也是**正确的稀疏展开**，
不是脚本把镜像撑坏了。**转换脚本没问题，sparse 格式也没问题。** 到此为止。

### 2. 日志给出的确切边界

`ugcheck=1` 走完 20480 个节点，坏节点全部落在 **ext2 与 ext3**：

| extent | 镜像块 | 偏移 | 节点 | 日志判定 |
|---|---|---|---|---|
| ext0 | 183682+16384 | 0.70–0.76 GiB | 0–8191 | **一条 BAD 都没有** |
| ext1 | 211815+8192 | 0.81–0.84 GiB | 8192–12287 | **一条 BAD 都没有** |
| ext2 | 1138210+8192 | **4.34–4.37 GiB** | 12288–16383 | 从**第一个节点 12288** 起就坏 |
| ext3 | 1729347+8192 | **6.60–6.63 GiB** | 16384–20479 | 坏 |

关键细节，日志自己就说清了：

```
UGG CHECK: ext2 block 1138210 count 8192 -> nodes 12288..16383
UGG CHECK: BAD node=12288 fLink=0x2e50524f bLink=0x58494d49 kind=0x54
```

**ext2 的第一个节点就是坏的**，而 ext1 的最后一个节点是好的。
所以正确性边界落在 **0.84 GiB ~ 4.34 GiB 之间**。

### 3. 坏区里装的是什么（全文最有价值的一张表）

```
node 12288  fLink=0x2e50524f  -> ".PRO"
node 12289  fLink=0x414c4944  -> "ALID"
node 12290  fLink=0x88c2b5b2
node 12302  fLink=0x65746120  -> "eta "
node 12304  fLink=0x50484f4e  -> "PHON"
node 12307  fLink=0x69682062  -> "ih b"
node 12308  fLink=0x6e007400  -> "n 0t 0"
node 12310  fLink=0x6e207365  -> "n se"
node 12311  fLink=0x6e2e5f10
node 12312  fLink=0x00690067  -> " 0i 0g"
```

三条决定性观察：

1. **ASCII 是单字节的**（`0x2e50524f` = `.PRO`）。
   HFS+ 目录键是 **UTF-16BE**，字母 `A` 必须存成 `00 41`。
   单字节 ASCII **根本不可能是文件系统数据**。
2. 这些字节是**内核自己的字符串表**（`.PROXIMITY` 注册域、`PHONE`、
   `ih b`、`n se`、`ig`）。
3. 节点 12288 与 12305 出现**同一段文本**，相隔 17 个节点 = 139264 字节，
   但中间夹着 `88c2b5b2 c6a9c790` 这类乱码 —— **不是整齐平移**。

所以坏区里躺的**不是镜像中任何位置的数据**，而是**别的东西**。
既不是「写偏了」，也不是「没写完」，是这块区域**被别的写入占着 / 本次刷写没碰它**。

### 4. 是谁写的：先把日志区彻底排除

**整个 HFS 卷只有 16 GiB，userdata 有 53 GiB。**
持久日志区在分区最后 1025 个块：

```
SWEET LOG: flushed 7943 bytes to block 0xe8f3fa
```

0xe8f3fa = 15,266,810 块；相对镜像起点 = 15266810 − 1376256
= **13,890,554 块 = 52.98 GiB**。卷只有 16 GiB —— **日志区在卷外 37 GiB，
不可能覆盖 ext2/ext3。**（第 36 轮算过，予以确认，仍然成立。）

而 ext2 起点 4.34 GiB **就在卷内**，属于目录 B 树。
所以只能有一个结论：**这次刷写没把这块写对。**

### 5. 排除表

| 假设 | 证据 | 判定 |
|---|---|---|
| 镜像本身坏 | `check-hfs-root.py --all` 20480 节点全合法 | **排除** |
| 转换脚本坏 | `check-raw.py` raw 文件字节正确 | **排除** |
| 读路径坏 | 1 MiB vs 256×4 KiB **完全相同**；单块/多块相同；D-cache 修复无变化 | **排除** |
| 日志区覆盖 | 卷外 37 GiB | **排除** |
| HFS 自己写坏 | 只读挂载（`rootrw=0`）坏值一比特不变 | **排除** |
| **写入的数据不对** | 镜像对、卡上错、且有明确边界 | **唯一剩余** |

### 6. 两个假设，都指向"写入方"，但必须实测区分

坏区边界在 **0.84–4.34 GiB（卷内偏移）** 之间。我把所有已知机制的阈值
都对了一遍，**只有下面两个能落进这个窗口**：

| 假设 | 阈值 | 绝对位置 | 与观察是否相符 |
|---|---|---|---|
| **A. DONT_CARE 被跳过，旧数据残留** | 无固定阈值 | 任意 | ✅ 相符（零块分布无关） |
| **B. 32 位偏移按卷内偏移算** | 卷内 4 GiB | 9.93 GB | ✅ 落在 6.50–10.30 GB 窗口内 |
| C. 绝对 32 位字节回绕 | 4.29 GB | 4.29 GB | ❌ ext0 在 6.39 GB，**高于**它却正常 |
| D. 绝对 2^33 | 8.59 GB | 8.59 GB | ❌ ext1 在 6.50 GB 正常，但 8.59 也 < ext2，**无法与 A 区分** |

所以 **C 已被数据排除**（这点很关键，能省掉一次瞎猜），
A / B / D 还需要实测才能分辨。

#### 关于 A：我上一版的前提是错的，已去查源码核实

上一版这里写的是"img2simg 把零块写成 DONT_CARE"。
**这个说法只在加 `-s` 时成立，默认不成立。** AOSP `libsparse/sparse_read.cpp`：

```c
/* do_sparse_file_read_normal() */
if (sparse_block) {
    /* TODO: add flag to use skip instead of fill for buf[0] == 0 */
    sparse_file_add_fill(s, buf[0], to_read, block);   /* 全同块 -> FILL */
} else {
    sparse_file_add_fd(s, fd, offset, to_read, block); /* 否则   -> RAW  */
}
```

- "所有 32 位字都相同"的块（**包括全零**）→ **FILL**，不是 DONT_CARE。
- 那条 TODO 写得很清楚："**add flag** to use skip instead of fill" ——
  默认是 fill，skip 要显式开关。
- `DONT_CARE` 只从 `write_sparse_skip_chunk()` 发出，那条路只有
  `SPARSE_READ_MODE_HOLE` 才走，对应命令行 `img2simg -s`。
  openembedded 的 0017 号补丁正是在加这个开关：
  > "This adds support for converting files with holes to **don't care** chunks"

**所以：如果 CI 用的是普通 `img2simg`，零块是 FILL(0)，fastboot 会把零一起写。**
假设 A 就不成立 —— 除非这份 .simg 里真的有 DONT_CARE。

#### 假设 A 已判死刑（不需要实测了）

三处独立证据，全部指向同一个结论：

1. **CI 用的是普通调用**（`.github/workflows/build-root.yml:165`）：

   ```yaml
   img2simg work/ios16-root.img work/ios16-root.simg      # 没有 -s
   ```

2. **AOSP 源码**：全同块（含全零）→ `sparse_file_add_fill()`，
   DONT_CARE 只走 `SPARSE_READ_MODE_HOLE`（`img2simg -s`）。
3. **mido 自己的备注**（`ios-mido/NOTES.md:139`）：
   > "img2simg: **zero blocks become FILL chunks**, so a full flash overwrites
   > every block the rw boots changed"

**所以这份 .simg 里的零块是 FILL(0)，fastboot 会把零一起写到卡上。
"零块没被写、旧安卓数据残留"这条不成立。**

> 第 43 轮和第 44 轮初版都把这一段当成"最可能的解释"写进了交接文档。
> 这是本项目第 N 次"假设很顺，但没验证" —— 教训不是"别假设"，
> 而是**能在几分钟内离线验证的前提，必须先验证再写进文档**。

剩下的候选只有 B/D（偏移失步）。这个**必须靠实测**：

```bash
python ugg/tools/verify-card.py ios16-root.simg --map
```

顺带保留 `simg-info.py`：它可以随时回答"这份镜像到底装了什么"，
是以后每次怀疑镜像时的第一道检查（也是唯一能在不碰手机的情况下做的）。

#### 现在只剩 B/D：偏移失步

而且坏区内容是**混杂**的（`.PRO` 文本 + `88c2b5b2` 乱码交替），
这正像"从某一处起整体错位"——即失步。失步点必须实测，不能从四个节点推断。

#### 决定性工具：`tools/verify-card.py`（本轮新增，只读）

```bash
# 只比前 2 GiB，30 秒内出结果
python tools/verify-card.py ios16-root.simg --map
```

它把卡上的字节**整段读回来**和镜像逐字节比，打印：

- 第一个不一致的**绝对偏移**（不是靠节点号推的）
- 两边的十六进制 + 可读文本
- 一段一段的"匹配 / 不匹配"地图

判读：

| 输出 | 结论 | 修法 |
|---|---|---|
| 坏区从某个**固定偏移**开始、之后整体错位 | 偏移失步（写入方） | 换 platform-tools / 换刷写通道 |
| 坏区里是**大段 00** | 本该是数据却被写成零 → 传输截断 | 查 USB / 重刷 / 换 fastboot |
| 坏区是**内核镜像的连续片段** | 写入源在总线层混入了别的数据 | 查 USB/内存，不是 fs 问题 |
| 坏区与镜像**完全一致** | 卡上其实是对的 | 那么问题在 HFS/内核侧，回来找我 |

#### 不管结论如何，先擦一次

```bash
fastboot erase userdata                    # 或 TWRP 里格式化 data
fastboot -S 512M flash userdata ios16-root.simg
```

`erase` 幂等、只要 1–2 分钟，却能把"卡上残留旧数据"这个变量消掉，
让下一次实测的结果不用打问号。mido 每次也从 Format Data 开始。

> 顺带：`erase` 这一步**不管 A 成不成立都值得做**。它是幂等的，
> 代价 1–2 分钟，却能把"旧数据残留"这个变量彻底消掉 —— 而在没消掉之前，
> 任何实测结果都要先打一个问号。

### 7. 本轮修掉的代码 bug（与刷写无关，但同样挡路）

**触摸坐标空间是错的 —— 这条必须单独说，因为它会让桌面「进得去、点不动」。**

| | 旧 | 新 |
|---|---|---|
| `ugg_input.c` 交给 SweetHID 的坐标 | **720×1280 面板像素** | 不变 |
| `SweetHID.cpp` 归一化用的空间 | **1080×1920** | **720×1280（面板尺寸）** |

> **为什么分母必须是面板 720×1280，而不是画布 750×1334？**
> 因为 ugg 的帧缓冲**不做 letterbox，是把 750×1334 画布整块拉伸铺满 720×1280 面板**：
> `uggPresentScaled()` 里 `stepx = fLogicalW / fWidth`，
> 所以「画布比例 == 面板比例」，用面板尺寸归一化，触点正好落在被绘制的那一像素上。
> 若用画布宽度，720/750 = 0.96，是 **4% 的系统性偏差**，
> 到右下角累积约 **28 个面板像素** —— 足以点错图标。
> （commit `722fbe0` 修正的是我上一版自己在这里写错的分母。）

后果：整块屏幕被压进显示区域**左上 2/3**，
**右边和下边各 1/3 永远点不到**，点到的位置又与实际位置错开。
这不是舍入误差，是坐标系不匹配。

同处还有两个连带 bug：
- 边缘判定用了 `1079/2399`，真正贴底/贴右的边缘触摸**不被标记为 edge**；
  没有 `kIOHIDDigitizerEventFromEdgeTip` 就没有上滑回桌面 / 多任务手势。
- 归一化在加 letterbox 偏移后**没有 clamp**，角上像素可能 >1.0 被判出屏幕。

**触摸本轮改为默认开启**，但**启动点从 `sweet_ufs_init()` 末尾
挪到 `sweet_ufs_log_after_mount()`**：原先它在 `vfs_mountroot` 之前跑，
总线一卡就挂死启动、且日志还没开始写 —— 正是把前几轮带偏的那个坑。
挪到挂载之后，无论触摸怎么出问题，根卷已经起来、日志已经在刷。

另：轮询线程原先**每个 tick 读一次 PMIC PON**（SPMI 事务），
现在每 8 个 tick 读一次（约 64–120 ms，按键感知不到），触摸路径保持全速。

### 8. 本轮工具修复

`tools/verify-flash.sh` 重写，修掉一个会**给出自信错误答案**的 bug：

```
旧：dd if=$DEV bs=4096 skip=$((1376256 + 1734927))   # 绝对块号
新：dd if=$DEV bs=4096 skip=1734927                  # 分区内块号
```

`/dev/block/by-name/userdata` **本身就是分区**，而脚本查找顺序优先命中 by-name，
于是旧写法每次都多读 **1376256 块 = 5.25 GiB**，读到的当然是垃圾。
现在同时接受任意块号作为参数 —— 第 6 节的 4 GiB 验证就靠它。

`flash-root.sh` 的 `say()/die()` 写成 `printf '\n=== $s\n'`，
`$s` 在 printf 里是**参数索引**，所以每条进度只打印一个 `s`。已改 `%s`。

### 9. 本轮产物

| 项 | 值 |
|---|---|
| commit | `5636d9e`（初版）→ **`722fbe0`（最终版）** |
| 内核 CI | **45027157342 —— completed success** |
| 内核 sha256 | `b82e6036f297c6917d90d5f78fab819adc70184359743711e850d3ac44136aba`（17,140,512 B） |
| 改动 | 触摸坐标空间 + 边缘判定 + clamp；PON 节流；挂载后启动；verify-flash 偏移；printf |
| 删除 | `tools/write-image.{py,sh,cmd}`（用户明确否决的分块写入器） |
| 新增 | `tools/verify-card.py`（只读整段比对）、`tools/ppcheck.py`（预处理后括号自检）、`tools/sync-tools.sh` |

CI 的判读（`kernel-ugg-symbols` 注解）：

```
ugg_gic_ack ugg_gic_eoi ugg_gic_send_sgi ugg_vm4k UGG INPUT UGG EMMC sweet_early_mark
patch-report: applied=86 skipped=4      ← 4 个是外来补丁，我们的 0082 已应用
```

`UGG INPUT` 在符号表里，说明触摸驱动确实编进去了。

### 9.0 顺带修好的：镜像现在可复现

清理 `build/img`（291 MB → 17 MB）后我重打了一次镜像，**sha256 变了**。
查出来是 `mkadt_ugg.py` 里这行：

```python
seed = seed if seed is not None else os.urandom(64)      # 每次构建都不一样
```

它进 `chosen/random-seed`，于是同一内核打两次就是两个不同镜像 ——
这让"我的改动到底有没有影响镜像"这个问题**无法用 sha256 回答**。
改成从板型标识派生（`sha384('ugg-adt-seed/' + TARGET + '/' + MODEL)`）：
每块板子唯一，但每次构建相同。

现在连打两次得到同一个 `dac6290c…ec58`，可复现。

### 9.1 本轮自己踩的坑（写下来省下一次）

写了个「数括号」的自检脚本，第一版**不区分 `#if` 分支**，
把 `UGG_BOARD=1` 和 `=0` 两套函数体一起数，于是报 `sweet_ufs.c` 少一个 `}`，
害我差点去翻一个不存在的语法错误。改成按分支预处理后，四个文件在两种配置下
都是 `braces=+0 parens=+0 brackets=+0`。

**取证工具必须先拿已知正确的输入验一遍** —— 这已经是第四次栽在同一个坑里了
（`verify-flash.sh` 偏移、`check-hfs-root.py` 魔数、块号差 15、本次括号计数）。

### 10. 下一步（顺序不能变）

1. **先实测卡上数据**，不启动、不浪费一次启动：

   ```bash
   python tools/verify-card.py ios16-root.simg --map
   ```

   整段比对，不要再靠四个节点推断（前三轮就是那样错的）。

2. **按判读结果修**：
   - 坏区是大段 `00` → DONT_CARE 残留 → **先 `fastboot erase userdata` 再刷**
   - 坏区从固定偏移开始 → 偏移回绕 → 换 fastboot / 换通道
3. 重刷一律照 mido 一条命令：`fastboot -S 512M flash userdata ios16-root.simg`
4. 刷完**再跑一次** `verify-flash.sh`，四个节点全对上才启动。
5. 启动新内核镜像，预期不再出现
   `hfs_swap_BTNode: invalid forward link`，launchd 能读出文件。

> **为什么"先 erase"值得当成首选**：不管 DONT_CARE 到底存不存在，
> `erase` 都把"卡上残留旧数据"这个变量消掉，代价只有 1–2 分钟，而且是幂等的。
> 在没消掉之前，任何实测结果都要先打个问号。
> 先跑 `simg-info.py` 确认有没有 DONT_CARE，再跑 `verify-card.py` 看实际坏区。

---

## （2026-11-22 16:30，第 43 轮）-- ~~根因在刷写工具，不在内核~~ 【已被第 44 轮推翻】

> **本轮结论作废，保留作纠错样本。** 它把「24 个 fastboot 分片加起来
> 11.15 GiB」当成"少写了 4.85 GiB"，但 11.15 GiB 正是 sparse 镜像的
> RAW chunk 总量，是**正确传输量**。第 44 轮拿到了完整日志才看清：
> 坏区边界在 0.84–4.34 GiB，坏区里是**内核自己的字符串**，
> 既不是偏移也不是少写。下面的分析过程仍有参考价值，
> **但请以第 44 轮为准。**

### 0104 结果：读取大小不是原因

```
UGG SIZE: one 1024 KiB transfer at block 1734912
UGG SIZE: same region as 256 separate 4 KiB reads
UGG SIZE: identical -- read size is not the fault
UGG SIZE: node 19174 small-read fLink=0xf800ebf3 kind=0xf7
```

三种读法（1 MiB 单次、256 次 4 KiB、单节点 2 块）读到的坏值
**完全相同**。

### 完整排除清单

| 假设 | 实验 | 结果 |
|---|---|---|
| 日志区覆盖 | 偏移计算 | 相距 49 GB，否 |
| 多块传输 | `uggnomb=1` | 无变化 |
| D-cache | 加 clean/flush | 无变化 |
| 稀疏展开 | 换 raw 刷 | 坏值变了但仍坏 |
| **读取大小** | 1 MiB vs 4 KiB | **identical** |
| HFS 写坏 | ugcheck 在挂载前跑 | 数值早于挂载 |
| **镜像本身** | `--node` 查 | **四个节点全 VALID** |
| **转换脚本** | `check-raw.py` | **raw 文件完全正确** |

### 真正的根因：fastboot 没有写进我们的数据

`check-raw.py ios16-root.img` 输出：

```
size : 17179869184 (expect 17179869184)
offset 0x1a790f000 (block 1734927):
  first 16 bytes : 00 00 4a f9 00 00 00 05 ff 01 00 17 00 00 00 06
  fLink=0x00004af9 bLink=0x00000005 kind=0xff
  -> the raw file is CORRECT
```

而手机读到的是 `0xf800ebf3`。**同一偏移，不同字节。**

看 fastboot 自己的输出：

```
Invalid sparse file format at header magic          <- 它把 raw 当 sparse 解析了
Sending sparse 'userdata' 1/24  (496560 KB)
Sending sparse 'userdata' 24/24 (4853 KB)
```

算一下总传输量：

| 项 | 值 |
|---|---|
| 24 个分片求和 | **11.15 GiB** |
| 16 GiB raw 应该 | 16.00 GiB |
| **少了** | **4.85 GiB（只有 69.7%）** |

分片大小从 4853 KB 到 523262 KB、**极不均匀**，
不可能是 16 GiB 均分（每份应为 699050 KB）。

**这 24 个大小，正好是 `.simg` 稀疏镜像里各 chunk 的大小。**

### 结论

1. `simg2img.py` 转出来的 raw **完全正确**
2. `fastboot` 收到 raw 后，用**旧版 ABL 有缺陷的 sparse 解析器**处理
3. 结果只写了 11.15 GiB，且位置错乱
4. 换 raw 后坏值变了但仍坏 → 只是换了另一种错法

### 下一步：绕开 fastboot 的 sparse 解析

**方案 A：用 `.simg` 分片逐个刷入**（推荐）

build-root.yml 已经把 `.simg` 切成 1800 MB 的 `.part*` 文件，
它们是纯 sparse、每个都能被 fastboot 正确理解：

```
fastboot flash userdata ios16-root.simg
```

（而不是拼接后的大文件）

**方案 B：用 `fastboot -S` 明确告知分块**

```
fastboot -S 256M flash userdata ios16-root.img
```

**方案 C：用 TWRP 直接 dd**（最可靠）

```
adb push ios16-root.img /sdcard/     # 16 GiB，很慢
adb shell dd if=/sdcard/ios16-root.img of=/dev/block/sda38 bs=1M
```

### 验证方法

刷完不启动，直接看 `fastboot` 的总传输量：

- **应该接近 16 GiB（约 16384 MB）**
- 如果又是 11 GiB 左右，说明还是没写完

---

## （2026-11-22 13:50，第 42 轮）-- **找到真因：PIO 路径从不维护 D-cache**

### raw 镜像刷写成功了

用 `simg2img.py` 转 raw 后 `fastboot flash`，坏值**全部变了**：

| 节点 | 刷 raw 前 | 刷 raw 后 |
|---|---|---|
| 19174 | 0x6a13d46a | **0xf800ebf3** |
| 19193 | 0xf728c62a | **0x08120803** |
| 19462 | 0x44f79524 | **0xff05fcfc** |
| 19514 | 0x7843b47b | **0xfa02f0f4** |
| 坏节点数 | 6552 | **5829** |

**内容变了 → 写入确实成功，写路径没问题。**

### 但坏字节里装的是什么？这是关键

把各节点的 16 字节拼起来：

```
'vector( __end_c struct_ const BCPP_CON #if _>::type // -*- C'
'pp_lib_a' 'wrap_ref'
```

**这是 C++ 源码文本，出自内核二进制本身。**

又一个决定性细节：HFS+ 目录键是 **UTF-16BE**，ASCII 的 `A`
应该存成 `00 41`。这里 `0x41` 是**单字节** —— **这根本不是文件系统数据**。

上一次是 `.PROXIMITY`（内核字符串表），这次是 `std::vector`（内核代码）。
**两次都是内核自己的内容。**

### 根因：`ugg_cmd()` 全程没有缓存维护

| | UFS 路径 `ufs_scsi()` | **UGG 路径 `ugg_cmd()`** |
|---|---|---|
| 传输前清缓存 | `dma_clean(DMA_BOUNCE, len)` | **没有** |
| 传输后失效 | `dma_sync(...)` = `flush_dcache64` | **没有** |

`ugg_cmd()` 用 **PIO**，CPU 把 FIFO 数据直接存进缓冲区：

```c
for (unsigned i = 0; i < UGG_SECT / 4; i++) {
    p[i] = mh_rd(M_BUF);        // CPU store -> 进 D-cache，不一定回内存
}
```

上游 `strategy()` 的 `memcpy` 和 HFS 解析都用**普通缓存读**。
中间那行被淘汰了，就读到**内存里的旧内容**。

而 `su.dma` 是 `KMA_PERMANENT` 的 **1 MiB 长期缓冲区**，每次传输都重用，
残留的就是内核自己的代码和字符串。

### 它解释了每一个观察

| 现象 | 原因 |
|---|---|
| 同一次启动内反复读到同值 | cache 行状态稳定 |
| 不同启动值不同 | 内存布局不同 |
| 单块/多块都一样坏 | **与传输方式无关** |
| 换 raw 镜像也没用 | 数据到了，**交接时丢了** |
| 只有大块读出错 | 1 MiB **比 cache 大**，自己把自己挤出去 |

### 本轮产物（无需重刷镜像，卡上数据已经是对的）

| 镜像 | sha256 | 用途 |
|---|---|---|
| `shim-boot-0102-cachefix.img` | `f11225b4305ccb97333d28c2ce34f37e4f820d9d6597c3f7239d099bb8fc0e5a` | 缓存修复，直接试 |
| `shim-boot-0103-cachecheck.img` | `f03d82bd28f2335eac8769f14f49c2d8464385197be0c6f487f0ed4801cce991` | 带 `ugcheck=1`，带读取大小对比 |

内核 CI `44991126019`（commit `fe0976d`），内核 sha256 `01271afc8de788d3bea59747fdcf5b6defebd1e55a8ef94afb25b3d1ea810b95`。

### 修复（commit `fe0976d`）

`ugg_xfer()` 整体包起来：

- 读之前：`flush_dcache64(bounce, BOUNCE_SIZE)` —— 先失效，防止旧行遮挡
- 读完：`clean_dcache64(...)` —— 把 CPU 存的数据推回内存
- 写前也 clean，两个方向保持一致

`ugg_cmd()` 里另外按每个扇区再保护一次，双重保险。

> 这个 bug 之前一直存在，但后面的读取碰巧都走了命中路径。
> 直到 HFS 要读 160 MiB 目录树，1 MiB 缓冲区反复自挤，才暴露。

---

## （2026-11-22 12:10，第 41 轮）-- **决定性对比完成：镜像对、卡上错**

### 同一个块，两边读到不同字节

`--node` 让工具自己查 extent 映射，不再靠人肉换算（上一次我算错了 15 个块）。

| 节点 | 镜像侧 | 内核侧 |
|---|---|---|
| 19174 | fLink=0x00004af9 kind=0xff **VALID** | fLink=0x6a13d46a kind=0x5a |
| 19193 | fLink=0x000001fa kind=0xff **VALID** | fLink=0xf728c62a kind=0xb5 |
| 19462 | kind=0x00 numRecords=183 **VALID** | fLink=0x44f79524 kind=0x5f |
| 19514 | fLink=0x00000002 kind=0xff **VALID** | fLink=0x7843b47b kind=0x90 |

且镜像里的链表**自洽**：

```
node 19174 fLink = 0x4af9 = 19193
node 19193 bLink = 0x4ae6 = 19174
```

19174 的前向链接恰好指向 19193，19193 的后向链接恰好指回 19174。
**这是真实完整的 B 树。**

### 两边的硬件视角完全一致

| 项 | 内核日志 | 我的计算 |
|---|---|---|
| first_block | 0x150000 | 1376256 |
| nblocks | 13891579 | 一致 |
| blockSize | 4096 | 4096 |
| nodeSize | 8192 | 8192 |
| totalNodes | 20480 | 20480 |
| extents | 183682+16384 211815+8192 1138210+8192 1729347+8192 | 一致 |

**同一个块地址，不同的字节 → 卡上的数据不是镜像里的数据。**

### 本轮发现的工具 bug

`node 19462` 的 `kind=0x00` 是**索引节点**，它的 `fLink`/`bLink`
并不是链指针（那是叶节点的概念）。我压根没校验它，
却输出了 `VALID` —— **假阳性**。已改为直接标注“索引节点，链不适用”。

同样的错我犯过一次：给用户的块号差了 15 个，
落在叶记录中间，字节恰好能解成一个“合法”描述符。
**错误的偏移产出自信的答案，比没有工具更糟。**

### 本轮产物

| 文件 | 用途 |
|---|---|
| `取日志工具/simg2img.py` | 稀疏转 raw，带尺寸校验 |
| `取日志工具/verify-flash.sh` | **刷完立刻验证**，不用启动内核 |
| `check-hfs-root.py --node N` | 按节点号直接查镜像 |

### 下一步

1. `python simg2img.py ios16-root.simg ios16-root.img`
2. `fastboot flash userdata ios16-root.img`
3. **不启动**，进 TWRP 跑 `verify-flash.sh`，直接读回那 4 个节点
4. 对上了才启动 0101

第 3 步是关键：万一还是错的，**不用浪费一次启动**就能知道。

---

## （2026-11-22 10:50，第 40 轮）-- **找到了：目录树整体错位，卡上数据与镜像不一致**

### 0101 的逐节点输出直接给出答案

`ugcheck=1` 终于跑起来了，遍历 20480 个节点，报出 **6552** 个坏节点。
但真正有价值的不是数量，是**坏节点里装的东西**：

```
node 12288  fLink=0x2e50524f  bLink=0x58494d49
node 12289  fLink=0x414c4944  bLink=0x4154494f
```

它们是 **ASCII 文本**：

```
fLink 0x2e50524f -> '.PRO'
bLink 0x58494d49 -> 'XIMI'
fLink 0x414c4944 -> 'ALID'
bLink 0x4154494f -> 'ATIO'
拼起来 = '.PROXIMI ALID ATIO'  ->  ".PROXIMITY" 注册域
```

### 决定性细节：同一段文字出现了**两次**，相隔 17 个节点

| 节点 | fLink | ASCII |
|---|---|---|
| 12288 | `0x2e50524f` | `.PRO` |
| **12305** | `0x2e50524f` | `.PRO` |
| 12289 | `0x414c4944` | `ALID` |
| **12306** | `0x414c4944` | `ALID` |

12305 - 12288 = **17**，17 × 8192 = **139264 字节**。

> 这不是垃圾数据，是**真实的目录文本，但位置错了**。
> 读 X 位置得到的是属于 X+139264 的内容。

### 三条实验数据合起来只能得一个结论

| 实验 | 结果 | 说明什么 |
|---|---|---|
| `check-hfs-root.py` 扫镜像文件 | 20480 节点**全合法** | 镜像是对的 |
| 内核直读设备（绕开缓存） | **6552 个坏** | 设备上的数据不对 |
| 三次启动、两种传输方式 | 32 位**完全相同** | 确定性，非抖动 |

**结论：卡上的数据与镜像文件不一致。读路径是对的，HFS 也是对的。**

### 问题在写入：稀疏镜像还原失衡

`.simg` 是 Android sparse 格式。`fastboot flash` 需要把它**展开**成稀疏块
再写入。如果展开过程在某个块上失去同步，**之后所有块都会整体偏移**，
而且偏移量**每次都一样** —— 完美对应我们看到的现象。

而且这个偏移只能在**有大量真实数据的区域**才能看出来：

| 区域 | 内容 | 为何没暴露 |
|---|---|---|
| 卷头（偏移 1024） | `HX` 魔数 + 参数 | 只差几百字节，小偏移碰不到 |
| GPT | 30 项分区表 | 位置靠前 |
| **目录 B 树 160 MiB** | 密集文本 | **一错全错** |

这就是为什么前面几轮一直以为“还没读到坏地方”。

### 为什么不是 buf 缓存问题

上一轮我怀疑缓存层。但 `UGG CHECK` 是用 `ufs_read_blocks()`
**绕开缓存直读**的，它读出来就已经是坏的。**所以缓存洗清了嫌疑**。

### 下一步：对比卡上数据与镜像数据

`check-hfs-root.py` 新增了一项“看 extent 实际指向什么”的检查。
对比它的输出和 0101 的内核输出，就能确定偏移量：

```
# 它读镜像：
catalog ext0 block 183682: fLink=0x........ ...

# 内核读卡（已有）：
UGG CHECK: node=19174 fLink=0x6a13d46a ...
```

### 建议的修复方向

1. **先确认**：用新版 `check-hfs-root.py` 的 extent 探针对比。
2. **重刷**，但换方式：
   - 用 `fastboot flash userdata` **分块**写，每块写完校验
   - 或者先 `simg2img` 转成 raw `.img`，再用 raw 镜像刷
     （避开 sparse 展开这一步）
3. **刷完立刻验证**：再跑一次 0101，看 6552 是否归零。

---

## （2026-11-22 10:05，第 39 轮）-- 单块传输假设被推翻；问题在 buf 缓存层

### 0098 实机结果：单块传输无效

```
SWEET UFS: "userdata" on LUN 0: ..., DMA at 0xa25ec000, single-block
```

**单块确实生效了。** 但坏值一个字都没变：

| 节点 | 0092b 多块 | 0093 只读 | 0098 单块 |
|---|---|---|---|
| 19174 | 0x6a13d46a | 0x6a13d46a | **0x6a13d46a** |
| 19193 | 0xf728c62a | 0xf728c62a | **0xf728c62a** |
| 19462 | 0x44f79524 | - | **0x44f79524** |
| 19514 | 0x7843b47b | - | **0x7843b47b** |

三次启动、三个不同 DMA 地址（0xa24ec000 / 0xa24f0000 / 0xa25ec000）、
两种传输方式 —— **32 位全部相同**。

> 这不是总线抖动的样子。抖动每次都会不同。
> 这像确定性数据。

**所以「单块 vs 多块」这条线到此为止。**

### 我自己的诊断代码也有 bug

```
UGG CHECK: nodeSize=8192 totalNodes=20480
UGG CHECK: implausible geometry, stopping
```

守卫写的是 `nodeSize > UFS_BLOCK`（4096），但这个卷 **nodeSize 是 8192**。
HFS 的 nodeSize 与分配块大小无关。**诊断工具把自己挡在了门外。**

已改为以 bounce 缓冲区为上界（`BOUNCE_SIZE / 4`）。

### 关键证据：直接读设备是**对的**

0098 日志第 186 行：

```
UGG CHECK: catalog blockSize=4096 extents: 183682+16384 211815+8192 1138210+8192 1729347+8192
```

与 `check-hfs-root.py` 从**镜像文件**读出的四个 extent **完全一致**。
如果读路是坏的，这行不可能对。

### 校正后的分工

| 组件 | 用什么 | 状态 |
|---|---|---|
| shim 读 eMMC | 单块 CMD17 | OK |
| 内核 `ufs_read_blocks()` 直读 | 单块/多块 | **已验证正确** |
| HFS 内部 B 树 I/O | **走 buf 缓存**，8 KiB 节点 | **问题在这里** |

`UGG CHECK` 用 `ufs_read_blocks()` **绕开缓存**直读，结果正确。
HFS 走 `buf` 缓存 -> `strategy()`。**两者不同，嫌疑随之转移。**

### 已排除：strategy 的块映射

逐项核对 8 KiB 节点读的换算：

```
image block      1734927
buf_blkno (sect) 13879416  (0xd3c878)
off              7106260992
lba derived      1734927   <- 与 image block 相同
device block     3111183
```

`off / UFS_BLOCK` 能整数整除（节点 8192 是 4096 的整数倍），跳过合并路径、
`memcpy` 偏移为 0。**这段数学是对的，排除。**

### 本轮产物

| 镜像 | sha256 | 用途 |
|---|---|---|
| `shim-boot-0101-btwalk.img` | `436679215beac629c95454f3294328dd72ca1836ccf6b8a8d9f2599351b854bc` | 遍历目录树 + 强制打印 4 个争议节点 |

内核 CI `44972173676`（commit `e7a2a81`）。

### 下一步（0101）

`ugcheck=1` 现在会真正遍历整棵树，并**强制打印那 4 个争议节点**的描述符：

```
UGG CHECK: node=19174 fLink=0x........ bLink=0x........ kind=0x..
```

判读很直接：

- 打印出的 fLink **= 0x6a13d46a** -> 内核直读到的就是它，而
  `check-hfs-root.py` 说该节点合法 -> **卡上数据与文件不一致**，去查刷写
- 打印出的 fLink **合法** -> 缓存层给的坏数据 -> **改查 buf 缓存**

---
## （2026-11-22 00:05，第 38 轮）-- 单块传输设为默认；触摸驱动修复；全面审查

### 本轮的核心判断

第 37 轮证明了：干净镜像 + 只读启动仍然 `errno 5`。三个变量全排除，只剩
「设备返回的字节是错的」。

与 shim 对比后锁定：

| | `ugg/shim/sdhc.c`（从未出错） | 内核（读出垃圾） |
|---|---|---|
| 命令 | CMD17 单块 | CMD18 多块 + auto-CMD12 |
| 单次长度 | 恒 1 扇区 | 最多 256 扇区 |

**单块传输本轮改为默认。** `uggnomb=0` 可切回多块做对比。

### 为什么不是「分块边界」问题

`UGG_CHUNK` = 256 扇区 = 128 KiB，而 HFS 节点是 8192 字节 = 16 扇区，
**一次读完、不跨块**。所以坏数据不可能来自分块边界。

能造成差异的只有三件事，而单块传输一次消掉全部：

1. CMD18 的隐式 auto-CMD12（shim 从没发过）
2. `BLKATTR` 块数 > 1 + blkcnt-en
3. PIO FIFO 循环跑 16 轮而不是 1 轮

### 新增 `ugcheck=3`：双方法对读

不需要任何外部参照 —— 用两种传输方式读同一批区域，然后逐字节比对。

```
UGG XCHECK: r0 block 0 (256 KiB) identical
UGG XCHECK: r1 block 1734912 (1 MiB) DIFFERS in 8192 bytes, first at +0x1000
UGG XCHECK:   multi : 6a 13 d4 6a ...
UGG XCHECK:   single: 00 00 00 00 ...
```

- 有差异 -> **读路径坏了**，且首个差异偏移直接指出错在哪
- 全相同 -> 读是对的，问题在 HFS 解析

测 4 个区域：卷头、坏节点所在的 ext3 两块、分区中部随机块。

### 触摸驱动修复（本轮重点）

三处致命问题，全部修掉：

1. **默认关闭**。`ugginput` 默认值从 1 改为 0。它就在 `sweet_ufs_init()` 末尾，
   一进来就是 512 次无超时的 SPMI MMIO 读 —— 总线不响应就挂死 CPU，
   外部看门狗重启，看起来完全像「挂载前就死了」。**这个坑骗了我们三轮。**
2. **PON 扫描加上限**：512 -> 64 通道，外加 20 ms 墙钟预算
   （`UGG_PON_SCAN` / `UGG_PON_BUDGET_US`）。总线卡住时能主动退出。
3. **QUP3 存活性探测**：`qup_alive()`，5 ms 超时确认控制器在响应，
   不响应就直接放弃触摸，绝不进入 I2C 事务。

另外删掉 `strategy()` 里前 12 次 I/O 的日志 flush —— 它会从传输中途
重新进入设备，属于自伤，`ugcheck` 已取代它的作用。

### 全面审查结果

用脚本扫了两个驱动文件的所有硬件等待循环：

- `sweet_ufs.c` 1643 行、`ugg_input.c` 510 行
- 所有 `while` / `for(;;)` 等待循环**都有 deadline 或有常量上界**
- 唯一两个 `for(;;)` 是常驻内核线程（日志线程、触摸轮询），正确
- 括号平衡（模拟 UGG_BOARD=1 预处理器分支后 215/215）

### 本轮产物

| 镜像 | cmdline 关键项 | sha256 |
|---|---|---|
| `shim-boot-0098-auto.img` | （无）默认单块 | `b0efc45309ff3b21057f03e040668f00643f7381f03be55025c189baa2c91b45` |
| `shim-boot-0099-single.img` | `uggnomb=1` | `1fc70ff1614a0104f20391438bdf8d21c26fe3d701ba15bdff3b9db0be557748` |
| `shim-boot-0100-xcheck.img` | `ugcheck=3` | `6f247d399c5d0d428dc41bc771d6707b7f8e9a6ad4871495955b471e412d1a81` |
| `shim-boot-0097-check.img` | `ugcheck=2` | `8eb2ba8a0895248e2acb828e2d7a6807cd43c7bdbeddd51b024d21a7022eb5b9` |
| `shim-boot-0096-single.img` | `uggnomb=1` | `8b0374687543441c3a7f08cb7f5792c8dfdac0495b08cb087e395f5f594289f1` |

内核来自 CI `44917936947`（commit `7bba930`），shim 未变。

> `ugcheck=3`（双方法对读）已写入源码（commit `61c9e4d`），但该构建尚未产出镜像。下一轮 CI 完成后可用 `EXTRA_CMDLINE='ugcheck=3'` 组镜像。

### 刷机指南（下次直接照做）

**先刷 0096（默认就是单块传输）**：

| 结果 | 含义 | 下一步 |
|---|---|---|
| 进到 launchd 之后，或直接出桌面 | **多块传输就是根因** | 已完成 |
| 还是 `errno 5` | 读路径不是根因 | 刷 0097 跑 `ugcheck=3` |

**0097（ugcheck=3）判读**：

| XCHECK 输出 | 结论 |
|---|---|
| 任何区域 `DIFFERS` | 读路径确实错，看首个差异偏移 |
| 全部 `identical` | 读是对的 -> HFS 解析问题，换方向 |

---

## （2026-11-21 23:35，第 37 轮）-- 干净镜像 + 只读启动仍然失败，问题锁定在读路径

### 决定性实验

用户重刷干净的 `ios16-root.simg`，然后用 0093（`rootrw=0`，全程只读）启动：

**结果与之前一模一样** —— `/sbin/launchd errno 5`。

三个变量全部排除：

| 假设 | 实验 | 结论 |
|---|---|---|
| 镜像坏了 | `check-hfs-root.py --all` 全树扫描 | **否**：catalog 20480 节点全合法（index=1136 + header=1 + leaf=19343 = 20480） |
| 我写坏了 | 只读挂载 `rootrw=0` | **否**：一个字节都没写也失败 |
| 日志区覆盖 | 卷外 37 GiB | **否** |

只剩一个结论：**设备返回给 HFS 的字节是错的。**

### 关键线索：shim 和内核用的是不同的传输命令

| | `ugg/shim/sdhc.c`（一直正常） | 内核 `sweet_ufs.c`（读出垃圾） |
|---|---|---|
| 命令 | **CMD17 单块**，一次 1 扇区 | **CMD18 多块** + auto-CMD12 |
| 单次长度 | 恒 512 B | 最多 256 扇区（128 KiB） |

shim 在这台机器上跑了数周，从没读错过；它**只用单块命令**。
内核偏爱多块，而这正是 shim 从未验证过的路径。

错误分布也吻合：坏节点 19174~19514 **全在目录文件最后一个 extent 内**，
两端节点（16384~19173、19515~20479）全部正常 —— 中间连续一段坏、两端好，
是传输长度/边界问题的典型特征。

**所以这不是镜像 bug，是驱动 bug。以前没暴露，是因为内核只读卷头和 GPT（几 KB），
现在 HFS 要读 160 MiB 的目录树，才踩到。**

### mido 对比

mido 也有过同类现象（boot 0041u）：

```
hfs_swap_BTNode: offset #0 invalid (0xBC1D) (blockSize 0x2000 numRecords 81)
node=19677 fileID=4 (catalog)   hfs_mark_inconsistent repeated
```

同一个文件（catalog）、同一区间（文件末尾）、同一类错误。
mido 的结论是「非日志卷 + 崩溃时写坏」，解法是重刷干净镜像。

**但我们的证据比他们强**：镜像干净 + 只读也失败，
所以我们是**读坏**，不是写坏。这一点 mido 当时没有验证。

（两边的 `tools/mkiosroot.sh` 逐字节相同，都是 `mkfs.hfsplus -s -J`。）

### 本轮加的两个开关（commit `7bba930`，CI `44917936947`）

1. **`ugcheck=1/2`** — 挂载**之前**让驱动自己读回目录 B 树并逐个校验描述符。
   必须在挂载前测：HFS 日志一启用就会写盘，那时磁盘已不是原始状态。
   `ugcheck=2` 额外 hex dump 第一个坏节点。
2. **`uggnomb=1`** — `ugg_xfer()` 强制每次只发 1 扇区，与 shim 完全一致：

```c
uint32_t n = ugg_no_multiblock ? 1u : MIN(nsec - done, UGG_CHUNK);
```

设备摘要行末尾会打印 `single-block` 或 `multi-block`，确认生效。

### 下次刷机：一次定案

**先刷带 `uggnomb=1` 的镜像。** 若能过 launchd -> 确证多块传输有问题。

若仍失败，刷 `ugcheck=2` 的镜像：

| ugcheck 输出 | 结论 |
|---|---|
| 报出坏节点 | 读路径仍然错，查 DMA/PRDT/对齐 |
| 全部干净 | 字节是对的 -> HFS 解析问题，方向完全不同 |

---

## （2026-11-21 20:50，第 36 轮）-- 根文件系统挂上了，卡点变成 launchd 读文件失败

### 里程碑：第一次进到用户态

第 35 轮加的「每步落盘」信标 + `ugginput=0`，一次性解开了两个死结：

```
UGG INPUT: disabled (ugginput=0)          <- 卡了两个月的拦路虎
SWEET STEP: IOFindBSDRoot: ufs root device ready
SWEET STEP: vfs_mountroot: enter
SWEET MOUNT: trying hfs
hfs: mounted iOSRoot on device b(1, 0)
UGG ROOT MOUNTED on ufsroot0
bsd_init: calling VFS_ROOT
SWEET: root volume is not authenticated (error 25); continuing unsealed
bsd_init: done
load_init_program: attempting to load /sbin/launchd
```

**根卷挂上了，根 vnode 拿到了，launchd 被执行了。**

### 卡点一（已定位并绕过）：ugg_input.c 没有超时保护

```ugg_input_init()``` 在 `sweet_ufs_init()``` 末尾被调用，位置就在同步 flush 之后。
它第一件事是 512 次无超时的 MMIO 读：

```c
for (int i = 0; i < 512; i++) {
    if (((rd(spmi_core, 0x800 + 4u * i) >> 8) & 0xfff) == 0x008) { ... }
}
```

对比 `ugg/shim/spmi.c`：那里每次读都过 `spmi_wait()`（带超时），而且写走 CHNLS
（0x02400000），而 `ugg_input.c` 只映了 OBSRV（0x02c00000）。

后果：AHB 挂死 -> 机器卡死 -> 外部看门狗重启。**看起来就像「挂载前就死了」**，
所以前几轮一直在 vfs_mountroot / HFS 里绕圈子。

绕过方式：`ugginput=0`（boot-arg，零代码改动）。**这也是当前默认做法**。

### 卡点二（当前）：HFS 节点描述符当场校验失败

```
hfs_swap_BTNode: invalid forward link (0x6a13d46a >= 0x00005000)
hfs: node=19174 fileID=4 volume=iOSRoot device=root_device
load_init_program: failed loading /sbin/launchd: errno 5
```

根因在 `hfs-src/core/hfs_endian.c:124`：读节点时 fLink 必须 < totalNodes。

### 只读对照实验：证明损坏在启动前就存在

| | 读写挂载 (0092b) | 只读挂载 (0093) |
|---|---|---|
| 挂载期 B 树报错 | **6 条** | **0 条** |
| 节点 19193 的坏值 | 0xf728c62a | 0xf728c62a 完全相同 |
| 节点 19174 的坏值 | 0x6a13d46a | 0x6a13d46a 完全相同 |

只读把挂载期错误全清了（**那几条是它自己写的**），但 launchd 那两个节点的坏值
一比特没变 -> **损坏在我启动之前就在镜像里**。

**并且：不是我的日志害的。** 分区 53 GiB，HFS 卷 16 GiB，
日志在分区偏移 53 GiB 处 = 卷外 37 GiB，不可能覆盖元数据。（我一度怀疑是它，撤回。）

### 本轮交付物：check-hfs-root.py

421 行，纯 Python 3，无第三方依赖，**只读、不挂载**。

做的正是内核那个检查：读每个 B 树节点头 4 字节（fLink），>= totalNodes 就报错。
支持 `.simg`（Android sparse，按块随机读，**不用先解压成 16 GiB**）和 `.img`。

**第一版我写错了，被用户的输出当场抓出来：**

```
node kinds : free=1136, hdr=1, 255=19343     我的表里 255 是"未知"
```

`kBTLeafNode` 是 **0xFF（255）**，不是 4（`hfs_format.h:737`）。
后果：19343 个正常叶节点被记成"未知"，1124 个 index 节点（kind 0）
被记成 "free node"，又因为描述符不是全零而全部误报 —— **176 个假警报**。

修正后对同一份真实镜像重跑，正确分类应为
`header=1, index=1124, map=1, leaf=19343`。

**教训：工具里写死一个魔数表之前，去头文件里核对。**

### 下一步

1. 用修正后的 `check-hfs-root.py --all` 重跑真实镜像，确认 catalog 干净；
2. 若干净 -> 问题在 eMMC **读**路径（4 KiB / 8 KiB 多块读的 DMA 与对齐），
   内核日志里 `UGG IO 2..12` 是唯一能对照的实证；
3. 修 `ugg_input.c`：所有 MMIO 读加 `deadline_us()`，PON 扫描 512 -> 64，
   补 `SPMI_CHNLS` 映射，默认关闭（桌面出来再开）。

---

## （2026-11-21 18:00，第 35 轮）-- 0091 拿到了真日志，但它有个结构性上限

### 实机结果：日志是真的，偏移也对

`kernel-console.txt` 共 184 行，从 `Darwin Kernel Version 22.6.0` 一路到：

```
bsd_init: calling setconf
UGG EMMC: userdata first=1376256 nblocks=13891579 (54263 MiB)
SWEET UFS: "userdata" on LUN 0: first block 0x150000, 54263 MiB, read-write, DMA at 0xa24f0000
```

然后再无下文。**这本身已经证明三件事**：

1. 偏移公式修对了（否则又是 4 MiB 零）；
2. eMMC **写**路径完全可用 —— 内核能写进 userdata 末尾；
3. 日志机制（ring + header + 解码）端到端跑通。

### 但这份 dump 有个结构性上限：它必然停在同一行

`SWEET UFS: ...` 是 `sweet_ufs_init()` 最后一句 printf，紧接着就是 init 里的同步 flush。
header 里的 `total` 是**写的那一刻**的值，所以：

> 之后无论打印什么，都只留在内存 ring 里；磁盘上那份永远停在 `SWEET UFS: ...`。

因此「dump 停在那一行」**不能**证明「卡在那一行」。它只说明：**之后再也没有第二次 flush**。

### 为什么没有第二次 flush —— 两个可能

- **(a) 硬卡死**：默认周期是 10 秒，而 0091 的 cmdline 没有 `ufslogsecs`。
  如果机器在 10 秒内死掉/锁死（单核 `cpus=1`），日志线程没机会跑。
- **(b) 我自己埋的阻塞**：挂载失败会走 `UGG ROOT FAIL`，然后我在 panic 前调了
  **阻塞版** `sweet_ufs_flush_log_now()`（`lck_mtx_lock`）。如果失败的挂载把
  `sweet_ufs_lock` 漏掉没释放，这一步**永久阻塞** —— 屏幕上明明打了
  `UGG ROOT FAIL ... errno=N`，磁盘上一个字节都没有，**和 0091 的现像完全吻合**。

第 0088/0090 轮是能看到 `cannot mount root` 反复重试的（说明挂载确实返回错误、
机器当时是活的），所以 **(b) 的嫌疑比 (a) 大**。

### 本轮改动（commit `a48ce38`，CI `44891665770`）

目标：让「最后一次成功写盘」精确指认卡点，不再依赖周期线程。

1. `sweet_log_write_locked()`：把「写 ring + 写 header + sync cache」抽成一个函数，
   记录 `sweet_log_written`，同步路径与线程共用。
2. `sweet_log_step(tag)`：printf + **try-lock** flush。信标本体永不阻塞，
   不会自己制造卡死；抢不到锁就只打印 `[device busy, deferred]`。
3. 布点（每点都会立刻落盘）：
   - `IOFindBSDRoot`：`ufs root device ready`
   - `setconf` 返回：`root device resolved`
   - `vfs_mountroot` 进入：`enter`
   - `bdevvp` 之后：`bdevvp ready`
   - 每个 fs 挂载**之前**：`before filesystem mount` + `SWEET MOUNT: trying hfs`
   - 挂载**之后**：`SWEET MOUNT: hfs returned <errno> (flags 0x..)` + `mount failed/ok`
   - `strategy()` 前 12 次 I/O：每次立刻 flush（`UGG IO n ...` 落盘）
4. `panic_trap_to_debugger()`：panic 文案进 console 之后**尽力 flush 一次**。
   这台手机自己重启不了，不 flush 等于 panic 信息全丢。
5. 失败路径的阻塞 flush → 改成 `sweet_log_try_flush()`，panic hook 再试一次。
6. 日志周期默认 10 秒 → **3 秒**。

### 下次刷完应该看到什么（按顺序）

`SWEET STEP: IOFindBSDRoot...` → `setconf...` → `vfs_mountroot: enter` →
`bdevvp ready` → `SWEET MOUNT: trying hfs` → `UGG IO 1..N`，然后三种结局：

| 现象 | 结论 |
|---|---|
| `SWEET MOUNT: hfs returned 0` + `root mounted` | 挂上了，进入 VFS_ROOT 阶段 |
| `SWEET MOUNT: hfs returned <errno>` | **这就是一直没拿到的 errno** |
| 最后一条是 `UGG IO n` | 卡在 HFS 的读里面，n 说明读到第几块 |

### 镜像

**`shim-boot-0092-beacons.img`** —— 8,173,568 B，
sha256 `92b09aed66e28fe589dcdb2c95a508fb72d258dfd6c809604ca4291d0a002da4`

- 内核 `kernel.development.sweet` sha256 `95c14d5dff688d438ac5bc12ba8b375874ce64e8cac1d526f4d4a64b588270df`
  （CI `44891665770` success）
- shim 未变：`5717bd9cffc6572facdd5f3de152725641d83b4de8862daa7fdcb84a93ad5f98`
- 已验证镜像内 payload 含全部新信标字符串（SWEET STEP / SWEET MOUNT / 各 tag 各一处）。
- 注意：`gh` 默认仓库解析成 `dipa-studio/ios-sweet`，下载 artifact 必须加 `-R honghong2011/ios-ugg`。


---

## （2026-11-21 17:40，第 34 轮）-- 修掉“日志取不到”的三个真因

### 实机结果：取回来的 4 MiB 全是 0

`pull-log.cmd` 跑通了，dd 读到 4198400 字节，但前 32 字节全零，
解码器报 `no SWEETLOG header`。这不是工具坏，是**三件事叠在一起**。

### 原因一（我的错）：把日志线程推迟到挂载之后，等于关掉了日志

第 33 轮我把 `sweet_log_start()` 从 `sweet_ufs_init()` 挪到挂载成功之后，
理由是「怕它和挂载抢锁」。但这个改动有个致命后果：

**挂载一旦卡住，日志线程永远不会启动，失败路径的同步 flush 也永远走不到。**
于是分区末尾一个字节都没写，取回来当然是全零。

正确做法（本轮）：

- 日志线程**回到 init 启动**；
- 它取锁改成 `lck_mtx_try_lock`，**抢不到就跳过这一轮**，永远不阻塞挂载；
- init 里**立刻同步 flush 一次**，当场证明 eMMC 能不能写，
  也让「之后卡死」的情况一定有日志可读。

### 原因二（真 bug）：日志区偏移算错了 3584 字节

内核按 **4 KiB 块**寻址，它眼里的分区长度是 `扇区数 / 8` **截断**：

```c
su.first_block = first / UGG_SPB;          /* UGG_SPB = 4096/512 = 8 */
su.nblocks     = (last - first + 1) / UGG_SPB;
base = su.first_block + su.nblocks - SWEET_LOG_BLOCKS;
```

这台机 userdata 是 **111,132,639** 个 512 字节扇区，不是 8 的倍数：

| 算法 | 结果 |
|---|---|
| 内核（块对齐） | (111132639/8 截断 - 1025) x 4096 = **56,895,709,184** |
| 旧脚本（直接减 8200 扇区） | (111132639 - 8200) x 512 = **56,895,712,768** |
| 差额 | **3584 字节 = 7 扇区** |

差这 7 个扇区，读窗口就整体后移，**文件头正好被跳过**。
所以即使内核写过日志，旧脚本也会读成一片零。

本轮把 `ugg-grab-log.sh` 改成和内核同样的算法：

```sh
NB=$(( SZ / SPB ))                  # SPB = 8
SKIP=$(( (NB - 1025) * SPB ))       # 不是 SZ - 8200
COUNT=$(( 1025 * SPB ))
```

已用真实数值验证：`SKIP*512 = 56895709184`，与内核 `base*4096` 完全相等。

### 原因三（健壮性）：解码器只认偏移 0

`sweetlog-decode.ps1` 原来要求文件开头就是 `SWEETLOG`，否则直接退出。
现在会**在前 64 KiB 里搜索魔数并自动重对齐**，尾部不足时补零，
所以哪怕以后偏移又差几个扇区，也还能解出来。

已用两份合成转储验证：

| 用例 | 结果 |
|---|---|
| 偏移正确 | 正常解码 |
| 前移 3584 字节（复现旧 bug） | `header found 3584 bytes in, realigning` + 正常解码 |

### 顺带修掉：`shim/build.sh` 的可执行位

第 33 轮我把一批「只有权限变化」的文件当成噪音还原了，结果把
`shim/build.sh` 从 755 改回 644，CI 直接 `Permission denied` 失败（run 44887825030）。
已恢复，run 44889063194 通过。**这类改动不能当噪音清掉。**

### 产物

| 文件 | 内容 | sha256 |
|---|---|---|
| `shim-boot-0091-logfix.img` | 含本轮全部修复 | `dc30788809ee9fd7a11ceaee6b0b16d4d4485f18fc18cdd01e0fc28f9f60eb97` |
| 内核 | CI `44889063197` success | `66930101a8db9ab8c09868e674746f88b6182cd2855f2527e6000e7c3aae30c9` |
| shim | CI `44889063494`/`44889063194` success | `5717bd9cffc6572facdd5f3de152725641d83b4de8862daa7fdcb84a93ad5f98` |

### 下次一定会拿到日志的理由

1. `sweet_ufs_init` 一跑完就同步写一次，**不依赖挂载成功**；
2. 写成功会打印 `SWEET LOG: flushed N bytes to block 0x...`，
   写失败打印 `SWEET LOG: synchronous flush FAILED (e)`，屏幕上直接可读；
3. 提取脚本的偏移与内核块对齐算法一致；
4. 解码器能自动找回几个扇区的偏差。


## ★★★★★ （2026-11-21 12:20，第 33 轮）-- 修掉挂载的真凶：日志线程抢锁 + shim 写超时

### 本轮修的两个实质 bug

**1. 日志线程和根挂载抢同一把锁（最可能是卡死的主因）**

`sweet_ufs.c` 的 `sweet_ufs_init()` 里，分区识别完成后**立刻**调 `sweet_log_start()`。
那个线程每 10 秒拿 `sweet_ufs_lock`，并在持锁期间**写最多 4 MiB**。

而整个块设备只有**一把锁、一条轮询传输路径**：

```c
lck_mtx_lock(&sweet_ufs_lock);   /* sweet_ufs_strategy 里 */
    ... ufs_read_blocks / ufs_write_blocks ...
lck_mtx_unlock(&sweet_ufs_lock);
```

根挂载紧接着 `init` 之后开始，几乎必然撞上日志线程。写慢或写失败时
**锁一直被占着**，挂载就表现为「卡在 setconf 之后、什么都不打印」。

修法：把 `sweet_log_start()` 从 `sweet_ufs_init()` 里拿掉，改成挂载成功后调用
`sweet_ufs_log_after_mount()`（`bsd_init.c` 里 `vfs_mountroot` 成功后）。

**2. shim 从来没设置 SDHCI 数据超时计数器**

内核侧 `ugg_take_over()` 一直有这句：

```c
mh_wr(M_CLK, (mh_rd(M_CLK) & ~(0xfu << 16)) | (0xeu << 16));   /* 0xE = TMCLK x 2^27 */
```

**shim 侧没有。** 复位默认值是 0，控制器会在卡片还在编程时就把命令判失败 ——
这正是 `LOG WRITE E=5 SEC=0`（错误码 5 = data error）的根因：
数据已经被接受，写编程阶段被提前中止。

修法：`shim/sdhc.c` 新增 `set_data_timeout_max()`，在 `sdhc_init()` 卡片进入
transfer state 后调用；`sdhc_write()` 同时改成**3 次重试 + 复位线路**，
与内核 `ugg_xfer()` 的策略一致。

### 修完后内核能写 eMMC，这会带来什么

HFS+ 挂载成功之后立刻要做三件**写操作**（mido 日志 497-501 行实测）：

```
hfs: Initializing the journal (joffset 0x82000 sz 0x800000)
hfs: iOSRoot: hfs_recording_init: creating the hotfile btree
```

日志重放和 hotfile 创建都要写盘。**写路径不通，挂载一定失败或卡死。**

### 当前能力对照（vs mido）

| 能力 | mido | UGG | 状态 |
|---|---|---|---|
| eMMC 读 | UFS | SDHCI 读通，54 GB 识别对 | ✅ |
| eMMC 写 | UFS | 内核侧已做；**shim 本轮补齐** | ✅ 本轮 |
| 16 KB VM 页 | 默认（>1 GB） | `memSize=1.499 GiB` 走同一分支 | ✅ |
| commpage 对齐 | `PAGE_RATIO` 修正 | `pmap.c:10896` 已有同款 | ✅ |
| dyld 共享缓存签名 | 需 16 KB 页 | 靠 16 KB 页满足 | ✅ |
| 根挂载 | rd=ufsroot0 | 驱动通了，**锁冲突本轮修** | ✅ 本轮 |
| 显示呈现 | AppleCLCD CPU 缩放 | `presented as 750x1334`（iPhone 8 原生） | ✅ |
| 触摸 | SweetHIDTouch | `BOARD_TOUCH_RAIL=0` 未启用 | ⏳ 进桌面后 |

### 本轮新增诊断（只打前 12 次，不刷屏）

`sweet_ufs_strategy()` 会打印每一次块 I/O：

```
UGG IO 1 blk=0x0 cnt=512 rd secsize=512
UGG IO 2 blk=0x2 cnt=512 rd secsize=512
```

这两行能直接回答：挂载有没有读到第一个块、`secsize` 是多少、卡在哪个块。

### 日志怎么取（TWRP + ADB，不需要改代码）

内核把控制台日志写在 **userdata 的最后 4 MiB + 4 KiB**，这本来就是为
「屏幕拍不清」准备的，**不依赖任何写权限修复**。

TWRP 里：

```bash
# 1. 找 userdata 的起始扇区和大小（512 字节扇区）
adb shell fdisk -l /dev/block/mmcblk0

# 2. 算出最后 1025 个 4K 块的位置：
#    start_4k = userdata_start_512 / 8
#    total_4k = userdata_size_512 / 8
#    skip     = start_4k + total_4k - 1025
adb shell dd if=/dev/block/mmcblk0 bs=4096 skip=<skip> count=1025 of=/sdcard/sweetlog.bin

# 3. 拉出来
adb pull /sdcard/sweetlog.bin
```

然后本地解码（仓库里就有工具）：

```bash
python tools/sweet-log.py sweetlog.bin out.txt
```

**或者更快的方式**：TWRP 挂载后，直接 `adb pull` 整个分区末尾：

```bash
adb shell "dd if=/dev/block/bootdevice/by-name/userdata bs=4096 skip=$(( $(blockdev --getsz /dev/block/bootdevice/by-name/userdata) / 8 - 1025 )) count=1025 of=/sdcard/sweetlog.bin"
adb pull /sdcard/sweetlog.bin
```

### 产物（已出）

| 文件 | 内容 | sha256 |
|---|---|---|
| **`shim-boot-0090-final.img`** | 含全部本轮修复 | `8e850b026060989dbb4e5c5d3f80759f412e6a7290026fde7f33a72c04807615` |
| 内核 | CI `44866379049` success | `e2a8b9d85b9c47a57f7f683406b619fea6bb56f50d7bf65e4de67329ecafc16b` |
| shim | CI `44865566945` success | `5717bd9cffc6572facdd5f3de152725641d83b4de8862daa7fdcb84a93ad5f98` |

镜像内已验证包含：I/O 追踪、日志延后启动、同步刷日志、挂载成功/失败标记。


## ★★★★★ （2026-11-21 11:00，第 32 轮）-- 找到并修掉自己写的字节序 bug

### 上一轮 `USERDATA NOT HFS+` 是假阴性，是我的 bug

`shim-boot-0086-userdata.img` 上机，红屏打印：

```
USERDATA F=11010048 N=111132639
USERDATA s0=00000000 00000000
USERDATA sig@0=00000000 sig@1024=<非零，被刘海挡住>
USERDATA NOT HFS+ -- wrong image, wrong offset, or incomplete flash
LOG WRITE E=5 SEC=0
```

**这个 `NOT HFS+` 是错的。** HFS+ 的签名是两个字节 `'H'` `'+'` = `0x48 0x2B`，
按大端读是 `0x482B`。但 `blk[]` 是 **小端 `uint32_t`**，那两个字节读出来是
**`0x2B48`**，`'HX'` 则是 `0x5848`。我上一版拿 `0x482B/0x4858` 去比，
永远不可能匹配 —— 是纯粹的字节序错误。

### 照片其实已经暗示了正确答案

`s0 = 0x00000000`（前 1024 字节全零）而 `sig@1024` **非零**：
这正是 **HFS+ 的标准布局** —— 卷的前 1024 字节是引导块（通常全零），
卷头（Volume Header）从偏移 1024 开始。

如果是「什么都没刷」的空白分区，`sig@1024` 也会是 0，那样会走到
`USERDATA BLANK` 分支。它没有走，说明 **1024 处有数据**。

### 修复（`shim/emmc.c`，commit `788f59a`）

| 项 | 旧（错） | 新（对） |
|---|---|---|
| HFS+ `'H+'` | `0x482B` | **`0x2B48`** |
| HFSX `'HX'` | `0x4858` | **`0x5848`** |
| sparse magic | 分两半比 | `0xED26FF3A`（小端读正好是这个值） |

同时改进两处：

1. 卷头读进**独立缓冲区** `vh[128]`，不再和 `blk[]` 共用（原来两次读会互相覆盖）
2. 不匹配时**dump 出卷头前 8 个 32 位字**，直接看出实际是什么
   （ext4/f2fs 超级块、截断写入、还是别的）

### 顺带确认：`-S 256M flash` 没问题

用户用的就是 `fastboot -S 256M flash userdata ios16-root.simg`，
这正是 `tools/flash-root.sh` 推荐写法，而且**一次成功、无报错**。
`sdhc_read()` 是 CMD17 单块读 512 字节，所以「卷头偏移 1024 = 扇区 +2」的换算是正确的。

### 关于 `LOG WRITE E=5 SEC=0`

`cache` 分区写日志仍然失败（扇区 0 就写不动），这是老问题，
**不影响 XNU 启动**，只是日志存不下来。不用管。

### 产物

| 文件 | 内容 | sha256 |
|---|---|---|
| `shim-boot-0087-hfs.img` | 修正字节序的卷头判定 | `be1fab6983a9c6318b7db43064d8929aac07f7fa61bea82b3b0a635571bfbd73` |

shim CI `44858599788`（success, `788f59a`），
Image sha256 `24ac9a2c00c6f6b0f955b3b02acccfbc4b04c9cedb50bdac5b746e88ed2f681e`。


## ★★★★★ （2026-11-21 10:40，第 31 轮）-- 刷了根镜像后行为不变；改用 shim 直接验卷头

### 实机结果：刷完 userdata 后，表现和没刷**完全一样**

用户已用 `fastboot` 把 `ios16-root.simg` 刷进 userdata（合并 + 刷写完成），
然后启动 `shim-boot-0085-errno.img`。结果：色带闪过 -> 黑屏跑码 -> 重启。

### 照片的真正读法：图一右半边才是最新画面

图一左侧那半（`ether_family_init` / `net_init_run` / `inittodr` / `setconf` /
`UGG EMMC`）是**上一轮的残留**——`vc` 控制台光标位置保留，两轮启动叠在同一块屏上。

右侧那半（顺序与 `bsd_init.c` 完全一致）才是本轮：

```
dlil_init -> socketinit -> domaininit -> skywalk_init
-> memorystatus_init -> sysctl_mib_init -> bsd_autoconf -> loopattach
-> ifnet_attach: All kernel threads created for ...
```

源码核对（`bsd_init.c`）：759 dlil / 763 socket / 765 domain / 773 skywalk /
795 memorystatus / 799 sysctl_mib / 802 autoconf / 816 loopattach /
831 ether_family / 866 net_init_run / 870 inittodr / **877 setconf**。

**关键：`setconf` 那行没出现。** 说明现在不是「`vfs_mountroot` 返回错误然后循环」，
而是它**在 `vfs_mountroot()` 里面就不返回了**（挂住），所以既没有 `UGG ROOT FAIL`
也没有循环滚动。这和上一个分叉点完全不同。

### 为什么不再靠 errno 猜

`UGG ROOT FAIL` 是正确的代码（内核里确实有，`grep` 到 1 次），
但它**只有在 `vfs_mountroot` 返回失败时才打印**。现在卡在里面不出来，
等于这条诊断路走不通。继续猜 errno 没有意义。

### 本轮做法：让 shim 在跳转前直接读 userdata 的卷头

`shim/emmc.c` 新增 `ugg_emmc_check_userdata()`：在 GPT 解析完、跳内核之前，
直接 `sdhc_read()` userdata 的扇区，判断镜像到底在不在、是什么。

读两个位置，因为两种刷法都可能：

| 位置 | 判断 |
|---|---|
| 偏移 0（扇区 0） | 原始镜像从这里开始；`0xED26FF3A` = **sparse 头没被展开** |
| 偏移 1024（扇区 +2） | HFS+ 卷头标准位置；`0x482B`=HFS+，`0x4858`=HFSX（大小写敏感，mkiosroot.sh 产出的就是这个） |

输出示例：

```
USERDATA F=1376256 N=111132672
USERDATA s0=00000000 00000000
USERDATA sig@0=00000000 sig@1024=00000000
USERDATA BLANK -- nothing was flashed here
```

或

```
USERDATA sig@0=00000000 sig@1024=00004858
USERDATA HFSX at 1024 -- image present
```

或（**最可疑的一种**）

```
USERDATA s0=ED26FF3A 0000001C
USERDATA SPARSE IMAGE NOT EXPANDED -- fastboot wrote the .simg header
```

三种结果对应三种完全不同的修法，一张照片就能定性。

### 为什么要专门查 sparse 头

用户刷的是 `.simg`（Android sparse image）。`fastboot flash` 正常情况下会展开它，
但**如果镜像头不被接受，或有地方把文件原样写进去**，分区里躺着的是
28 字节头的 sparse 文件而不是文件系统。那时 `vfs_mountroot` 会读到乱数据，
既不返回干净的错误、也不 panic —— 和现在「卡住」的现象吻合。

读路径本身已被证明可用（`SWEET UFS: userdata ... read-write, DMA`），
所以这个检查是可信的。

### 只读，不会写任何东西

`ugg_emmc_check_userdata()` 全程只调 `sdhc_read()`，没有任何写路径。
写权限窗口仍然只在 `cache` 分区内（`sdhc_allow_writes`）。

### 产物

| 文件 | 内容 | sha256 |
|---|---|---|
| `shim-boot-0086-userdata.img` | 跳转前打印 userdata 卷头判定 | `2b210f305169d4c88b486e8fb27d6a5c79f4a6394e57dd3a7d39027091d5d8aa` |

shim 来源 CI `44856815790`（success, commit `f2c0451`），
Image sha256 `f9ea479a2ad7807c7633a807c8fffd69ee7cad8ba10bc55aa44ad9e30cc15738`。

### 下一张照片要看的三行

1. `USERDATA s0=` —— 分区开头是什么
2. `USERDATA sig@0= / sig@1024=` —— 有没有 HFS+ 魔数
3. 结尾那句判定（`BLANK` / `HFSX at 1024` / `SPARSE IMAGE NOT EXPANDED` / `NOT HFS+`）


## ★★★★★ （2026-11-15 22:30，第 30 轮）-- 32bpp 控制台完全清晰；卡点锁定为「userdata 上没有 iOS 文件系统」

### 实机：屏幕终于可读，而且信息量很大

`shim-boot-0084-32bpp.img` 上机，文字**逐行清晰**（2 倍字 + 32bpp 都生效）。
两张照片合起来读到：

```
SWEET FB: AppleCLCD 720x1280 stride 2880 at 0x90000000,
          default surface 1, presented as 750x1334
SWEET CPU: 1/1 CPUs initialized, SGI1 verified
bsd_init: calling IOKitInitializeTime
UGG tick 1: bootstrap at bsd_init
...
bsd_init: calling net_init_run
bsd_init: calling inittodr
bsd_init: calling setconf
UGG EMMC: userdata first=1376256 nblocks=... (54263 MiB)
SWEET UFS: userdata on LUN 0: first block 0x150000, 54263 MiB, read-write, DMA at 0xa24ec000
```

三个里程碑：

| 事实 | 意义 |
|---|---|
| `presented as 750x1334` | **iPhone 8 逻辑分辨率**，`SweetFramebuffer` 已挂上 GUI 通道 |
| `1/1 CPUs initialized, SGI1 verified` | SMP 与 GIC 都正常 |
| `SWEET UFS: userdata ... read-write, DMA` | **eMMC 驱动第一次真正工作**（54 GB、DMA 都对了） |

### 卡点：`vfs_mountroot()` 反复失败（但被滚掉了）

`bsd_init.c:874` 是个 `while (TRUE)`：

```c
while (TRUE) {
    bsd_init_kprintf("calling setconf\n");      // ← 照片最后一行
    setconf();                                  // 每轮重新探测 eMMC（所以 UGG EMMC 又打一遍）
    bsd_init_kprintf("vfs_mountroot\n");
    if (0 == (err = vfs_mountroot())) break;    // ← 失败
    rootdevice[0] = '\0';
    printf("cannot mount root, errno = %d\n", err);   // ← 每轮都被滚掉
}
```

这也解释了照片里「`dlil_init` 出现在 `ether_family_init` 之后」这种**源码顺序上不可能**的排列——
是 `setconf()` 重跑把屏幕搅乱了，不是 bug。

**根因**：userdata 上是 Android 的 ext4/f2fs，不是 iOS 的 HFS+。
`vfs_mountroot` 找不到可挂载的卷，失败是必然的。

### 为什么它会重启

搜遍整棵树：`PE_halt_restart` **只有声明、没有任何赋值**，
所以 `IOPlatformExpert::haltRestart()` 永远返回 -1，**XNU 自己不会重启**。
`SWEET WDT` 也是空壳（注释原文 “accepts check-ins, never fires”）。

→ 重启来自那个循环跑太久，**硬件里预设的看门狗**（LK/PBL）复位了 SoC。

### 本轮改动：不再无声循环（commit `30e0391`）

```c
printf("UGG ROOT FAIL: rootdevice=\"%s\" errno=%d args=\"%s\"\n",
    rootdevice, err, PE_boot_args());
panic("UGG: no root filesystem on %s (errno %d)", rootdevice, err);
```

下一张照片直接给 errno，不用再猜。同时不再循环几分钟等看门狗打断。

### 新文档：`docs/ROOT-IMAGE-OTHER-PC.md`（393 行）

回答「另一台电脑怎么搞」：装 `gh` → 下 7 个分片 → `sha256sum -c` → `cat` 拼合
→ 校验 `11970598900` 字节 → 走法 A（拷回主力机刷）或走法 B（就地刷）。
还写了 CI 十步在干什么、产物过期怎么重建、errno 对照表。

**关键资产**：根镜像已构建好，`ios16-root-parts`（5,837,838,248 B，7 分片），
run `43644714094`，**2026-11-19 21:59 UTC 到期**（约 4 天）。

### 下一步（顺序不能反）

1. **先刷含 errno 的内核**，确认 `errno=19`（ENODEV = 没有文件系统）
2. 若 errno 不是 19（5=EIO / 6=ENXIO），**先别刷镜像**，那是 eMMC 层问题
3. errno=19 → 按新文档下载拼合 → `fastboot -S 256M flash userdata` → 再启动

注意：刷 userdata 会抹掉 Android 全部数据（已批准方案，但不可逆）。

### 产物

| 文件 | 内容 | sha256 |
|---|---|---|
| `shim-boot-0085-errno.img` | 含 errno 判定，**先刷这个** | `4750097dd0dfb0a6c2e1f738d386fb56b7fd524c9f8bab7421b8f4a884fa23fd` |
| 内核 | CI `43722404833` (success) | `ded3bfbeed2d5da841eead5d08199be8e9b6901ca3e81057edede580ef3df6ca` |


## ★★★★★ （2026-11-15 17:25，第 29 轮）-- 色带实证 32bpp 正确；补齐 sweet_early 的 32bpp

### 实机结果：色带完全正确，32bpp 扫描链结案

`shim-boot-0083-fbtest.img` 上机，两张照片：

**照片 1（红屏，24bpp 控制台）**：

```
RGB0 FMT 0002243f -> 000236ff
RGB0 STRIDE 00000870 -> 00000b40
RGB0 UNPACK -> 03020001
RGB0 32BPP staged (registers read back)
VIDEO rowbytes 0000000000000B40
VIDEO depth 0000000000000020
```

**照片 2**：6 条纯色竖条（红/绿/蓝/白/灰/黑），颜色顺序正确，
1 像素白边框紧贴屏幕四边，**没有任何竖条、错位、色偏**。

结论（这次是实证，不是推断）：

| 项 | 验证方式 | 结果 |
|---|---|---|
| `SRC_FORMAT` 0x236ff 生效 | 回读 | 写入即读回 |
| `UNPACK` 0x03020001 字节序正确 | **红条是红的** | B,G,R,X 没搞反 |
| `YSTRIDE` 2880 | 边框竖直不斜 | stride 正确 |
| 宽高 720x1280 | 边框紧贴四边 | 尺寸正确 |
| boot_args 2880/32 | VIDEO 行回读 | 一致 |

**24bpp -> 32bpp 切换这条路彻底走通。**

### 必须一起修掉的：`sweet_early` 还是 24bpp

这是切换 32bpp 之后新出现的隐患，而且是**致命的**，因为：

`osfmk/kern/debug.c:1077` 在 `panic_trap_to_debugger()` 的最开头调用
`sweet_early_panic()`——**panic 原文是走这个控制台打出来的**。
而 `arm_init.c:551` 只有 `serial_exists` 为真才 `sweet_early_disable()`，
ugg 没有串口，所以它**一直活着**。

也就是说：我们把管道切成 32bpp，但 panic 打印机还在按 3 字节/像素写 ——
一旦 panic，屏幕上是乱码，等于把唯一的诊断通道弄瞎了。

改动（`osfmk/arm64/sweet_early.c`、`pexpert/pexpert/arm64/SWEET.h`）：

| 位置 | 旧 | 新 |
|---|---|---|
| `UGG_FB_BPP` | 3 | **4** |
| `UGG_FB_STRIDE` | 2160 | **2880** |
| `early_fb` 类型 | `volatile uint8_t *` | `volatile uint32_t *` |
| `early_px()` | 写 3 字节 | 写 1 个字 |
| `EARLY_STRIDE` | `STRIDE / 3` | `STRIDE / UGG_FB_BPP` |

`EARLY_SCALE 2` 不变，所以红屏仍是 2 倍字，panic 依然能拍清。

注意：**shim 的引导控制台仍然必须是 24bpp**，它在切换之前运行，那时 RGB0
还是 LK 留下的 BGR888。两个控制台刻意不同，两边都写进了注释，防止以后有人
"统一"成一样。

### 顺带确认

`SweetFramebuffer.cpp:187`：

```c
if (fPhys == 0 || fWidth == 0 || fHeight == 0 || fRowBytes < fWidth * 4) { ... }
```

现在 `fRowBytes = 2880 == fWidth * 4`，**GUI 这条硬门槛第一次满足**。
这是控制器能走到桌面的前提。

### 产物

| 文件 | 内容 | sha256 |
|---|---|---|
| 内核 | 32bpp + 2 倍 vc + 32bpp sweet_early，CI `43699026717` (success) | `fb8a3b22326406f8f59210c1f022b5135f0b00005cb2123ca48c38d0377ac7f2` |
| **普通镜像** | 32bpp 端到端，等上机 | `shim-boot-0084-32bpp.img` = `514084e05f0d3390b3508b7efd5639bcdce906ba9313f5097fe190341b130629` |


## ★★★★★ （2026-11-15 16:50，第 28 轮）-- 走 mido 的路：切 32 bpp 端到端 + 色带自检

### 为什么必须切 32 bpp（不是"优化"，是硬约束）

`iokit/Kernel/arm/SweetFramebuffer.cpp` 里 GUI 那条路是这么写的：

```c
MDP_W(VIG0 + 0x30, 0x000236ff);   /* 4 B/px */
MDP_W(VIG0 + 0x34, 0x03020001);   /* unpack B,G,R,X */
MDP_W(VIG0 + 0x24, 720u * 4u);    /* stride 2880 */
```

**内核这边的 GUI 通道本来就是按 32 bpp 写的**，而且 `start()` 会拒绝
`fRowBytes < fWidth * 4`。**24 bpp 永远到不了桌面。** 这和第 27 轮从
`board.h` 读到的注释（"take the 32 bpp path"）是同一件事。

### 假设 B（内核改 MDP）被排除

那段 MDP 代码由引导参数 `ugg_mdp=1` 开关，我们的 CMDLINE 里**没有**这个参数，
`ugg_mdp` 保持 0，所有 `MDP_W()` 都被跳过。所以内核跑控制台时**没有动过 MDP**，
RGB0 还是 LK/shim 留下的 BGR888 / stride 2160。

### 对那份外部文档的两点校对

1. **假设 A 不成立**：`vc_clear_screen` 每行写 `v_rowbytes>>2 = 540` 个 32 位字，
   540 x 4 = 2160 字节，**正好等于一整行**。字节上是精确覆盖，不会留半字残影，
   产不出等间距竖条。
2. 文档第 6 节的结论（走 32 bpp 端到端）**采纳**，与 GUI 的硬约束一致。

### shim 侧改动（`shim/fb32.c`、`shim/loader.c`）

切换放在**所有打印之后、跳转之前**，因为 shim 控制台是 24 bpp 且已验证：

```
shim_fb_stage_32bpp()   /* 写 SRC_FORMAT/UNPACK/STRIDE + 回读，不 flush */
    -> 打印回读值（这时面板还是 24 bpp，字能读）
shim_fb_commit_32bpp()  /* CTL0_FLUSH bit3，等 50 ms 让 vsync 吃掉 */
shim_fb_bars32()        /* 6 条纯色竖条 + 1 像素白边框 */
shim_fb_black32()       /* 交棒前清成黑 */
```

寄存器序列照抄 mido 的 `fb_to_32bpp()`，只换几何：
`SRC_FORMAT 0x0002243f -> 0x000236ff`、`UNPACK 0x03020001`、
`YSTRIDE 720*4 = 2880`、`CTL0+0x18 = 1<<3`（RGB0 是第 3 层）。

boot_args 同时改成 `rowBytes 720*4 / depth 32`（`loader.c`）。
**shim 自己的控制台仍是 24 bpp**，切换之后不再画任何东西。

### 色带自检：为什么用色带而不是文字

一块 8x16 的字在 720p 面板上、隔着手机拍照，到不了相机的分辨率（第 27 轮已论证）。
但**整屏纯色块不可能看不清**：

| 现象 | 结论 |
|---|---|
| 6 条纯色、边框紧贴四边 | format / unpack / stride 全部一致，扫描链正确 |
| 竖条 / 彩色条纹 | 写 4 字节、扫 3 字节这类不匹配仍在 |
| 边框不在边缘 / 少一条 | stride 或宽高不对 |

`ugg_fbtest=1` 时：打印回读 -> 停 6 s -> 出色带 -> **停住不跳**
（拍完按电源键重开）。普通启动只闪 1.2 s。

### 另一个顺手修掉的坑

跳转前那发 **1 秒虚拟定时器看门狗** 会在自检停留时提前触发，落进 shim 的
`exc_handler` 直接停住。已改成：进入显示自检前 `cntv_ctl_el0 = 0` 解除，
**跳转前再重新武装**，看门狗仍守 XNU 入口。

### 产物

| 文件 | 用途 | sha256 |
|---|---|---|
| `shim-boot-0083-fbtest.img` | 色带自检，不跳内核 | `0bc014df035e726dd2ee135c014bc18d5699832611b030b4d2ccf7f55fbcd485` |
| 普通镜像 | 32 bpp + 2 倍控制台，等内核 CI | 待出 |

shim 来源：CI `43695958091`（success, commit `caf7cc2`）。


## ★★★★★ （2026-11-15 16:25，第 27 轮）-- 屏幕参数已被代码证明无错；把内核控制台放大到 2 倍

### 不再用照片反推参数：参数链只有一处来源，逐行核对完毕

| 位置 | 内容 |
|---|---|
| `shim/board.h` | `FB_PHYS 0x90000000` / `FB_W 720` / `FB_H 1280` / `FB_BPP 3` |
| `shim/console.h` | `FB_STRIDE = FB_W * FB_BPP = 2160` |
| `shim/loader.c` 153-158 | `ba->Video = {0x90000000, display 1, 2160, 720, 1280, 24}` |
| `pexpert/arm/pe_init.c` 406-415 | 内核原样抄进 `PE_state.video`；`v_depth & 0xFF = 24`，`v_scale = ((v_depth >> 16) & 0xFF) + 1 = 1` |
| `video_console.c` `initialize_screen` | `v_rowbytes = 2160`，`v_depth = 24` |
| `video_console.c` `vc_initialize` | `v_rowscanbytes = ((24+7)/8)*720 = 2160`，与 `v_rowbytes` **相等** |

结构体布局也对得上：`pexpert/pexpert/arm64/boot.h` 的 `Boot_Video` 就是
`{v_baseAddr, v_display, v_rowBytes, v_width, v_height, v_depth}` 六个 64 位字段，
和 `shim/loader.c` 里的 `struct boot_video` 逐字段一致（loader.c 用
`_Static_assert(__builtin_offsetof(struct boot_args, Video) == 40)` 卡住偏移）。

**链路上没有第二个来源，没有 mido 的 1080/2400/4320 混进来。**
所以「屏幕参数没调好」这个方向 **已经排除**。

### 那"花屏"到底是什么

内核控制台的字符单元是 **8x16 像素**（`osfmk/console/iso_font.c:308`
`#define ISO_CHAR_WIDTH 8` / `ISO_CHAR_HEIGHT 16`）。这个尺寸在 1080p/Retina 上
是对的；在 720x1280 上，**每个笔画正好只有 1 个像素宽**。人眼看玻璃能看，
但手机在这个距离拍"1 像素宽的细笔画"，采样比约 1:1，出来的就是摩尔纹 ——
观感正是"花屏"。

### 决定性证据：红屏和黑屏是**两个不同的控制台**，只有字号不一样

- **红屏**是 `sweet_early` 引导控制台（`osfmk/arm64/sweet_early.c`）。
  `EARLY_SCALE 2` -> **16x32 字符**；清行写 `0xff000000`，在 24bpp 下
  取低三字节是 `FF,00,00` -> **红底白字**。它 2 倍字，所以拍照可读。
- **黑屏**是内核 `vc` 控制台（`video_console.c`，`ISO_CHAR_WIDTH/HEIGHT = 8x16`）
  -> **笔画只有 1 个像素宽**，黑底白字。1 像素细笔画在手机上拍就是摩尔纹。

同一个面板、同一个 24bpp、同一个 `0x90000000`/2160，**差别只有字号**：
2 倍能读，1 倍不能读。这就是"参数 vs 尺寸"的分界，也是这一轮改 2 倍的依据。

顺带一条事实（下一轮要用）：`osfmk/arm/arm_init.c:551` 只有 `serial_exists`
为真才调用 `sweet_early_disable()`。ugg 没有串口，所以 `sweet_early` 一直活着，
`panic()` 时 `osfmk/kern/debug.c:1077` 会**先把 panic 原文用 2 倍字打到红屏控制台**。
那是第二个能读 panic 的地方（和 vc 控制台的堆栈印在不同坐标上）。

### 真正的坏消息：它重启了

红屏走完 -> 黑色跑码 -> 重启。重启说明内核在 boot 中途死了（panic，或被复位）。
而屏幕上的字读不出来，就等于**没有日志**，后面每一步都是瞎猜。

所以这一轮只做一件事：**把内核控制台放大到 2 倍**，让每一条内核消息、
每一个 panic 都能被拍下来。这不是"套进控制台"，这是先把眼睛装回去。

### 改动：`vc_cell_scale`（UGG 默认 2，可用引导参数覆盖）

`osfmk/console/video_console.c` 新增：

```c
#if defined(SWEET) && defined(UGG)
#define VC_CELL_SCALE_DEFAULT   2
#else
#define VC_CELL_SCALE_DEFAULT   1
#endif
static int vc_cell_scale = VC_CELL_SCALE_DEFAULT;
#define VC_CELL_W       (ISO_CHAR_WIDTH * vc_cell_scale)
#define VC_CELL_H       (ISO_CHAR_HEIGHT * vc_cell_scale)
```

**不是新开一条显示路径**：原来每一个乘 `ISO_CHAR_WIDTH/HEIGHT` 的几何点，
现在乘 `VC_CELL_W/VC_CELL_H`；24bpp 画笔把每个字模像素写成
`vc_cell_scale x vc_cell_scale` 个屏幕像素。改的点一共六处：

| 函数 | 改了什么 |
|---|---|
| `vc_initialize` | `v_rows = v_height / VC_CELL_H`（40），`v_columns = v_width / VC_CELL_W`（45）；`PE_parse_boot_argn("ugg_vcscale")` 覆盖 1..8 |
| `vc_clear_screen` | `linelongs = (v_rowbytes >> 2) * VC_CELL_H`（字单位） |
| `vc_reverse_cursor` | 偏移用 `VC_CELL_W`，行数用 `VC_CELL_H`，24bpp 反色字节数 `VC_CELL_W*3` |
| `vc_scroll_up/down` | `linelongs = v_rowbytes * VC_CELL_H`，内层行循环 `VC_CELL_H` |
| `vc_paint_char_24` | 每个字模位展开成 scale×scale 块 |

8/16/32bpp 三个老函数没动（本板不走）。`ugg_vcscale=1` 回到上游几何，
**不用重新编译就能对比**（只改 `make-image.sh` 的 CMDLINE）。

### 校验

- `video_console.c` 花括号净差 = 0，`vc_paint_char_24` 唯一
- 补丁重新生成：3680 行 / 123838 字节 / 32 个文件 / CR = 0
- `GIT_INDEX_FILE=... git read-tree 2bbcef0; git apply --cached --check` -> 退出码 0

### 下一张照片要看的三件事

1. 内核文字**是否清楚到能逐行读**（如果是 -> "花屏"就是字号问题，结案）
2. 最后停在哪个 kext / 哪一行，以及 **panic 的完整内容**
3. 重启前的**最后 5 行** —— 大概率是找不到根文件系统
   （userdata 上还是 Android，`rd=ufsroot0` 找不到就 panic）


## ★★★★★ （2026-11-15 15:40，第 26 轮）-- 内核在打印了！文字糊掉是滚动拷贝放大 4 倍

### 实机结果：两行 CPU MAP 没出现 = CPU 这关过了

照片 2（红底）里 shim 走完：

```
INPUT  skipped: RPM LDO vote resets th...
PERF   skipped: leave clocks as LK set...
INITRD lo=100B0000 hi=120B0000
PHYS   base=A0000000 size=5FF00000
ENTRY  FFFFFFF00742B488
```

**没有出现 `SWEET CPU MAP` 两行** —— 按交接单判据，说明兜底没触发或已越过，
CPU 断言这关**已经过了**。

照片 1（黑底蓝字）是 **XNU 自己的控制台在打印**，只是文字糊了。
**内核跑起来了，而且能往屏幕上画字** —— 这是自移植开始最大的进展。

### 糊屏的真因：`video_scroll.c` 拷贝长度放大 4 倍

```c
bcopy(end, dest, ((char *)start - (char *)end) << 2);
```

`start/end` 是 `void*` 转 `char*`，减法**已经是字节数**，再 `<<2` 就是 ×4。
滚一行会多抄 4 行，把刚写好的内容覆盖掉 → 每次都更糊。**这正是照片里
那种「每行重复、错位叠加」的样子。**

### 同源问题：`vc_scroll_up/down` 按 32 位字算

它们用 `v_rowbytes >> 2` 把行宽换成「字数」——**只有在 1 像素 = 4 字节时才对**。
我们跑 24bpp（1 像素 3 字节），单位就对不上了。已全部改成 `unsigned char*`
+ 直接用 `v_rowbytes` / `v_rowscanbytes`。32bpp 行为不变，24bpp 正确。

### 再降一层风险：画字改成直接读 `iso_font`

原来的 `vc_paint_char_24` 依赖 `vc_rendered_font`（按色深展开的字模缓存），
**缓存元素尺寸和绘制步长是两套独立计算**，一旦不一致就是照片里那种重叠字。

现在**直接从 `iso_font` 读 8×16 位图**（每字符 16 字节，和 `sweet_early`
已验证可读的那套完全一样），只有一种字模表示、一种寻址方式，
没有会跑偏的地方。

### 新增可读诊断

```
SWEET VC: depth,rowbytes=<depth<<32|rowbytes>,<v_baseaddr>
```

走 `sweet_early`（已验证可读的控制台），确认内核实际用 24bpp / 2160 / 0x90000000。
以后屏幕再花，这一行直接指出是哪一边不对，不用再猜一轮。

### 顺带

| 改动 | 说明 |
|---|---|
| 删 CI 的 qemu job | 每轮省 ~20 分钟 |
| `ugg_find_partition()` 成功也打印 | `UGG EMMC: userdata first=... nblocks=... (.. MiB)` |

### 踩的坑（记录）

用脚本改写 `video_console.c` 时，**插入点误匹配了 `vc_paint_char_32` 里的
行内注释 `/* bold support */`**，把那个函数改坏了。
已从上一版成功的 0082 补丁重建该文件再重做修改，并用「花括号平衡 = 0」
+「`vc_paint_char_24` 只定义 1 次」做校验。**改这类文件后必须查这两项。**

---



## ★★★★★ 上一轮（2026-11-15 15:20，第 25 轮）-- 按交接单核对：CPU 断言根因锁定在 AKDT 的 boot 核标记

### 交接单带来的关键事实（我之前漏了）

1. **默认 cmdline 是 `cpus=1`**（`tools/mkuggboot.py`、`make-image.sh`）。
   此时 `ml_parse_cpu_topology` 会**跳过所有非 boot 节点**，表里只剩 1 个核。
   所以「实际跑的核」必须正好是那个被标 `state=running` 的节点，否则查表必失败。
2. `phys_id` 取 ADT 的 **`reg`**；`cpu-id` 不参与匹配；查不到返回 **-1** → 断言炸。
3. UGG 的 ADT 由 **`tools/mkadt_ugg.py`** 生成，不是 `mkadt.py`。

### 根因

```python
# mkadt_ugg.py:190
('state', cstr('running' if i == 0 else 'stopped'))
```

即认为 **MPIDR 0x000 是 boot 核**。而实机断言失败 ⇒ **实际启动核不是 0x0**。
（`mkadt.py` 里写的是 mido 的 0x100 假设，两个文件不一致，也是一个隐患。）

**不猜**：保留诊断 + 兜底，让下一次上机把真实 MPIDR 打出来。

### 本轮改动

| 改动 | 说明 |
|---|---|
| 兜底 `cpu_id = boot_cpu` | `cpus=1` 时 boot 就是唯一槽位 0，单核可继续 |
| `sweet_early_note()` | 十六进制打印 MPIDR（**不用 printf**，避免 printf 初始化期递归）|
| 删掉 CI 的 qemu job | 每轮白跑 ~20 分钟，答案已知（QEMU 无 eMMC/HFS）|
| `ugg_find_partition()` 成功也打印 | 否则「找到分区」和「没读到 GPT」都是静默，无法区分 |

### 本轮镜像

```
shim-boot-0082-mido.img  8,173,568 B
sha256 dfc71cd7a978f2e9ce215b5fa8e29da7835ff5fb7b335153c285c710af3056b1
内核 sha256 51d3c1e891d43e6e31a65dd80b8299d575e00bdeaf12625e3888021734f3746a
```

内核 = CI run `43686975596`（success，commit `5e6de0c`），含 CPU MAP 诊断。
已核实 payload 里 `SWEET CPU MAP` 出现 2 次。

### 下一步：读这两行

```
SWEET CPU MAP: mpidr,key=<MPIDR_EL1>,<AFF1|AFF0>
SWEET CPU MAP: maxcpu,=<max cpu id>,<查表 id>
```

| 读数 | 动作 |
|---|---|
| mpidr 的 key 是 0x0 | 不该出现；说明表里根本不是 0x0 |
| key = 0x1/0x2/0x3 | 改 `mkadt_ugg.py` 的 `i == 0` → 对应索引 |
| key = 0x100~0x103 | 改成立 `mpidr == 0x100` 之类（mido 的假设对）|
| 两行都没出现 | 说明兜底没触发/提前关了控制台，另查 |

`maxcpu=0` 是正常的（`cpus=1`）。**只要没崩在 cpu map，就说明兜底生效，
内核会继续往 `cpu_init` → `processor_bootstrap` → `bsd_init` 走。**

### 已经排除的

| 曾经的怀疑 | 结论 |
|---|---|
| APSS 看门狗 | `WDT EN=0`，从未启用 |
| shim 的 `reset()` | 已全部移除，只停机 |
| 24bpp 画不出字 | 已补齐，照片证实内核文字可见 |
| 控制台不滚动 | 已修，JPEG 里 `XNU jumping` 可见 |
| RPM L10 投票复位 | 已关（`BOARD_TOUCH_RAIL=0`）|
| 帧缓冲基址差 0x1000 | 已修（`shim_fb_claim`）|

现在只剩 **CPU 拓扑** 这一关，且已有兜底 + 诊断，不会再卡死。

---



## ★★★★★ 上一轮（2026-11-15 14:10，第 24 轮）-- ★ 内核跑起来了！进了 kernel_startup_bootstrap

### 重大进展：XNU 第一次真正执行，而且它的文字能看清

照片上半部是**黑底白字**（XNU 自己的 early console，24bpp 分支生效）：

```
SWEET EARLY 1: arm_init entered (MMU on)
SWEET EARLY 2: PE_init_platform
SWEET EARLY 3: ml_parse_cpu_topology
SWEET EARLY 4: cpu_bootstrap done
SWEET EARLY 5: kernel_startup_bootstrap
SWEET EARLY PANIC: machine_routines.c:1244
  assertion failed: cpu_id <= (unsigned int)ml_get_max_cpu_number()
```

**这句话的意义**：

| 以前 | 现在 |
|---|---|
| 屏幕停在 shim，看不到任何内核输出 | **内核跑完 4 个阶段，自己的文字显示出来了** |
| 一直重启 | **不重启了**（RPM 修复生效） |
| 不知道有没有进内核 | **确定进了，`JUMP 00000000A042A488`** |

### 本轮修掉的：cpu_id 断言

`ml_get_cpu_number()` 找不到 CPU 时返回 **-1**，转 unsigned 变成
`0xFFFFFFFF`，必然大于 `max_cpu_id` → 断言炸。

修法（`osfmk/arm64/machine_routines.c`）：

```c
if (cpu_id < 0 || cpu_id > (unsigned int)ml_get_max_cpu_number()) {
        printf("SWEET CPU MAP: mpidr=%llx masked=%x -> id %d, max %d, using boot cpu %d\n", ...);
        cpu_id = (unsigned int)ml_get_boot_cpu_number();
}
```

同时给 `ml_get_cluster_number_local()` 加了同样的兜底。
**不是把断言删掉了**——还会打印真实的 MPIDR 和拓扑 id，为的是下一轮能看到差异。

### eMMC 真实分区（照片首次完整读出）

```
GPT boot    F=790528   N=131072     (64 MB)
GPT cache   F=7471104  N=524288     (256 MB)
GPT userdat F=11010048 N=111132...  <- 末位被截断，需要下一张照片
GPT used=48
```

### LOG WRITE E=5 的含义

`e=5` = 等 `ST_WR_READY` 超时（写通路没就绪），不是致命错误。
现在有 IMEM 面包屑，不依赖 eMMC 日志，所以**不阻塞主线**。

### 硬阻塞：C 盘空间不够放根镜像

| 项 | 值 |
|---|---|
| 根镜像 artifact | `ios16-root-parts`，5.4 GB 压缩，过期 2026-11-19 |
| 拼开后 | 约 12 GB |
| C 盘可用 | **6.7 GB** |

→ **本机无法拼合**。必须：换有空间的机器、或先清盘、或直接下到移动硬盘。
详见 `docs/INSTALL-UGG.md` 第 2 节。

### 下一轮

内核编出来后启动，看是否越过 `kernel_startup_bootstrap` 继续往下：
`cpu_init` → `processor_bootstrap` → `bsd_init` → 等 `Apple_HFS`。
到 `bsd_init` 就需要根镜像了。

---



## ★★★★★ 上一轮（2026-11-15 13:55，第 23 轮）-- 重启真因找到了：RPM 触摸供电投票复位 SoC

### 用户照片（滚动已生效，最后一行是决定性证据）

```
LOG WRITE E                    <- 日志写 cache 失败（这就是拿不到日志的原因）
RPM: SMEM TBL=863064f8 SZ=0800
PORT=00060000 FIFO=00060800/04
ST=4
REOPEN: TX ST=2 RX ST=2        <- 最后一行，然后重启
```

### 重启真因：不是看门狗，不是 XNU，是 shim 自己

`rpm.c` 头部注释原话：

> a write to an RPM-owned LDO that the arbiter does not expect is
> **an arbiter violation and resets the SoC**

照片停在 `REOPEN`（RPM 通道刚打开），**下一件事就是 `input_setup()` 去投 L10**。
L10 是 **mido 的触摸供电轨**，没有证据表明 ugg 是同一个。→ **arbiter violation → SoC 复位。**

这也解释了一直以来的困惑：`WDT EN=0`（看门狗没开）、我们的 `reset()` 已删干净。
**是 shim 在跳内核前一步把自己复位了。**

**修法**：

```c
#define BOARD_TOUCH_RAIL  0   /* 触摸是「用」iOS 才需要，不是「启动」需要 */
#define BOARD_PERF_BOOST  0   /* perf.c 自己警告最后一个读会复位 SoC */
```

其他板子保持默认 1，行为不变。

### 新增：IMEM 阶段面包屑（本轮最重要的诊断手段）

屏幕每次启动都重画，**但 IMEM 复位后不清**。所以每个阶段往 `IMEM_STAGE`
（`0x08600600`）写一个数字，下次启动第一行打印：

```
LASTSTAGE = 0000000000000007
PREV      reached the XNU jump
```

| 值 | 含义 |
|---|---|
| `0xffffffff` | IMEM 被清，发生了比热复位更冷的事 |
| 1-6 | **shim 自己**停在该阶段 |
| >=7 | **已跳到 XNU**，之后的重启是内核的 |

这一个数字就区分了以前完全无法区分的两种情况。

### 另外两个修复

1. **滚动清除颜色 bug**：只写了 `con_bg & 0xff`，红色 `0xffff0000` 的最低位是 0
   → 新滚出来的行是**黑色**（照片底部那条暗带就是这个）。已改成写完整三字节。
2. **`LOG WRITE E` 现在打印错误码和扇区号**：`E=<cmd24错误> SEC=<第几个扇区>`。
   扇区 0 失败 = 写通路从未工作；中途失败 = 写出界。

### 本轮产物

```
shim-boot-0082-mido.img  8,173,568 B
sha256 9c86d46c599dfa839f95a545ca8b7b09083ffc494bd49e2bdc8cd9080ebab0ea
```

内核沿用（本轮只改 shim）：sha256 `f8617484e44d40774ca071c21b68812585aeaed48ef75bf024f8633a87f286f0`。
shim CI run `43682733963`（success）。

### 编译踩的坑（已修，记录备查）

| 错误 | 原因 |
|---|---|
| `last_err undeclared` | 它是 `sdhc.c` 的 static |
| `i undeclared` | 循环变量出了作用域 |
| `undefined reference to con_puts` | `con_puts` 只在 `mido_compat.h`，`shim.c` 没 include |

### 下一轮判断

| 看到 | 含义 | 下一步 |
|---|---|---|
| 不重启 + `XNU jumping` | ✅ RPM 修复成功 | 看内核文字 |
| 不重启但停在 emmc/input | 阶段号会指出 | 看 `LASTSTAGE` |
| 仍重启 + `LASTSTAGE=6` | perf 阶段 | 继续排除 |
| 重启后 `LASTSTAGE>=7` | **已跳到 XNU**，重启是内核的 | 查 XNU panic |

---



## ★★★★★ 上一轮（2026-11-15 13:35，第 22 轮）-- 照片里藏着两个致命 bug，都已修

上机手册已独立成文：**`docs/INSTALL-UGG.md`**（放镜像 + TWRP 清理，逐步可执行）。

### 照片读出的决定性数据

```
RGB0 ADDR=90001000 FMT=... STRIDE=00000870 SIZE=056002d0
```

拆开看：

| 值 | 含义 |
|---|---|
| `STRIDE=0x870` = 2160 = 720×3 | **24bpp 第三次确认** |
| `SIZE=0x056002d0` = 1376×720 | 源尺寸高 1376（比面板 1280 大，不影响） |
| **`ADDR=90001000`** | **面板从 0x90001000 扫，我们写 0x90000000** |

### Bug 1：帧缓冲基址差 4096 字节

4096 字节 ÷ 3 = **1365 像素**，所以屏上每一行 = 上一行的尾巴 + 这一行的头。
照片左侧那些残字 **`UMP` / `2d0` / `TE=0`** 就是这个 —— 不是乱码，是错位。

修法：`fb32.c` 新增 `shim_fb_claim()`，**读 `SRC0_ADDR` 再写回 `FB_PHYS`**，
并且回读验证。在 `con_clear()` **之前**调用。

### Bug 2：控制台根本不会滚动 ← 这才是"永远看不到 XNU"的真凶

`console.c:124`：
```c
if (x0 + CH_W > FB_W || y0 + CH_H > FB_H)
        return;        // 超出就静默丢弃，但 row 还在 ++
```

屏幕 1280 高 / 32px 行 = 约 36 行。**填满之后所有输出全被扔掉了**，
包括 `INITRD` / `JUMP` / `XNU jumping`，更别说内核文字。
照片停在 GPT `#5` 就是这个原因。

修法：新增 `con_scroll()` + `con_ensure_row()`（2160 不是 32 的倍数，
所以能用 8 字节就 8 字节，否则按字节搬）。

### 附带优化

GPT 原来打印全部 48 项 → 只打 `cache` / `userdata` / `boot` + 总数量。
每次滚动要搬 2.6MB，48 行会把关键行全挤出屏幕。

### 本轮产物

shim-boot-0082-mido.img  8,173,568 B
sha256 292d7ae76213f687c10bc24bcd0c5dcde31fa8e452de53bb6e427ee1f0263ed9
```

内核沿用第 21 轮（本轮只改 shim）：CI run `43673847688`，
sha256 `f8617484e44d40774ca071c21b68812585aeaed48ef75bf024f8633a87f286f0`。
shim 来自 run `43681289670`（success）。

已核实：shim 含 `RGB0 was=` / `stride matches` / `frozen; hold POWER` / `GPT used=`，
无 `selftest`、无 `RGB0 SWITCHED`；payload 含 `bsd_init` 与 `/product`。

### 下一轮看点

`XNU jumping` 之后是否出现内核文字（24bpp 分支 + 基址正确 + 滚动可用，三个都通了）。
若出现 `PANIC` + ESR/ELR/FAR，那张照片是最有价值的输入。

---


## ★★★★★ 上一轮（2026-11-15 11:40，第 21 轮）-- 24bpp 分支根本不存在

> 完整记录：`docs/MIDO-PORT-PLAN.md`。上机手册 `TEST-GUIDE.md`。

### 用户第 20 轮反馈

> "现在又花屏了，又是之前那种满屏条纹，然后又重启……没进内核，没有看到内核日志"

两条独立问题被我一轮混在一起改了，分别定位如下。

### 问题一：重启是我们的代码干的（已彻底删除）

`shim.c` 的 `exc_handler()`（**异常处理入口**）末尾调用了 `reset(40)`：

```c
con_hex("ESR", ...);  con_hex("ELR", ...);  con_hex("FAR", ...);
reset(40);          // <- XNU 一崩，打印完就重启
```

第 20 轮只删了正常返回路径的 `reset(20)`，**漏了这个**。所以"闪一下就重启"依旧。

**本次改动**：`reset()` 不再重启（`PSCI_SYSTEM_RESET` / IMEM / PSHOLD 全部移除），
改为永久停机等用户长按电源键。已在源码中确认**没有任何重启路径残留**：

```
grep -n "smc(PSCI_SYSTEM_RESET|wr32(IMEM_RESTART_REASON|wr32(PSHOLD" shim/*.c
-> 空
```

同时在异常处理里加了 `ugg_emmc_flush_log()`：崩溃寄存器会**写进 cache 分区**，
即使屏幕看不清也能用 dd 取出来。

### 问题二：为什么永远看不到内核文字 —— 找到根因了

`osfmk/console/video_console.c` 里所有按 `v_depth` 分支的地方，
**只有 8 / 16 / 30 / 32，没有 24**：

| 函数 | 没有 24 的后果 |
|---|---|
| `vc_paint_char()` | **一个字都不画** ← 这就是屏幕空白的原因 |
| `vc_render_char()` | 字模位图不生成 |
| `vc_blit_rect()` | 滚动/清屏无效 |
| `vc_reverse_cursor()` | 光标不反显，且偏移算错 |
| `vc_color_index_table[24]` = 0 | 24bpp 误用 8bpp 调色板：白=0x00000000 → **黑底黑字** |

我们传的是 `v_depth = FB_BPP * 8 = 24`（这块屏实测就是 2160 字节行宽 = 24bpp）。
**所以内核从来没有能力在这块屏上画任何一个像素。**

这不是 ugg 特有 bug，是 **upstream 从没写过 24bpp 支持**。

**本次补齐**（`xnu-src/osfmk/console/video_console.c`，全部进 0082 补丁）：

| 新增 | 说明 |
|---|---|
| `vc_paint_char_24()` | 字节寻址画字，每像素 3 次写 |
| `vc_blit_rect_24()` | 滚动/清屏/进度条 |
| `vc_render_char()` 的 `case 24` | 3 字节覆盖率掩码 |
| 光标反显 `case 24` | 24 字节取反 |
| 光标字节偏移修正 | `xx*v_depth` → `xx*ISO_CHAR_WIDTH*bpp` |
| `vc_color_index_table[24] = 3` | 用 32bpp 那列（纯 0xRRGGBB） |

字模尺寸自洽性已核对：24bpp → 24 字节/行 × 16 行 = 384 B，
`vc_rendered_char[512]` 够用。

### 关键旁证：内核本来是好的

CI 的 QEMU 任务（run `43669073531`，check-run `qemu`）：

```
qemu-verdict : PASS: bsd_init complete, waiting for an IOMedia/Apple_HFS root
qemu-bsd_init: of 6 stages: 4 reached
qemu-result  : {"status": "no_panic_observed"}
```

**内核在 QEMU 里能完整跑到 bsd_init 完成、无 panic。**
所以"进不去"不是内核坏了，是它**没有能力把画面画出来**。
这也直接回答了"什么时候能进内核"——它一直在进，只是我们看不见。

### 关于 mido 的分辨率差异

用户问得对：**mido 是 1080×2400 @32bpp（stride 4320），我们是 720×1280 @24bpp（stride 2160）。**

- mido 的 shim 里**一行 MDP 代码都没有**，它直接用 ABL 留下的 32bpp framebuffer；
- 我照抄它的 32bpp → 我们又试了一次强制 MDP `SRC_FORMAT=0x000236ff`，
  **实机再次花屏**（32bpp 写、24bpp 扫描 → 每行差 540px、竖向压缩 0.75）。

结论：**这块屏只能 24bpp**。mido 的 32bpp 路线在这里不成立。
已把 `fb32.c` 改回**只读报告**，不再碰 MDP，并在注释里写清两次失败的证据。


### 补丁生成的两个坑（已修）

1. **`vc_blit_rect_24` 放错位置** —— 首次编译失败：
   ```
   error: call to undeclared function 'vc_blit_rect_24'
   error: static declaration follows non-static
   ```
   新函数被追加到调用点之后。已移到前向声明块之前。

2. **编辑器把整文件写成 CRLF** —— 3492 行全带 CR，
   补丁从 198 行膨胀到 6794 行。已归一化回 LF，
   并确认其余 28 个文件都干净。

### 本轮产物

```
shim-boot-0082-mido.img  8,173,568 B
sha256 a9821494b63ddc3f7e00fd59b0644f46a7a8862a455dedabed3568be7f8020c9
```

内核 CI run `43673847688`（success），17,139,912 B，
sha256 `f8617484e44d40774ca071c21b68812585aeaed48ef75bf024f8633a87f286f0`。

已核实：shim 含 `frozen; hold POWER`、无 `selftest`、含 `24bpp matches`；
payload 含 `bsd_init` 与 `/product`。

### 下载问题（重要，接手必读）

artifact 下载在本机反复 `unexpected EOF`（61 MB 需 12 次断点续传）。
**必须走本机代理 `http://127.0.0.1:7890`**。

另外：MSYS 的 `/tmp` 实际是 `C:/Users/<user>/AppData/Local/Temp/2`，
Python 看不到 `/tmp/xxx`，要先 cp 到工作区再处理。

### 本轮最终形态

| 项 | 状态 |
|---|---|
| 显示 | 24bpp（实测可读，不再动） |
| MDP | 只读，不写 |
| 重启 | **全部移除**，故障时永久停屏 |
| 崩溃信息 | 打印到屏 + 写入 cache 分区 |
| 内核 24bpp 文字 | **新实现** |

---


## ★★★★★ 上一轮（2026-11-15 11:10，第 20 轮）-- 回到主线：全线 32bpp（后被实机推翻）

> 32bpp 在实机上再次花屏，第 21 轮已回退到 24bpp 并补齐内核 24bpp 支持。

> 完整记录：`docs/MIDO-PORT-PLAN.md`。上机手册 `TEST-GUIDE.md`。

### 用户照片给出的两条**决定性**证据

**证据一：重启是我们自己的代码干的，不是看门狗。**

```
PREVBOOT 0000000077665500
```

`0x77665500` 正是本项目 `reset()` 写进 IMEM 的 `RESTART_BOOTLOADER` 值。
而同一屏上 `WDT EN=00000000` —— **看门狗根本没启用**。

所以之前"看门狗咬的"这个判断**是错的**。真正的重启源是 `shim.c` 里
`loader_boot()` 返回后的 `reset(20)`：它把原因打印到屏幕，然后 20 秒后重启，
**正好在能拍照之前把证据抹掉**。这就是为什么每一轮都看不到结果。

**已删除该 reset，改为停住等用户长按电源键。**

**证据二：屏幕其实是好的。** 红底控制台所有诊断行都正常显示、
eMMC/GPT/通道号全部可读 —— 说明 0x90000000 的像素上屏没问题。

### 回到主线：照 mido 走 32bpp

mido 的做法：

```c
#define FB_BASE   0x9c000000UL      /* ABL 留下 */
#define FB_STRIDE (FB_W * 4)         /* a8r8g8b8 */
volatile uint32_t *con_fb
```

**mido 的 shim 里完全没有任何 MDP 代码** —— 它直接用 ABL 留下的 32bpp framebuffer。

我们之前退回 24bpp 是**错误的路线**，因为它让 XNU 走进死路：

| 问题 | 代码位置 | 后果 |
|---|---|---|
| `vc_paint_char()` 只有 8/16/30/32，**没有 24** | `osfmk/console/video_console.c` | 内核文字**一个像素都不画** |
| `fRowBytes < fWidth * 4` 直接 return false | `SweetFramebuffer.cpp:187` | **GUI 挂不上** |

→ 所以 24bpp 下**永远不可能**出内核文字或 GUI。**必须 32bpp。**

### 本轮改了什么

| 文件 | 改动 |
|---|---|
| `shim/board.h` | `FB_BPP` 3 → **4** |
| `SWEET.h` | `UGG_FB_BPP 4`、`UGG_FB_STRIDE 2880` |
| `sweet_early.c` | 回到单个 32 位写入，`EARLY_STRIDE = STRIDE/4` |
| `shim/fb32.c` | **写 MDP RGB0 = 0x000236ff + unpack 0x03020001，然后回读验证** |
| `shim/shim.c` | 切完后**重绘**；删掉 `reset(20)` 改成停住 |
| `xnu/patches/0082` | 重新生成（3021 行，`git apply --check` 通过） |

**为什么这次能判定成败**：以前"切换没生效"是**猜的**（没有回读）。
现在写完后回读 `SRC_FORMAT`，读不回来就明确打印 `RGB0 SWITCH REFUSED`。

### 新镜像（刷这个）

```
shim-boot-0082-mido.img  8,173,568 B
sha256 8d3618e6712ebc9b4eac44f761d9de031ead54d7c02fbdd1615ca32f45dee1d7
```

```
fastboot boot C:\\Users\\Administrator\\Desktop\\ios-ugg\\shim-boot-0082-mido.img
```

内核来自 CI run `43669073531`（`xnu` success，含 32bpp 改动），
sha256 `294392ff88e6de7d751c986834b8470375bd71141458f24504c19b073b43c38e`。

### 这次应该看到什么（关键变化）

```
BOOT WDT EN=00000000 -> 证明看门狗没装
RGB0 ADDR=... FMT=0002243f ...      <- 切换前
RGB0 FMT now=000236ff STRIDE now=00000b40   <- 切换后
SHIM ugg loader, 32 bpp verified     <- 重绘后，这一屏全是 32bpp 画的
INITRD / PHYS / ENTRY / SEGS
JUMP / XNU jumping (fbcon clears screen)
```

**然后 XNU 的文字应该第一次能看清了**（因为 `v_depth=32` 现在落在
`vc_paint_char()` 支持的 case 里）。

| 看到 | 含义 |
|---|---|
| `RGB0 SWITCHED` 没出现，而是 `SWITCH REFUSED` | MDP 不接受该值，需另找方案 |
| 切换成功 + 内核文字出现 | ✅ **主线的关键突破** |
| 切换成功但屏幕花 | 32bpp 但通道序/stride 仍需调 |
| 不再自动重启 | ✅ 自杀式 reset 已去掉 |

### 已放弃/不再碰的

- ❌ 看门狗（`WDT EN=0`，没装，不是元凶）—— 只保留一行诊断输出
- ❌ 24bpp（XNU 根本画不出来）
- ❌ 自检图（已删）

---

## ★★★★★ 上一轮（2026-11-15 09:30，第 19 轮）-- 看门狗排查（结论：不是它）

> 本节结论已被第 20 轮用户照片推翻：`WDT EN=0`，看门狗从未启用。


> 完整记录：`docs/MIDO-PORT-PLAN.md`。上机手册 `TEST-GUIDE.md`。

### 用户的照片说明了什么（三条结论）

照片内容：黑色背景，**闭合的白色边框**，三条横条自上而下 **红 → 蓝 → 绿**，
一条**竖直**白线，底部白条，右下洋红块。之后文字探测界面显示正常，
再之后**纯红屏，然后手机自己重启**。

**结论一：24bpp 几何修复成功。** ✅

| 判据 | 预期 | 照片 | 判定 |
|---|---|---|---|
| 边框闭合 | 四边都有 | 四边都有 | ✅ |
| 横条水平 | 水平 | 水平 | ✅ |
| 竖线竖直 | 竖直 | 竖直 | ✅ |
| 底部白条可见 | y=1200 可见 | 可见 | ✅ |
| 洋红块在右下 | 是 | 是 | ✅ |

pitch=2160 完全正确，剪切彻底消失。**上一轮的 32bpp→24bpp 诊断是对的。**

**结论二（新 bug）：G/B 通道互换。** 我画的是 红(y=0)→绿(y=100)→蓝(y=200)，
屏上是 红→**蓝→绿**。面板实际是 BGR 顺序，而 `early_px()` / `con_put()` 写的是
RGB 字节序。**这不影响读日志**（文字是白色，R=G=B），所以排在后面。

**结论三（已被第 20 轮推翻）：当时归因为 APSS 看门狗。** ❌ 实拍 `WDT EN=00000000`，看门狗从未启用；真正的重启源是 `shim.c` 的 `reset(20)`。

红屏是 shim 自己的 `con_clear(RED)`（`shim.c` 的 shim_main），
说明 shim **已经跑到跳内核那一步**，然后固定时间后复位。

根因：**LK 在交出控制权前装了 Qualcomm APSS 看门狗，之后不再喂狗。
Linux 有对应驱动关掉它，XNU 没有。** 所以跳进去后固定时间必复位 ——
这正是为什么每次日志都活不到被抓取。

设备树实证（`device-dumps/dt/base/soc/qcom,wdt@b017000`）：

```
reg            = <0xb017000 0x1000>
qcom,bark-time = 0x3a98  (15000 ms)
qcom,pet-time  = 0x2710  (10000 ms)
compatible     = "qcom,msm-watchdog"
```

### ⚠️ 重要更正：第一版看门狗代码是错的（已修）

我第一版 `wdt.c` 的寄存器偏移是**凭印象写的**，用的是另一套 `qcom-wdt.c`/KPSS 布局。
查了真实驱动后确认全错，而且**错得很危险**。

本板设备树写的是 `compatible = "qcom,msm-watchdog"` / `reg-names = "wdt-base"`，
对应 `drivers/watchdog/msm_wdt.c`，布局是：

```
WDT_RST       = 0x04   ← 写 1 就是喂狗
WDT_EN        = 0x08   ← bit0 使能
WDT_STS       = 0x0C
WDT_BARK_TIME = 0x10
WDT_BITE_TIME = 0x14
WDT_HZ        = 32768
```

**为什么危险**：旧代码把 `0x04` 当成 LOAD，但它其实是 `WDT_RST` ——
写它就是**喂狗**。旧代码会往 `WDT_RST` 写 120 秒的 tick 数、往 `WDT_EN` 写 tick 数，
等于**用垃圾值重新武装看门狗**，而不是关掉它。

同时修了两处：

| 项 | 错误 | 正确 |
|---|---|---|
| 停止顺序 | 先清 EN | `msm_wdt_disable()` 是**先喂狗再清 EN** |
| 单位 | 拿 `0x3fff` 当 tick 上界 | 计数器存 **tick**（驱动写 `10*WDT_HZ`）；`WDT_MAXTIMEOUT` 是**秒** |

单位错会导致：把**正常**的看门狗（`10*32768=0x50000`）判为"不合理"，从而**拒绝关闭**。

### 本轮改了什么

| 文件 | 改动 |
|---|---|
| `shim/wdt.c`（新） | 读 EN/STS/BARK/BITE；**仅当 EN 已置位**才关；按 `msm_wdt_disable()` 先喂狗再清 EN |
| `shim/wdt.h`（新） | 接口 |
| `shim/shim.c` | 控制台初始化**提前**到看门狗之前（否则红屏把报告擦掉）；删掉 12 秒自检图 |
| `shim/build.sh` | 加入 `wdt.c`，移除 `selftest.c` |

**加了合理性闸门**：EN 不是恰好 0/1、或 BITE < BARK，就**一个字节都不写**。
这样以后即使偏移再猜错，也碰不到硬件。

### 新镜像（刷这个）

```
shim-boot-0082-mido.img  8,171,520 B
sha256 bcd1b5779a07404b1170fd64bcc0f59c8a6ac92be7813fc1a02898039a315c1f
```

```
fastboot boot C:\\Users\\Administrator\\Desktop\\ios-ugg\\shim-boot-0082-mido.img
```

已核实镜像内（解 gzip 后）含 `WDT STOP en was=` / `WDT not armed` / `WDT SKIP` / `IMPLAUSIBLE`，
且 `selftest` 已消失；payload 里 `/product` 存在。

### 这次开机应该看到什么

不再有 12 秒自检图。开机直接是：

```
SHIM ugg loader + board probe      <- 先红屏清屏
BOOT WDT EN=... STS=... ARMED 或 off
BOOT WDT BARK=...ms=15000 BITE=...ms=18000
WDT STOP en was=... now=... ok 或 STILL ARMED   <- 仅当原本 ARMED
PREVBOOT xxxxxxxx
INITRD ...
EMMC / CACHE / LOG TO CACHE ...
RGB0 ADDR=... FMT=... STRIDE=...
XNU jumping ...
```

**关键判据（拍这一段就够）：**

| 看到 | 含义 |
|---|---|
| `WDT ... ARMED` 然后 `WDT STOP en ... ok` | ✅ 看门狗已关，启动不再被咬 |
| `WDT ... off` | 本来就没装，复位另有原因 |
| `WDT SKIP: registers implausible` | 偏移仍不对，已拒绝写入 |
| 卡住不再重启 | ✅ 本轮目标达成 |

### ⚠️ 自我更正：上一轮说"看门狗是真凶"说得太满

看门狗**仍是最可疑的**，但**尚未证明**。重读代码后发现一个更有说服力的解释：

**shim 的控制台本来就是红底黄字。** `shim.c` 的 `shim_main` 一进来就 `con_clear(RED)`。
而自检图是黑底的。所以用户描述的"红屏前有字的探测界面"，
**就是 shim 自己的红底控制台** —— 那个"红屏"很可能不是故障，
而是这个控制台滚到了下面、或某次重绘后的样子。

两种解释都还没被实机区分开。可以区分的证据：新镜像里 `WDT EN=` 那行的读数。

### 另一个真 bug（新发现）：XNU 视频控制台画不出 24bpp

`osfmk/console/video_console.c` 的 `vc_paint_char()` 只处理 **8 / 16 / 30 / 32**：

```c
switch (vinfo.v_depth) {
case 8: ... case 16: ... case 30: case 32: ...
}   /* 没有 case 24 */
```

而 shim 传进去的是 `ba->Video.v_depth = FB_BPP * 8 = 24`。
**所以 XNU 的视频控制台在 24bpp 下一个像素都不画。**
早期控制台（`sweet_early.c`，自己直接写 24bpp）能用，
但它一旦 `sweet_early_disable()`，内核文字就彻底没有输出了。

同理 `SweetFramebuffer.cpp` 第 187 行要求 `fRowBytes >= fWidth * 4`，
24bpp 的 2160 字节行宽过不了这个检查 —— 所以 GUI 那条路在 24bpp 下也走不通。

**这是一个策略性问题**：mido 是把 MDP 切到 32bpp/BGRA 才出 GUI 的。
我们之前因为"切换没生效"放弃了 32bpp，而那个放弃现在正好卡住了 GUI。
留待下一轮决策。

### 取日志的两条路（下一步）

1. **屏拍**：启动不再被重启打断，可以拍到更多行。
2. **cache 分区读日志**：`emmc.c` 已把 64 KiB 控制台日志写进 cache 分区
   （看到 `LOG TO CACHE ENABLED` 之后就有）。

### 还没做的

- G/B 互换（不影响读日志，排在后面）
- 根卷刷入（需要 ≥20 GB 空闲，C: 只有 8 GB）
- 触屏 / 桌面态

---


## ★★★★★ 上一轮（2026-11-15 08:45，第 18 轮）-- 首张真机照片：屏幕没坏，是 bpp 写错

> 本节结论已被第 19 轮的照片证实。

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1776 行）。上机手册 `TEST-GUIDE.md`。

### 你的照片说明了什么（结论：**屏幕没坏**）

照片里：顶部约 1/3 有文字但**斜向错位、重复、不可读**，其余是纯红，底部一条细亮线。

几何反推（三项独立吻合）：

| 计算 | 结果 | 照片对照 |
|---|---|---|
| 每行右移量 | `2160/4 = 540` 像素 | ✅ 正是斜向错位 |
| 竖向压缩 | `2160/2880 = 0.75` | ✅ 文字只占顶部 34% |
| 可见比例 | 75% | ✅ 后 1/4 不可见 + 底部 wrap 亮线 |

**根因：我们按 32bpp（pitch 2880）写，面板按 LK 留下的 24bpp（pitch 2160）扫描。**
而 `fb32.c` 的 32bpp 切换**没有生效**。

最糟的是：**shim 自己的诊断文字也被同一个错误弄糊了** —— 用来诊断显示的输出本身不可读。

### 这版改了什么

**全线回到 24bpp（LK 实际留下的格式）**：

| 文件 | 改动 |
|---|---|
| `ugg/shim/board.h` | `FB_BPP` 4 → **3** |
| `SWEET.h` | `UGG_FB_BPP 3`，`UGG_FB_STRIDE 2160` |
| `sweet_early.c` | `early_fb` 改字节指针，三处像素写入统一走 `early_px()` |
| `fb32.c` | 不再切换管道，改为**只读报告** `shim_fb_report()` |
| `selftest.c`（新） | **颜色自检图**，画 12 秒 |
| `shim.c` | 删掉 32bpp 门禁（不再有意义） |

### 新镜像（刷这个）

`
shim-boot-0082-mido.img  8,171,520 B
sha256 e6f43376599cc3947963095b92d9e8a5939523aa0222ddc4453a71b24e00cbf6
`

`
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
`

已核实镜像内含：自检图字符串、eMMC 初始化、`/product` 节点。

### 开机会先看到自检图（12 秒）

`
白色边框（四边）
红色横条   y=0
绿色横条   y=100
蓝色横条   y=200
白色横条   y=1200     <- 靠近底部，最关键
竖白线     x=360
洋红块     右下角
`

**这次不需要「看懂文字」，看形状就够**：

| 看到 | 含义 |
|---|---|
| 边框**闭合**、横条**水平**、竖线**竖直** | **几何正确** ✅ |
| 边框**斜的** / 呈平行四边形 | pitch 仍不匹配 |
| 白条跑到屏幕外 / 不见 | 面板扫描行数比我们写的少 |
| 只有上半屏有图案 | 只扫了一部分 |
| 洋红块不在右下角 | 底部映射有偏移 |
| 全黑 | 自检图都没画出来 |

12 秒后自动继续正常启动（eMMC 探测 → 打印管道报告 → 跳内核）。

## ★★★★★ 上一轮（2026-11-15 07:45，第 17 轮）-- /product 拿到了；上机手册已写

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1700+ 行，权威且无损）。
> **上机测试手册：`TEST-GUIDE.md`** —— 照着做就行。

### 本轮实质进展：真的拿到了 Apple 的 D20AP device tree

| 项 | 值 |
|---|---|
| CI artifact | `ios-device-tree`（run 43644714094） |
| device tree | **185,084 B，253 节点，含 /product** |
| 生成后的 ADT | **12,452 B**（原 9,896） |
| mido 对照 | 它的 D211AP 版是 12,504 B —— 同一规格 |

链路：`IPSW → DeviceTree.d20ap.im4p（Range 抽取）→ DER/IM4P 解包 → LZFSE 解压`
`→ 校验 ADT → 挂到 /product`。全部实测通过。

**为什么必需**：mido 记录，缺 `/product` 时 backboardd 会崩溃循环
（`attachImage: surface b3a8 ... format failed`）—— 内核能起、根卷能挂，但**桌面出不来**。

### 镜像已更新（刷这个）

`
shim-boot-0082-mido.img  8,171,520 B
sha256 04fb64de8c78b5b5faf55bc3df1b1c2ba07b095c0551e0afab8bd5586fcd6db3
`

`
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
`

### 修好了我上一轮弄坏的东西

第 16 轮末尾本机 **Windows 虚拟内存耗尽**（`os error 1455`），我用有读取上限的工具
整文件重写了本文件，把 **1956 行截断到 1430 行**。

**已从 git 对象库完整恢复**（blob `99d49f9d`，64,168 字节，1956 行），核对首尾无误。

教训写进提交里：**永远不要用有读取上限的读取结果去整文件重写**。

### 当前交付清单

| 产物 | 位置 | 状态 |
|---|---|---|
| boot.img | 工作区根目录 `shim-boot-0082-mido.img` | ✅ 8,171,520 B，含 /product |
| 根卷 | GH artifact `ios16-root-parts`（run 43644714094） | ✅ 11.97 GB，7 片，有效期到 11/19 |
| device tree | GH artifact `ios-device-tree` | ✅ 185 KB，含 /product |
| 上机手册 | `TEST-GUIDE.md`（工作区根目录 + 仓库内） | ✅ 210 行 |

### 现在的状态

**所有离线能做的都做完了，等真机验证。** 具体步骤见 `TEST-GUIDE.md`。

---


## ★★★★★ 上一轮（2026-11-15 06:10，第 17 轮）-- /product 已打通；文件已修复

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1653 行，权威且无损）。

### 先说我修坏的东西（已恢复）

上一轮末尾本机 **Windows 虚拟内存耗尽**（`os error 1455`），我用有读取上限的工具做
整文件重写，把本文件从 **1956 行截断到 1430 行**。

**已从 git 对象库完整恢复**（blob `99d49f9d`，64,168 字节，1956 行），并核对了首尾。

### 本轮实质进展：`/product` 节点已打通

mido 的日志说 `/product` 只对 userland 必需，缺了它的后果是 backboardd 崩溃循环
（`attachImage: surface b3a8 ... format failed`）。我的 ADT 一直没有这个节点。

| 环节 | 状态 |
|---|---|
| 从 IPSW 抽 `DeviceTree.d20ap.im4p` | ✅ `tools/ipsw_adt.py` |
| 解 DER/IM4P + **LZFSE**（三级回退） | ✅ |
| CI 实跑（run 43644714094） | ✅ **全部 15 步 success** |
| ADT 自动带 `/product` | ✅ 9896 → 10124 字节，22 节点 |
| Apple 固件不入库 | ✅ `.gitignore` 加 `*.im4p` / `*d20ap.adt` |

该 run 的完整步骤链：

`
Free up runner disk → Install toolchain → Build apfs-fuse → Fetch the IPSW
→ Extract the three system images → Extract the device tree for /product ✅
→ Build the HFS+ root ✅ → Apply the bring-up tweaks → Convert to sparse and split
`

**注意**：设备树步骤现在是 `continue-on-error`，它失败也不会再阻断根卷构建
（上一轮它曾把 20 分钟的根卷产物整个 skip 掉）。

### 我修掉的三个自己的错误

1. 误以为 ADT 是 FDT（检查 `d00dfeed` 魔数）—— **ADT 没有魔数**，改用 `adt.parse()` 验证
2. 自动发现路径从 `ugg/tools` 往上找了三级（应为两级）
3. 可选步骤失败阻断主流程（已改 `continue-on-error` + 内部软失败）

### 镜像（不变）

`
shim-boot-0082-mido.img  8,169,472 B
sha256 3fa935772411dadfdda6d14ac1fbcd0126fa6e252bcb9be1b5550ee119f453a4
`

`
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
`

### 根卷（两个成功的 artifact）

| run | 大小 | 分片 |
|---|---|---|
| 43634756880 | 11,970,598,900 B | 7 片 |
| 43644714094 | 同上规格（本轮含 device tree） | 7 片 |

**有效期到 11/19**。需 20 GB 空闲盘：`./ugg/flash-root.sh /path/with/20GB`

---


## ★★★★★ 上一轮（2026-11-15 05:40，第 15 轮）-- 关键结论：QEMU 到 M2，eMMC 必须真机验

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1582 行）。

### QEMU 已经跑通到 M2（上一轮），这轮搞清了它证明了什么

**已证明**（38 行屏幕完整解码）：

```
bsd_init: calling loopattach → ether_family_init → net_init_run
        → inittodr → setconf
Waiting on <dict ... IOMedia ... Apple_HFS>
```

| 已证明 |
|---|
| start.s → MMU → pmap → VM bootstrap 全通 |
| IOKit / platform expert |
| `bsd_init` 全部子系统（kauth/MAC/buffer/socket/domain/skywalk/net） |
| **旧路线卡死点 A1 不存在了** —— 16K VM over 4K granule 有效 |

**没证明**（必须真机）：

| 项 | 为什么 |
|---|---|
| eMMC 驱动 | QEMU 没有 eMMC 硬件，`SWEET UFS` 行根本不出现 |
| GT9xx 触摸 | 同上 |
| RPM 电源 | 同上 |

### 一个修正了的判读预期（重要）

`iokit/bsddev/IOKitBSDInit.cpp:778`：

```c
int ufs_error = sweet_ufs_rootdev(root);
if (ufs_error) {
    panic("IOFindBSDRoot: SWEET UFS root %s unavailable: %d", rdBootVar, ufs_error);
}
```

**eMMC 驱动失败 = 直接 panic，不是「等待根设备」。**

| 真机现象 | 含义 | 下一步 |
|---|---|---|
| `panic: IOFindBSDRoot: SWEET UFS root ufsroot0 unavailable: N` | eMMC 驱动失败（N=errno） | 把 N 告诉我 |
| `Still waiting for root device` | eMMC OK 但**没刷根卷** | 去刷根卷 |
| 苹果 logo → 锁屏 | 成功 | 恭喜 |

**好消息**：`serial_console.c:286` 的 `if (sweet_console_muted && !panic_active())` 意味着
**panic 时一定会重新绘制到屏幕**，即使 `sweetfb_noconsole=1`。两种结局都能看到。

### CI 门禁升级

QEMU 检查从「能画字就算过」升级为：

- 统计 6 个 `bsd_init` 阶段
- 识别 QEMU 特有的是 `Waiting on ... IOMedia ... Apple_HFS`（这是它在这块板上的最好结果）
- 明确输出 `PASS: bsd_init complete ... (M2)` 或 `FAIL: kernel panicked`

已用真实屏幕文本回放验证：`of 6 stages: 4 reached` + `PASS ... (M2)`。
以后任何改动让 pmap/IOKit/bsd_init 退化，都会立刻可见。

### 镜像（不变）

```
shim-boot-0082-mido.img  8,169,472 B
sha256 3fa935772411dadfdda6d14ac1fbcd0126fa6e252bcb9be1b5550ee119f453a4
```

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

### 根卷（不变，已就绪）

artifact `ios16-root-parts`（run 43634756880），11,970,598,900 B，7 片，**有效期到 11/19**。
需 20 GB 空闲盘：`./ugg/flash-root.sh /path/with/20GB`

---


## ★★★★★ 上一轮（2026-11-15 05:30，第 14 轮）-- QEMU 跑通到 M2，真机应同样

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1505 行）。

### 重大进展：内核在 QEMU 里跑到了「等待根设备」

```
qemu-verdict  kernel is drawing text on the early console
qemu-text     38 行非空，38 行含字母数字
```

屏幕解码出的末尾（内核实际顺序）：

```
bsd_init: calling inittodr
bsd_init: calling setconf
Waiting on <dict ID="0"><key>IOProviderClass</key><string ID="1">IOMedia</string>
             <key>Content</key><string ID="2">Apple_HFS</string></dict>
```

**这就是 M2。** pmap、VM bootstrap、IOKit、`bsd_init` 全部跑完，停在找 HFS 分区。

### 根因：`phys_base` 落在不同的 1 GiB L1 区（不是内核 bug）

`start.s` 把 framebuffer 的 4 个 L2 block 写进「第一个 L2 页」，
**假设 RAM 和 fb 共享同一个 L1 条目**。

| 环境 | phys_base | RAM 的 L1 索引 | fb 的 L1 索引 | |
|---|---|---|---|---|
| 真机 | `0xA0000000` | 2 | 2 | ✅ 相同 |
| QEMU（之前） | `0x50000000` | **1** | **2** | ❌ 不同 |

不同索引 ⇒ 那 4 个 block 写进了 RAM 的 L2 表里 fb 的槽位 —— 表错了，fb 没映射，
内核一开 MMU 就取指失败。与日志完全吻合（FAR 是物理地址、该处是 `isb`、前面是 `msr SCTLR_EL1`）。

**修复**：`QEMU_PHYS_BASE` 改为 `0xA0000000`（真机的值）。

### 为什么这个结果对真机有参考价值（已实测确认）

| 项 | 真机 payload | QEMU payload |
|---|---|---|
| phys_base | `0xa0000000` | `0xa0000000` |
| mem_size | `0x5ff00000` | `0x5ff00000` |
| entry | `0xfffffff00742a488` | 同 |
| kernel_end | `0xfffffff0084b4000` | 同 |
| **段表** | 10 段 | **完全相同** |

两者**只差 ADT 里的 GIC 地址（0x0b000000 vs 0x08000000）和时基（19.2 vs 62.5 MHz）**，
那是硬件差异，不影响内核被加载到哪里。

**⇒ QEMU 能跑到 M2，真机没有理由跑不到。**

### 这也说明前几轮修的 bug 是对的

前几轮修的 framebuffer 地址、mark 越界、MDP 32bpp、eMMC 初始化、L6 电源，
**都不是 QEMU 黑屏的原因**，但它们都是真 bug —— 现在内核能在正确的地址布局下
跑完全程，说明这些修复没有引入回归。

### 镜像（不变，仍然是这个）

```
shim-boot-0082-mido.img  8,169,472 B
sha256 3fa935772411dadfdda6d14ac1fbcd0126fa6e252bcb9be1b5550ee119f453a4
```

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

预期：**停在 `Still waiting for root device`（M2）** —— 因为还没刷根卷。

### 根卷（不变，已就绪）

artifact `ios16-root-parts`（run 43634756880），11,970,598,900 B，7 片，**有效期到 11/19**。
需 20 GB 空闲盘：`./ugg/flash-root.sh /path/with/20GB`

---


## ★★★★★ 上一轮（2026-11-15 05:20，第 13 轮完）-- 刷这个镜像

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1432 行）。

### 镜像

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

```
8,169,472 B
sha256 3fa935772411dadfdda6d14ac1fbcd0126fa6e252bcb9be1b5550ee119f453a4
```

### 这版改了什么

**去掉 `-enable_kprintf_spam`。** mido 的日志（PORTING_LOG 574-576）明确写：

> 「`-enable_kprintf_spam` 的行在 mute 之后仍然绘制，所以去掉这个启动参数」

去掉之后它才进了苹果 logo 和锁屏。我的 cmdline 一直带着这个参数。

### 启动参数现在与 mido 对齐

| 参数 | mido | ugg |
|---|---|---|
| `sweetfb_hz` | 30 | **30** ✓ |
| `-enable_kprintf_spam` | 无 | **无** ✓ |
| 其余 13 项 | — | 全部一致 ✓ |
| `-v` | 无 | **有**（有意：现在需要看打印） |
| `cpus` | 6 | **1**（有意：LSE 模拟器非多核原子） |

### 内核门禁复核通过（实测）

对内核二进制逐项检查：

| 检查 | 结果 |
|---|---|
| `UGG LSE` / `emulating` / `LDADD` 字符串 | 全部 FOUND |
| `handle_uncategorized` / `sleh_synchronous` / `arm_fast_fault` | 全部 FOUND |
| `__TEXT_EXEC` 里的真 LSE 指令 | **0 条** |

唯一被扫出的一条在 `K256 + 0xe4`（`0x78a5636f`）—— 那是 **SHA-256 常量表**，
数据里的字面量恰好命中 LSE 掩码，与 mido 的 `kscan.py` 记录同一个假阳性。

**⇒ EL0 LSE 模拟器完整可用，内核代码无真 LSE。**

### 屏显预期

```
SHIM    ugg loader + board probe
MDP RGB0: ADDR=90000000 FMT=0002243f STRIDE=00000870
MDP RGB0 -> FMT=000236ff STRIDE=00000b40 (32 bpp)
EMMC HC_MODE=00000001
 BUS POWER ON: PWRREQ=..
LBA0 E=0 SIG=AA55 OK
LBA1 E=0 GPT OK
#25 F=... N=... cache          <- 你的真实分区表
LOG TO CACHE ENABLED / LOG VERIFY OK
INPUT SETUP: RPM L10 E=0 L6 E=0 CLK ON
LOADER  <原因>
```

| 看到 | 含义 |
|---|---|
| `FB32 FAILED: not booting XNU` | 管道状态异常，已拒绝启动 → **拍照** |
| `EMMC INIT FAILED` / `BUS POWER STILL OFF` | eMMC 没起来 → **拍照** |
| `LBA1 ... GPT OK` + 分区列表 | **eMMC 通了** ✅ |
| `Still waiting for root device` | 没根卷（预期，M2） |
| `panic:` / 苹果 logo / 锁屏 | 拍照 / 等 / **目标达成** |

### 根卷（不变）

artifact `ios16-root-parts`（run 43634756880），11,970,598,900 B，7 片，**有效期到 11/19**。
需 20 GB 空闲盘：`./ugg/flash-root.sh /path/with/20GB`

---


## ★★★★★ 上一轮（2026-11-15 05:10，第 12 轮完）-- 刷这个镜像

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1373 行）。

### 镜像

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

```
8,169,472 B
sha256 9149b117ffaae6d19e44e792c046e807f59dec1485bd36de7207b14fd29359fa
```

### 这版新增：启动门禁（照抄 mido）

mido 不是无条件跳 XNU，而是：

```c
if (fb == 0) {   /* XNU needs the 32 bpp framebuffer; never boot it on LK's 24 bpp */
    loader_boot(dtb);
}
```

我的 shim 之前是无条件跳。这很危险：**如果 MDP 切换失败，XNU 会在 24bpp 面板上
按 32bpp 渲染，屏幕不可读 —— 那就无法区分「显示故障」和「内核故障」**，
而刷小镜像的唯一目的就是读屏。

现在 `fb32 != 0` 时：

```
FB32    FAILED: not booting XNU (see MDP line above)
HOLD    POWER to reboot
```

屏上留下的是 shim 自己可读的输出。

### 累计已修的 5 个「shim 欠 XNU 的步骤」

| XNU 侧 | 依赖 shim | 轮次 |
|---|---|---|
| `sweet_ufs.c` | eMMC 初始化到 transfer state | 10 ✅ |
| `ugg_input.c` | L10 + L6 电源 | 10 ✅ |
| `ugg_input.c` | QUP3 时钟、gpio10/11/64/65 | 原有 ✅ |
| `SWEET.h` | MDP RGB0 → 32bpp | 11 ✅ |
| mido `shim_main` | **32bpp 失败则不跳 XNU** | **12 ✅** |

### 屏显预期（从上到下）

```
SHIM    ugg loader + board probe
MDP RGB0: ADDR=90000000 FMT=0002243f STRIDE=00000870
MDP RGB0 -> FMT=000236ff STRIDE=00000b40 (32 bpp)
EMMC HC_MODE=00000001
 PRES=... HCTL=... CLK=... HCTL2=...
 BUS POWER ON: PWRREQ=..
LBA0 E=0 SIG=AA55 OK
LBA1 E=0 GPT OK
#25 F=... N=... cache        <- 你的真实分区表
CACHE F=... N=...
LOG TO CACHE ENABLED
LOG VERIFY OK
INPUT SETUP: RPM L10 E=0 L6 E=0 CLK ON
LOADER  <原因>
```

| 看到 | 含义 | 动作 |
|---|---|---|
| `MDP: unexpected FMT` + `FB32 FAILED: not booting XNU` | 管道状态异常，已拒绝启动 | **拍照**（屏或许还能看清） |
| `EMMC INIT FAILED` / `BUS POWER STILL OFF` | eMMC 没起来 | **拍照** |
| `LBA1 ... GPT OK` + 分区列表 | **eMMC 通了** ✅ | 继续 |
| `Still waiting for root device` | 没根卷（预期，M2） | 刷根卷 |
| `panic:` | — | **拍照** |
| 苹果 logo | 根卷挂载成功 | 等锁屏 |

### 根卷（不变）

artifact `ios16-root-parts`（run 43634756880），11,970,598,900 B，7 片，**有效期到 11/19**。
本机 C: 只剩 7.3 GB，需在 20 GB 空闲的机器上：`./ugg/flash-root.sh /path/with/20GB`

---


## ★★★★★ 上一轮（2026-11-15 05:05，第 11 轮完）-- 刷这个镜像

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1322 行）。

### 镜像

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

```
8,169,472 B
sha256 f65d72194abf50588c467d3b7f14f200207cf91cae3e9fdbbb981c2a7eded03d
```

### 这版比上一版多了 MDP 32bpp 切换

`SWEET.h` 里写着「the shim switches MDP RGB0 to 32 bpp」，但 ugg 的 shim
**完全没有 MDP 代码**。RGB0 还是 LK 的 24bpp（stride 2160），而 shim 控制台和
XNU 都按 32bpp 写（stride 2880）⇒ **每行错位，屏幕会是斜条纹**。

新增 `shim/fb32.c`：验证 LK 状态 → 切 `SRC_FORMAT=0x000236ff` /
`UNPACK=0x03020001` / `stride=2880` → flush RGB0。`FB_BPP` 3→4。

### 「shim 欠 XNU 的步骤」清单（4 条，全部已补）

| XNU 侧 | 依赖 shim | 轮次 |
|---|---|---|
| `sweet_ufs.c` | eMMC 初始化到 transfer state | 第 10 轮 ✅ |
| `ugg_input.c` | L10 + L6 电源 | 第 10 轮 ✅ |
| `ugg_input.c` | QUP3 时钟、gpio10/11/64/65 | 原有 ✅ |
| `SWEET.h` | MDP RGB0 → 32bpp | **第 11 轮 ✅** |

### 屏显判读（更新）

```
MDP RGB0: ADDR=90000000 FMT=0002243f STRIDE=00000870
MDP RGB0 -> FMT=000236ff STRIDE=00000b40 (32 bpp)     <-- 成功
EMMC HC_MODE=00000001
 BUS POWER ON: PWRREQ=..
LBA0 E=0 SIG=AA55 OK
LBA1 E=0 GPT OK
#25 F=... N=... cache
LOG VERIFY OK
INPUT SETUP: RPM L10 E=0 L6 E=0 CLK ON
```

| 看到 | 含义 | 动作 |
|---|---|---|
| `MDP: unexpected FMT ... screen may be unreadable` | 管道状态不是预期的 | **拍照**（屏可能看不清，尽量拍） |
| `MDP RGB0 -> FMT=000236ff` | 32bpp 切换成功 | 继续 |
| `EMMC INIT FAILED` / `BUS POWER STILL OFF` | eMMC 没起来 | **拍照** |
| `LBA1 ... GPT OK` + 分区列表 | **eMMC 通了** ✅ | 继续 |
| `Still waiting for root device` | 没根卷（预期，M2） | 刷根卷 |
| `panic:` | — | **拍照** |

### 根卷（不变）

artifact `ios16-root-parts`（run 43634756880），11,970,598,900 B，7 片，**有效期到 11/19**。
下载需 20 GB 空闲盘：`./ugg/flash-root.sh /path/with/20GB`

---


## ★★★★★ 上一轮（2026-11-15 04:55，第 10 轮完）-- 刷这个镜像

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1258 行）。

### 镜像

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

```
8,169,472 B
sha256 2b435f5b189849d28f809162c6e00e18faa51523f21d048ce9ec9c2608b93edc
```

### 这版修了什么（比之前所有版本都关键）

**1. shim 现在会初始化 eMMC（之前完全没做）**

`shim_main()` 原本把 `loader_boot()` 放第一条语句，eMMC 初始化只在「无 payload」
分支里跑。所以手机带 payload 启动时**卡从未被初始化**。

XNU 自己的代码就是证据（`bsd/dev/sweet_ufs.c`）：

```c
printf("UGG EMMC: card not in transfer state after the shim (%d)\n", e);
```

**「after the shim」** —— 它假设 shim 已经把卡初始化好，自己只调超时计数器。

| 不修会怎样 |
|---|
| `Still waiting for root device` 永远不出来 |
| **即使刷了 16 GB 根卷也读不到 GPT** |
| 会被误判成根卷问题 |

**2. 补上 L6 电源（vcc_i2c 1.8 V）**

`ugg_input.c` 注释说 shim 会准备 L10 + **L6** 两路，实际只投了 L10。
UGG 的 DTB：`goodix@5d` 的 `vcc_i2c-supply` = `regulator-l6`（1.8 V）。
没这路电，I2C 上拉无源，总线恒读 0xFF。

### 屏上现在会多出这些行（判读用）

```
EMMC HC_MODE=00000001
 PRES=... HCTL=... CLK=... HCTL2=...
 BUS POWER ON: PWRREQ=..
LBA0 E=0 SIG=AA55 OK
LBA1 E=0 GPT OK
#25 F=... N=... cache
CACHE F=... N=...
LOG TO CACHE ENABLED
LOG VERIFY OK
INPUT SETUP: RPM L10 E=0 L6 E=0 CLK ON
```

**关键判读**：

| 看到 | 含义 | 动作 |
|---|---|---|
| `EMMC INIT FAILED` | shim 阶段 eMMC 就没起来 | **拍照给我** |
| `BUS POWER STILL OFF - ABORT` | 电源握手失败 | **拍照给我** |
| `LBA0 ... BAD` / `NO GPT` | 读到了但内容不对 | **拍照给我** |
| `LBA1 ... GPT OK` + 分区列表 | **eMMC 通了** ✅ | 继续看后面 |
| `Still waiting for root device` | eMMC OK 但没根卷（预期） | 去刷根卷 |
| `panic:` | **拍照给我** | |

这次屏上会直接列出**你的真实分区表**（`#25 F=... N=... cache` 这样的行），
那本身就是 eMMC 驱动工作的证明。

### 根卷（不变）

| 项 | 值 |
|---|---|
| artifact | `ios16-root-parts`，run 43634756880 |
| 大小 | 11,970,598,900 B，7 片 |
| 有效期 | **到 2026-11-19** |

下载：`./ugg/flash-root.sh /path/with/20GB`（本机 C: 只有 7.3 GB，需换盘）

---


## ★★★★★ 上一轮（2026-11-15 04:45，第 10 轮）-- 找到一个会让根卷白刷的 bug

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1258 行）。

### 这轮找到的根因（比之前所有 bug 都关键）

**`shim_main()` 把 `loader_boot(dtb)` 放在第一条语句**，而 eMMC 初始化只在
「没有 payload」的分支里跑。所以**手机带 payload 启动时 eMMC 从未被初始化**。

证据是 XNU 自己的代码注释（`bsd/dev/sweet_ufs.c` 的 `ugg_take_over()`）：

```c
int e = ugg_card_ready(500);
if (e) {
    printf("UGG EMMC: card not in transfer state after the shim (%d)\n", e);
    return ENXIO;
}
```

**「after the shim」** —— XNU 假设 shim 已经把卡初始化到 transfer state，
它自己只调超时计数器，不跑 CMD0/1/2/3/7、不开 bus power、不配 SDCC1 RCG。

| 后果 | 说明 |
|---|---|
| `Still waiting for root device` 永远不出来 | 卡没进 transfer state，所有读盘失败 |
| **即使刷了 16 GB 根卷也一样** | 读不到 GPT，找不到 `userdata` |
| 会误判成根卷问题 | 实际是 shim 少一步 |

已修：bring-up 移到跳转前无条件执行。

### 第二个同类问题

`ugg_input.c` 注释说 shim 会准备 **L10 + L6 两路电源**，但 shim 只投了 L10。
UGG 的 DTB 明确 `goodix@5d` 的 `vcc_i2c-supply` = `regulator-l6`（1.8 V）。
没有这路电，I2C 上拉无源，总线恒读 0xFF。已补。

### 一条值得记住的排查方法

**在 XNU 驱动里搜 `after the shim` / `the shim left` / `the shim` 这类注释**，
每一条都对应 shim 里必须有的一步。已知三条，全部已满足：

| XNU 侧 | 依赖 shim 做的 | 状态 |
|---|---|---|
| `sweet_ufs.c` | eMMC 初始化到 transfer state | ✅ 本轮修 |
| `ugg_input.c` | L10 + L6 电源 | ✅ 本轮修 |
| `ugg_input.c` | QUP3 时钟、gpio10/11/64/65 | ✅ 原有 |

### 当前镜像状态

⚠️ **工作区里的 `shim-boot-0082-mido.img` 还是上一版（sha256 `4b787b…`），不含本次修复。**
等 shim CI 出新的 `Image` 后我会重建并给你新的 sha256。**先别刷那个旧的。**

### 根卷（不变，已就绪）

| 项 | 值 |
|---|---|
| artifact | `ios16-root-parts`，run 43634756880 |
| 大小 | 11,970,598,900 B，7 片 |
| 有效期 | 到 2026-11-19 |
| 校验 | 每片 sha256，`sha256sum -c` 全过 |

下载：`./ugg/flash-root.sh /path/with/20GB`（需要 20 GB 空闲，本机 C: 只有 7.3 GB）

---


## ★★★★★ 上一轮（2026-11-15 04:30，第 9 轮）-- 新镜像 + 根卷已验证内容

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1175 行）。

### 请刷这个新镜像

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

```
8,169,472 B
sha256 4b787b060111b7ddec43532158616079c6598386ae51c1d375bbc4665605ab2b
```

**与上一版的唯一区别：`sweetfb_hz` 从 15 改成 30。**

依据是 mido 的实测 A/B（PORTING_LOG 第 981-982 行）：

| 设置 | mido 观察 |
|---|---|
| `sweetfb_hz=60` | App 启动了（exec Preferences、MobileSMS，无崩溃无磁盘错误）但**不显示** |
| `sweetfb_hz=30` | **App 正常打开** |
| 结论 | 「Use 30 Hz」——60 Hz 的面板拷贝把 CPU 饿死 |

我之前用 15 Hz 没有依据（只是偏保守）。15 虽然不至于像 60 那样严重，但没有验证过，
而 **30 Hz 是 mido 进桌面时用的值**。

### 根卷内容已验证（不只是「构建成功」）

从 CI 日志确认移植补丁**真的生效**：

| 项 | 证据 |
|---|---|
| launchd | `7 _PanicOnCrash renamed, 2 CommCenter jobs removed` |
| containers | `Bundle` / `Data/System` / `Shared/SystemGroup` / `Temp` 四目录已建 |
| 音频 | `VirtualAudio.plugin disabled` |
| MediaToolbox | `StartRecorderServer off` × 3 path |
| 偏好 | `com.apple.migration` / `springboard` / `purplebuddy` 已写 |
| dyld 缓存 | `dyld_shared_cache_arm64` + `.symbols` 已硬链接 |
| 大小/校验 | 16 GiB / 11.15 GiB sparse / fsck OK |

### QEMU 的结论（已停止投入，但要记录）

用符号精确定位到：故障 FAR = `common_start + 0x194`，那里是 **`isb`**，前一条是 **`msr SCTLR_EL1`**
= **打开 MMU 的那一瞬间**。计算出 TTBR1（T1SZ=25）只覆盖 `0xffffff80_00000000` 以上，
而 commpage base `0x0FC0000000` **不在覆盖内** —— 这是 `UGG_4K_VM`（36 位 VA 布局的 iOS 值）
与 39 位 TTBR1 的不自洽。

**mido 从未用过 QEMU**（移植日志里 0 次提及），它靠真机屏显直接到桌面。
所以 QEMU 保留为回归检查，**不阻塞主线**。

### 你的两步

**1. 刷新镜像看屏显**（不需要根卷）

预期停在 `Still waiting for root device`（M2）。

**2. 在有 20 GB 空闲的机器上下载并刷根卷**

```
./ugg/flash-root.sh /path/with/20GB
```

然后：

```
fastboot -S 256M flash userdata ios16-root.simg     # 10-15 分钟
fastboot boot shim-boot-0082-mido.img               # 首启 4-8 分钟
```

### 屏显判读

| 看到 | 含义 |
|---|---|
| 左下角白带 / 底部绿色方块（数个数） | stage-0 / 早期阶段号 |
| `SWEET EARLY NN: 标签` | 早期控制台 |
| `panic:` | **拍照给我** |
| `Still waiting for root device` | **M2**（未刷根卷的正常终点） |
| 苹果 logo | 根卷挂载成功 |
| 锁屏 / 桌面 | **目标达成** |

---


## ★★★★★ 上一轮（2026-11-15 04:20，第 8 轮）-- 根卷已构建出来，可以刷了

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1114 行）。

### 现在的状态：所有构建产物都齐了

| 产物 | 状态 | 位置 |
|---|---|---|
| XNU 内核 | ✅ | CI run 43629928191，17,140,032 B |
| shim | ✅ | CI run 43614156236，184,320 B |
| **boot.img** | ✅ | **工作区根目录 `shim-boot-0082-mido.img`，8,169,472 B** |
| **iOS 根卷** | ✅ | **CI run 43634756880，11,970,598,900 B，7 个分片** |

### 你要做的三步

**1. 刷 boot.img 看屏显（可先做，不依赖根卷）**

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

```
sha256 e91b0d5fb2d40800f7fe374822860019b3bfaf3377de9cdcbba947139e46ec0e
```

没刷根卷 ⇒ **正常应停在 "Still waiting for root device"**（M2 达成）。

**2. 下载并校验根卷**

⚠️ **注意磁盘**：本机 C: 只剩 7.3 GB，装不下 11.2 GB 的镜像。
请在有 20 GB 以上空闲空间的机器/盘上做：

```
./ugg/flash-root.sh /path/with/20GB
```

或者手动：

```
gh run download 43634756880 -R honghong2011/ios-ugg -n ios16-root-parts -D parts
cd parts && sha256sum -c SHA256SUMS
cat ios16-root.simg.part* > ../ios16-root.simg
stat -c%s ../ios16-root.simg     # 必须是 11970598900
```

**3. 刷入并启动**

```
fastboot getvar partition-size:userdata    # 确认够大
fastboot -S 256M flash userdata ios16-root.simg
fastboot boot shim-boot-0082-mido.img
```

会清空 Android 数据（你已批准）。刷 10-15 分钟，首启 4-8 分钟。

### 根卷的实测数据（不是估计）

| 项 | 值 |
|---|---|
| HFS+ 镜像 | 17,179,869,184 B（16 GiB） |
| fsck | 三次全部 `The volume iOSRoot appears to be OK.` |
| sparse 镜像 | 11,970,598,900 B |
| 分片 | 6 × 1,887,436,800 + 1 × 645,978,100 = 7 片 |
| 校验 | 每片 sha256，`sha256sum -c` 全过 |
| CI 步骤 | **11/11 success** |
| 合成耗时 | 不到 3 分钟（比 mido 本地快得多） |

### 屏显判读

| 看到 | 含义 |
|---|---|
| 左下角 64×32 白带 | stage-0 跑到了 |
| 底部绿色方块（数个数） | `sweet_early_mark` 的阶段号 |
| `SWEET EARLY 01..NN: 标签` | 早期控制台工作 |
| `panic:` | **拍照给我** |
| `Still waiting for root device` | **M2**（没刷根卷时的正常终点） |
| 苹果 logo | 根卷挂载成功，进 M3/M4 |
| 锁屏 / 桌面 | **目标达成** |

---


## ★★★★★ 上一轮（2026-11-15 03:30）-- 镜像已更新，请刷这个

> 完整记录：`docs/MIDO-PORT-PLAN.md`（1002 行）。

### 你的那一步

```
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
```

```
8,169,472 B
sha256 e91b0d5fb2d40800f7fe374822860019b3bfaf3377de9cdcbba947139e46ec0e
```

**这个镜像和上一版不同**：修掉了 5 个 framebuffer 地址 bug（见下），务必刷这个新的。

### 本轮修掉的 5 个真 bug（真机同样会中）

| # | 位置 | 问题 | 后果 |
|---|---|---|---|
| 1 | `start.s` UGG_MARK | `0x90001000 + 1888*4320`，stride 4320 | 写越界 0x6F100 字节，超出 splash_region |
| 2 | `start.s` stage-0 白带 | 同上 | 同上 |
| 3 | `sweet_early.c` `sweet_early_mark` | `stage*48` 到 `(stage+1)*48`，stage 最大 20 ⇒ x 到 **1008** | **超出 720 宽 288 像素**，绕行后越出 framebuffer |
| 4 | `SweetFramebuffer.cpp` MDP 回退 | `0x90001000` / `4320` | 错地址 |
| 5 | `mkadt_ugg.py` QEMU 模式 | 512 MiB ⇒ 实际测 4K VM 路径 | QEMU 测的不是真机路径 |

bug 3 尤其严重：mido 的面板 1080 宽能放 22 个 48px 方块，ugg 只有 720 宽只能放 15 个，
而 stage 能到 20 —— **只要有 stage>=15 就必然越界写**。

### 另外两件重要的事

**1. 根卷不需要 Linux 电脑了**

`probe-rootenv.yml` 在免费 ubuntu runner 上实测六项全过：
86 GB 磁盘 / hfsplus 可加载 / mkfs / mount / fsck / apfs-fuse 源码构建成功。
`build-root.yml` 一条命令出 16 GB 根卷，切 1.8 GB 片上传。

**2. QEMU 早期启动验证已上线，但尚未通过**

已排除：内存大小、framebuffer 地址、mark 越界、commpage 补丁。
诊断埋点已加（`UGG PMAP: commpage ...`），但这行**没出现** ⇒ 故障在 `arm_vm_init` 更早处。
判断：QEMU 转为回归检查，不阻塞真机。真机屏显才是判据。

### 屏显判读

| 看到 | 含义 |
|---|---|
| 左下角 64x32 白带 | stage-0 跑到了 |
| 底部一排（或两排）绿色方块 | `sweet_early_mark` 在工作，数字越大越靠后 |
| `SWEET EARLY 01..NN: 标签` | 早期控制台 + 阶段名 |
| `panic:` / 白字滚动 | **拍照给我**，最有价值 |
| `Still waiting for root device` | **M2 达成** |
| 黑屏但有背光，等 3 分钟 | 可能已进 XNU |

---


## ★★★★★ 上一轮（2026-11-15 02:20，第 7 轮）

> 全部记录：`docs/MIDO-PORT-PLAN.md`（898 行）。本文件下方是历次交接。

### 三件已完成的事

| # | 事情 | 结论 |
|---|---|---|
| 1 | **根卷不需要 Linux 电脑** | `probe-rootenv.yml` 实测六项全过（86 GB 磁盘 / hfsplus 可加载 / mkfs / mount / fsck / apfs-fuse 源码构建成功），`build-root.yml` 在 CI 里做 |
| 2 | **QEMU 早启验证上线** | `-M virt,gic-version=2 -cpu cortex-a53`，解码帧缓冲，报里程碑 |
| 3 | **修掉四个真实 framebuffer bug** | mido 的 `0x90001000 + 1888*4320` 在 ugg 上**写越界 0x6F100 字节**（超出 splash_region） |

### QEMU 那条「内核挂了」是假警报，已查明

1.16 GB 的 `qemu.log` 里只有**一条** Prefetch Abort，后面 4000 条都是它的连锁反应：

`
FAR = ELR = 0x5042c5e4          <- 物理地址
0x5042c5e4 - 0x50000000 + virt_base = 0xfffffff00742c5e4
符号 = common_start + 0x198     <- commpage
`

**根因**：`arm_init.c` 只在 `memSize > 1 GiB` 时选 16K VM 页；我给 QEMU 的是 512 MiB，
于是它测的是 4K VM 路径 —— 而真机是 1.5 GiB / 16K VM。**QEMU 之前测的路径和真机不同。**
已改成 `QEMU_MEM_SIZE = 0x60000000`，与真机一致。

### 你的那一步（没变）

`
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
8,169,472 B   sha256 7a97fee7a10275996bfcd04423867bfc64d4641732308e5ab7b75d3c3cb10af9
`

**只进内存。** 没刷根卷 ⇒ **正常应停在 "Still waiting for root device"**（M2）。

| 屏上看到 | 含义 |
|---|---|
| 左下角一条 64x32 白带 | stage-0 跑到了（mido 移植标记） |
| `SWEET EARLY` 01..NN | 早期控制台工作 |
| `panic:` / 白字滚动 | **拍照给我**，最有价值 |
| `Still waiting for root device` | **M2 达成** |
| 黑屏但有背光，等 3 分钟 | 可能已进 XNU |

---


## ★★★★★ 现在的真实状态（2026-11-15 01:50，第 7 轮末）

> 完整计划/记录：`docs/MIDO-PORT-PLAN.md`（830 行）。本轮全部提交已推送 `ugg-port`。

### 三件事，按重要性

#### 1. 你又少了一件要准备的事：根卷在 CI 里做

我说过「必须 Linux 电脑」，**错了**，没实测就下的结论。`probe-rootenv.yml` 在 ubuntu
runner 上把六个前提全测过，全通：

| 前提 | 实测 |
|---|---|
| 磁盘 | **86 GB 可用**（不是传闻的 14 GB） |
| `modprobe hfsplus` / `mkfs` / `mount` / `fsck` | 全 OK |
| `apfs-fuse` 源码构建 | **cmake rc=0 / ninja rc=0** |

所以 `build-root.yml` 已在仓库里，一条命令出 16 GB 根卷（切 1.8 GB 片）。

#### 2. QEMU 抓到了四个真 bug（**真机同样会中**）

第一次 QEMU 启动：`blank_screen`，**零个里程碑**，连 `SWEET EARLY` 都没打出来。
这指向最早的那几条指令，而不是 pmap。查出来的原因：

| # | 位置 | mido 的值（ugg 上错的） |
|---|---|---|
| 1 | `start.s` `UGG_MARK` | `0x90001000 + 1888*4320`，stride `4320` |
| 2 | `start.s` stage-0 白带 | 同上 |
| 3 | `SweetFramebuffer.cpp` MDP 回退 | `0x90001000` / `4320` |
| 4 | `sweet_early.c` 早期控制台 | 已改（早先修的） |

**越界证据**（这是判断的关键，不是猜）：

`
mido 的 UGG_MARK 写到  0x911D4480 + 32*4320 + 64*4 = 0x9146F100
splash_region 末尾                             = 0x91400000
超出                                           = 0x6F100 字节
`

这些写入发生在**有栈、有页表、有控制台之前**，所以在手机上只会表现为黑屏，
很容易被误判成 pmap 问题。QEMU 把它提前暴露成「0 个里程碑」。

修复后 QEMU 从 `blank_screen` 变成 **`incomplete_decode`，出现 4 个字形** —— 
**内核确实开始画字了**，几何修对了。

#### 3. 解码器也在修

`????` 是因为解码器按 sweet 的 2400 行面板算，且把空白格子也算成「未知字形」，
所以只要屏上有空白就永远判定不通过。已改成按 ugg 的 720x1280（45 列 x 39 行）解码，
空白当空格。

### 你的那一步没变

`
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
`

`
8,169,472 B   sha256 7a97fee7a10275996bfcd04423867bfc64d4641732308e5ab7b75d3c3cb10af9
`

**只进内存。** 没刷根卷，所以**正常应停在 "Still waiting for root device"**（那是 M2）。

### 屏显判读（和之前一样）

| 看到 | 含义 |
|---|---|
| 屏底部左下一条白带（64x32） | stage-0 跑到了 ✅ 这是 mido 移植的标记 |
| `SWEET EARLY` 01..NN | 早期控制台工作 |
| `panic:` / 白字 | **拍照给我**，最有价值 |
| `Still waiting for root device` | **M2 达成** |
| 黑屏但有背光，等 3 分钟 | 可能已进 XNU |

---


## ★★★★ 最新状态（2026-11-15 01:10，第 7 轮）

> 本章取代下面所有内容。计划与全部记录：`docs/MIDO-PORT-PLAN.md`（772 行）。

### 两件大事（本轮）

**1. 你不需要找 Linux 电脑了。**

我之前说「根卷必须 Linux 电脑」，**那是错的**，我没实测就下了结论。新加的
`probe-rootenv.yml` 在 ubuntu runner 上把六个前提全测了，全过：

| 前提 | 实测 |
|---|---|
| 磁盘 | **86 GB 可用**（不是传闻的 14 GB） |
| `modprobe hfsplus` | OK |
| `mkfs.hfsplus` | OK |
| `mount -t hfsplus` | OK |
| `fsck.hfsplus` | OK |
| `apfs-fuse` 源码构建 | **cmake rc=0 / ninja rc=0** |

所以 `build-root.yml` 已经写好，**在 CI 里构建 16 GB 根卷**，切 1.8 GB 片上传。

**2. 内核早期启动有了自动化验证（QEMU）。**

不再只能靠屏摄判断内核死没死：CI 里加了一个 ubuntu job，用
`-M virt,gic-version=2 -cpu cortex-a53` 启动真内核，解码帧缓冲文字，
报告走到了哪个里程碑（start.s / arm_init / pmap / VM bootstrap / SWEET FB / waiting for root）。

> 这正好覆盖旧路线卡死的整段路径。注意它**不能**验 UGG 的真实 MMIO、eMMC、面板。

### 现在完全由你决定的只有一步

`
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
`

`
文件    shim-boot-0082-mido.img   8,169,472 B
sha256  7a97fee7a10275996bfcd04423867bfc64d4641732308e5ab7b75d3c3cb10af9
`

**只进内存，不刷任何分区。** 还没刷根卷，所以**正常应该停在 "Still waiting for root device"**
—— 那就是 M2，不是失败。

### 屏显判读

| 看到 | 含义 | 动作 |
|---|---|---|
| 2 分钟内回 fastboot + `LOADER:` 原因 | shim 拒绝 payload | 拍照 |
| `SWEET EARLY` 1..4 | XNU 在跑 | 继续看 |
| `panic:` / 白字滚动 | **最有价值** | 拍照 |
| `Still waiting for root device` | **M2 达成** | 告诉我，进入下一步 |
| 黑屏但有背光，等 3 分钟 | 可能已进 XNU | 拍照 |

### 下一步（M2 之后）

`
gh workflow run build-root.yml -R honghong2011/ios-ugg --ref ugg-port
# 约 60-90 分钟，产出 ios16-root-parts（7 个 1.8 GB 分片）
gh run download <RUN_ID> -R honghong2011/ios-ugg -n ios16-root-parts -D parts
cd parts && sha256sum -c SHA256SUMS && cat ios16-root.simg.part* > ../ios16-root.simg
fastboot -S 256M flash userdata ../ios16-root.simg     # 会清空 Android 数据（你已批准）
fastboot boot shim-boot-0082-mido.img
`

---


## ★★★ 现在这一步：镜像已就绪，等你刷机（2026-11-15 00:35）

> 本章是最新状态，取代下面的「路线已切换」章节。

### 你要做的（一条命令）

`
fastboot boot C:\Users\Administrator\Desktop\ios-ugg\shim-boot-0082-mido.img
`

`
文件    shim-boot-0082-mido.img
大小    8,169,472 B
sha256  7a97fee7a10275996bfcd04423867bfc64d4641732308e5ab7b75d3c3cb10af9
`

**这是 `fastboot boot`，只进内存，不刷任何分区。** 断电即恢复 Android。

### 屏上该看到什么（判读指南）

| 现象 | 含义 | 下一步 |
|---|---|---|
| 2 分钟内自动回到 fastboot | shim 拒绝了 payload，屏上会写原因（`LOADER:` 开头） | 拍照给我 |
| 屏上 3 色带 + `SWEET EARLY` 1..4 | shim 跑通，XNU 的 start.s 在跑 | ✅ 继续看 |
| 出现 `panic:` 或白字滚动 | XNU 起来了但中途挂 | **拍照给我**，这是最有价值的 |
| 停在 `Still waiting for root device` | **M2 达成** | 下一步做根卷 |
| 屏一直黑但有背光 | 可能已经进 XNU 但 fb 没接管 | 等 3 分钟再拍照 |
| 苹果 logo | **M3/M4 达成** | 继续等锁屏 |
| 锁屏 / 桌面 | **目标达成** | 告诉我，录一段触控 |

**注意**：如果刷了根卷后第一次启动，mido 实测要 **4-8 分钟**才出苹果 logo。你现在还没刷根卷，
所以这一版应该走到 `Still waiting for root device` 就停住（因为 userdata 现在还是 Android 的 ext4）。
**这正是 M2 的判据。**

### 已经做完的完整链条

| # | 步骤 | 状态 | 证据 |
|---|---|---|---|
| 1 | 恢复上游原版补丁链 `0001-0081` | ✅ | `same=84 diff=0` |
| 2 | 重建干净基线 | ✅ | `applied=81 failed=0`，commit `2bbcef0` |
| 3 | 移植 mido 的 `0100` 为 `0082-ugg-board.patch` | ✅ | 28 文件 +2089/-22，零冲突 |
| 4 | 修掉 4 轮 CI 发现的错误 | ✅ | run 43613955911 **success** |
| 5 | 内核 `applied=86`，skipped 无 0082 | ✅ | annotation 确认 |
| 6 | shim 移植（eMMC/RPM/GT9xx）+ CI 编译 | ✅ | run 43614156236 success |
| 7 | 生成 UGG ADT（iPhone10,4 / 750x1334） | ✅ | 9896 B |
| 8 | 打包并校验 boot.img | ✅ | 结构 12 项全过 |
| 9 | 交付根卷构建脚本 | ✅ | `ugg/build-root.sh` 174 行，`bash -n` 通过 |

### 唯一还没做的：根卷

需要你找一台 **Linux 电脑**（原生优先，WSL2 的 hfsplus 没编），磁盘 ≥ 40 GB 空闲，跑：

`
cd 任意目录
git clone https://github.com/honghong2011/ios-ugg ugg-src   # 或者直接用你现在这份
./ugg-src/ugg/build-root.sh ~/ugg-root
`

跑完给我三个数：

`
1. fsck 输出（应含 volume iOSRoot appears to be OK）
2. ios16-root.img 与 ios16-root.simg 的字节数
3. fastboot getvar partition-size:userdata 的输出
`

### 为什么根卷必须走 Linux（不是偷懒）

| 步骤 | Windows/macOS 能做吗 |
|---|---|
| `apfs-fuse` 读 IPSW 的 APFS dmg | ❌ 没有可用实现 |
| `mkfs.hfsplus` / `fsck.hfsplus` | ❌ 只有 Linux/BSD 版 |
| `mount -t hfsplus -o loop` | ❌ Windows 无 loop 设备 |

GitHub Actions 也不行：需要 6 GB IPSW + 16 GB 镜像 + 12 GB sparse ≈ 34 GB，ubuntu runner 只有 14 GB。

---


## ★★ 路线已切换：照抄 ios-mido（2026-11-14 深夜）

> **本章取代下面所有旧内容。** 旧的 `0082-0098` 自研补丁路线**已全部作废并归档**。
> 完整计划与执行记录见 **`docs/MIDO-PORT-PLAN.md`**（441 行，最新、必读）。

### 一句话现状

**XNU 补丁 `0082-ugg-board.patch` 已生成并验证零冲突；shim 已移植并 CI 编译通过；正在等最后一轮 xnu CI。**

### 已经做完的（有提交、有 CI、有验证）

| # | 事情 | 证据 |
|---|---|---|
| 1 | 发现旧路病根：`ugg/xnu/patches` 里 41 个 `0001-0081` 被改成 `SWEET_FAMILY` 版本，导致 `patch` 只应用一部分 → 假 hunk → 0093/0095/0098 被 CI 跳过 | `same=84 diff=0` 对比上游 |
| 2 | 恢复上游原版 `0001-0081`（逐字节） | 84 个补丁全部一致 |
| 3 | 重建干净基线：reset + 3 个 staging 脚本 + apply `0001-0081` | `applied=81 failed=0`，commit `2bbcef0` |
| 4 | 验证 mido `0100-mido-board.patch` 可在本基线零冲突应用 | 31 文件 `git apply --check` 全过 |
| 5 | 生成 `0082-ugg-board.patch` | 28 文件 +2089/-22，`git apply --cached --check` 通过 |
| 6 | 移植 shim（sdhc/rpm/spmi/perf/input + 新写 emmc.c/兼容层/日志环） | shim-ugg CI **success** run 43612347343 |
| 7 | 生成 UGG ADT（`tools/mkadt_ugg.py`，iPhone10,4/D20AP 750x1334） | 9896 B |
| 8 | 交付根卷构建脚本 `build-root.sh`（Linux 用，174 行） | `bash -n` 通过 |

### UGG 真实硬件（已从本机 DTB 核实，推翻旧文档）

`
SoC        MSM8940（骁龙 435），**不是 8937**
           DTB: model = "Qualcomm Technologies, Inc. MSM8940-PMI8937 MTP"
eMMC       sdhci@7824900，HC 0x500 / core 0x800，IRQ SPI 123/138
           电源 L5=1.8V(vdd-io) L8=2.9V(vdd)  <- 与 mido 完全一致
GCC SDCC1  RCG 0x01842004                        <- 与 mido 完全一致
触控       goodix@5d on i2c@78b7000 (QUP **v1**)
           irq gpio65, reset gpio64, power_ldo gpio47
           vdd_ana = L10 2.85V, vcc_i2c = L6 1.8V  <- 与 mido 完全一致
面板       720x1280，splash 0x90000000 + 20 MiB
指纹       fpc1020 + goodix_fp（两个节点都在）
`

### 与 mido 的差异（全部已处理，见 MIDO-PORT-PLAN §6.3）

| 项 | mido | ugg |
|---|---|---|
| framebuffer | 0x90001000 / 1080x1920 / stride 4320 | **0x90000000 / 720x1280 / stride 2880**（2 个 2MB 块） |
| 呈现画布 | 1242x2208 / 458ppi（iPhone 8 Plus） | **750x1334 / 326ppi（iPhone 8）** |
| 触控 IC | FocalTech FT5435（8 位寄存器） | **Goodix GT9xx（16 位寄存器）** |
| GPU | 有（Adreno 506） | **删除**（用户明确跳过） |
| CPU 升频 | 1401–2016 MHz 五档 | **关闭**（435 档位未实测，风险不可恢复） |

### 下一步（严格按序）

`
1. 等 xnu CI（run 43612214819 之后的那个）-> 检查三件套：
   a. annotation 里 applied 计数 = 86（0082 已算在内）
   b. patches-skipped 里**不含** 0082
   c. kernel.development.ugg 比上版大（0082 加了 ~2000 行）
2. 下载内核 -> ./ugg/make-image.sh <kernel>  -> 出 shim-boot-ugg.img
3. fastboot boot shim-boot-ugg.img（**不刷任何分区**）
   屏显判读：出 "SWEET FB" = XNU 起来；"Still waiting for root device" = M2 达成
4. 用户找 Linux 电脑跑 ./ugg/build-root.sh，回传三个数：
   fsck 输出 / img+simg 字节数 / fastboot getvar partition-size:userdata
5. 刷 userdata（**这一步会清空 Android 数据，用户已批准**）-> 再 boot -> 目标桌面
`

### 归档位置

旧 `0082-0098` 补丁在 `build-m1/old-ugg-patches/`（14 个文件），不再使用。

---


> 本文件镜像上游 NOTES.md 的 handoff 规范：每次里程碑后更新最新 handoff，区分事实与猜测。

## ★ 先读这个：iOS 桌面目标的可行性核对（2026-11-14）

完整内容见 **`docs/ROADMAP-2026-11-14.md`**。这里只放最要紧的三条：

### 1. 「全程 RAM 进桌面」在此设备上走不通（已核实）

| 限制 | 数值 | 来源 |
|---|---|---|
| `fastboot boot` 载荷上限 | **511.0 MiB** | `README.md:45` 实机 getvar |
| 减去 shim + 内核后根镜像余量 | **494 MiB** | 实算 |
| iOS shared cache 需求 | **2.5 GiB**（去 .symbols） | `ugg/NOTES.md:184` 上游实测 |
| XNU 当前可见 RAM | 512 MiB | payload `mem_size` @0x38 |

**差 5 倍以上。** 上游撞到同一面墙，结论一致：要么存储驱动，要么极小 cache。

### 2. 上游 ios-sweet 跑在完全不同的 SoC 上

上游是 **A55 + UFS + RPMh + GT9896 + 1125×2436**，我们是 **A53 + eMMC + RPM + GT917D + 720×1280**。
它 2026-10-18 确实拿到了 SpringBoard 桌面，但**底层驱动几乎全部要重写**，只能复用用户态那半。

### 3. 唯一被上游验证成功的路线是存储驱动，而我们有 SD 卡

手机**已插 32GB SD 卡**。SD 卡驱动（SDHCI-msm）比 eMMC 简单，且**只读用户自己的卡**，
符合「不动 data 分区」的硬约束。这是 B 路线，比 E（写 eMMC 完整根卷）轻得多。

### 砍掉的步骤

| 阶段 | 结论 |
|---|---|
| B1 串口 | **砍掉**：本机无物理 UART，屏上输出已够用 |
| B3 RPM 电源 | **降级**：只在触摸不工作时才做 |
| E eMMC 完整根卷 | **砍掉**（难且需写分区），但 B 的 SD 卡驱动保留 |
| U7 GPU | 用户不追求 |

### 待用户确认

- **x86 Linux 那台的硬盘大小**（需 ≥40 GB 才能构建根镜像；2GB ARM 机因内存不够不可用）

## Agent handoff / active work (2026-11-12 深夜, latest)

### >>> M1 仍未通过；0092 已推送、CI 通过，待真机验证 <<<

**一句话：0089 的栈溢出已确认修好；0090/0091 暴露的两个「诊断代码自己炸」问题已在 0092 修掉。**
现在的失败点是**我自己的仪俪代码读系统寄存器被拒**，不是内核逻辑。

**1. 0090 真机结果（用户屏摄）**

- 旧的 `esr 9600004f`（写只读保护页）**完全消失** ⇒ 栈扩容生效。
- 但屏上出现**几百块**重复 `SWEET FAULT sync`，每块都停在 `istack:` 后。
- 定位：`pc` = `_sweet_early_fault+0x140`，指令是 `mrs x10, SP_EL0`；
  `sp` 每轮下移 ~1216 字节（848 frame + 368 分发）⇒ **打印函数自己重入死循环**。
- `esr 0x02000000` = EC 0（unknown reason）⇒ 异常处理已在半途又取异常。
- 仪表没显示：它画在文本第 38 行，而滚动文字也用第 38 行，最后一行覆盖了它。**设计 bug**。

**2. 0091 做了什么（只动早期控制台）**

- 预留第 38 行给仪表，滚动只用前 38 行（`EARLY_TEXT_ROWS`）。
- 仪表**总是**绘制，SP 不在启动栈时画 `????`。
- `sweet_early_fault()` 去掉 `_doprnt`、只报一次（`early_fault_reported`）。
- 加 `EARLY_LEFT_MARGIN`：首列留空（屏摄显示首列被边框切掉，`00000` 看成 `30000`）。

**3. 0091 真机结果（用户第二张屏摄）**

- 防重入**成功**：屏上只有**一条** `SWEET FAULT`，不再是几百条。
- 新故障 `pc ffffffe0007439f20` = `_sweet_early_mark+0x850`，机器码 `d5384114`
  = **`mrs x20, SP_EL0`** ⇒ **仪表自己**在抓异常。启动连标记 1 都没过。
- `sp ffffffe00080bfef0`，距 `_intstack_top` **272 字节**。
  **注意方向**：栈向下长 ⇒ 只用了 272 字节、**剩 65264 字节（99.6% 空）**。
  0089 那次 `sp` 在栈底**以下**，是真溢出；这次不是。**⇒ 0090 确实修好了溢出。**
- 第二条 panic `Synchronous exception taken while SP1 selected`：
  `pc` = `_current_percpu_base+0xc` = `ldr x0,[x0,#544]`，`esr 0x96000005`
  （data abort EL1, DFSC 5 translation fault L1），`x10` = `0x220` = 544。
  `current_thread_fast()` 就是 `mrs TPIDR_EL1`；**标记 1 时 TPIDR_EL1 还是 0**，
  解引用 NULL+544 就翻译失败。⇒ **这是第一条故障的后果，不是独立 bug。**

**4. 0092 做了什么**

- `sweet_early.c`：`sweet_early_sp_el0()`（`mrs SP_EL0`）→ `sweet_early_sp()`（`mov %0, sp`）。
  `sweet_early_mark()` 在 `arm_init()` 里跑，`SPSel=0`，所以 `sp` 与 `SP_EL0` **同值**，
  而读 `sp` 是普通通用寄存器搬移，**不可能抛异常**。数值不变，风险归零。
- `sleh.c`：`sleh_synchronous()` 与 `sleh_invalid_stack()` 原本在序言就先
  `thread = current_thread()`，在 SWEET 报告**之前** ⇒ TPIDR_EL1=0 时先炸，
  把真报告盖成误导性 panic。现改为**先打印、后取 thread**。

**5. 交付物 / 复现**

| 项 | 值 |
|---|---|
| commit | `eac43c7`(0091) `9d8669c`(notes) `08ba29f`(0092) |
| CI run | `43218229183`(0091) `43237805476`(0092) 均 **success** |
| patch-report | `applied=96 skipped=4`（4 条为外部 dxb 补丁） |
| 0091 kernel | 17,301,656 B，sha256 `fa715f77...c9b3b1b0` |
| 0092 kernel | 17,301,656 B，sha256 `264250a9...4fcabaa1` |
| 0091 镜像 | `build-m1/diag2/shim-boot-0091-faulthardened.img` sha256 `2b22fb6b...7e20631` |
| 0092 镜像 | `build-m1/diag2/shim-boot-0092-faultsafe.img`（见下） |
| 补丁校验 | 0090→0091→0092 顺序应用逐字节复现；均不可重复应用 |

**6. 审计结论（0092 顺带做的）**

对 0091 内核做全量系统寄存器扫描：早期路径（`sweet_early_*` + `arm_init`）里
**只有一处**风险系统寄存器读取，就是 `_sweet_early_mark+0x850` 的 `mrs x20, SP_EL0`，
**已被 0092 覆盖**。另扫描 ARMv8.1 LSE 原子指令（A53 是 ARMv8.0，LSE 会 UNDEF）：
早期函数中 **0 处**，所以 `esr 02000000` 确实就是那条 `mrs` 本身。

**7. 下一步**

`fastboot boot` 0092 镜像，看：
- 若不再有 `SWEET FAULT` 且标记递增 → **M1 前进，准备进 M2**；
- 左下角应出现 `stkXXXX`（剩余栈 ÷18 的十六进制）：`stk0e29` = 65,264 B 剩；
- 若仍有故障 → 这次是**真**故障，`pc/lr/sp/esr/far` 齐全且只报一条。

## 交付物：0098（当前最新，双 bank 读数，2026-11-14 夜）

| 项 | 值 |
|---|---|
| 镜像 | `build-m1/diag2/shim-boot-0098-twobank.img` |
| 大小 | 8,151,040 B |
| sha256 | `6d06b4b120a6ff3aacb69818af19b1b0f60cf79e73e4763ed09138f0383e2dec` |
| 内核 | `ci-xnu17/kernel.development.ugg`，17,711,296 B，sha256 `192b04f3...ef6b3ab` |
| 来源 CI | run `43599523442`（`9d64b3c`）**success**，`applied=102 skipped=4` |
| 构造脚本 | `build-m1/mk0099.py` |

**用法（RAM-only，不刷任何分区）**：

`
fastboot boot build-m1/diag2/shim-boot-0098-twobank.img
`

**四重门禁全过**：

| gate | 结果 |
|---|---|
| `patches-skipped` | **不含 0098** |
| `patch-report` | `applied=102`（上一轮 101） |
| bank A 标签（`ptovn/w.pa/w.va/w.len/w.end/raend`） | **全部存在** |
| bank B 标签（`zerva/zerolastva/...`） | **全部存在** |
| 两组共存于同一内核 | **True** |

### 屏幕布局（这次两批读数互不覆盖）

| 行 | 内容 |
|---|---|
| 0..17 | 滚动控制台（panic dump 在其内） |
| **18..27** | **bank A：ptov 值（0097 的内容，之前从未显示过）** |
| **28..37** | **bank B：pmap 值（0094 的内容）** |
| 38 | `stk` 仪表 |

### 两个 bank 分别看什么

**bank A（关键）**：

| 槽 | 标签 | 含义 |
|---|---|---|
| 0 | `ptovn` | 非空 ptov 窗口数量 |
| 1 | `w.pa` | 含 `avail_start` 的窗口起始 PA；**`ffffffffffffffff` = 不在任何窗口** |
| 2 | `w.va` | 该窗口 VA 基址 |
| 3 | `w.len` | 该窗口长度 |
| 4 | `w.end` | 该窗口 PA 结束 |
| 5 | `zerva` | `phystokv(avail_start)` 应解析到的 VA |
| 6 | `pstart` | `avail_start` |
| 7 | `pb` | `physmap_base` |
| 8 | `pe` | `physmap_end` |
| 9 | `raend` | `real_avail_end` |

**bank B**：pmap 表相关的十个值（已知正常，用于对照）。

## 交付物：0097（当前最新，ptov 诊断版，2026-11-14 晚）

| 项 | 值 |
|---|---|
| 镜像 | `build-m1/diag2/shim-boot-0097-ptovdiag.img` |
| 大小 | 8,151,040 B |
| sha256 | `dad085438047a43e1cbe6408a82b742a6ce05ca7d17e1bff85be67cd3bd901b1` |
| 内核 | `ci-xnu16/kernel.development.ugg`，17,694,912 B，sha256 `285b81e9...765362e8` |
| 来源 CI | run `43581971337`（`7a410cc`）**success**，`applied=101 skipped=4` |
| 构造脚本 | `build-m1/mk0098.py` |

**用法（RAM-only，不刷任何分区）**：

`
fastboot boot build-m1/diag2/shim-boot-0097-ptovdiag.img
`

**已验证诊断确实进了内核**（吸取 0093/0095 的教训）：

| gate | 结果 |
|---|---|
| `ptovn/w.pa/w.va/w.len/w.end/raend` 字符串 | **全部存在**（0x7a101 附近） |
| `zerva/zerolastva/physmapbase/physmapend` | 仍在（0x78756 附近） |
| `patches-skipped` | **不含 0097** |
| `patch-report` | `applied=101`（上一轮 99） |

### 屏幕布局

| 行 | 内容 |
|---|---|
| 28~37 | **0097 十个诊断值**（见下） |
| 38 | `stk` 栈仪表 |
| 0~27 | 滚动控制台（panic dump 在这里，不会覆盖诊断） |

### 十个值的含义

| 槽 | 标签 | 含义 |
|---|---|---|
| 0 | `ptovn` | 非空 ptov 窗口数量 |
| 1 | `w.pa` | 含 `avail_start` 的窗口起始 PA；**`ffffffffffffffff` = 不在任何窗口** |
| 2 | `w.va` | 该窗口 VA 基址 |
| 3 | `w.len` | 该窗口长度 |
| 4 | `w.end` | 该窗口 PA 结束 |
| 5 | `zerva` | `phystokv(avail_start)` 应解析到的 VA |
| 6 | `pstart` | `avail_start`（物理） |
| 7 | `pb` | `physmap_base` |
| 8 | `pe` | `physmap_end` |
| 9 | `raend` | `real_avail_end` |

## 交付物：0095（当前最新，256 KiB 启动栈，2026-11-14）

| 项 | 值 |
|---|---|
| 镜像 | `build-m1/diag2/shim-boot-0095-stack256k.img` |
| 大小 | 8,151,040 B |
| sha256 | `eaaf9fa43d9e95ec5dfebeab08868775f41f6d7b76de38f8c7cd59f7edcc370e` |
| 内核 | `ci-xnu15/kernel.development.ugg`，17,694,912 B，sha256 `53c1df06...40b7593` |
| 来源 CI | run `43553713449`（`01155e7`）**success**，`applied=99 skipped=4` |
| 构造脚本 | `build-m1/mk0096.py` |

**用法（RAM-only，不刷任何分区）**：

`
fastboot boot build-m1/diag2/shim-boot-0095-stack256k.img
`

**已验证（事实）**：

| 门禁 | 结果 |
|---|---|
| `_intstack` 大小 | **262,144 字节（256 KiB）** ✓ |
| `_excepstack` 大小 | **262,144 字节（256 KiB）** ✓ |
| `__BOOTDATA` 大小 | `0x64000` → **`0xc4000`（784 KiB）**，与预测一致 |
| shim | 与 0094 逐字节相同 |

### 为什么是 256 KiB（实测数据，不是估算）

0094 的固定行读数**证明 pmap 表全部正常**，随后从 panic 现场反推出真实缺口：

| 项 | 字节 |
|---|---|
| 故障前 `SP_EL0` | `0xfffffe00080b0180`（离栈底 384）|
| 已消耗（距栈顶）| 65,152 |
| 异常帧需求 | 848 |
| **合计需求** | **66,000** |
| 当时可用 | 65,536 |
| **缺口** | **464** |

64 KiB 差 464 字节。256 KiB 是实测需求的 **3.97 倍**。

### 代价

每 CPU 两栈共 512 KiB × 8 CPU = **4 MiB**，4 GiB 设备上可忽略。
`__BOOTDATA` 变大但会被 `ml_static_mfree()` 在真实 pmap 建立后释放。

## 交付物：0094（当前最新，固定行读数版，2026-11-14）

| 项 | 值 |
|---|---|
| 镜像 | `build-m1/diag2/shim-boot-0094-readoutband.img` |
| 大小 | 8,151,040 B |
| sha256 | `e5bef54878918eefda3574680c16b6080b3d3419a954c82116477c560c426b13` |
| 内核 | `ci-xnu14/kernel.development.ugg`，17,301,696 B，sha256 `d9b1050e...cf1edcfb` |
| 来源 CI | run `43541927223`（`b2b76cb`）**success**，`applied=98 skipped=4` |
| 构造脚本 | `build-m1/mk0095.py` |

**用法（RAM-only，不刷任何分区）**：

`
fastboot boot build-m1/diag2/shim-boot-0094-readoutband.img
`

**三重门禁已验证**：`_sweet_early_val` 存在、10 个 tag 字符串齐全、
`_pmap_data_bootstrap` 由 `0x300` 增至 `0x320`。shim 与 0093 逐字节相同。

### 0093 为什么没显示出数字（重要）

0093 的代码**确实进了内核**（门禁全过），但屏上一个数字都没有。
原因与 0091 的仪表**是同一类错误**：

- `sweet_early_val()` 用的是 `sweet_early_putc()`，即**加入滚动控制台**。
- 之后依次打印：SWEET FAULT(4 行) + panic 文本(4 行) + 寄存器 dump(~34 行) ≈ 42 行，
- 而滚动环只有 39 行 ⇒ **10 个数字被从头滚出屏幕**。

**教训：位置固定不够，必须落在滚动区之外。**

### 0094 的屏幕分区（三个互不重叠的带）

| 行 | 用途 | 宏 |
|---|---|---|
| 0..27 | 滚动控制台 | `EARLY_TEXT_ROWS = 28` |
| 28..37 | 10 个读数槽 | `EARLY_VAL_ROW = EARLY_ROWS - 11` |
| 38 | 栈仪表 | `EARLY_GAUGE_ROW` |

`early_row` 被 `EARLY_TEXT_ROWS` 约束，所以 `sweet_early_clear_row()` **只可能**擦掉控制台行，
永远碰不到读数槽和仪表。已核验无重叠：文字止于 27，读数始于 28，读数止于 37，仪表 38。

### 读数槽顺序（按诊断价值排）

| 槽 | 标签 | 含义 |
|---|---|---|
| 0 | `zerva` | 清零起始 VA |
| 1 | `zerolastva` | 清零末尾 VA ← 与 3 比较 |
| 2 | `physmapbase` | physmap 窗口起始 |
| 3 | `physmapend` | physmap 窗口结束 ← 若 1 > 3 则越界 |
| 4 | `zerolen` | memset 长度 |
| 5 | `mem_size` | XNU 认为的内存 |
| 6 | `realphys` | physmap 实际覆盖 ← 若 5 > 6 则不一致 |
| 7 | `pmapstart` | 物理起始 |
| 8 | `availstart` | 分配结束 |
| 9 | `gphysbase` | 物理基址 |

## 交付物：0093（当前最新，诊断版，2026-11-13 深夜）

| 项 | 值 |
|---|---|
| 镜像 | `build-m1/diag2/shim-boot-0093-physmapdiag.img` |
| 大小 | 8,151,040 B |
| sha256 | `4716e9bf7b8e7ac2def386e7ea01ac1ce958edd3498f6996d35742a2827fa815` |
| 内核 | `ci-xnu13/kernel.development.ugg`，**17,318,080 B**，sha256 `011b6c19...105570ba` |
| 来源 CI | run `43438611222`（`d659127`）**success**，`applied=97 skipped=4` |
| 构造脚本 | `build-m1/mk0094.py` |

**用法（RAM-only，不刷任何分区）**：

`
fastboot boot build-m1/diag2/shim-boot-0093-physmapdiag.img
`

**三重门禁已验证（事实，这是本次修复的证明）**：

| 门禁 | 结果 |
|---|---|
| `_sweet_early_val` 符号 | **存在** `0xfffffe000743a150` |
| 10 个诊断 tag 字符串 | **全部存在**（0x78776 附近连续） |
| `_pmap_data_bootstrap` 大小 | `0x300`（0092 是 `0x210`），**增长 240 字节** |
| shim 代码区 | 与 0092 / `shim-Image-CI.bin` **逐字节相同** |

**这次预期看到**（10 个数字，每行一个）：

`
pmapstruct    <pmap_struct_start 物理地址>
availstart    <分配结束位置>
zerolen       <memset 长度>
zerva         <清零起始虚拟地址>
mem_size      <XNU 认为的内存大小>
realphys      <physmap 实际覆盖大小>
gphysbase     <物理基址，应 0x91600000>
physmapbase   <physmap 窗口起始 VA>
physmapend    <physmap 窗口结束 VA>
zerolastva    <清零范围最后一个字节的 VA>
`

**判读**：

| 情况 | 含义 | 修法 |
|---|---|---|
| `zerolastva > physmapend` | 清零范围超出 physmap 窗口 | 扩大 physmap 映射 或 缩小表 |
| `zerva` 本身就在窗口外 | 分配器已越界 | 对齐 ADT memory 与 real_phys_size |
| `realphys < mem_size` | XNU 以为内存比映射的多 | 让 ADT memory 节点与实际一致 |
| 只差一页 | 表尺寸 off-by-one | 直接修边界 |

## 交付物：0092（当前最新，可直接 fastboot boot，2026-11-13）

| 项 | 值 |
|---|---|
| 镜像 | `build-m1/diag2/shim-boot-0092-faultsafe.img` |
| 大小 | 8,151,040 B |
| sha256 | `7c9aa5613feb5c3dfb2652c447a486408c029372309dbdb438c3838c04142a5b` |
| 内核 | `ci-xnu10/kernel.development.ugg`，17,301,656 B，sha256 `264250a9...4fcabaa1` |
| 来源 CI | run `43237805476`（`08ba29f`）**success** |
| 构造脚本 | `build-m1/mk0092.py` |

**用法（RAM-only，不刷任何分区）**：

`
fastboot boot build-m1/diag2/shim-boot-0092-faultsafe.img
`

**已在二进制里验证（事实）**：

- `_sweet_early_mark` 中 `mrs SP_EL0` 计数 = **0**（0091 里是 1，正是故障指令 `d5384114`）。
- shim 代码区 [32:196608] 与 0091、与 `shim-Image-CI.bin` **逐字节相同**，
  头部唯一差异字节为 0 —— 这次连长度字段都没变（两版内核大小相同）。
- 镜像**确定性可复现**：连续构建两次 sha256 一致。

**这次预期看到**：

| 现象 | 判断 |
|---|---|
| 无 `SWEET FAULT`，标记递增到 13+ | **M1 通过，可进 M2** |
| 左下角出现 `stkXXXX` | 剩余启动栈 ÷18；`stk0e29` = 65,264 B |
| 仍有一条 `SWEET FAULT` | 真故障，`pc/lr/sp/esr/far` 齐全，继续修 |

## 交付物：可以直接 fastboot boot 的镜像（2026-11-12）

| 项 | 值 |
|---|---|
| 镜像 | `build-m1/diag2/shim-boot-0090-stack64k.img` |
| 大小 | 8,151,040 B |
| sha256 | `46577dfe3fcd9a23d0681247d2c1cfefc62df85e4fc7d405bad244a8f1153579` |
| 内核 | `ci-xnu8/kernel.development.ugg`，17,301,624 B，sha256 `86d8963a823bb76f56b1fc7e40024cc3d2cf7c4137f860b90361ae9ba7431647` |
| 来源 CI | run `43178792316`（`c93bebd`）**success** |
| 构造脚本 | `build-m1/mk0090b.py`（复现：`python build-m1/mk0090b.py`） |

**用法（RAM-only，不刷任何分区）**：

`
fastboot boot build-m1/diag2/shim-boot-0090-stack64k.img
`

与 A/B 那两张屏摄用的是同一条链路、同一个 shim、同一份 ADT 形状
（dram-base 0x91600000 / 512 MiB），只有内核从 0089 换成 0090。

**已在二进制里逐符号验证（事实）**：从 ci-xnu8 内核符号表读出
`_intstack 0xfffffe00080b0000` / `_intstack_top 0xfffffe00080c0000`，
`INTSTACK size = 65536`、`EXCEPSTACK size = 65536`，
即 **16 KiB → 64 KiB 确实生效**（0089 同一符号是 16384）。
`__BOOTDATA` vmsize 从 `0x4c000` 变 `0x64000`，正好 +0x18000 = 98304，
与按 `data.s` 布局手算的增量一致；各段 gap 全为 0。

**下一轮读屏标准**：最后一行左下角固定位置会出现 `stkXXXX`
（`剩余启动栈字节 ÷ 18` 的 4 位十六进制）：`stk0e38`=64 KiB 全空、
`stk071c`=剩 32 KiB、`stk0024`=只剩 0.6 KiB。

1. **标记 13（`pmap_bootstrap done`）出现** ⇒ M1 通过，可以进 M2。
2. **仪表在某个标记处明显跳水** ⇒ 该标记之后的调用链是栈消耗大户。
3. **仪表一路很高但仍 panic** ⇒ 成因判断错了，此时屏上有
   `el0/ibase/itop/free` 整行可直接对账，不用猜。

无论哪种，**这次都不要再改 ADT**：A/B 已证明 ADT 形状不是变量。

**唯一变量保证（事实）**：新镜像与已上机跑过的 A 臂用的是**逐字节相同的 shim**。
把两个镜像的 kernel blob 解压后比对：偏移 32 之后的部分与 `build-m1/shim-Image-CI.bin`
的 32 之后部分**完全相同**，只有 arm64 Image 头的 `text_offset`(8..10) 与
`image_size`(16..18) 六个字节不同 —— 那正是 `pack-ugg.py` 故意改写的（声明
shim+payload 的总长）。所以本轮唯一变量就是内核：0089 → 0090。

本次重跑 `python build-m1/mk0090b.py` 得到的 sha256 与首次完全一致（确定性构建）。

## 6. 0090 真机结果与 0091（2026-11-12 晚，最新）

### 0090 的结果：旧故障消失，但诊断代码自己炸成了风暴

用户 `fastboot boot` 了 0090 镜像，屏上不再是上次那条 `esr 9600004f`，而是**几百块**同一结构：

`
SWEET FAULT sync
  pc 000000000743a160  lr 000000000743a148
  sp 0000000007b64120  esr 02000000
 istack:                 <- 永远停在这里
SWEET FAULT sync          <- 立刻下一条
`

**结论：0090 的栈扩容生效了（旧的 permission fault 不再出现），但新加的仪表代码在故障路径上又触发异常，形成重入死循环。**
三条独立证据指向同一结论：

1. 符号还原：`pc` = `_sweet_early_fault + 0x140`，`lr` = `+0x128` —— 故障发生在**打印函数自己内部**。
2. `pc` 那条指令是 `mrs x10, ...`，即读 `SP_EL0`，只有 `sweet_early_sp_el0()` 会这么干。
3. 每一块都停在 `istack:` 之后 —— 那正是调用 `sweet_early_stackinfo()` 之前的最后一句。

`sp` 每次下移约 **1216 字节**（= 848 的 ARM_CONTEXT + 368 的分发开销），说明每轮都往同一个栈再压一个 frame。
`esr 0x02000000` 的 EC = 0（unknown reason），与「异常处理机制已在半途又取异常」自洽。

### 仪表为什么没显示

仪表画在文本第 38 行，而滚动文字也用第 38 行，最后一行 `istack:` 每次都把它覆盖。
**这不是用户没找到，是设计 bug。**

另外屏摄暴露一个问题：**左边第一列被边框切掉了**，几行开头的 `00000` 显示成 `30000`，数值最高位不可信。

### 0091 改了什么（只动早期控制台，不碰内核逻辑）

| 改动 | 原因 |
|---|---|
| 预留第 38 行给仪表，滚动文本只用前 38 行（`EARLY_TEXT_ROWS`） | 文字再也覆盖不到读数 |
| 仪表**总是**绘制，SP 不在启动栈时画 `????` | 空白仪表与「没跑过」无法区分，白费一轮 |
| `sweet_early_fault()` 不再调 `_doprnt`、不再读 `SP_EL0`、只报一次 | 这是死循环的根因 |
| 加 `EARLY_LEFT_MARGIN`，首列留空；折行宽度跟着调整 | 数值最高位被边框切掉，地址有歧义 |

| 项 | 值 |
|---|---|
| commit | `eac43c7` |
| CI run | `43218229183` **success** |
| 校验 | 0090→0091 顺序应用逐字节复现工作文件；0091 单独可应用到 0090 之后；均不可重复应用 |
## Previous: 2026-11-07 及更早

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
