param(
    [Parameter(Position=0)]
    [string]$InputFile
)

$Host.UI.RawUI.WindowTitle = "HP Prime MPEG-1 转换器"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "========================================"
Write-Host "      HP Prime MPEG-1 视频转换器"
Write-Host "========================================"
Write-Host "输出规格：320×240 / 25 FPS / MPEG-1 / .m1v"
Write-Host "宽高比保持不变；宽屏视频黑边填在下方。"
Write-Host ""

# 检查 FFmpeg
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpeg) {
    Write-Host "错误：没有找到 ffmpeg。" -ForegroundColor Red
    Write-Host "请先安装 FFmpeg，并确保 ffmpeg.exe 已加入 PATH。"
    Read-Host "按 Enter 退出"
    exit 1
}

# 获取输入文件
if ([string]::IsNullOrWhiteSpace($InputFile)) {
    $InputFile = Read-Host "输入视频文件路径（可以把文件直接拖到窗口里）"
}

$InputFile = $InputFile.Trim().Trim('"').Trim("'")

if (-not (Test-Path -LiteralPath $InputFile -PathType Leaf)) {
    Write-Host "错误：文件不存在：" -ForegroundColor Red
    Write-Host $InputFile
    Read-Host "按 Enter 退出"
    exit 1
}

$InputFile = (Resolve-Path -LiteralPath $InputFile).Path

# 质量选择
Write-Host ""
Write-Host "选择质量："
Write-Host "  1. 极低   (q=20，最小文件/最低码率)"
Write-Host "  2. 低     (q=14)"
Write-Host "  3. 中     (q=10，等同于你当前使用的参数)"
Write-Host "  4. 高     (q=6，画质更好)"
Write-Host ""

do {
    $qualityChoice = Read-Host "请输入 1 / 2 / 3 / 4"
} while ($qualityChoice -notin @("1","2","3","4"))

switch ($qualityChoice) {
    "1" { $qualityName = "极低"; $q = 20 }
    "2" { $qualityName = "低";   $q = 14 }
    "3" { $qualityName = "中";   $q = 10 }
    "4" { $qualityName = "高";   $q = 6  }
}

# 时长
Write-Host ""
do {
    $durationText = Read-Host "转换时长（分钟；0 = 全部转换，可输入 0.5 之类的小数）"
    $minutes = 0.0
    $durationOK = [double]::TryParse($durationText, [ref]$minutes) -and $minutes -ge 0
    if (-not $durationOK) {
        Write-Host "请输入大于等于 0 的数字。" -ForegroundColor Yellow
    }
} while (-not $durationOK)

# 输出文件名
$source = Get-Item -LiteralPath $InputFile
$durationTag = if ($minutes -eq 0) {
    "full"
} else {
    ($minutes.ToString("0.##", [System.Globalization.CultureInfo]::InvariantCulture) + "min")
}

$outputName = "{0}_Prime_{1}_{2}.m1v" -f $source.BaseName, $qualityName, $durationTag
$outputPath = Join-Path $source.DirectoryName $outputName

# 如果目标文件已经存在，自动避免覆盖
if (Test-Path -LiteralPath $outputPath) {
    $n = 1
    do {
        $outputName = "{0}_Prime_{1}_{2}_{3}.m1v" -f $source.BaseName, $qualityName, $durationTag, $n
        $outputPath = Join-Path $source.DirectoryName $outputName
        $n++
    } while (Test-Path -LiteralPath $outputPath)
}

# 转码参数
# 对 16:9 输入会得到 320×180 的有效画面，并在下方补 60px 黑边。
# 对其他宽高比也会自动等比缩放到 320×240 内。
$filter = "scale=320:240:flags=lanczos:force_original_aspect_ratio=decrease,pad=320:240:(ow-iw)/2:0:black,fps=25"

$ffArgs = @(
    "-hide_banner",
    "-i", $InputFile
)

if ($minutes -gt 0) {
    $seconds = [Math]::Round($minutes * 60, 3)
    $ffArgs += @("-t", $seconds.ToString([System.Globalization.CultureInfo]::InvariantCulture))
}

$ffArgs += @(
    "-map", "0:v:0",
    "-vf", $filter,
    "-c:v", "mpeg1video",
    "-pix_fmt", "yuv420p",
    "-bf", "0",
    "-g", "5",
    "-q:v", $q.ToString(),
    "-an",
    "-sn",
    "-dn",
    "-f", "mpeg1video",
    $outputPath
)

Write-Host ""
Write-Host "----------------------------------------"
Write-Host "输入：" $InputFile
Write-Host "质量：" $qualityName "(q=$q)"
if ($minutes -eq 0) {
    Write-Host "时长：全部"
} else {
    Write-Host "时长：" $minutes "分钟"
}
Write-Host "输出：" $outputPath
Write-Host "----------------------------------------"
Write-Host ""
Write-Host "开始转换..."
Write-Host ""

& $ffmpeg.Source @ffArgs

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "转换完成。" -ForegroundColor Green
    Write-Host "输出文件："
    Write-Host $outputPath
} else {
    Write-Host ""
    Write-Host "FFmpeg 转换失败，退出代码：$LASTEXITCODE" -ForegroundColor Red
}

Write-Host ""
Read-Host "按 Enter 退出"
