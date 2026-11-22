#!/bin/sh
# fetch-kernel.sh -- download the xnu-kernel artifact of a CI run, robustly.
#
#   ./fetch-kernel.sh RUN_ID [OUTDIR]
#
# Why not "gh run download": on this repository it frequently fails with
# "unexpected EOF" part way through the 62 MB zip, and it has no resume. This
# resolves the signed asset URL and downloads with curl -C - so a dropped
# connection continues instead of starting over.
#
# Machine-specific traps, all observed here:
#   * the curl shipped with Git (MSYS) is old: --retry-all-errors is unknown.
#   * unzip is not installed; PowerShell Expand-Archive is used instead.
#   * gh run download has been seen to HANG rather than error. Every loop below
#     is bounded by an iteration count and a size check, so this script cannot
#     hang forever the way a bare gh run download can -- that cost two rounds.
set -u

RUN=${1:?usage: fetch-kernel.sh RUN_ID [OUTDIR]}
OUT=${2:-ci-xnu$RUN}

[ -n "$(command -v gh)" ] || { echo "gh is required" >&2; exit 1; }

ART=$(gh api "repos/honghong2011/ios-ugg/actions/runs/$RUN/artifacts" \
      --jq '.artifacts[] | select(.name=="xnu-kernel") | .id' | head -1)
[ -n "$ART" ] || { echo "run $RUN has no xnu-kernel artifact" >&2; exit 1; }
echo "artifact $ART"

# The API answers 302 to a signed blob URL; reading that header without following
# it is the portable way to get the URL.
URL=$(curl -s -i -H "Authorization: token $(gh auth token)" \
      "https://api.github.com/repos/honghong2011/ios-ugg/actions/artifacts/$ART/zip" \
      | tr -d '\r' | awk 'tolower($1)=="location:"{print $2}')
[ -n "$URL" ] || { echo "could not resolve the signed URL" >&2; exit 1; }

ZIP=/tmp/xnu-kernel-$RUN.zip
rm -f "$ZIP"
i=1
while [ $i -le 8 ]; do
    echo "attempt $i"
    curl -L -C - --retry 3 --retry-delay 3 --max-time 900 -s -o "$ZIP" "$URL" || true
    sz=$(stat -c%s "$ZIP" 2>/dev/null || echo 0)
    echo "  $sz bytes"
    if [ "$sz" -ge 60000000 ]; then break; fi
    i=$((i + 1))
done

sz=$(stat -c%s "$ZIP" 2>/dev/null || echo 0)
if [ "$sz" -lt 60000000 ]; then
    echo "could not fetch the full artifact (got $sz bytes)" >&2
    echo "The connection keeps dropping; retry later or download by hand." >&2
    exit 1
fi

rm -rf "$OUT"
mkdir -p "$OUT"
if command -v unzip >/dev/null 2>&1; then
    unzip -o -q "$ZIP" -d "$OUT"
else
    powershell.exe -NoProfile -Command \
        "Expand-Archive -Force -Path '$(cygpath -w "$ZIP")' -DestinationPath '$(cygpath -w "$OUT")'"
fi
ls -l "$OUT"
sha256sum "$OUT"/kernel.* 2>/dev/null || true