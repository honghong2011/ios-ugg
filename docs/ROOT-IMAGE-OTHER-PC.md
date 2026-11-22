# 在另一台电脑上准备 iOS 根镜像 —— 完整操作手册

> 读者：手上有第二台电脑（Windows / Linux / macOS 都行）、需要把 iOS 16
> 根文件系统写进 Redmi Note 5A Prime（ugg）的 userdata 的**人**。
>
> 本文只写**已经验证过的事实**；没验证的会明确标「未验证」。
>
> 为什么需要另一台电脑：根镜像下载 5.8 GB、拼合后 11.97 GB，
> 加上临时文件要 **20 GB 空闲**。主力机 C 盘只剩 6.7 GB，装不下。

---

## 0. 一页速查（先看这个）

**镜像已经做好了，它躺在 GitHub 上，不用重新构建。**

| 项 | 值 |
|---|---|
| 产物名 | `ios16-root-parts` |
| 来源 run | `43644714094`（build-root，success） |
| 仓库 | `honghong2011/ios-ugg` |
| 大小 | **5,837,838,248 字节**（5.84 GB，7 个分片） |
| **到期** | **2026-11-19 21:59 UTC**（约 4 天，过期就没了） |
| 拼起来后 | `ios16-root.simg`，**11,970,598,900 字节** |
| 格式 | **Android sparse image**（不是 raw） |
| 文件系统 | HFS+ 大小写敏感、日志式、卷名 `iOSRoot` |

**在另一台电脑上要做的只有 4 步**：装 `gh` → 下载 → 校验 → 拼合。
刷写可以在主力机上做（`fastboot` 只要镜像文件，不需要 20 GB 空间）。

---

## 1. 那台电脑需要什么

### 1.1 硬件

| 项 | 要求 |
|---|---|
| 空闲磁盘 | **≥ 20 GB**（5.8 GB 下载 + 12 GB 拼合后，还要留余量） |
| 网络 | 能下 GitHub（**建议挂代理**，见 1.3） |
| USB | 不强制。只做「下载+拼合」的话不需要接手机 |

### 1.2 软件（三选一）

**Windows**（你要问的那种）

- Git for Windows（带 Git Bash）：https://git-scm.com/download/win
- GitHub CLI：https://cli.github.com  （装完执行 `gh auth login`，浏览器里点一下）

**Linux**

```
sudo apt install gh coreutils        # Debian/Ubuntu
sudo dnf install gh coreutils        # Fedora
```

**macOS**

```
brew install gh coreutils
```

（macOS 自带 `cat`，但校验用 `sha256sum`，所以要装 coreutils）

### 1.3 关于代理（**这一步最容易卡**）

GitHub 的 artifact 走 Azure blob，国内经常断流。实测症状：
`unexpected EOF`、`BadZipFile`、`error writing zip archive`。

**如果你有代理**（主机上 7890 端口那套），在 Git Bash 里：

```
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
```

`gh run download` 会继承这两个环境变量。

> 主力机这次就是因为代理时断时续，5.8 GB 下了好几次失败。
> 换台机器 + 稳定网络是最省事的做法。

---

## 2. 下载（逐条照抄）

### 2.1 登录一次

```
gh auth login
```

选 `GitHub.com` → `HTTPS` → `Login with a web browser`，浏览器里点一下就行。
（产物在公开仓库上，其实不登录也能下，但用 `gh` 最省事。）

### 2.2 建工作目录并进去

**Windows Git Bash**（盘符要选**空间够的那个**，比如 D 盘）：

```
mkdir -p /d/ugg-flash
cd /d/ugg-flash
```

**Linux / macOS**

```
mkdir -p ~/ugg-flash
cd ~/ugg-flash
```

### 2.3 先确认空间够

```
df -h .
```

**低于 20 GB 就别继续**，换盘或者先清理。

### 2.4 下载

**方式一：浏览器（最直观）**

打开这个链接，**滚到页面最底部**，在 **Artifacts** 区域点 `ios16-root-parts`：

```
https://github.com/honghong2011/ios-ugg/actions/runs/43644714094
```

> **必须登录 GitHub**。公开仓库的 artifact 也要求登录，没登录会看到 404。
> 下载得到 `ios16-root-parts.zip`（5,837,838,248 字节）。

解压它（**用 7-Zip，不要用 Windows 资源管理器**，5.8 GB 的 zip
资源管理器经常解到一半报错）：

```
右键 -> 7-Zip -> 提取到 ios16-root-parts\
```

解压后得到 7 个 `.part` 文件 + `SHA256SUMS`，把它们放进 `parts/` 目录：

```
mkdir -p parts
mv ios16-root-parts/* parts/
ls -l parts
```

**方式二：命令行（支持断点续传，更可靠）**

```
gh run download 43644714094 \
  -R honghong2011/ios-ugg \
  -n ios16-root-parts \
  -D parts
```

这一步拿 **7 个分片 + 一个 `SHA256SUMS`**，总共 5.84 GB，视网速 5–30 分钟。
断了重跑同一条命令会**接着下**，而且自动解压好。

> 浏览器下载**不支持断点续传**，5.8 GB 中途断了要从头再来；
> 网络不稳时优先用方式二。

### 2.5 看一眼下到了什么

```
ls -l parts
```

应该看到：

```
SHA256SUMS
ios16-root.simg.partaa
ios16-root.simg.partab
ios16-root.simg.partac
ios16-root.simg.partad
ios16-root.simg.partae
ios16-root.simg.partaf
ios16-root.simg.partag
```

**7 个 part**。少一个就是没下完，重跑 2.4（`gh` 会复用已下载部分）。

---

## 3. 校验（**不要跳过**）

```
cd parts
sha256sum -c SHA256SUMS
cd ..
```

每个分片要显示 `OK`。有一个 `FAILED` 就重新下载那个分片。
这一节能挡掉绝大多数「刷进去开不了机」。

---

## 4. 拼合成一个镜像

```
cat parts/ios16-root.simg.part* > ios16-root.simg
```

**Windows Git Bash 也可以直接用 `cat`**，不要用 `copy /b`（会搞坏内容）。

### 4.1 检查字节数（**关键**）

```
stat -c%s ios16-root.simg        # Linux / Git Bash
stat -f%z ios16-root.simg        # macOS
```

**必须等于 `11970598900`。**

不等于 → 分片缺了或拼错了，**不要刷**，回到第 2 步。

---

## 5. 怎么把镜像弄到主力机 / 直接刷

### 走法 A：在主力机上刷（推荐）

1. 把 `ios16-root.simg`（11.97 GB）从另一台电脑拷到主力机。
   **需要 USB 硬盘**，C 盘放不下。
2. 手机进 fastboot（关机后按住 **音量下 + 电源**）。
3. 主力机上执行：

```
fastboot getvar partition-size:userdata
```

   输出的字节数必须 **≥ 11,970,598,900**（userdata 是 54 GB，肯定够）。

```
fastboot -S 512M flash userdata 路径/ios16-root.simg
```

   `-S 512M` 是**分块传输**（mido 用的就是这个值，24–25 片）。
   全程 **10–15 分钟**，不要拔线。

4. 刷完开机：

```
fastboot boot shim-boot-0084-32bpp.img
```

### 走法 B：直接在另一台电脑上刷（更快，但那台要装 fastboot）

那台电脑也要有 `adb/fastboot`（Android platform-tools），并且插上手机。
步骤同上，只是路径从本地读，省掉 12 GB 的跨机拷贝。

> 判断：另一台如果是台式机、USB 口方便，走 B 更省事；
> 如果是笔记本、手机在主力机旁边，走 A。

---

## 6. 刷完应该看到什么

**第一段（红屏，shim 24bpp 控制台）**

```
RGB0 FMT ... -> 000236ff
RGB0 STRIDE ... -> 00000b40
RGB0 32BPP staged (registers read back)
VIDEO rowbytes ...0B40
VIDEO depth ...0020
```

然后闪一下色带（1.2 秒），跳内核。

**第二段（黑屏，内核 32bpp 控制台，2 倍字）**

先前是 `bsd_init: calling setconf` 之后无限循环然后重启。这次改成：

```
UGG EMMC: userdata first=... nblocks=... (54263 MiB)
SWEET UFS: userdata on LUN 0: ... read-write, DMA at 0x...
bsd_init: calling setconf
bsd_init: vfs_mountroot
```

**如果根镜像刷对了**，`vfs_mountroot` 会成功，继续往下走：
`VFS_ROOT` → `IOSecureBSDRoot` → `bsd_utaskbootstrap` → 启动 `launchd`。

**如果还是失败**，现在不会再默默循环，而是打出：

```
UGG ROOT FAIL: rootdevice=ufsroot0 errno=N args=...
```

然后 panic（红屏出现 `SWEET EARLY PANIC: UGG: no root filesystem ...`）。

**把 `errno=N` 拍下来**，含义：

| errno | 含义 | 说明 |
|---|---|---|
| 5 | EIO | 读到了扇区但解不出来 → 镜像没写对/没写完 |
| 6 | ENXIO | 设备不存在 → eMMC 没认出来 |
| 19 | ENODEV | 没有合适的文件系统 → **镜像没刷进去**，或不是 HFS+ |
| 22 | EINVAL | 参数不对 |
| 79 | EFTYPE | 文件系统类型不支持 |

---

## 7. 常见问题

### 7.1 下载报 `unexpected EOF` / `error writing zip archive`

代理不稳。重跑同一条命令即可（`gh` 会复用已下载部分）。
还不行 → 换网络，或者用 `curl -C -` 断点续传：

```
TOKEN=$(gh auth token)
curl -sSL -C - -H "Authorization: token $TOKEN" \
  -o parts.zip \
  "https://api.github.com/repos/honghong2011/ios-ugg/actions/artifacts/14134366629/zip"
unzip parts.zip -d parts
```

### 7.2 产物过期了怎么办（2026-11-19 之后）

重新构建一次即可，**不用在本机装 Linux**：

```
gh workflow run build-root.yml -R honghong2011/ios-ugg --ref ugg-port
```

在 **GitHub Actions 的 ubuntu-24.04 runner** 上跑，约 1–2 小时
（下 IPSW 约 3 GB、编译 apfs-fuse、rsync 合并、转 sparse、分片）。
产物会以新的 run id 出现，把本文的 `43644714094` 换成新的即可。

> 为什么必须在 CI 里做：本机没有 `apfs-fuse` / `mkfs.hfsplus` / `sudo mount`
> 这套东西，Windows 上装不了。runner 有 86 GB 空间和 root 权限。

### 7.3 拼合后字节数不对

```
ls -l parts/*.part*
```

逐个看大小，缺的那个重新下载。不要用 `cat` 之外的方式拼。

### 7.4 刷写中途卡住 / 掉线

```
# 拔线，重进 fastboot（音量下 + 电源），然后重刷
fastboot -S 512M flash userdata 路径/ios16-root.simg
```

刷 userdata 是**幂等**的，重刷不会更糟。

### 7.5 想确认镜像内容对不对（可选）

Linux 上可以挂载看看（需要 root）：

```
sudo apt install hfsprogs android-sdk-libsparse-utils
simg2img ios16-root.simg ios16-root.raw.img     # 12 GB，需要空间
sudo mount -t hfsplus -o loop,force ios16-root.raw.img /mnt
ls /mnt
sudo umount /mnt
```

应该看到标准 iOS 根结构：`Applications` `Library` `System` `usr` `private`，
卷名 `iOSRoot`。

> **注意**：`simg2img` 会再产生 12 GB，总共约 32 GB 空间。
> 只确认的话可以不展开，直接刷。

---

## 8. 顺序建议（重要）

**不要一上来就刷 userdata。** 按这个顺序：

1. **先刷新的内核镜像**（含 errno 判定改动），确认
   `UGG ROOT FAIL ... errno=19`（ENODEV = 没有文件系统）。
   这证明「读路径通、只是缺文件系统」，刷镜像才有意义。
2. 如果 errno 不是 19（比如 5 或 6），**先别刷**，把 errno 发回来，
   那是 eMMC 层的另一个问题。
3. errno 确认是 19 → 按本文下载并拼合 → 刷 userdata → 再启动。

**刷 userdata 会抹掉 Android 的全部数据**（照片、微信、应用）。
这是已批准的方案（iOS 接管 userdata），但**不可逆**，动手前自己确认一次。

---

## 9. 附：CI 里到底在做什么（`build-root.yml`）

| 步骤 | 做什么 | 产出 |
|---|---|---|
| 1. 腾空间 | 删 dotnet/android/ghc 等预装件，`df` 确认 86 GB 可用 | — |
| 2. 装工具 | `hfsprogs`、`apfs-fuse`(源码编译)、`rsync`、`libsparse-utils` | 能读写 HFS+、能读 APFS |
| 3. 下 IPSW | `tools/ipsw_url.py` 从 api.ipsw.me 解析 Apple CDN 直链 | `fw.ipsw`（约 3 GB） |
| 4. 抽三个 dmg | `unzip` + `tools/ipsw_roles.py` 找 OS / SYSTEMOS / APPOS | 三个 `.dmg` |
| 5. 抽设备树 | `tools/ipsw_adt.py`（失败不阻塞） | `d20ap.adt` |
| 6. **建 HFS+ 根** | `tools/mkiosroot.sh`：apfs-fuse 挂三卷 → rsync 合并 → 16 GiB HFS+ | `ios16-root.img` |
| 7. 打补丁 | `tools/sweet-root-tweaks.py` | 同上 |
| 8. 转 sparse | `img2simg` | `ios16-root.simg`（11.97 GB） |
| 9. 分片 | `split -b 1800M` | **7 个 part** + `SHA256SUMS` |
| 10. 上传 | `actions/upload-artifact` | `ios16-root-parts` |

**为什么 7 个分片**：GitHub 单文件 artifact 上限 10 GB，
`ios16-root.simg` 有 11.97 GB，所以切 1800 MB 一块 → 7 块。

**为什么是 sparse**：`fastboot flash` 直接吃 sparse image，
传输量比 raw 小（只传非零块），刷得快。

---

## 10. 附：需要下载/准备的东西清单（一句话版）

| 要不要 | 东西 | 在哪 |
|---|---|---|
| 要 | `ios16-root-parts`（7 个文件，5.84 GB） | GitHub artifact，run `43644714094` |
| 要 | `gh`（GitHub CLI） | cli.github.com |
| 不要 | IPSW 原始包 | CI 已经处理过了 |
| 不要 | apfs-fuse / hfsprogs | 只有重建时才需要，且在 CI 里 |
| 不要 | Linux 环境 | 下载+拼合在 Windows 上就行 |
| 可选 | 移动硬盘 | 只在「走法 A」跨机拷贝 12 GB 时需要 |

---

*最后更新：2026-11-15。产物 run `43644714094`，到期 2026-11-19。*
