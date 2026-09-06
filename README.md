# PrimeVideoPlayer

面向 **HP Prime G1 / 2025-09-15 固件**的离线无声视频播放器。

- `1.0.0`：以 rc6 行为为基线的瘦身正式包；保留 320×240@25 MPEG-1
  和现有 PVMJ/MJPG 行为。
- `1.1.0`：动态 MPEG-1 分辨率、八档标准帧率、四种缩放、精确时钟、
  高帧率策略、简体中文/English、深浅主题、持久设置页、实际显示 FPS
  与 50 ms 慢帧统计；另附可选 CUDA 源解码的 MPEG-1 转换器 V5。

- `1.1.1`：视频和叠层先在屏外合成，再统一送屏；覆盖播放、暂停、定位和叠层切换。
  文件列表按像素边界裁剪文件名，修复中英文名称提前截断或越界。

## 支持边界

- `.M1V`：MPEG-1 Video elementary stream，YUV420；支持
  `24000/1001`、24、25、`30000/1001`、30、50、`60000/1001`、60 FPS。
- `.MJPG`：项目的 `PVMJ` v1 容器，320×240 baseline JPEG。
- 输出固定为 320×240 RGB8888；M1V 可选择适应、原始、填充或拉伸。
- 不支持音频、MPEG-PS、MPEG-2、MP4、H.264、G2 或其他固件。

视频文件放在 `C:\DATA\PrimeVideoPlayer.hpappdir\`。完整按键、设置和使用
说明见 [播放器文档](docs/prime-video-player.md)。

## 开发

```text
python -m unittest tests.test_prime_video_player
```

项目自有代码采用 MIT；`pl_mpeg` 的 MIT 和 JPEGDEC 的 Apache-2.0 许可证
分别保留。
