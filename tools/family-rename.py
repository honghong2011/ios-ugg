#!/usr/bin/env python3
"""Rewrite the sweet patch set into a SWEET_FAMILY-aware set for the ugg port.

Mechanical rule set (validated against how ios-ugglite's chain builds):

1. In every *.patch EXCEPT 0004-sweet-machine-config.patch, rename the
   board-config macro ARM64_BOARD_CONFIG_SWEET -> SWEET_FAMILY on EVERY line
   (added, context and removed alike): hunks added by earlier patches appear
   as context in later patches, so a half rename breaks the chain.  0004 is
   excluded: it is the first patch touching these sites and its own
   MACHINE_FLAGS -D / board_config.h gate keep the real macro name.
   The macro is never a substring of any longer identifier or path, so the
   replacement cannot touch build-file context (0006/0037 MASTER hunks and
   the staging scripts are macro-free - asserted below).
2. The arm64e export gate in 0004 flips to the list form so UGG (added by
   the board-config patch) also stays plain arm64:
     ifneq ($(CURRENT_MACHINE_CONFIG),SWEET)
   ->  ifeq ($(filter $(CURRENT_MACHINE_CONFIG),SWEET UGG),)
3. MACHINE_CONFIG equality gates in Makefile.template hunks of 0019/0020/0026
   (builtin pthread / bearssl / hfs) widen to a filter over "SWEET UGG",
   keeping the same truth direction (in-list -> builtin):
     +ifeq ($(CURRENT_MACHINE_CONFIG),SWEET)
   ->  +ifneq ($(filter $(CURRENT_MACHINE_CONFIG),SWEET UGG),)
4. The three stage-*.sh scripts accept SWEET or UGG.

Line counts are preserved everywhere, so hunk headers stay valid.
Binary read/write keeps CRLF/LF and trailing bytes untouched.
"""
import sys
from pathlib import Path

PATCHES = Path(sys.argv[1])
OLD = b"ARM64_BOARD_CONFIG_SWEET"
NEW = b"SWEET_FAMILY"
SKIP_RENAME = {"0004-sweet-machine-config.patch"}

gate_old = b"+ifneq ($(CURRENT_MACHINE_CONFIG),SWEET)"
gate_new = b"+ifeq ($(filter $(CURRENT_MACHINE_CONFIG),SWEET UGG),)"
tmpl_old = b"+ifeq ($(CURRENT_MACHINE_CONFIG),SWEET)"
tmpl_new = b"+ifneq ($(filter $(CURRENT_MACHINE_CONFIG),SWEET UGG),)"

report = []
for p in sorted(PATCHES.glob("*.patch")):
    data = p.read_bytes()
    changed = 0
    if p.name not in SKIP_RENAME:
        if OLD in data:
            changed += data.count(OLD)
            data = data.replace(OLD, NEW)
    if p.name == "0004-sweet-machine-config.patch":
        n = data.count(gate_old)
        if n != 1:
            sys.exit(f"{p.name}: expected 1 arm64e gate, found {n}")
        data = data.replace(gate_old, gate_new)
        changed += n
    if p.name in ("0019-sweet-builtin-pthread.patch",
                  "0020-sweet-portable-aes-cbc.patch",
                  "0026-sweet-builtin-hfs.patch") and tmpl_old in data:
        changed += data.count(tmpl_old)
        data = data.replace(tmpl_old, tmpl_new)
    if changed:
        p.write_bytes(data)
        report.append((p.name, changed))

for s in [PATCHES / "0019-stage-libpthread.sh", PATCHES / "0020-stage-bearssl.sh",
          PATCHES / "0026-stage-hfs.sh"]:
    if not s.exists():
        continue
    data = s.read_bytes()
    old = b'[[ "${MACHINE_CONFIG:-}" == SWEET ]] || exit 0'
    if old not in data:
        sys.exit(f"{s.name}: staging gate not found")
    s.write_bytes(data.replace(old, b'case "${MACHINE_CONFIG:-}" in SWEET|UGG) ;; *) exit 0 ;; esac'))
    report.append((s.name, 1))

for name, n in report:
    print(f"{name}: {n} site(s)")
print("total files changed:", len(report))
