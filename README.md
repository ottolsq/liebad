# Liebad

Liebad 为 Windows 上的现场讲话、抖音桌面客户端和浏览器视频生成实时字幕：本地识别，置顶悬浮窗显示，导出 UTF-8 `.txt`。麦克风字幕原型已可运行。以下命令在 Windows、PowerShell、仓库根目录执行，解释器为 uv 装的 Python 3.12 建出的 `.venv`。

## 快速开始

```powershell
$python = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $python -m pip install -e .
& $python -m unittest discover -s tests/unit
$env:LIEBAD_WHISPER_MODEL = ".\models\faster-whisper-small"
& $python -m liebad
```

窗口出现在屏幕顶部，选择音源后点「开始」边说边看字幕，点「停止」后可「导出」。首次启动要加载并预热 Whisper `small` 与 `base`（约 8 秒）；临时字幕默认用同级的 `faster-whisper-base`，可用 `LIEBAD_WHISPER_PARTIAL_MODEL` 指定。

### 可选：wav2vec 2.0 与混合模式

「识别」下拉里的 wav2vec 2.0 与混合模式需要额外依赖和本地权重（`jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn`，Apache-2.0，约 1.28 GB）：

```powershell
& uv pip install --python $python --index-url https://download.pytorch.org/whl/cpu torch
& uv pip install --python $python transformers
& $python -c "from huggingface_hub import snapshot_download; snapshot_download('jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn', local_dir='models/wav2vec2-large-xlsr-53-chinese-zh-cn')"
```

权重放在别处时用 `$env:LIEBAD_WAV2VEC_MODEL = "..."` 指定（没装 uv 时把上面两条 `uv pip install` 换成 `& $python -m pip install`）；版本、体积与两套模型的实测数字见[测试记录](docs/test-records.md)。

集成测试需要素材，缺素材时跳过并报出缺少的变量名：设 `LIEBAD_TEST_MODEL`、`LIEBAD_TEST_WAV`、`LIEBAD_TEST_KEYWORD` 后运行 `& $python -m unittest discover -s tests/integration`。

## 文档

| 文档 | 内容 |
|---|---|
| [目标与范围](docs/goal.md) | 使用场景、首版范围和验收方式 |
| [技术架构](docs/architecture.md) | 音频采集、流式识别、显示和导出设计 |
| [项目计划](docs/plan.md) | 当前里程碑、完成标准和验收方式 |
| [项目协作约定](AGENTS.md) | 项目命令和完成定义 |

许可：待项目维护者确定。
