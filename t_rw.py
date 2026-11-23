import io, re
p = 'tools/make-hfs-fixture.py'
t = io.open(p, encoding='utf-8').read()

old_sig = 'def build(path, two_level):\n    """Write a fixture. two_level adds an INDEX root pointing at two leaves."""'
new_sig = (
'def build(path, mode):\n'
'    """Write a fixture. mode is "flat", "two", or "edge8k".\n'
'\n'
'    "flat"   root node IS the leaf; exercises only the leaf path.\n'
'    "two"    INDEX root pointing at two leaves; exercises the descent.\n'
'    "edge8k" 8192-byte nodes plus an index record whose offset is 1, putting its\n'
'             start at node_size-1. That is the shape that crashed on a real\n'
'             catalog: a key length was read one byte past the end of the node.\n'
'             The 4096-byte fixtures cannot produce that offset, which is why a\n'
'             passing fixture said nothing about it.\n'
'    """\n'
'    node_size = 8192 if mode == "edge8k" else NODE'
)
if old_sig not in t:
    raise SystemExit('signature not found')
t = t.replace(old_sig, new_sig)

bodyStart = t.index(new_sig) + len(new_sig)
bodyEnd = t.index('    vol[20 * BS:20 * BS + 8]')
body = t[bodyStart:bodyEnd]
body = body.replace('NODE', 'node_size')
body = body.replace('node_sizeODE', 'node_size')
# mknode / mknode calls already had 3 args; add node_size.
body = re.sub(r'mknode\((0x[0-9a-f]+), (\d+), (\[[^\]]*\])\)', r'mknode(\1, \2, \3, node_size)', body)
body = re.sub(r'mknode\((0x[0-9a-f]+), (\d+), (list\(zip\([^)]*\)\))\)', r'mknode(\1, \2, \3, node_size)', body)
body = body.replace('if two_level:', 'if mode in ("two", "edge8k"):')
old_idx = '        index = mknode(0x00, 2, list(zip(offs, (ia, ib))), node_size)'
new_idx = (
'        if mode == "edge8k":\n'
'            # roff = 1 -> start = node_size - 1: the crash shape.\n'
'            index = mknode(0x00, 3, list(zip(offs + [1], (ia, ib, b""))), node_size)\n'
'        else:\n'
'            index = mknode(0x00, 2, list(zip(offs, (ia, ib))), node_size)'
)
if old_idx not in body:
    raise SystemExit('index line not found')
body = body.replace(old_idx, new_idx)
t = t[:bodyStart] + body + t[bodyEnd:]
io.open(p, 'w', encoding='utf-8', newline='\n').write(t)
print('rewrote build() for three modes')
