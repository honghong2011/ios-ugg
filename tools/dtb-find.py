import struct, sys
MAGIC = 0xd00dfeed

def find_fdts(d):
    offs, i = [], 0
    while True:
        j = d.find(b'\xd0\x0d\xfe\xed', i)
        if j < 0: return offs
        offs.append(j); i = j + 4

def cstr(b, pos):
    e = b.index(b'\x00', pos)
    return b[pos:e].decode('utf-8', 'replace')

def walk(b, base):
    (magic, totalsize, off_struct, off_strings, off_rsv, version,
     lastcomp, bootcpu, size_strings, size_struct) = struct.unpack_from('>10I', b, base)
    pos = base + off_struct
    end = pos + size_struct
    st = base + off_strings
    path, props = [], None
    while pos < end:
        tag = struct.unpack_from('>I', b, pos)[0]; pos += 4
        if tag == 1:
            name = cstr(b, pos)
            pos += (len(name) + 4) & ~3
            path.append(name); props = {}
            yield '/'.join(path), props
        elif tag == 2:
            if path: path.pop()
        elif tag == 3:
            ln, nameoff = struct.unpack_from('>II', b, pos); pos += 8
            val = b[pos:pos+ln]; pos += (ln + 3) & ~3
            if props is not None:
                props[cstr(b, st + nameoff)] = val
        elif tag == 4:
            continue
        elif tag == 9:
            break

d = open(sys.argv[1], 'rb').read()
for base in find_fdts(d):
    nodes = list(walk(d, base))
    gx = [(p, pr) for p, pr in nodes if 'goodix' in p and '5d' in p]
    print("nodes:", len(nodes), "| goodix@5d matches:", len(gx))
    if not gx:
        continue
    ph = {}
    for p, pr in nodes:
        for k in ('phandle', 'linux,phandle'):
            if k in pr and len(pr[k]) == 4:
                ph[int.from_bytes(pr[k], 'big')] = p
    for p, pr in gx:
        print("node:", p)
        for prop in ('vdd_ana-supply', 'vcc_i2c-supply'):
            if prop in pr:
                v = int.from_bytes(pr[prop], 'big')
                tgt = ph.get(v, '??')
                print("   %-18s -> 0x%02x %s" % (prop, v, tgt))
                for p2, pr2 in nodes:
                    if p2 == tgt:
                        for q in ('regulator-name','qcom,resource-name','qcom,resource-id'):
                            if q in pr2:
                                raw = pr2[q]
                                if q == 'qcom,resource-id':
                                    print("        %-22s %d" % (q, int.from_bytes(raw,'big')))
                                else:
                                    print("        %-22s %s" % (q, raw.rstrip(b'\x00').decode('utf-8','replace')))
    break
