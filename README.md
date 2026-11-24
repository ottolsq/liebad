# Liebad

Liebad 为 Windows 上的现场讲话、抖音桌面客户端和浏览器视频生成实时字幕。项目处于立项阶段：首版以麦克风、抖音桌面客户端和浏览器为音源，用本地 Whisper 识别，在屏幕顶部的置顶悬浮窗显示字幕，并导出 UTF-8 `.txt`。麦克风字幕原型已可运行。

## 快速开始

Windows、PowerShell，仓库根目录执行，解释器为 uv 装的 Python 3.12 建出的 `.venv`：

```powershell
$python = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $python -m pip install -e .
& $python -m unittest discover -s tests/unit
$env:LIEBAD_WHISPER_MODEL = ".\models\faster-whisper-small"
& $python -m liebad
```

窗口出现在屏幕顶部，选择麦克风后点「开始」边说边看字幕，点「停止」后可「导出」UTF-8 `.txt`。首次启动要加载并预热两个模型（约 8 秒）；临时字幕默认用同级的 `faster-whisper-base`，可用 `LIEBAD_WHISPER_PARTIAL_MODEL` 指定。

识别集成测试需要素材，缺素材时跳过并报出缺少的变量名：

```powershell
$env:LIEBAD_TEST_MODEL = ".\models\faster-whisper-small"
$env:LIEBAD_TEST_WAV = ".\temp\audio\recording_2.wav"
$env:LIEBAD_TEST_KEYWORD = "最稳妥"
& $python -m unittest discover -s tests/integration
```

模型与素材的获取方式、实测耗时和已知问题见[测试记录](docs/test-records.md)。

## 文档

| 文档 | 内容 |
|---|---|
| [目标与范围](docs/goal.md) | 使用场景、首版范围和验收方式 |
| [技术架构](docs/architecture.md) | 音频采集、流式识别、显示和导出设计 |
| [项目计划](docs/plan.md) | 当前里程碑、完成标准和验收方式 |
| [项目协作约定](AGENTS.md) | 项目命令和完成定义 |

许可：待项目维护者确定。
