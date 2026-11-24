# 测试记录

按批次记录本机实测的环境、素材、参数和结果。复跑命令都在仓库根目录执行，解释器为 `.venv\Scripts\python.exe`。

| 批次 | 日期 | 范围 | 结论 |
|---|---|---|---|
| 1 | 2026-11-24 | 本地工具链与 Whisper 中文转写 | 工具链通过；`small` 模型可用，需固定 `language="zh"`、做增益归一化，并后置繁转简 |

## 第 1 批：本地工具链与 Whisper

### 环境

| 项 | 实测值 |
|---|---|
| Windows | 11 25H2，构建号 `26200.9974`，x64 |
| CPU / 内存 | i7-12700H（20 逻辑核）/ 15.7 GB |
| Python | 3.12.16，64 位，uv 独立构建，位于 `.python\cpython-3.12.16-windows-x86_64-none\python.exe` |
| 虚拟环境 | `.venv`，pip 26.3 |

依赖（`pip check` 退出码 `0`，输出 `No broken requirements found.`）：`faster-whisper==1.2.1`、`ctranslate2==4.9.1`、`onnxruntime==1.32.0`、`av==15.1.0`、`tokenizers==0.23.3`、`numpy==2.5.5`、`huggingface-hub==2.4.0`、`opencc-python-reimplemented==0.1.7`，共 26 个包。

`av` 必须锁 `15.1.0`：`19.0.2` 移除了 `metadata_errors` 参数，`faster_whisper.audio.decode_audio` 会抛 `TypeError`。

### 模型

两个模型都由 Hugging Face 的 Systran 官方 CTranslate2 仓库直接下载，以 `local_files_only=True` 离线加载。

| 模型 | 本地目录 | 大小 | 说明 |
|---|---|---|---|
| `Systran/faster-whisper-base` | `models\faster-whisper-base\` | 147,886,409 B | 首个候选，中文准确率不达标 |
| `Systran/faster-whisper-small` | `models\faster-whisper-small\` | 486,215,847 B | 复核后选定的原型基线 |

### 实施过程

1. 检查解释器：系统只有 Python 3.15.2（`py -0p` 仅 3.15），而 `faster-whisper==1.2.1` 硬依赖 `onnxruntime`，其 win wheel 只到 cp314。用 uv 把 3.12.16 装进仓库 `.python\`，不动系统 Python。
2. 建虚拟环境：`& $base -m venv .\.venv` 的 ensurepip 失败（`No module named pip`，`tempfile.py` 里 `_resetperms` 报 `PermissionError: [WinError 5]`）。定位到沙箱内 0700 目录不可写（`os.mkdir(p, 0o700)` 后写入报 `PermissionError [Errno 13]`，`0o777` 正常），与 Python 版本无关。
3. 绕开 pip 的临时目录：改用 `uv venv .venv --python 3.12` + `uv pip install --python .venv\Scripts\python.exe "faster-whisper==1.2.1" pip`，`UV_CACHE_DIR` 放在 `temp\uv-cache`。安装成功，`python -m pip check` 退出码 `0`。
4. 下载模型：用 `temp\download_model.py` 按 HF 直链拉取 Systran 的 CTranslate2 仓库文件，校验字节数后离线加载。
5. 写 `tools/probe_whisper.py`：首个版本直接调 `faster_whisper.audio.decode_audio(path)`，在 `av==19.0.2` 上抛 `TypeError: open() got an unexpected keyword argument 'metadata_errors'`（`faster_whisper/audio.py:46`）。改为脚本内用 `wave` 读 PCM 并转 float32 后传数组，绕过该解码路径；随后把 `av` 锁到 `15.1.0`。
6. 准备素材：先试 Windows SAPI 合成中文，`GetInstalledVoices()` 抛 `NullReferenceException` 且无中文语音，放弃；改用 HF 数据集 `carlot/AIShell` 的公开样本。用户随后提供真人录音 `.m4a`，用 PyAV 转成 16 kHz 单声道 WAV。
7. 首轮结论是 `base` 模型中文只对约六成，经用户批准下载 `small`（486 MB）复核，确认 `small` 明显更好后定为基线。
8. 参数对照：`temp\ab_test.py` 比较语言、增益、提示词组合；`temp\zh_shape_test.py` 统计繁体字数量。据此定下 `language="zh"` + `--gain 15` 组合。

### 素材 A：公开中文样本

`temp\audio\aishell_sample.wav`：Hugging Face 数据集 `carlot/AIShell` 首行样本，16000 Hz、单声道、16-bit，6.00 s，峰值 0.047。

人工参考文本：而 对 楼市 成交 抑制 作用 最 大 的 限 购

| 模型与配置 | 识别输出 | 推理耗时 | RTF |
|---|---|---|---|
| `base`，自动语言 | 而对面螺式成交一直作用最大的线构 | 1.225 s（冷）/ 1.186 s（温） | 0.20 |
| `small`，`language="zh"` | 而对面楼是成交一直作用最大的先购 | 2.35–2.42 s（首跑 6.57 s） | 0.39–0.40 |
| `small`，`language="zh"` + 增益 ×15 | 而對面樓市成交一直作用最大的先購 | 2.155 s | 0.359 |
| `small`，`language="zh"` + 增益 ×15 + 简体提示词 | 而对面楼是成交一直作用最大的先购。 | 2.311 s | 0.385 |
| `small`，`language="zh"` + 增益 ×15 + `--simplify` | 而对面楼市成交一直作用最大的先购 | 1.918 s | 0.320 |

参考关键词 `成交` 在各配置均命中。`base` 错 3 处（楼市 → 面螺式、抑制 → 一直、限购 → 线构）；`small` 修正了 `楼市`，仍错 `抑制 → 一直`、`限购 → 先购`。最后一行先出繁体再经 `opencc t2s` 转简体，`楼市` 仍正确，说明后置转换不损伤已正确的字。

### 素材 B：真人录音

源文件 `C:\Users\ottol\Documents\录音\录音 (2).m4a`，346,788 B，AAC 48000 Hz 双声道，13.525 s，峰值 0.020、RMS 0.0023（约 -53 dBFS，录音电平很低）。转成 `temp\audio\recording_2.wav`（16000 Hz 单声道 16-bit，432,854 B，216,405 样本）后测得。

人工参考文本：如果你是通过 API 调用 最稳妥按中文五百字 英文一千字 以内 来写

| 模型与配置 | 识别输出 | 推理耗时 | RTF |
|---|---|---|---|
| `base`，自动语言 | 如果你是通過API釣用最紋伙反充文500次英文1000次以內來寫 | 1.666 s | 0.123 |
| `base`，`language="zh"` | 同上 | 0.841–0.967 s | 0.06–0.07 |
| `base`，`language="zh"` + 简体提示词 | 如果你是通过API吊泳罪文伙,反充文500次,英文1000次。以内来写。 | 0.943–1.313 s | 0.07–0.10 |
| `small`，自动语言 | 如果你是通过API调用最文破坏中文500字,英文1000次以内来写。 | 5.475 s | 0.405 |
| `small`，`language="zh"` | 同上 | 3.603 s | 0.266 |
| `small`，`language="zh"` + 增益 ×15 | 如果你是通过API调用最稳妥,按中文500字,英文1000次,以内来写。 | 2.46–3.62 s（三次连跑 2.46 / 2.51 / 2.58 s） | 0.182–0.191 |
| `small`，`language="zh"` + 增益 ×15 + 简体提示词 | 如果你是通过API调用罪文,破判中文500字,英文1000次,以内来写。 | 3.437 s | 0.254 |

`small` + `language="zh"` + 增益 ×15 是最佳组合（多次连跑文本一致）：`API调用`、`最稳妥`、`按中文`、`以内来写` 均正确，剩余错误是 `五百字` 记成 `500字`（数字格式，语义无损）和 `一千字` 记成 `1000次`（`字` → `次`，语义错误）。参考关键词 `最稳妥` 命中，`百字` 不命中。

### 简体与繁体输出

同一模型、同一参数（`small` + `language="zh"` + 增益 ×15）下，输出字形随音频变化：真人录音稳定出简体（繁体字 0），公开样本不加提示词时出繁体（繁体字 3）。加提示词能把输出拉成简体（繁体字 0），但两份素材上准确率都变差。

| 素材 | 提示词 | 繁体字 | 输出 |
|---|---|---|---|
| 真人录音 | 无 | 0 | 如果你是通过API调用最稳妥,按中文500字,英文1000次,以内来写。 |
| 真人录音 | 以下是普通话的句子。 | 0 | 如果你是通过API调用罪文破坏中文500字英文1000次以内来写。 |
| 真人录音 | 以下是普通话的句子，请用简体中文转写。 | 0 | 如果你是通过API调用罪文,破判中文500字,英文1000次,以内来写。 |
| 真人录音 | 我们今天讨论简体中文的转写结果。 | 0 | 如果你是通过API调用最文破版中文500字英文1000次以内来写。 |
| 公开样本 | 无 | 3 | 而對面樓市成交一直作用最大的先購 |
| 公开样本 | 上面三种提示词 | 0 | 而对面楼是成交一直作用最大的先购。 |

繁体字统计只覆盖 `對樓購內來寫這說…` 等一组常用繁体专用字，用于判断字形倾向，不等同于完整的繁简检测。

结论：简体输出不能靠提示词保证，且提示词会以准确率换字形。已选定方案：解码固定 `language="zh"`、不加提示词，输出后用 `opencc`（`t2s`）转简体。探测脚本的 `--simplify` 已实现并验证：公开样本由 `而對面樓市成交一直作用最大的先購` 转为 `而对面楼市成交一直作用最大的先购`，`楼市` 保持正确，推理耗时 1.918 s（未转换时 2.155 s，差异在噪声范围内）。

### 命令

```powershell
$python = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $python -m pip check
& $python .\tools\probe_whisper.py --model-dir .\models\faster-whisper-small --wav .\temp\audio\recording_2.wav --language zh --gain 15 --simplify --keyword 最稳妥
& $python .\tools\probe_whisper.py --model-dir .\models\faster-whisper-small --wav .\temp\audio\aishell_sample.wav --language zh --gain 15 --simplify --keyword 楼市
```

两条探测命令退出码均为 `0`。

### 参数

`WhisperModel(model_dir, device="cpu", compute_type="int8", local_files_only=True)`；`beam_size=5`、`vad_filter=False`、`condition_on_previous_text=False`、`cpu_threads` 取库默认值。增益由探测脚本的 `--gain` 在转写前乘到采样点上并裁剪到 `[-1, 1]`；`--prompt` 透传为 `initial_prompt`；`--simplify` 用 `opencc.OpenCC("t2s")` 转换每段文本后再拼接，关键词匹配也在转换后的文本上做。

### 结论与待办

- 速度：`small` 在 13.5 s 录音上推理稳定在约 2.5 s（RTF 0.18–0.19），机器有其他负载时实测到 4.3 s（RTF 0.32）；`base` 为 0.84–1.67 s（RTF 0.06–0.12）。首跑含线程预热会慢一倍左右。
- 准确率：`base` 两份素材都只对约六成内容；`small` 在真人录音上 24 字错 1 处（`一千字` → `1000次`），可用。原型基线定为 `small`。
- 增益归一化影响明显：同一段低电平录音，增益 ×15 把 `最文破坏` 修正为 `最稳妥`，`base` 也仅在此配置下救回 `調用`。采集链路需要软件增益或 AGC。
- 简体输出已定：解码固定 `language="zh"`、不加提示词，输出后用 `opencc`（`t2s`，`opencc-python-reimplemented==0.1.7`）转简体；脚本 `--simplify` 已实现，公开样本的 `對面樓市` 转成 `对面楼市` 后仍正确。`opencc` 目前只装在 `.venv` 里，待第 2 批建 `pyproject.toml` 时正式固定版本。
- `av` 必须锁 `15.1.0`，升级前需重跑本记录。
