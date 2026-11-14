#!/usr/bin/env python3
"""Resolve the exact IPSW URL for a device/version from api.ipsw.me.

Used by .github/workflows/build-root.yml. Written as a file rather than an
inline heredoc because the quoting inside a YAML block scalar is a trap.
"""
import argparse
import json
import sys
import urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('device', help='e.g. iPhone10,4')
    ap.add_argument('version', help='e.g. 16.7.16')
    a = ap.parse_args()

    url = 'https://api.ipsw.me/v4/device/%s?type=ipsw' % a.device
    with urllib.request.urlopen(url, timeout=120) as fh:
        data = json.load(fh)

    fws = [f for f in data.get('firmwares', []) if f.get('version') == a.version]
    if not fws:
        sys.exit('no firmware %s for %s (have: %s)' % (
            a.version, a.device,
            ', '.join(sorted({f.get('version', '?') for f in data.get('firmwares', [])})[-6:])))

    fw = fws[0]
    print(fw['url'])
    print('build %s, %d bytes' % (fw.get('buildid'), fw.get('filesize', 0)), file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
