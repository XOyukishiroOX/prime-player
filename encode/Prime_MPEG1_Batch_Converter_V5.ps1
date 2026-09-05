param(
    [Parameter(Position=0, ValueFromRemainingArguments=$true)]
    [string[]]$InputFiles,

    [ValidateSet("Auto", "CUDA", "CPU")]
    [string]$DecodeMode = "Auto"
)

$Host.UI.RawUI.WindowTitle = "HP Prime MPEG-1 批量转换器 V5"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "========================================"
Write-Host "      HP Prime MPEG-1 批量转换器 V5"
Write-Host "========================================"
Write-Host "支持：一次选择 / 拖入多个视频文件"
Write-Host "输出：保持源宽高比 / 最大 320×240 / MPEG-1 / .m1v"
Write-Host "缩放：Spline + gblur sigma=0.3 / SAR=1:1"
Write-Host "编码：RD / Trellis 2 / mv0 + skip_rd / 无 B 帧"
Write-Host "帧率：逐文件自动匹配 MPEG-1 标准帧率"
Write-Host "GOP：逐文件按输出帧率约 2 秒动态设置（48 / 50 / 60）"
Write-Host "解码：可选 NVIDIA CUDA；MPEG-1 编码与滤镜仍由 CPU 执行"
Write-Host "不添加黑边"
Write-Host ""

# -------------------------
# 检查 FFmpeg / FFprobe
# -------------------------
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
$ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue

if (-not $ffmpeg) {
    Write-Host "错误：没有找到 ffmpeg。" -ForegroundColor Red
    Write-Host "请先安装 FFmpeg，并确保 ffmpeg.exe 已加入 PATH。"
    Read-Host "按 Enter 退出"
    exit 1
}

if (-not $ffprobe) {
    Write-Host "错误：没有找到 ffprobe。" -ForegroundColor Red
    Write-Host "完整 FFmpeg 安装通常会同时包含 ffprobe.exe。"
    Read-Host "按 Enter 退出"
    exit 1
}

# -------------------------
# 检查并选择解码路径
# -------------------------
function Test-CudaDecodeAvailable {
    $hardwareLines = @(& $ffmpeg.Source -hide_banner -hwaccels 2>&1)
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    $compiledWithCuda = $false
    foreach ($line in $hardwareLines) {
        if ($line.ToString().Trim() -eq "cuda") {
            $compiledWithCuda = $true
            break
        }
    }
    if (-not $compiledWithCuda) {
        return $false
    }

    & $ffmpeg.Source `
        -hide_banner `
        -loglevel error `
        -init_hw_device "cuda=primecheck:0" `
        -f lavfi `
        -i "color=size=16x16:rate=1" `
        -frames:v 1 `
        -f null `
        - 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

$cudaAvailable = Test-CudaDecodeAvailable

if ($DecodeMode -eq "Auto") {
    if ($cudaAvailable) {
        Write-Host ""
        Write-Host "检测到可初始化的 NVIDIA CUDA 解码设备。" -ForegroundColor Cyan
        Write-Host "  1. CUDA 硬件解码（推荐）"
        Write-Host "  2. CPU 软件解码"
        do {
            $decodeChoice = Read-Host "请输入 1 / 2"
        } while ($decodeChoice -notin @("1", "2"))
        $DecodeMode = if ($decodeChoice -eq "1") { "CUDA" } else { "CPU" }
    }
    else {
        $DecodeMode = "CPU"
        Write-Host "未检测到可初始化的 NVIDIA CUDA 解码设备，将使用 CPU 解码。" -ForegroundColor Yellow
    }
}
elseif ($DecodeMode -eq "CUDA" -and -not $cudaAvailable) {
    Write-Host "错误：已指定 CUDA，但 FFmpeg 无法初始化 NVIDIA CUDA 解码设备。" -ForegroundColor Red
    Write-Host "请检查 NVIDIA 驱动和 FFmpeg 构建，或使用 -DecodeMode CPU。"
    Read-Host "按 Enter 退出"
    exit 1
}

$decodeArgs = @()
if ($DecodeMode -eq "CUDA") {
    $decodeArgs = @("-hwaccel", "cuda")
}
Write-Host ("解码路径：{0}" -f $DecodeMode) -ForegroundColor Cyan

# -------------------------
# 若没有拖入文件，弹出多选文件框
# -------------------------
if (-not $InputFiles -or $InputFiles.Count -eq 0) {
    try {
        Add-Type -AssemblyName System.Windows.Forms

        $dialog = New-Object System.Windows.Forms.OpenFileDialog
        $dialog.Title = "选择一个或多个需要转换的视频文件"
        $dialog.Multiselect = $true
        $dialog.CheckFileExists = $true
        $dialog.Filter = "视频文件|*.mp4;*.mkv;*.mov;*.avi;*.webm;*.m4v;*.ts;*.m2ts;*.flv;*.wmv;*.mpg;*.mpeg|所有文件|*.*"

        $result = $dialog.ShowDialog()
        if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
            Write-Host "未选择文件。"
            exit 0
        }

        $InputFiles = @($dialog.FileNames)
    }
    catch {
        Write-Host "无法打开文件选择窗口：" -ForegroundColor Red
        Write-Host $_.Exception.Message
        Read-Host "按 Enter 退出"
        exit 1
    }
}

# -------------------------
# 清理并校验输入文件列表
# -------------------------
$validFiles = New-Object System.Collections.Generic.List[string]

foreach ($file in $InputFiles) {
    if ([string]::IsNullOrWhiteSpace($file)) {
        continue
    }

    $clean = $file.Trim().Trim('"').Trim("'")

    if (-not (Test-Path -LiteralPath $clean -PathType Leaf)) {
        Write-Host "错误：文件不存在：" -ForegroundColor Red
        Write-Host $clean
        Read-Host "按 Enter 退出"
        exit 1
    }

    $resolved = (Resolve-Path -LiteralPath $clean).Path
    $validFiles.Add($resolved)
}

if ($validFiles.Count -eq 0) {
    Write-Host "没有有效输入文件。" -ForegroundColor Red
    Read-Host "按 Enter 退出"
    exit 1
}

Write-Host ""
Write-Host ("已选择 {0} 个文件：" -f $validFiles.Count) -ForegroundColor Cyan
for ($i = 0; $i -lt $validFiles.Count; $i++) {
    Write-Host ("  [{0}/{1}] {2}" -f ($i + 1), $validFiles.Count, $validFiles[$i])
}

# -------------------------
# 质量选择：一次选择，应用于全部文件
# -------------------------
Write-Host ""
Write-Host "选择质量（应用于全部文件）："
Write-Host "  1. 极低   q=20"
Write-Host "  2. 低     q=14"
Write-Host "  3. 中     q=10  推荐"
Write-Host "  4. 高     q=6"
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

# -------------------------
# 时长：一次选择，应用于全部文件
# -------------------------
Write-Host ""
do {
    $durationText = Read-Host "每个文件转换时长（分钟；0 = 全部转换，可输入 0.5 等小数）"
    $minutes = 0.0
    $durationOK = [double]::TryParse(
        $durationText,
        [System.Globalization.NumberStyles]::Float,
        [System.Globalization.CultureInfo]::CurrentCulture,
        [ref]$minutes
    ) -and $minutes -ge 0

    if (-not $durationOK) {
        Write-Host "请输入大于等于 0 的数字。" -ForegroundColor Yellow
    }
} while (-not $durationOK)

# -------------------------
# FPS 工具函数
# -------------------------
function Convert-FpsFractionToDouble([string]$value) {
    if ([string]::IsNullOrWhiteSpace($value)) {
        return 0.0
    }

    if ($value -match '^([0-9.]+)/([0-9.]+)$') {
        $num = [double]$Matches[1]
        $den = [double]$Matches[2]
        if ($den -ne 0) {
            return $num / $den
        }
        return 0.0
    }

    $result = 0.0
    if ([double]::TryParse(
        $value,
        [System.Globalization.NumberStyles]::Float,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [ref]$result
    )) {
        return $result
    }

    return 0.0
}

function Get-SourceFpsInfo([string]$FilePath) {
    $fpsRaw = (& $ffprobe.Source `
        -v error `
        -select_streams v:0 `
        -show_entries stream=avg_frame_rate `
        -of default=noprint_wrappers=1:nokey=1 `
        -- "$FilePath" 2>$null | Select-Object -First 1)

    if ($null -ne $fpsRaw) {
        $fpsRaw = $fpsRaw.Trim()
    }

    if ([string]::IsNullOrWhiteSpace($fpsRaw) -or $fpsRaw -eq "0/0") {
        $fpsRaw = (& $ffprobe.Source `
            -v error `
            -select_streams v:0 `
            -show_entries stream=r_frame_rate `
            -of default=noprint_wrappers=1:nokey=1 `
            -- "$FilePath" 2>$null | Select-Object -First 1)

        if ($null -ne $fpsRaw) {
            $fpsRaw = $fpsRaw.Trim()
        }
    }

    $sourceFps = Convert-FpsFractionToDouble $fpsRaw

    if ($sourceFps -le 0) {
        throw "ffprobe 无法取得有效视频帧率。"
    }

    return [PSCustomObject]@{
        Raw = $fpsRaw
        Numeric = $sourceFps
    }
}

function Get-OutputFpsInfo([double]$sourceFps) {
    $fpsExpr = "25"
    $fpsDisplay = "25"
    $outputFpsNumeric = 25.0
    $fpsMode = "非指定标准帧率，转换为 25 FPS"

    if ([Math]::Abs($sourceFps - (24000.0 / 1001.0)) -lt 0.05) {
        $fpsExpr = "24000/1001"
        $fpsDisplay = "23.976"
        $outputFpsNumeric = 24000.0 / 1001.0
        $fpsMode = "保持源帧率"
    }
    elseif ([Math]::Abs($sourceFps - 24.0) -lt 0.01) {
        $fpsExpr = "24"
        $fpsDisplay = "24"
        $outputFpsNumeric = 24.0
        $fpsMode = "保持源帧率"
    }
    elseif ([Math]::Abs($sourceFps - 25.0) -lt 0.01) {
        $fpsExpr = "25"
        $fpsDisplay = "25"
        $outputFpsNumeric = 25.0
        $fpsMode = "保持源帧率"
    }
    elseif ([Math]::Abs($sourceFps - (30000.0 / 1001.0)) -lt 0.05) {
        $fpsExpr = "30000/1001"
        $fpsDisplay = "29.970"
        $outputFpsNumeric = 30000.0 / 1001.0
        $fpsMode = "保持源帧率"
    }
    elseif ([Math]::Abs($sourceFps - 30.0) -lt 0.01) {
        $fpsExpr = "30"
        $fpsDisplay = "30"
        $outputFpsNumeric = 30.0
        $fpsMode = "保持源帧率"
    }
    elseif ([Math]::Abs($sourceFps - 50.0) -lt 0.05) {
        $fpsExpr = "25"
        $fpsDisplay = "25"
        $outputFpsNumeric = 25.0
        $fpsMode = "50 FPS / 2"
    }
    elseif (($sourceFps -ge 59.85) -and ($sourceFps -lt 59.99)) {
        $fpsExpr = "30000/1001"
        $fpsDisplay = "29.970"
        $outputFpsNumeric = 30000.0 / 1001.0
        $fpsMode = "59.94/59.97 FPS / 2"
    }
    elseif ([Math]::Abs($sourceFps - 60.0) -lt 0.05) {
        $fpsExpr = "30"
        $fpsDisplay = "30"
        $outputFpsNumeric = 30.0
        $fpsMode = "60 FPS / 2"
    }

    $gop = [int][Math]::Round($outputFpsNumeric * 2.0)

    return [PSCustomObject]@{
        Expr = $fpsExpr
        Display = $fpsDisplay
        Numeric = $outputFpsNumeric
        Mode = $fpsMode
        Gop = $gop
    }
}

# -------------------------
# 输出时长标签
# -------------------------
$durationTag = if ($minutes -eq 0) {
    "full"
} else {
    ($minutes.ToString("0.##", [System.Globalization.CultureInfo]::InvariantCulture) + "min")
}

$durationSeconds = $null
if ($minutes -gt 0) {
    $durationSeconds = [Math]::Round($minutes * 60, 3)
}

# -------------------------
# 批量转换
# -------------------------
$successCount = 0
$failedCount = 0
$failedFiles = New-Object System.Collections.Generic.List[string]
$totalCount = $validFiles.Count

Write-Host ""
Write-Host "========================================"
Write-Host "开始批量转换"
Write-Host "========================================"

for ($index = 0; $index -lt $totalCount; $index++) {
    $InputFile = $validFiles[$index]
    $source = Get-Item -LiteralPath $InputFile

    Write-Host ""
    Write-Host "============================================================"
    Write-Host ("[{0}/{1}] {2}" -f ($index + 1), $totalCount, $source.Name) -ForegroundColor Cyan
    Write-Host "============================================================"

    try {
        $sourceFpsInfo = Get-SourceFpsInfo $InputFile
        $outputFpsInfo = Get-OutputFpsInfo $sourceFpsInfo.Numeric
    }
    catch {
        Write-Host "跳过：无法正确读取视频帧率。" -ForegroundColor Red
        Write-Host $_.Exception.Message
        $failedCount++
        $failedFiles.Add($InputFile)
        continue
    }

    # 输出文件名
    $outputName = "{0}_Prime_{1}_{2}.m1v" -f $source.BaseName, $qualityName, $durationTag
    $outputPath = Join-Path $source.DirectoryName $outputName

    if (Test-Path -LiteralPath $outputPath) {
        $n = 1
        do {
            $outputName = "{0}_Prime_{1}_{2}_{3}.m1v" -f $source.BaseName, $qualityName, $durationTag, $n
            $outputPath = Join-Path $source.DirectoryName $outputName
            $n++
        } while (Test-Path -LiteralPath $outputPath)
    }

    # FPS 先执行，再缩放和低通。
    # 最大 320×240，保持宽高比、不加黑边、SAR=1:1。
    $filter = "fps=$($outputFpsInfo.Expr),scale='min(320,iw)':'min(240,ih)':flags=spline:force_original_aspect_ratio=decrease:force_divisible_by=2:reset_sar=1,gblur=sigma=0.3"

    $ffArgs = @(
        "-hide_banner",
        "-nostdin"
    )
    $ffArgs += $decodeArgs
    $ffArgs += @("-i", $InputFile)

    if ($null -ne $durationSeconds) {
        $ffArgs += @(
            "-t",
            $durationSeconds.ToString([System.Globalization.CultureInfo]::InvariantCulture)
        )
    }

    $ffArgs += @(
        "-map", "0:v:0",
        "-vf", $filter,
        "-c:v", "mpeg1video",
        "-pix_fmt", "yuv420p",
        "-bf", "0",
        "-mbd", "rd",
        "-trellis", "2",
        "-mpv_flags", "+mv0+skip_rd",
        "-g", $outputFpsInfo.Gop.ToString(),
        "-sc_threshold", "0",
        "-q:v", $q.ToString(),
        "-an",
        "-sn",
        "-dn",
        "-f", "mpeg1video",
        $outputPath
    )

    Write-Host ("源帧率：{0} ({1:N3} FPS)" -f $sourceFpsInfo.Raw, $sourceFpsInfo.Numeric)
    Write-Host ("输出帧率：{0} FPS ({1})" -f $outputFpsInfo.Display, $outputFpsInfo.Mode)
    Write-Host ("GOP：{0} 帧（约 2 秒）" -f $outputFpsInfo.Gop)
    Write-Host ("质量：{0} (q={1})" -f $qualityName, $q)
    if ($minutes -eq 0) {
        Write-Host "时长：全部"
    } else {
        Write-Host ("时长：{0} 分钟" -f $minutes)
    }
    Write-Host ("输出：{0}" -f $outputPath)
    Write-Host ""

    & $ffmpeg.Source @ffArgs

    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host ("[{0}/{1}] 转换完成。" -f ($index + 1), $totalCount) -ForegroundColor Green
        $successCount++
    }
    else {
        Write-Host ""
        Write-Host ("[{0}/{1}] 转换失败，FFmpeg 退出代码：{2}" -f ($index + 1), $totalCount, $LASTEXITCODE) -ForegroundColor Red
        if ($DecodeMode -eq "CUDA") {
            Write-Host "CUDA 解码失败；本脚本不会静默改用 CPU 重试。可用 -DecodeMode CPU 重新运行。" -ForegroundColor Yellow
        }
        $failedCount++
        $failedFiles.Add($InputFile)
    }
}

# -------------------------
# 汇总
# -------------------------
Write-Host ""
Write-Host "========================================"
Write-Host "批量转换结束"
Write-Host "========================================"
Write-Host ("总文件数：{0}" -f $totalCount)
Write-Host ("成功：{0}" -f $successCount) -ForegroundColor Green

if ($failedCount -gt 0) {
    Write-Host ("失败：{0}" -f $failedCount) -ForegroundColor Red
    Write-Host ""
    Write-Host "失败文件："
    foreach ($failed in $failedFiles) {
        Write-Host ("  {0}" -f $failed) -ForegroundColor Red
    }
} else {
    Write-Host "失败：0"
}

Write-Host ""
Read-Host "按 Enter 退出"
if ($failedCount -gt 0) {
    exit 1
}
exit 0
