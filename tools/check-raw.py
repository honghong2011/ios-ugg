
import io, struct, os, sys

# Read the raw file at the exact offset of node 19174 and compare with
# what the .simg reports. This catches a bad simg2img run.
path = sys.argv[1] if len(sys.argv) > 1 else "ios16-root.img"
OFF = 1734927 * 4096
print("file :", path)
print("size :", os.path.getsize(path), "(expect 17179869184)")
f = open(path, "rb")
f.seek(OFF)
d = f.read(16)
fl = struct.unpack(">I", d[0:4])[0]
bl = struct.unpack(">I", d[4:8])[0]
print("offset 0x%x (block 1734927):" % OFF)
print("  first 16 bytes :", d.hex(" "))
print("  fLink=0x%08x bLink=0x%08x kind=0x%02x" % (fl, bl, d[8]))
print()
print("  expect from the .simg : fLink=0x00004af9 bLink=0x00000005 kind=0xff")
print("  kernel reads on phone : fLink=0xf800ebf3 bLink=0xf802ef07 kind=0xf7")
if fl == 0x00004af9:
    print("  -> the raw file is CORRECT")
    print()
    print("  So the file is fine and the card is not. fastboot did not write")
    print("  what this file contains. Its own output showed it parsing the raw")
    print("  file as a sparse image (\"Invalid sparse file format at header")
    print('  magic\") and then transferring only 11.15 GiB of 16 GiB.')
elif fl == 0xf800ebf3:
    print("  -> the raw file ITSELF holds the values the phone sees")
    print("  -> the conversion is wrong, not the flash")
else:
    print("  -> the raw file holds something else entirely!")
