#!/usr/bin/env python3
"""Find the OS / SystemOS / AppOS disk images in an unpacked IPSW.

Names change between builds, so the roles are resolved through
BuildManifest.plist by their manifest keys, not by file name. Writes one
<ROLE>.path file per role into the unpacked directory and prints the mapping.
"""
import os
import plistlib
import sys

# iPhone identifier -> the DeviceClass in BuildManifest
DEVCLASS = {
    'iPhone10,3': 'd22ap',
    'iPhone10,4': 'd20ap',
    'iPhone10,5': 'd211ap',
    'iPhone10,6': 'd21ap',
}


def main():
    if len(sys.argv) < 3:
        sys.exit('usage: ipsw_roles.py UNPACKED_DIR DEVICE')
    d, device = sys.argv[1], sys.argv[2]
    code = DEVCLASS.get(device, 'd20ap')

    man = plistlib.load(open(os.path.join(d, 'BuildManifest.plist'), 'rb'))
    ident, chosen = None, None
    for i in man['BuildIdentities']:
        blob = str(i.get('Info', {})).lower()
        if code in blob:
            ident, chosen = i, code
            break
    if ident is None:
        ident, chosen = man['BuildIdentities'][0], 'first'
        print('warning: no %s identity, using the first one' % code, file=sys.stderr)

    roles = {}
    for key, val in ident.get('Manifest', {}).items():
        if not isinstance(val, dict):
            continue
        path = val.get('Info', {}).get('Path')
        if not path:
            continue
        if key == 'OS':
            roles['OS'] = path
        elif key.startswith('Cryptex1,SystemOS'):
            roles['SYSTEMOS'] = path
        elif key.startswith('Cryptex1,AppOS'):
            roles['APPOS'] = path

    missing = [r for r in ('OS', 'SYSTEMOS', 'APPOS') if r not in roles]
    if missing:
        sys.exit('identity %s has no %s' % (chosen, ', '.join(missing)))

    for role, path in roles.items():
        full = os.path.join(d, path)
        if not os.path.exists(full):
            sys.exit('%s file missing on disk: %s' % (role, full))
        print('%-9s %s  (%.2f GiB)' % (role, path, os.path.getsize(full) / 2 ** 30))
        open(os.path.join(d, role + '.path'), 'w').write(path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
