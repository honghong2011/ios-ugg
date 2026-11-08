import struct
import sys

LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2


def load(data):
    magic, = struct.unpack_from("<I", data, 0)
    if magic != 0xfeedfacf:
        raise SystemExit("not a 64-bit little-endian Mach-O: magic %#x" % magic)
    cputype, cpusub, filetype, ncmds, sizeofcmds, flags = struct.unpack_from("<iiIIII", data, 4)
    off = 32
    segs = []
    symtab = None
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, off)
        if cmd == LC_SEGMENT_64:
            segname = data[off + 8:off + 24].split(b"\0")[0].decode()
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", data, off + 24)
            segs.append((segname, vmaddr, vmsize, fileoff, filesize))
        elif cmd == LC_SYMTAB:
            symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", data, off + 8)
            symtab = (symoff, nsyms, stroff, strsize)
        off += size
    return segs, symtab


def symbols(data, symtab):
    symoff, nsyms, stroff, strsize = symtab
    strtab = data[stroff:stroff + strsize]
    out = []
    for i in range(nsyms):
        o = symoff + i * 16
        n_strx, n_type, n_sect, n_desc, n_value = struct.unpack_from("<IBBHQ", data, o)
        if n_value == 0 or n_strx == 0:
            continue
        end = strtab.find(b"\0", n_strx)
        if end < 0:
            continue
        name = strtab[n_strx:end].decode("latin-1")
        if name:
            out.append((n_value, name))
    out.sort()
    return out


def main():
    data = open(sys.argv[1], "rb").read()
    segs, symtab = load(data)
    print("=== segments ===")
    for s in segs:
        print("  %-16s vmaddr %#x vmsize %#x fileoff %#x filesize %#x" % s)
    print("=== symtab ===", symtab)
    syms = symbols(data, symtab)
    print("total symbols:", len(syms))
    for a in sys.argv[2:]:
        addr = int(a, 16)
        best = None
        for va, name in syms:
            if va <= addr:
                best = (va, name)
            else:
                break
        if best:
            print("%#x -> %s + %#x" % (addr, best[1], addr - best[0]))
        else:
            print("%#x -> (no symbol below)" % addr)


main()
