# PrimeVideoPlayer 1.0.0

面向 **HP Prime G1 / 2025-09-15 固件**的离线无声视频播放器。

## 功能

- 播放 320×240、25 FPS 的 MPEG-1 Video elementary stream（`.M1V`）。
- 播放项目的 PVMJ v1 MJPG 容器（`.MJPG`）。
- 支持目录扫描、暂停/继续、前后切换、定位、进度恢复和退出恢复屏幕。
- 使用 Prime 原生 RGB8888 输出，不依赖网络。

## 使用

把视频文件放入：

```text
C:\DATA\PrimeVideoPlayer.hpappdir\
```

在计算器上打开 PrimeVideoPlayer。`ENTER` 暂停或继续，左右切换文件，
上下调整定位，`ESC` 返回或退出。

## 支持边界

本版只支持 HP Prime G1 的 2025-09-15 固件。它不支持 G2、音频、
MPEG-PS、MPEG-2、MP4 或 H.264。

项目自有代码采用 MIT；`pl_mpeg` 的 MIT 和 JPEGDEC 的 Apache-2.0
许可证分别保留在 `vendor/`。
