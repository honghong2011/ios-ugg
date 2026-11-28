# run-this.ps1 -- does fastboot actually write the blocks the phone complains about?
#
# Reads the Android sparse chunk table and reports, for the 4K block where this
# image's catalog extent 3 lives, whether that block is covered by RAW data (so it
# gets written) or by DONT_CARE/FILL (which fastboot skips or fills with zeros).
#
#   powershell -ExecutionPolicy Bypass -File run-this.ps1 ..\work\ios16-root.simg
#
# The whole file is walked strictly sequentially through one BinaryReader. An
# earlier version mixed $fs.Position with $br.ReadUInt16(), and because a
# BinaryReader buffers, every chunk after the first was read from the wrong place:
# it reported 27642 chunks covering a single block.

param(
    [Parameter(Mandatory=$true, Position=0)][string]$Image,
    [int]$ProbeBlock4K = 1729287
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Image)) { Write-Host "no such file: $Image"; exit 2 }

$size = (Get-Item -LiteralPath $Image).Length
$fs = [System.IO.File]::OpenRead($Image)
$br = New-Object System.IO.BinaryReader($fs)

# 0xED26FF3A as a PowerShell literal is Int32 (negative); ReadUInt32 gives UInt32.
$SPARSE_MAGIC = [uint32]3978755898
$magic = $br.ReadUInt32()
Write-Host ("file   : {0} ({1:N0} bytes)" -f $Image, $size)
Write-Host ("magic  : 0x{0:X8}" -f $magic)
if ($magic -ne $SPARSE_MAGIC) { Write-Host "NOT a sparse image"; $br.Dispose(); $fs.Dispose(); exit 1 }

$major       = $br.ReadUInt16()
$minor       = $br.ReadUInt16()
$fhsz        = $br.ReadUInt16()
$chsz        = $br.ReadUInt16()
$blkSz       = $br.ReadUInt32()
$totalBlks   = $br.ReadUInt32()
$totalChunks = $br.ReadUInt32()
$csum        = $br.ReadUInt32()

Write-Host ("block  : {0} bytes" -f $blkSz)
Write-Host ("blocks : {0:N0} ({1:N2} GiB expanded)" -f $totalBlks, ($totalBlks * $blkSz / 1GB))
Write-Host ("chunks : {0:N0}" -f $totalChunks)

# Skip the rest of the header (should be none for fhsz=28).
if ($fhsz -gt 28) { [void]$br.ReadBytes($fhsz - 28) }

$RAW = 0xCAC1; $FILL = 0xCAC2; $DONTCARE = 0xCAC3; $CRC = 0xCAC4

$rawBlks = [int64]0; $fillBlks = [int64]0; $dcBlks = [int64]0; $crcCnt = [int64]0
$runs = New-Object System.Collections.ArrayList
$cur = [int64]0
$probeChunk = -1; $probeKind = 'not covered'

for ($i = 0; $i -lt $totalChunks; $i++) {
    if (($i % 5000) -eq 0 -and $i -gt 0) { Write-Host ("  ... chunk {0:N0}" -f $i) }

    $ct  = $br.ReadUInt16()
    $res = $br.ReadUInt16()
    $csz = $br.ReadUInt32()      # chunk total size in bytes, header included
    $tsz = $br.ReadUInt32()      # payload size in BYTES
    $dataBytes = [int64]($csz - $chsz)

    switch ($ct) {
        $RAW {
            $blocks = [int64]($tsz / $blkSz)
            $rawBlks += $blocks
            if ($probeChunk -lt 0 -and $cur -le $ProbeBlock4K -and $ProbeBlock4K -lt ($cur + $blocks)) {
                $probeChunk = $i; $probeKind = 'RAW (written)'
            }
            $cur += $blocks
        }
        $FILL {
            $blocks = [int64]($tsz / $blkSz)
            $fillBlks += $blocks
            if ($probeChunk -lt 0 -and $cur -le $ProbeBlock4K -and $ProbeBlock4K -lt ($cur + $blocks)) {
                $probeChunk = $i; $probeKind = 'FILL (constant bytes)'
            }
            $cur += $blocks
        }
        $DONTCARE {
            $blocks = [int64]($tsz / $blkSz)
            $dcBlks += $blocks
            [void]$runs.Add([pscustomobject]@{ Start = $cur; Len = $blocks; End = $cur + $blocks })
            if ($probeChunk -lt 0 -and $cur -le $ProbeBlock4K -and $ProbeBlock4K -lt ($cur + $blocks)) {
                $probeChunk = $i; $probeKind = 'DONT_CARE (fastboot SKIPS this)'
            }
            $cur += $blocks
        }
        $CRC {
            $crcCnt++
        }
        default {
            Write-Host ("  unknown chunk type 0x{0:X4} at #{1}" -f $ct, $i) -ForegroundColor Yellow
        }
    }

    if ($dataBytes -gt 0) { [void]$br.ReadBytes([int]$dataBytes) }
}

$br.Dispose(); $fs.Dispose()

Write-Host ""
Write-Host "chunk summary:"
Write-Host ("  RAW       {0,12:N0} blocks = {1,10:N1} MiB" -f $rawBlks,  ($rawBlks  * $blkSz / 1MB))
Write-Host ("  FILL      {0,12:N0} blocks = {1,10:N1} MiB" -f $fillBlks, ($fillBlks * $blkSz / 1MB))
Write-Host ("  DONT_CARE {0,12:N0} blocks = {1,10:N1} MiB" -f $dcBlks,   ($dcBlks   * $blkSz / 1MB))
Write-Host ("  CRC32     {0,12:N0}" -f $crcCnt)
Write-Host ("  covered   {0,12:N0} blocks  (header says {1:N0})" -f $cur, $totalBlks)
Write-Host ""

if ($cur -ne $totalBlks) {
    Write-Host "WARNING: chunk table covers a different number of blocks than the header claims." -ForegroundColor Yellow
}

Write-Host ("probe: 4K block {0:N0} (byte {1:N0})" -f $ProbeBlock4K, ([int64]$ProbeBlock4K * 4096))
if ($probeChunk -ge 0) {
    Write-Host ("  -> chunk #{0}: {1}" -f $probeChunk, $probeKind)
    if ($probeKind -like 'DONT_CARE*') {
        Write-Host ""
        Write-Host "*** fastboot SKIPS this region: the card keeps whatever was there before. ***" -ForegroundColor Red
        Write-Host "    That is why the phone reads garbage where the image has a good node."
        Write-Host "    FIX: flash the raw .img instead, or erase the partition first."
        exit 1
    } else {
        Write-Host ""
        Write-Host "This block IS written by fastboot, so the DONT_CARE theory is dead." -ForegroundColor Green
    }
} else {
    Write-Host "  -> not covered by any chunk"
}

if ($runs.Count -gt 0) {
    Write-Host ""
    Write-Host ("{0} DONT_CARE run(s); largest 10:" -f $runs.Count)
    $runs | Sort-Object Len -Descending | Select-Object -First 10 | ForEach-Object {
        Write-Host ("  4K blocks {0,10:N0} .. {1,10:N0}  = {2,9:N1} MiB" -f $_.Start, ($_.End - 1), ($_.Len * $blkSz / 1MB))
    }
} else {
    Write-Host ""
    Write-Host "No DONT_CARE chunks at all -- every block is written." -ForegroundColor Green
}
