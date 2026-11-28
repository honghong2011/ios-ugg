# run-this.ps1 -- one command to answer: is the block the phone complains about
# actually present in the sparse image we flashed, or does fastboot skip it?
#
#   powershell -ExecutionPolicy Bypass -File run-this.ps1 E:\ios-ugg\img\work\ios16-root.simg

param([Parameter(Mandatory=$true, Position=0)][string]$Image)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Image)) { Write-Host "no such file: $Image"; exit 2 }

$fs = [System.IO.File]::OpenRead($Image)
$br = New-Object System.IO.BinaryReader($fs)

$magic = $br.ReadUInt32()
Write-Host ("file   : {0}" -f $Image)
Write-Host ("magic  : 0x{0:X8}" -f $magic)
# 0xED26FF3A as a PowerShell literal is Int32 (-316218726); ReadUInt32 returns
# UInt32 (3978755898). Comparing them is always false, which is how the first
# version reported 'NOT a sparse image' for a perfectly valid file.
if ($magic -ne [uint32]3978755898) { Write-Host "NOT a sparse image"; $fs.Close(); exit 1 }

$major=$br.ReadUInt16(); $minor=$br.ReadUInt16()
$fhsz =$br.ReadUInt16(); $chsz =$br.ReadUInt16()
$blkSz=$br.ReadUInt32(); $totalBlks=$br.ReadUInt32()
$totalChunks=$br.ReadUInt32(); $csum=$br.ReadUInt32()

Write-Host ("block  : {0} bytes" -f $blkSz)
Write-Host ("blocks : {0} ({1:N2} GiB expanded)" -f $totalBlks, ($totalBlks*$blkSz/1GB))
Write-Host ("chunks : {0}" -f $totalChunks)
Write-Host ""

$counts = @{ 0xCAC1=0; 0xCAC2=0; 0xCAC3=0; 0xCAC4=0 }
$dontCareBlocks = 0
$runs = New-Object System.Collections.ArrayList

$fs.Position = $fhsz
$cur = [int64]0
for ($i = 0; $i -lt $totalChunks; $i++) {
    $base = $fs.Position
    $ct = $br.ReadUInt16(); $res = $br.ReadUInt16()
    $csz = $br.ReadUInt32(); $tsz = $br.ReadUInt32()
    $dblks = [int64]($tsz / $blkSz)
    if ($counts.ContainsKey([int]$ct)) { $counts[[int]$ct] += $dblks }
    if ($ct -eq 0xCAC3) {
        $dontCareBlocks += $dblks
        [void]$runs.Add([pscustomobject]@{ Start=$cur; Len=$dblks; End=$cur+$dblks })
    }
    $cur += $dblks
    $fs.Position = $base + $csz
}
$fs.Close()

Write-Host "chunk summary:"
Write-Host ("  RAW       {0,10:N0} blocks = {1,8:N1} MiB" -f $counts[0xCAC1], ($counts[0xCAC1]*$blkSz/1MB))
Write-Host ("  FILL      {0,10:N0} blocks = {1,8:N1} MiB" -f $counts[0xCAC2], ($counts[0xCAC2]*$blkSz/1MB))
Write-Host ("  DONT_CARE {0,10:N0} blocks = {1,8:N1} MiB" -f $counts[0xCAC3], ($counts[0xCAC3]*$blkSz/1MB))
Write-Host ""

# The phone's catalogue extent 3 sits at 4K block 1729287 (byte 7,083,159,552).
$probeBytes = [int64]1729287 * 4096
$probeBlk   = [int64]($probeBytes / $blkSz)
Write-Host ("catalog ext3 starts at 4K block 1729287 = byte {0:N0} = sparse block {1:N0}" -f $probeBytes, $probeBlk)

$hit = $runs | Where-Object { $probeBlk -ge $_.Start -and $probeBlk -lt $_.End }
if ($hit) {
    Write-Host ""
    Write-Host "*** THAT BLOCK IS INSIDE A DONT_CARE RUN ***" -ForegroundColor Red
    Write-Host ("    run covers sparse blocks {0:N0}..{1:N0} ({2:N1} MiB)" -f $hit.Start, ($hit.End-1), ($hit.Len*$blkSz/1MB))
    Write-Host "    fastboot SKIPS DONT_CARE, so this part of the card keeps old data."
    Write-Host "    That is why the phone reads garbage where the image has a good node."
    Write-Host ""
    Write-Host "    FIX: flash as raw, or erase the partition first."
} else {
    Write-Host ""
    Write-Host "That block is NOT in a DONT_CARE run -- so it was written." -ForegroundColor Green
    Write-Host "The DONT_CARE theory is dead; the fault is elsewhere."
}

Write-Host ""
if ($runs.Count -gt 0) {
    Write-Host ("{0} DONT_CARE run(s); largest 8:" -f $runs.Count)
    $runs | Sort-Object Len -Descending | Select-Object -First 8 | ForEach-Object {
        Write-Host ("  sparse blocks {0,10:N0} .. {1,10:N0}  = {2,8:N1} MiB" -f $_.Start, ($_.End-1), ($_.Len*$blkSz/1MB))
    }
}
