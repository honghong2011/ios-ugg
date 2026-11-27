# check-sha256.ps1 -- verify an image against a published SHA256SUMS file on Windows.
#
# Works with PowerShell 5.1 (Get-FileHash) and needs no Python, no Git Bash, no
# winget. Also accepts a bare hash, and falls back to certutil if Get-FileHash is
# missing (very old systems).
#
#   .\check-sha256.ps1 ios16-root.simg
#   .\check-sha256.ps1 ios16-root.simg -Expected <hash>
#   .\check-sha256.ps1 ios16-root.simg -Sums ASSEMBLED-SHA256.txt
#
# Exit codes: 0 match, 1 mismatch, 2 usage/IO error.

param(
    [Parameter(Mandatory = $true, Position = 0)][string]$File,
    [string]$Expected,
    [string]$Sums
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $File)) {
    Write-Host "no such file: $File" -ForegroundColor Red
    exit 2
}

$size = (Get-Item -LiteralPath $File).Length
Write-Host ("file : {0}" -f $File)
Write-Host ("size : {0:N0} bytes ({1:N2} GiB)" -f $size, ($size / 1GB))

# Resolve the expected hash.
if (-not $Expected -and $Sums) {
    if (-not (Test-Path -LiteralPath $Sums)) {
        Write-Host "no such sums file: $Sums" -ForegroundColor Red
        exit 2
    }
    $name = Split-Path -Leaf $File
    foreach ($line in Get-Content -LiteralPath $Sums) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        # sha256sum format: "<hash>  <name>"  (two spaces, or ' *' for binary)
        if ($t -match '^([0-9a-fA-F]{64})\s+\*?(.+)$') {
            $h = $Matches[1]
            $n = (Split-Path -Leaf ($Matches[2].Trim()))
            if ($n -eq $name) { $Expected = $h; break }
        }
    }
    if (-not $Expected) {
        Write-Host "no entry for $name in $Sums" -ForegroundColor Yellow
        exit 2
    }
}

Write-Host "hashing (a 12 GB file takes a minute or two)..."
if (Get-Command Get-FileHash -ErrorAction SilentlyContinue) {
    $actual = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash.ToLower()
} else {
    # certutil prints the hash as the second field of the line that follows the
    # file name; grab the last 64-hex token.
    $out = & certutil -hashfile $File SHA256
    $line = $out | Where-Object { $_ -match '^[0-9a-fA-F ]{64,}$' } | Select-Object -First 1
    $actual = ($line -replace '\s', '').ToLower()
}

Write-Host ("sha256: {0}" -f $actual)

if (-not $Expected) {
    Write-Host ""
    Write-Host "no expected hash given; this is the hash of the file you have." -ForegroundColor Yellow
    Write-Host "compare it with ASSEMBLED-SHA256.txt by eye, or re-run with -Sums/-Expected."
    exit 0
}

$Expected = $Expected.Trim().ToLower()
if ($actual -eq $Expected) {
    Write-Host ""
    Write-Host "OK: matches" -ForegroundColor Green
    exit 0
} else {
    Write-Host ""
    Write-Host "MISMATCH" -ForegroundColor Red
    Write-Host ("  expected {0}" -f $Expected)
    Write-Host ("  actual   {0}" -f $actual)
    exit 1
}
