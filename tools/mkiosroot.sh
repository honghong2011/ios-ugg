#!/bin/bash
# Build the SWEET iOS root: one case-sensitive HFS+ image holding an iOS OS
# root filesystem plus its cryptexes, for the userdata partition (rd=ufsroot0).
#
#   mkiosroot.sh OS.dmg SYSTEMOS.dmg APPOS.dmg OUT.img [SIZE]     (SIZE default 16G)
#
# The IPSW images are raw APFS with LZBITMAP-compressed files: they are read
# through apfs-fuse (decompressing), so the HFS+ copy is uncompressed. On a
# device /private/preboot is its own volume holding the cryptexes, which
# /System/Cryptexes/{OS,App} link to; here they live inside the one volume.
# Owners, modes, symlinks and hard links are preserved (rsync -aH as root).
#
# The volume is journaled (XNU replays the journal after a panic; Linux only
# mounts it read-write with -o force and leaves the journal empty). SWEET
# additions: /System/Library/Caches/com.apple.dyld hard-links the SystemOS
# cryptex shared cache (ignition_level=1 looks there), and
# /private/var/keybags/systembag.kb is the plain-plist system keybag that
# keybagd reads with /defaults/no-effaceable-storage (tools/mkadt.py).
set -euo pipefail

[[ $# -ge 4 ]] || { sed -n '2,12p' "$0"; exit 2; }
os=$(realpath "$1") sysos=$(realpath "$2") appos=$(realpath "$3") out=$4 size=${5:-16G}
[[ ! -e $out ]] || { echo "refusing to overwrite $out" >&2; exit 1; }

# Pre-flight tool check
missing_tools=()
for tool in apfs-fuse mkfs.hfsplus rsync; do
	command -v "$tool" >/dev/null 2>&1 || missing_tools+=("$tool")
done

if [[ ${#missing_tools[@]} -gt 0 ]]; then
	echo "Error: missing required host utilities: ${missing_tools[*]}" >&2
	echo "  Install instructions:" >&2
	echo "    Arch Linux:    sudo pacman -S apfs-fuse hfsprogs rsync" >&2
	echo "    Ubuntu/Debian: sudo apt install apfs-fuse hfsprogs rsync" >&2
	echo "    Fedora:        sudo dnf install apfs-fuse hfsplus-tools rsync" >&2
	exit 1
fi

work=$(mktemp -d)
mounts=()
cleanup() {
	local busy=0
	for m in "${mounts[@]}"; do
		if mountpoint -q "$m"; then
			sudo umount "$m" 2>/dev/null || true
		fi
		mountpoint -q "$m" && busy=1
	done
	# Never recurse into a directory that is still mounted (the root is writable).
	if [[ $busy == 0 ]]; then
		rm -f "$work"/*.dmg
		rmdir "$work"/* "$work" 2>/dev/null || true
	else
		echo "still mounted under $work: left in place" >&2
	fi
}
trap cleanup EXIT

# apfs-fuse splits its options on ',' (e.g. in iPhone10,3 paths): use links.
# Keep the .dmg name: apfs-fuse only parses UDIF images (the OS one is UDIF,
# the cryptexes are raw APFS) when the file name ends in .dmg.
apfs_mount() {
	ln -s "$1" "$work/$2.dmg"
	mkdir "$work/$2"
	# As root: a user's FUSE mount is unreadable to the root rsync below.
	sudo "$(command -v apfs-fuse)" "$work/$2.dmg" "$work/$2"
	mounts+=("$work/$2")
}
apfs_mount "$os" os
apfs_mount "$sysos" sysos
apfs_mount "$appos" appos

truncate -s "$size" "$out"
mkfs.hfsplus -s -J -v iOSRoot "$out"
mkdir "$work/root"
sudo mount -t hfsplus -o loop,force "$out" "$work/root"
mounts=("$work/root" "${mounts[@]}")

copy() {
	echo "copying $1 -> ${2#"$work/root"}"
	sudo mkdir -p "$2"
	sudo rsync -aH --numeric-ids "$1/" "$2/"
}
copy "$work/os/root" "$work/root"
copy "$work/sysos/root" "$work/root/private/preboot/Cryptexes/OS"
copy "$work/appos/root" "$work/root/private/preboot/Cryptexes/App"

# ---------------------------------------------------------------------------
# dyld shared cache
#
# On iOS, libSystem exists ONLY inside dyld_shared_cache_arm64. Without a real
# cache, launchd can be exec'd and still fail on every import, so no desktop.
#
# mido's working image has it as 3.10 GiB across 44 files (the main file plus
# numbered sub-caches, .dylddata and .symbols). Ours was 384 KiB, one file, with
# the 4-byte magic 'dyld' instead of 'dyld_v1' -- a stub.
#
# Two things were wrong and both are handled here:
#   1. the source directory was guessed; four candidates are now probed and the
#      one holding a dyld_v1 file is chosen,
#   2. the link loop copies every file in that directory, not just one.
#
# The probe output is printed in a shape the CI artifact can carry, because this
# build has never recorded which candidate actually held the cache.
# ---------------------------------------------------------------------------
cachedst="$work/root/System/Library/Caches/com.apple.dyld"
sudo mkdir -p "$cachedst"

echo "--- dyld shared cache candidates"
for cand in \
    System/Library/dyld \
    System/Library/Caches/com.apple.dyld \
    private/preboot/Cryptexes/OS/System/Library/dyld \
    private/preboot/Cryptexes/OS/System/Library/Caches/com.apple.dyld; do
	src="$work/root/$cand"
	if [ -d "$src" ] && [ -n "$(ls -A "$src" 2>/dev/null)" ]; then
		n=$(ls -1 "$src" 2>/dev/null | wc -l)
		m=$(du -sm "$src" 2>/dev/null | cut -f1)
		echo "  $cand: ${n} entry(ies), ${m} MiB"
		for f in "$src"/*; do
			[ -f "$f" ] || continue
			sz=$(wc -c < "$f" 2>/dev/null || echo 0)
			mg=$(dd if="$f" bs=1 count=16 2>/dev/null | od -An -tc | tr -d " \n")
			echo "    $(basename "$f") ${sz} bytes magic ${mg}"
		done
	else
		echo "  $cand: absent"
	fi
done

# Pick the first candidate that holds a file beginning with dyld_v1.
dsc=
for cand in \
    System/Library/dyld \
    System/Library/Caches/com.apple.dyld \
    private/preboot/Cryptexes/OS/System/Library/dyld \
    private/preboot/Cryptexes/OS/System/Library/Caches/com.apple.dyld; do
	src="$work/root/$cand"
	[ -d "$src" ] || continue
	for f in "$src"/*; do
		[ -f "$f" ] || continue
		mg=$(dd if="$f" bs=1 count=7 2>/dev/null | od -An -tc | tr -d " \n")
		case "$mg" in
			*d*y*l*d*_*v*1*) dsc=$cand; echo "chosen: $cand (found dyld_v1 in $(basename "$f"))"; break ;;
		esac
	done
	[ -n "$dsc" ] && break
done

if [ -z "$dsc" ]; then
	echo "ERROR: no dyld_v1 shared cache found in any candidate directory." >&2
	echo "       libSystem lives only inside that cache, so launchd could exec" >&2
	echo "       and then fail on every import -- no desktop. The candidate listing" >&2
	echo "       above shows what each location actually holds." >&2
	exit 1
fi

# Link EVERY file: the real cache is a set (main + sub-caches + data + symbols).
linked=0
for f in "$work/root/$dsc"/*; do
	[ -f "$f" ] || continue
	if sudo ln -f "$f" "$cachedst/${f##*/}" 2>/dev/null; then
		linked=$((linked + 1))
	else
		echo "ERROR: could not hard-link $f into the shared cache" >&2
		exit 1
	fi
done

# Verify by content, not by counting: a stub can be one file too.
main_cache="$cachedst/dyld_shared_cache_arm64"
if [ ! -f "$main_cache" ]; then
	echo "ERROR: dyld_shared_cache_arm64 did not land in the cache directory." >&2
	exit 1
fi
cache_bytes=$(wc -c < "$main_cache")
cache_mib=$((cache_bytes / 1048576))
cache_magic=$(dd if="$main_cache" bs=1 count=7 2>/dev/null | od -An -tc | tr -d " \n")
echo "shared cache: ${linked} file(s), main file ${cache_bytes} bytes (${cache_mib} MiB), magic ${cache_magic}"

case "$cache_magic" in
	*d*y*l*d*_*v*1*) : ;;
	*)
		echo "ERROR: dyld_shared_cache_arm64 magic is '${cache_magic}', not dyld_v1." >&2
		echo "       That is a stub, not a cache. libSystem would not resolve." >&2
		exit 1
		;;
esac
if [ "$cache_mib" -lt 100 ]; then
	echo "ERROR: the shared cache is only ${cache_mib} MiB; a real one is ~1000." >&2
	echo "       Check the candidate listing above for the directory that holds it." >&2
	exit 1
fi
# System keybag for the built-in AppleKeyStore (no passcode).
sudo install -d -m 0700 -o 0 -g 0 "$work/root/private/var/keybags"
printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' \
	'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' \
	'<plist version="1.0"><dict><key>KeyBagKeys</key><data>U1dFRVQ=</data></dict></plist>' |
	sudo install -m 0600 -o 0 -g 0 /dev/stdin "$work/root/private/var/keybags/systembag.kb"

df -h "$work/root"
sudo umount "$work/root"
# Linux hfsplus decomposes some non-ASCII names (localized Shortcuts examples)
# differently from Apple's tables; let fsck_hfs rewrite them, then verify.
fsck.hfsplus -f -y "$out" | grep -v 'Illegal name' || true
fsck.hfsplus -f -n "$out"
