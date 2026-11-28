import struct, os
SPARSE=0xED26FF3A; BLK=4096
# Mimic the real file: MANY chunks (img2simg emits RAW runs plus FILL for zero runs).
TOTAL = 4194304
chunks = []
blk = 0
# 20000 small RAW chunks of 8 blocks each, then a big DONT_CARE, then FILL.
data8 = bytearray()
for i in range(8):
    b=bytearray(BLK); b[0:4]=struct.pack('>I',0x4226); b[8]=0xFF; data8+=b
for i in range(20000):
    chunks.append(struct.pack('<HHII',0xCAC1,0,12+len(data8),len(data8))+bytes(data8))
    blk += 8
# FILL 1000 blocks (zeros)
chunks.append(struct.pack('<HHII',0xCAC2,0,16,1000*BLK)+struct.pack('<I',0)); blk += 1000
# DONT_CARE covering the ext3 block region
dc = TOTAL - blk
chunks.append(struct.pack('<HHII',0xCAC3,0,12,dc*BLK)); blk += dc
out = r'C:\Users\Administrator\Desktop\f.simg'
open(out,'wb').write(struct.pack('<IHHHHIIII',SPARSE,1,0,28,12,BLK,TOTAL,len(chunks),0)+b''.join(chunks))
print("wrote %s: %d chunks, %d blocks, ext3 block %d in DONT_CARE (starts %d)" % (out,len(chunks),blk,1729287,20000*8+1000))
