#!/usr/bin/env python3
"""Sanity-check a downloaded IPSW before spending an hour on it."""
import os
import sys
import zipfile


def main():
    if len(sys.argv) < 2:
        sys.exit('usage: check_ipsw.py FILE.ipsw')
    p = sys.argv[1]
    size = os.path.getsize(p)
    if not zipfile.is_zipfile(p):
        sys.exit('%s is not a zip (%d bytes): the download was truncated or the '
                 'URL returned an error page' % (p, size))
    z = zipfile.ZipFile(p)
    names = z.namelist()
    manifest = [n for n in names if n.endswith('BuildManifest.plist')]
    if not manifest:
        sys.exit('no BuildManifest.plist inside %s' % p)
    dmg = [n for n in names if n.endswith('.dmg')]
    print('IPSW ok: %d bytes (%.2f GiB), %d entries, %d dmg, manifest %s'
          % (size, size / 2 ** 30, len(names), len(dmg), manifest[0]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
