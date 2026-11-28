# Analyze the sparse image: does it contain DONT_CARE chunks that fastboot would SKIP?
# If the ext3 region falls inside a DONT_CARE run, fastboot never writes it, and the
# card keeps whatever was there before -- which is exactly what we observe.
import struct, sys, os
SIG = 0xed26ff3a
path = sys.argv[1]
f = open(path, 'rb')
magic, major, minor, fhsz, chsz, blk, total_blks, total_chunks, csum = struct.unpack('<IHHHHIIII', f.read(28))
print("magic 0x%08x (sparse=%s)" % (magic, magic == SIG))
print("block size    :", blk)
print("total blocks  :", total_blks, "=", total_blks*blk//1048576, "MiB")
print("total chunks  :", total_chunks)
f.seek(fhsz)
kinds = {}
runs = []
blk_no = 0
for i in range(total_chunks):
    ct, res, csz, tsz = struct.unpack('<HHII', f.read(12))
    data_blks = tsz * blk // csz if csz else 0
    kinds[ct] = kinds.get(ct, 0) + data_blks
    if ct == 3:  # DONT_CARE
        runs.append((blk_no, data_blks))
    blk_no += data_blks
    f.seek(csz - 12, 1)
names = {0xCAC1:'RAW', 0xCAC2:'FILL', 0xCAC3:'DONT_CARE', 0xCAC4:'CRC32'}
print()
print("块类型分布:")
for k, v in sorted(kinds.items()):
    print("  %-10s %8d blocks = %8.1f MiB" % (names.get(k, hex(k)), v, v*blk/1048576))
print()
print("DONT_CARE 段数:", len(runs))
ext3_blk = 1729287
hit = [r for r in runs if r[0] <= ext3_blk < r[0]+r[1]]
print()
print("ext3 起点（4K 块 %d = 稀疏块 %d）落在 DONT_CARE 里吗?" % (ext3_blk, ext3_blk*4096//blk))
print("  ->", "YES -- fastboot 跳过了，卡上没写！" if hit else "no")
f.close()
