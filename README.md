# Liebad

Liebad 为 Windows 上的现场讲话、抖音桌面客户端和浏览器视频生成实时字幕：本地识别，置顶悬浮窗显示，导出 UTF-8 `.txt`。首版 `0.1.0` 已完成，兼容性以[首版阶段记录](docs/history/01-live-captions.md)中的实测场景为准。以下命令在 Windows、PowerShell、仓库根目录执行，解释器为 uv 装的 Python 3.12 建出的 `.venv`。

## 快速开始

已有 `.venv` 和本地模型时，在仓库根目录运行 **`.\start.cmd`**，或双击 `start.cmd`。浮窗和终端会显示 Whisper 的加载、预热和就绪状态；就绪后可点「开始」，使用 wav2vec 2.0 时也有加载和预热提示。在终端按一次 **Ctrl+C**，Liebad 会收尾、关闭浮窗并返回 PowerShell，无需回答 Y/N；若正在预热，可能等到当前预热操作结束。要保留字幕，请先点「停止」，再导出。下方命令用于开发安装和单元测试。

```powershell
$python = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $python -m pip install --no-build-isolation --no-index -e .
& $python -m unittest discover -s tests/unit
```

悬浮窗默认在屏幕上方居中并留出边距。可拖动标题栏移动浮窗，或拖动右下角调整大小。选择音源后点「开始」，长字幕以 `…` 省略较早的文字，优先显示末尾。点「停止」后可将完整定稿导出为 UTF-8 `.txt`。保存对话框优先打开可写的「文档」目录，无法写入时从启动目录打开。保存框打开时浮窗暂时隐藏。可以选择任何当前账号有写入权限的位置。写入失败时可在窗口中查看原因，并重新选择路径。如果用自己的 Windows 账号启动后仍无法写入「文档」，见[项目外导出排查](docs/test-records.md#windows-拒绝导出到项目外)。开发安装只需执行一次：已带 `--no-build-isolation --no-index`，直接用 `.venv` 里的 setuptools 且不访问 PyPI（默认的隔离构建会联网下载构建依赖，网络慢时看起来像卡住）。首次启动要加载并预热 Whisper `small` 与 `base`（约 8 秒）；临时字幕默认用同级的 `faster-whisper-base`，可用 `LIEBAD_WHISPER_PARTIAL_MODEL` 指定。下次启动会恢复上次的「识别」与音源选择（存于 `%APPDATA%\Liebad\overlay.ini`，可用 `LIEBAD_SETTINGS` 指定）。

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
