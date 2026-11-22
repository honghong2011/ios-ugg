# UGG kernel console log decoder.
#
# The kernel keeps a 4 MiB ring of every character that reached the console and
# writes it, preceded by a 4 KiB header, into the LAST 1025 blocks of 4 KiB of
# the userdata partition. Layout of that area (little endian):
#
#   0        8   magic "SWEETLOG"
#   8        4   version (1)
#   12       4   ring size in bytes
#   16       8   total bytes ever written
#   24       8   flush sequence number
#   4096     n   the ring itself
#
# Byte n of the console stream lives at ring offset (n mod ring size).

param(
    [Parameter(Mandatory=$true)][string]$InputFile,
    [string]$OutputFile = ""
)

$ErrorActionPreference = 'Stop'

# Relative paths are resolved next to this script, so the decoder works no
# matter which folder the caller is in.
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not [IO.Path]::IsPathRooted($InputFile)) {
    $candidate = Join-Path $scriptDir $InputFile
    if (Test-Path -LiteralPath $candidate) { $InputFile = $candidate }
}
if ($OutputFile -ne '' -and -not [IO.Path]::IsPathRooted($OutputFile)) {
    $parent = Split-Path -Parent $OutputFile
    if ($parent -ne '' -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path (Join-Path $scriptDir $parent) | Out-Null
    }
    $OutputFile = Join-Path $scriptDir $OutputFile
}

if (-not (Test-Path -LiteralPath $InputFile)) {
    Write-Host "[X] file not found: $InputFile"
    exit 1
}
if ($OutputFile -eq '') {
    $OutputFile = [IO.Path]::ChangeExtension($InputFile, '.txt')
}

$b = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $InputFile))
Write-Host ("    file size : {0} bytes" -f $b.Length)

if ($b.Length -lt 4096) {
    Write-Host '[X] smaller than one block -- dd did not read the right area'
    exit 2
}

# The dump should start exactly at the header, but the kernel addresses the
# area in whole 4 KiB blocks, so a capture taken with 512-byte rounding can be
# a few sectors late. Look for the magic in the first 64 KiB and shift if found,
# instead of rejecting an otherwise good dump.
$magic = [Text.Encoding]::ASCII.GetString($b, 0, 8)
if ($magic -ne 'SWEETLOG') {
    $wanted = [Text.Encoding]::ASCII.GetBytes('SWEETLOG')
    $limit = [Math]::Min($b.Length, 65536) - 8
    for ($i = 0; $i -le $limit; $i++) {
        if ($b[$i] -eq $wanted[0] -and $b[$i+1] -eq $wanted[1] -and
            $b[$i+2] -eq $wanted[2] -and $b[$i+3] -eq $wanted[3] -and
            $b[$i+4] -eq $wanted[4] -and $b[$i+5] -eq $wanted[5] -and
            $b[$i+6] -eq $wanted[6] -and $b[$i+7] -eq $wanted[7]) {
            Write-Host ("    note      : header found {0} bytes in, realigning" -f $i)
            $rest = New-Object byte[] ($b.Length - $i)
            [Array]::Copy($b, $i, $rest, 0, $rest.Length)
            $b = $rest
            $magic = 'SWEETLOG'
            break
        }
    }
}
if ($magic -ne 'SWEETLOG') {
    $hex = ($b[0..15] | ForEach-Object { $_.ToString('X2') }) -join ' '
    Write-Host "[X] no SWEETLOG header (first 16 bytes: $hex)"
    Write-Host '    The kernel never wrote the log area.'
    exit 3
}

$version = [BitConverter]::ToUInt32($b, 8)
$size    = [BitConverter]::ToUInt32($b, 12)
$total   = [BitConverter]::ToUInt64($b, 16)
$seq     = [BitConverter]::ToUInt64($b, 24)

Write-Host ("    header    : version {0}, ring {1} bytes, total {2} bytes, flush #{3}" -f $version, $size, $total, $seq)

if ($size -eq 0 -or ($size % 4096) -ne 0) {
    Write-Host "[X] ring size $size is not usable"
    exit 4
}

# A dump that was captured a little late is short by that much at the end.
# Pad with zeros rather than refusing: the useful bytes are the ones before the
# cut, and the ring index still points at the right offsets.
if ((4096 + $size) -gt $b.Length) {
    $need = (4096 + $size) - $b.Length
    Write-Host ("    note      : dump is {0} bytes short of a full ring, padding" -f $need)
    $padded = New-Object byte[] (4096 + $size)
    [Array]::Copy($b, 0, $padded, 0, $b.Length)
    $b = $padded
}
if ($total -eq 0) {
    Write-Host '[X] header is valid but zero bytes were logged'
    exit 5
}

$ring = New-Object byte[] $size
[Array]::Copy($b, 4096, $ring, 0, $size)

if ($total -le $size) {
    $len = [int]$total
    $text = New-Object byte[] $len
    [Array]::Copy($ring, 0, $text, 0, $len)
    $wrapped = $false
} else {
    $start = [int]($total % [uint64]$size)
    $len = $size
    $text = New-Object byte[] $len
    [Array]::Copy($ring, $start, $text, 0, $size - $start)
    if ($start -gt 0) {
        [Array]::Copy($ring, 0, $text, $size - $start, $start)
    }
    $wrapped = $true
}

[IO.File]::WriteAllBytes($OutputFile, $text)

Write-Host "    decoded   : $OutputFile ($($text.Length) bytes)"
if ($wrapped) {
    Write-Host '    note      : ring wrapped, the oldest bytes are gone'
}

# Show the tail, which is where the reason for a death usually is.
$s = [Text.Encoding]::UTF8.GetString($text)
$lines = $s -split "`r?`n"
Write-Host ''
Write-Host '    ---------- last 40 lines ----------'
$tail = $lines | Select-Object -Last 40
foreach ($l in $tail) { Write-Host "    $l" }
Write-Host '    ------------------------------------'

exit 0
