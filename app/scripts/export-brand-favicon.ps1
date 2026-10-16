$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$publicDir = Join-Path $PSScriptRoot '../public'
$brandDir = Join-Path $publicDir 'images/brand'

# Browser-format exports of the approved logo; do not change the source artwork.
function Export-PngFrame($source, $bounds, [int]$side) {
    $bitmap = [System.Drawing.Bitmap]::new($side, $side, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $stream = [System.IO.MemoryStream]::new()
    try {
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $scale = $side / [Math]::Max($bounds.Width, $bounds.Height)
        $width = $bounds.Width * $scale
        $height = $bounds.Height * $scale
        $target = [System.Drawing.RectangleF]::new(($side - $width) / 2, ($side - $height) / 2, $width, $height)
        $graphics.DrawImage($source, $target, $bounds, [System.Drawing.GraphicsUnit]::Pixel)
        $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        return ,$stream.ToArray()
    } finally {
        $stream.Dispose(); $graphics.Dispose(); $bitmap.Dispose()
    }
}

$day = [System.Drawing.Bitmap]::new((Join-Path $brandDir 'noise-lab-logo.png'))
$night = [System.Drawing.Bitmap]::new((Join-Path $brandDir 'noise-lab-logo-night.png'))
try {
    # Retain each image's nontransparent bounding box, measured from approved PNGs.
    $dayBounds = [System.Drawing.RectangleF]::FromLTRB(174, 108, 1537, 827)
    $nightBounds = [System.Drawing.RectangleF]::FromLTRB(174, 120, 1579, 831)
    [System.IO.File]::WriteAllBytes((Join-Path $brandDir 'favicon-32.png'), (Export-PngFrame $day $dayBounds 32))
    [System.IO.File]::WriteAllBytes((Join-Path $brandDir 'favicon-night-32.png'), (Export-PngFrame $night $nightBounds 32))
    $sizes = @(16, 32, 48, 64, 128, 256)
    $frames = foreach ($side in $sizes) { ,(Export-PngFrame $day $dayBounds $side) }
    $stream = [System.IO.MemoryStream]::new()
    $writer = [System.IO.BinaryWriter]::new($stream)
    try {
        $writer.Write([UInt16]0); $writer.Write([UInt16]1); $writer.Write([UInt16]$sizes.Count)
        $offset = 6 + 16 * $sizes.Count
        for ($i = 0; $i -lt $sizes.Count; $i++) {
            $dimension = if ($sizes[$i] -eq 256) { 0 } else { $sizes[$i] }
            $writer.Write([byte]$dimension); $writer.Write([byte]$dimension)
            $writer.Write([byte]0); $writer.Write([byte]0)
            $writer.Write([UInt16]1); $writer.Write([UInt16]32)
            $writer.Write([UInt32]$frames[$i].Length); $writer.Write([UInt32]$offset)
            $offset += $frames[$i].Length
        }
        foreach ($frame in $frames) { $writer.Write([byte[]]$frame) }
        [System.IO.File]::WriteAllBytes((Join-Path $publicDir 'favicon.ico'), $stream.ToArray())
    } finally { $writer.Dispose(); $stream.Dispose() }
} finally { $day.Dispose(); $night.Dispose() }
Write-Output 'Exported square day/night PNGs and multi-resolution ICO from existing logo.'
