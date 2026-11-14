#!/bin/bash
# ---------------------------------------------------------------------------
# ugg: build the iOS 16 root image   (run this on a Linux box)
#
#   ./build-root.sh [WORKDIR]           default WORKDIR = $HOME/ugg-root
#
# What it does:
#   1. downloads the iPhone 8 (iPhone10,4) iOS 16.7.16 20H392 IPSW (~5-6 GB)
#   2. extracts the three system disk images from it
#   3. merges them into ONE case-sensitive journaled HFS+ volume (16 GiB)
#   4. applies the bring-up tweaks that let an unmodified iOS userland boot on
#      a CPU-rendered phone (skip Setup, seed activation, kill the crash-looping
#      daemons, give backboardd/SpringBoard room)
#   5. converts the result to a sparse image for fastboot
#
# Requirements
#   - disk: >= 40 GB free in WORKDIR (IPSW 6 GB + image 16 GB + sparse 12 GB)
#   - root: it mounts loop devices
#   - packages (Ubuntu/Debian):
#       sudo apt install python3 python3-pip rsync hfsprogs \
#                        android-sdk-libsparse-utils curl unzip
#       pip3 install ipsw
#     apfs-fuse is not packaged on Ubuntu: build it once
#       sudo apt install libfuse3-dev cmake ninja-build zlib1g-dev libbz2-dev libssl-dev
#       git clone --depth 1 https://github.com/sgan81/apfs-fuse && cd apfs-fuse
#       git submodule update --init && mkdir build && cd build && cmake .. && make -j
#       sudo make install && sudo ldconfig
#
# Output: WORKDIR/ios16-root.simg
#
# NOTE: flashing this erases the phone's userdata partition. That is the
# intended, approved design for ugg (iOS takes over userdata; Android data is
# lost). Nothing else on the phone is touched.
# ---------------------------------------------------------------------------
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
WORK=${1:-$HOME/ugg-root}
IPSW_DIR=$WORK/ipsw
ROOT_IMG=$WORK/ios16-root.img
SPARSE=$WORK/ios16-root.simg
DEVICE=iPhone10,4                 # iPhone 8 / D20AP, the identity ugg presents
VERSION=16.7.16

say() { printf '\n=== $s\n' "$*"; }
die() { printf '\n!!! $s\n' "$*" >&2; exit 1; }

mkdir -p "$WORK"

# ---------------------------------------------------------------- pre-flight
say "pre-flight"
missing=()
for t in apfs-fuse mkfs.hfsplus rsync img2simg python3 curl unzip sudo; do
    command -v "$t" >/dev/null 2>&1 || missing+=("$t")
done
if [ "${#missing[@]}" -gt 0 ]; then
    die "missing: ${missing[*]}
  Ubuntu/Debian:
    sudo apt install rsync hfsprogs android-sdk-libsparse-utils python3 curl unzip
    (apfs-fuse must be built from source - see the header of this script)
  Fedora: sudo dnf install rsync hfsplus-tools android-tools python3 curl unzip"
fi
free_gb=$(df -BG --output=avail "$WORK" | tail -1 | tr -dc '0-9')
[ "$free_gb" -ge 40 ] || die "need >= 40 GB free in $WORK, have ${free_gb} GB"

# ------------------------------------------------------------------- 1. IPSW
if compgen -G "$IPSW_DIR/*.ipsw" >/dev/null; then
    say "IPSW already present, skipping download"
else
    say "downloading $DEVICE iOS $VERSION - about 5-6 GB"
    mkdir -p "$IPSW_DIR"
    python3 -m ipsw download ipsw --device "$DEVICE" --version "$VERSION" \
        --output "$IPSW_DIR" || die "ipsw download failed; fetch the .ipsw by hand
  from Apple's CDN and put it in $IPSW_DIR"
fi
IPSW=$(ls "$IPSW_DIR"/*.ipsw | head -1)
say "using $IPSW"

# --------------------------------------------------------- 2. system volumes
cd "$WORK"
rm -rf extract && mkdir -p extract
say "unpacking the IPSW"
unzip -q -o "$IPSW" -d extract

# The three images are named in BuildManifest.plist and the names change
# between builds, so resolve them by role instead of hard-coding file names.
python3 - "$WORK/extract" <<'PY'
import os, plistlib, sys
d = sys.argv[1]
man = plistlib.load(open(os.path.join(d, 'BuildManifest.plist'), 'rb'))
ident = None
for i in man['BuildIdentities']:
    blob = str(i.get('Info', {})).lower()
    if 'd20ap' in blob:
        ident = i
        break
if ident is None:
    ident = man['BuildIdentities'][0]
    print('warning: no D20AP identity, using the first one', file=sys.stderr)
wanted = {'OS': None, 'SYSTEMOS': None, 'APPOS': None}
for k, v in ident.get('Manifest', {}).items():
    if not isinstance(v, dict):
        continue
    p = v.get('Info', {}).get('Path')
    if not p:
        continue
    if k == 'OS':
        wanted['OS'] = p
    elif k.startswith('Cryptex1,SystemOS'):
        wanted['SYSTEMOS'] = p
    elif k.startswith('Cryptex1,AppOS'):
        wanted['APPOS'] = p
missing = [k for k, v in wanted.items() if not v]
if missing:
    sys.exit('could not identify: ' + ', '.join(missing))
for k, p in wanted.items():
    print(k, p)
    open(os.path.join(d, k + '.path'), 'w').write(p)
PY

OS_DMG=$WORK/extract/$(cat "$WORK/extract/OS.path")
SYS_DMG=$WORK/extract/$(cat "$WORK/extract/SYSTEMOS.path")
APP_DMG=$WORK/extract/$(cat "$WORK/extract/APPOS.path")
for f in "$OS_DMG" "$SYS_DMG" "$APP_DMG"; do
    [ -f "$f" ] || die "missing image $f"
done

# ------------------------------------------------------------- 3. HFS+ merge
say "building the 16G HFS+ root (slow: 20-60 min)"
[ ! -e "$ROOT_IMG" ] || { say "removing the previous $ROOT_IMG"; rm -f "$ROOT_IMG"; }
"$HERE/mkiosroot.sh" "$OS_DMG" "$SYS_DMG" "$APP_DMG" "$ROOT_IMG" 16G

say "checking the filesystem"
sudo fsck.hfsplus -fy "$ROOT_IMG" || true

# ------------------------------------------------------------- 4. the tweaks
say "applying the bring-up tweaks"
MNT=$WORK/mnt
mkdir -p "$MNT"
sudo mount -t hfsplus -o loop,force "$ROOT_IMG" "$MNT" || \
    die "mount failed. If this kernel has no hfsplus support (common on WSL2),
  use a native Linux box instead; see docs/MIDO-PORT-PLAN.md"
sudo python3 "$HERE/sweet-root-tweaks.py" "$MNT"
sync
sudo umount "$MNT"

say "re-checking the filesystem"
sudo fsck.hfsplus -fy "$ROOT_IMG"

# --------------------------------------------------------- 5. sparse + report
say "converting to a sparse image for fastboot"
img2simg "$ROOT_IMG" "$SPARSE"
ls -l "$ROOT_IMG" "$SPARSE"

say "done"
cat <<EOF

Root image:  $SPARSE

Flash it (erases the phone's userdata, which is the approved design):

  fastboot getvar partition-size:userdata
  fastboot -S 256M flash userdata "$SPARSE"
  fastboot boot shim-boot.img

Sanity checks before flashing:
  - the .simg is roughly 12 GB (16 GiB volume, ~12 GB used)
  - fsck says "volume iOSRoot appears to be OK"
  - the image contains System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64
    (about 2.5-3 GB)

Report back: the fsck output, the two file sizes, and
fastboot getvar partition-size:userdata.
EOF
