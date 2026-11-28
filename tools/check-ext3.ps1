# check-ext3.ps1 -- read one block straight out of an Android sparse image and
# decide whether it is a b-tree node.
#
# Why this exists: the phone reports bad fLink values for catalog nodes that live
# in the image's third extent, while check-hfs-root says that same block is a
# perfectly good node. Reading the block from the file the user actually flashed
# settles whether the file or the card is at fault, without flashing anything.
#
#   .\check-ext3.ps1 ..\work\ios16-root.simg
#   .\check-ext3.ps1 ..\work\ios16-root.simg -Block 1729287

param(
    [Parameter(Mandatory=$true, Position=0)][string]$Image,
    [int]$Block = 1729287,
    [int]$BlockSize = 4096
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Image)) { Write-Host "no such file: $Image"; exit 2 }

$fs = [System.IO.File]::OpenRead($Image)
$br = New-Object System.IO.BinaryReader($fs)

# --- sparse header ---
$magic = $br.ReadUInt32()
if ($magic -ne 0xED26FF3A) {
    Write-Host ("not a sparse image (magic 0x{0:X8}); treating as raw" -f $magic)
    $fs.Position = [int64]$Block * $BlockSize
    $raw = $br.ReadBytes($BlockSize)
} else {
    $major=$br.ReadUInt16(); $minor=$br.ReadUInt16()
    $fhsz=$br.ReadUInt16();  $chsz=$br.ReadUInt16()
    $blkSz=$br.ReadUInt32(); $totalBlks=$br.ReadUInt32()
    $totalChunks=$br.ReadUInt32(); $csum=$br.ReadUInt32()
    Write-Host ("sparse: block {0} B, {1} blocks ({2:N1} MiB), {3} chunks" -f $blkSz, $totalBlks, ($totalBlks*$blkSz/1MB), $totalChunks)

    # We want the 4K block $Block, i.e. byte offset $Block*4096 of the expanded image.
    $wantByte  = [int64]$Block * $BlockSize
    $wantChunk = [int64][math]::Floor($wantByte / $blkSz)   # sparse block index

    $fs.Position = $fhsz
    $cur = [int64]0
    $raw = $null
    for ($i = 0; $i -lt $totalChunks; $i++) {
        $ct  = $br.ReadUInt16(); $res = $br.ReadUInt16()
        $csz = $br.ReadUInt32(); $tsz = $br.ReadUInt32()
        # total_sz is a BYTE count, not a block count ({0} blocks = blkSz bytes each). The first
        # version of this line divided by chunk_sz and produced nonsense block counts.
        $dataBlks = [int64]($tsz / $blkSz)
        if ($wantChunk -ge $cur -and $wantChunk -lt ($cur + $dataBlks)) {
            $delta = $wantChunk - $cur
            switch ($ct) {
                0xCAC1 {   # RAW
                    $fs.Position = $fs.Position - 12 + $delta * $blkSz
                    $raw = $br.ReadBytes($BlockSize)
                    Write-Host ("found in RAW chunk #{0} (block offset {1})" -f $i, $delta)
                }
                0xCAC2 {   # FILL
                    Write-Host ("found in FILL chunk #{0} -- this block is a constant pattern, not data" -f $i)
                    $raw = New-Object byte[] $BlockSize
                }
                0xCAC3 {
                    Write-Host ("found in DONT_CARE chunk #{0} -- fastboot SKIPS this, the card keeps old data" -f $i)
                    $raw = New-Object byte[] $BlockSize
                }
                default {
                    Write-Host ("found in chunk type 0x{0:X4}" -f $ct)
                    $raw = New-Object byte[] $BlockSize
                }
            }
            break
        }
        $cur += $dataBlks
        $fs.Position = $fs.Position - 12 + $csz
    }
    if ($null -eq $raw) { Write-Host "block not covered by any chunk"; $fs.Close(); exit 1 }
}

$fs.Close()

# --- interpret as an HFS+ b-tree node descriptor ---
$fLink = ($raw[0] -shl 24) -bor ($raw[1] -shl 16) -bor ($raw[2] -shl 8) -bor $raw[3]
$kind  = $raw[8]
$nrec  = ($raw[10] -shl 8) -bor $raw[11]

Write-Host ""
Write-Host ("first 16 bytes : {0}" -f (($raw[0..15] | ForEach-Object { $_.ToString('x2') }) -join ' '))
Write-Host ("fLink          : 0x{0:X8}" -f [uint32]$fLink)
Write-Host ("kind           : 0x{0:X2}  ({1})" -f $kind, $(switch ($kind) { 0 {'index'} 1 {'header'} 2 {'map'} 0xFF {'leaf'} default {'?'} }))
Write-Host ("numRecords     : {0}" -f $nrec)
Write-Host ""
if ($kind -eq 0xFF -or $kind -eq 0x00 -or $kind -eq 0x01) {
    Write-Host "=> looks like a real b-tree node" -ForegroundColor Green
} else {
    Write-Host "=> NOT a b-tree node: this block holds something else" -ForegroundColor Red
}
