Prime MPEG-1 Batch Converter V5
================================

用途
----
把常见视频批量转换为 PrimeVideoPlayer 1.1.0 可直接播放的 MPEG-1
视频基本流（.m1v）。输出保持源宽高比，不加黑边，最大 320x240，偶数尺寸，
无音频、字幕和数据流。

使用
----
1. 双击 Prime_MPEG1_Batch_Converter_V5.cmd 后多选视频；或把多个视频文件
   拖到该 CMD 上。
2. 检测到可初始化的 NVIDIA CUDA 设备时，选择 CUDA 或 CPU 解码。
3. 选择质量和转换时长。

也可从 PowerShell 明确指定解码路径：

  powershell.exe -ExecutionPolicy Bypass -File .\Prime_MPEG1_Batch_Converter_V5.ps1 -DecodeMode CUDA video.mp4
  powershell.exe -ExecutionPolicy Bypass -File .\Prime_MPEG1_Batch_Converter_V5.ps1 -DecodeMode CPU video.mp4

CUDA 只负责源视频硬件解码；缩放、模糊和 MPEG-1 编码仍由 CPU 完成。
CUDA 解码某个输入失败时脚本会明确标记失败，不会静默改用 CPU 重试。

帧率规则
--------
- 24000/1001、24、25、30000/1001、30：保持。
- 50 -> 25。
- 59.94/59.97 -> 30000/1001。
- 60 -> 30。
- 其他帧率 -> 25。

要求
----
- Windows PowerShell 5.1 或更高版本。
- PATH 中可找到 ffmpeg.exe 和 ffprobe.exe。
- CUDA 模式需要 NVIDIA 显卡、可用驱动以及包含 CUDA 支持的 FFmpeg 构建。
