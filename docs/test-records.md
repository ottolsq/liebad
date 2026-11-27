# 测试记录

按批次记录本机实测的环境、素材、参数和结果。复跑命令都在仓库根目录执行，解释器为 `.venv\Scripts\python.exe`。

| 批次 | 日期 | 范围 | 结论 |
|---|---|---|---|
| 1 | 2026-11-24 | 本地工具链与 Whisper 中文转写 | 工具链通过；`small` 模型可用，需固定 `language="zh"`、做增益归一化，并后置繁转简 |
| 2 | 2026-11-24 | 字幕会话与 TXT 导出 | 10 个单测通过；可编辑安装成功，依赖固定到 `pyproject.toml` |
| 3 | 2026-11-24 | 接入 Whisper 和麦克风 | 21 个单测与集成测试通过；真实 WASAPI 采集到语音并转写成功，需做电平归一化 |
| 4 | 2026-11-24 | 置顶悬浮窗原型 | 25 个单测通过；真实麦克风端到端跑通，首字约 2.0 s，置顶、停止导出、关闭后重开麦克风均实测通过 |
| 5 | 2026-11-24 | 应用音频回环 | 36 个单测通过；浏览器与抖音同时播放时各自只识别选中进程，暂停播放后自动定稿，采集中关闭真实抖音会提示重新选择音源 |
| 6 | 2026-11-25 | Whisper 与 wav2vec 2.0 对比 | 45 个单测通过；wav2vec 2.0 首字 1.05–1.28 s（Whisper 2.56–4.21 s），但定稿 CER 0.400/0.778（Whisper 0.267/0.296）且不输出英文 |
| 6（追加） | 2026-11-25 | 界面可选识别引擎 | 59 个单测通过；悬浮窗可在 Whisper、wav2vec 2.0 与混合三种模式间切换，混合模式首字 3.0 s 且定稿与纯 Whisper 一致 |

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

一段自录的中文录音（`m4a`），346,788 B，AAC 48000 Hz 双声道，13.525 s，峰值 0.020、RMS 0.0023（约 -53 dBFS，录音电平很低）。转成 `temp\audio\recording_2.wav`（16000 Hz 单声道 16-bit，432,854 B，216,405 样本）后测得。

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
- 简体输出已定：解码固定 `language="zh"`、不加提示词，输出后用 `opencc`（`t2s`，`opencc-python-reimplemented==0.1.7`）转简体；脚本 `--simplify` 已实现，公开样本的 `對面樓市` 转成 `对面楼市` 后仍正确。`opencc` 已在第 2 批写入 `pyproject.toml` 的依赖，由 `pip install -e .` 安装。
- `av` 必须锁 `15.1.0`，升级前需重跑本记录。

## 第 2 批：字幕会话与 TXT 导出

### 环境

沿用第 1 批的 `.venv`（Python 3.12.16）。`pyproject.toml` 的构建后端是 setuptools，`pip install -e .` 会临时安装 `setuptools>=75`；`pip check` 退出码 `0`。

### 改动文件

| 文件 | 作用 |
|---|---|
| `pyproject.toml` | setuptools 后端、`src/` 布局，锁定 `av==15.1.0`、`faster-whisper==1.2.1`、`opencc-python-reimplemented==0.1.7` |
| `src/liebad/contracts.py` | `AudioBlock`、`AudioSource`/`SpeechRecognizer` 协议、`FinalCaption`、`CaptionState`、`CaptionSnapshot`、`CaptionOptions` |
| `src/liebad/session.py` | `CaptionSession`：20 ms 帧、RMS 判语音、停顿与 12 s 上限定稿、共同前缀固定、停止排空余音 |
| `src/liebad/export_txt.py` | `write_txt`：按定稿顺序逐段一行、UTF-8、换行写 `\n` |
| `tests/unit/test_session.py` | 9 个会话用例，含两条不足一帧尾音的回归 |
| `tests/unit/test_export_txt.py` | 1 个导出用例 |

### 实施过程

1. 包配置用 `setuptools>=75` + `setuptools.build_meta`，`[tool.setuptools] package-dir = { "" = "src" }`。
2. 首跑 8 个用例有 1 个失败：断言草稿序列恰好 2 条，实际是 `今天去上`、`今天去上海`、`今天去上明天去上海` 三条，属于测试断言过窄，删掉计数断言后通过。
3. `pip install -e .` 在 `workspace-write` 沙箱下失败：`ERROR: Could not install packages due to an OSError: [Errno 13] Permission denied: '<TEMP>\dsh-*\pip-build-tracker-*\e0d3f...'`。根因与第 1 批 ensurepip 相同：pip 用 `tempfile.mkdtemp()` 建临时目录，而 CPython 在 Windows 把 `0700` 落成受保护 DACL（`icacls` 都读不到），本会话进程在受限令牌下运行，写入被拒；默认模式或 `0o777` 建出的目录继承父目录 ACL，可正常写入。
4. 经用户确认，用一次性完全权限执行同一条 `& $python -m pip install -e .`，构建通过，随后恢复 `workspace-write`。
5. 导出用例不用 `tempfile.TemporaryDirectory()`（同样受 0700 DACL 影响）；临时目录统一由 `tests/unit/scratch.py` 建在已忽略的 `temp/` 下，`addCleanup` 里带重试删除，避免残留落到仓库根。
6. 补回归时发现缺陷：`_feed` 只派发完整 20 ms 帧，音源结束时不足一帧的尾音留在缓冲区里被丢掉，`_finalize` 拿到的是不含尾音的音频；若整段不足一帧，则完全不会调识别器。先写两条失败用例（`test_subframe_tail_reaches_recognizer_after_stop`、`test_stop_finalizes_subframe_audio_once`，均 `FAILED`），再加 `_flush_tail()` 把残余样本并入当前语段后定稿，两条转绿。

### 结果

| 命令 | 期望 | 实测 |
|---|---|---|
| `& $python -m pip install -e .` | 退出码 `0` | `Successfully built liebad`、`Successfully installed liebad-0.1.0`，退出码 `0` |
| `& $python -m pip check` | 退出码 `0` | `No broken requirements found.`，退出码 `0` |
| `& $python -c "import liebad"` | 版本 `0.1.0`，指向 `src/liebad` | `version 0.1.0`、`file <repo>\src\liebad\__init__.py`，退出码 `0` |
| `& $python -m unittest discover -s tests/unit` | 10 个用例全过 | `Ran 10 tests in 0.052s`、`OK`，退出码 `0` |

### 命令

```powershell
$python = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $python -m pip install -e .
& $python -m pip check
& $python -m unittest discover -s tests/unit
```

### 结论与待办

- 稳定的字幕开头、停顿定稿、停止时尾段恰好定稿一次、重复文字分段保留、静音不触发识别、12 s 强制分段，都已有固定结果覆盖，第 3 批可直接复用 `CaptionSession`；停止时不足一帧的尾音现在经 `_flush_tail()` 并入最后一段，只定稿一次，有两条回归用例。
- 依赖版本已固定到 `pyproject.toml`，`opencc` 不再只存在于 `.venv`。
- 沙箱限制：本会话里任何 `pip` 安装都会创建 0700 临时目录而失败，需要一次性完全权限；后续安装依赖沿用这条路径。

## 第 3 批：接入 Whisper 和麦克风

### 环境

沿用第 2 批的 `.venv`（Python 3.12.16、`faster-whisper` 1.2.1、CTranslate2 4.9.1、`av` 15.1.0、`onnxruntime` 1.32.0、`opencc-python-reimplemented` 0.1.7）。本批新增 `sounddevice==0.5.6`（带 `cffi==2.1.1`、`pycparser==3.12`），`pip check` 退出码 `0`，`pip list --format=freeze` 共 30 行。

### 改动文件

| 文件 | 作用 |
|---|---|
| `src/liebad/whisper_recognizer.py` | `WhisperRecognizer`：CPU INT8、`local_files_only=True` 复用同一模型，`from_env()` 读 `LIEBAD_WHISPER_MODEL`/`LIEBAD_WHISPER_LANGUAGE`，校验 `model.bin` 与 `tokenizer.json`，输出后 `opencc` 转简体 |
| `src/liebad/audio/pcm.py` | `Pcm16kConverter`：有状态 PyAV `AudioResampler`，`convert(bytes)` 与 `flush()` 保留滤波尾音 |
| `src/liebad/audio/microphone.py` | `list_microphones()` 只列 WASAPI 输入；`MicrophoneSource` 用 `RawInputStream` 回调入有界队列，消费端转换并兜住状态错误与队列溢出 |
| `src/liebad/audio/__init__.py` | 导出 `MicrophoneSource`、`Pcm16kConverter`、`list_microphones` |
| `tests/unit/test_pcm.py` | 5 个用例：整块与分块逐样本一致、时长换算、单声道、非法参数、收尾 |
| `tests/unit/test_microphone.py` | 4 个用例：假采集的正常排空、状态错误、队列溢出、启动前停止 |
| `tests/unit/test_whisper_recognizer.py` | 2 个用例：缺环境变量、模型目录缺文件 |
| `tests/integration/test_whisper.py` | 1 个用例：读三个环境变量，缺项报出具体名字并跳过 |
| `pyproject.toml` | 依赖新增 `sounddevice==0.5.6` |

### 实施过程

1. 先实测 PyAV 15.1.0 的重采样行为：48 kHz 双声道 `s16` 的 4800 样本一次 `resample` 得 1584 个 16 kHz 单声道样本，`resample(None)` 再补 16 个；按 3840/1920/960/480/240/7 字节分块与整块转换逐样本一致（`maxdiff 0.000000`）。
2. 识别器首版把 `list(mono16k)` 直接交给 `transcribe`，`faster_whisper/transcribe.py:876` 判定它不是 `np.ndarray` 后当成文件路径送 `decode_audio`，抛 `ValueError: File object has no read() method, or readable() returned False.`；改为 `np.asarray(mono16k, dtype=np.float32)`。
3. 集成测试首跑在原始电平上断言 `最稳妥` 失败（实际 `最文破判`）。同一 WAV 与 m4a 重新解码逐样本一致（`max diff 0.000000`），同配置连跑三次结果也完全相同，乘 15 倍增益后才对；差异只在电平，于是测试先归一化到峰值 0.3 再断言。
4. 真实设备：WASAPI 只有两个输入，一个是内置麦克风阵列（编号 `17`），一个是 USB-C 耳机麦克风（编号 `18`）。静音房间里 WASAPI 电平在 1e-5 量级，说话时峰值 0.05、RMS 0.008；同一设备的 WDM-KS 通道（编号 `26`）反而一直有 50–56 Hz 底噪，RMS 0.015–0.039。默认采集端点的音量读数为 `mute False level 1.000`，排除静音或音量归零。
5. 安装：`uv pip install -e .` 在写 `temp\uv-cache\builds-v0\...\liebad.egg-info` 时抛 `PermissionError: [WinError 5]`（uv 的构建临时目录同样是 0700），改用与第 2 批相同的一次性完全权限 `pip install -e .`。

### 结果

| 命令 | 期望 | 实测 |
|---|---|---|
| `& $python -m unittest discover -s tests/unit` | 21 个用例全过 | `Ran 21 tests in 0.481s`、`OK`，退出码 `0` |
| `& $python -m unittest discover -s tests/integration`（三个变量齐全） | 关键词命中 | `最稳妥` 在去空格文本中，`Ran 1 test in 4.266s`、`OK`，退出码 `0` |
| `& $python -m unittest discover -s tests/integration`（不设变量） | 报出缺项并跳过 | `skipped 'missing LIEBAD_TEST_MODEL, LIEBAD_TEST_WAV, LIEBAD_TEST_KEYWORD'`，`OK (skipped=1)`，退出码 `0` |
| `& $python -m pip check` | 退出码 `0` | `No broken requirements found.` |
| 真实麦克风采集后转写 | 非空文本 | 45.01 s 采集里 4.60–13.10 s 有声（峰值 0.0523），归一化后 `今天我们来验证本地语音专写看看段曲和准确率`，推理 2.78 s、RTF 0.327 |
| 停止后再次打开同一设备 | 两次都成功 | 各 16,043 个样本，峰值 0.0017 / 0.0003，耗时 1.36 s / 1.30 s |

### 命令

```powershell
$python = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $python -m unittest discover -s tests/unit
$env:LIEBAD_TEST_MODEL = ".\models\faster-whisper-small"
$env:LIEBAD_TEST_WAV = ".\temp\audio\recording_2.wav"
$env:LIEBAD_TEST_KEYWORD = "最稳妥"
& $python -m unittest discover -s tests/integration
```

真实麦克风自检按「枚举设备 → 采集一段 → 归一化 → 转写 → 再开一次」的顺序在 `temp\mic_speech.py`、`temp\mic_reopen.py` 里做过，属于一次性探测脚本，不入库。

### 结论与待办

- 采集、转换、识别三段在本机真实设备上接通：WASAPI 采集到语音，PyAV 转成 16 kHz 单声道，`WhisperRecognizer` 出简体文本，端到端 8.5 s 语音推理 2.78 s（RTF 0.33），24 字错 2 处（`转写` → `专写`、`断句` → `段曲`）。
- WASAPI 语音的 RMS 只有 0.005–0.008，低于会话默认的 `speech_rms_threshold=0.01`；第 4 批接界面时必须实测临时字幕能否出得来，必要时在采集侧加增益或下调门限。
- WDM-KS 通道有 50–56 Hz 底噪且 RMS 常高于门限，会误触发语音判定，不作为默认通道。
- 依赖安装仍需一次性完全权限：`pip` 与 `uv` 的构建临时目录都用 0700 目录。
- 本批没有改 `CaptionSession`，第 4 批直接复用；集成测试要求素材先归一化到峰值 0.3。

## 第 4 批：置顶悬浮窗原型

### 环境

沿用第 3 批的 `.venv`（Python 3.12.16、`faster-whisper` 1.2.1、CTranslate2 4.9.1、`av` 15.1.0、`onnxruntime` 1.32.0、`opencc-python-reimplemented` 0.1.7、`sounddevice` 0.5.6）。本批新增 `PySide6-Essentials==6.12.0`（带 `shiboken6==6.12.0`，`Prepared 2 packages in 35.91s`、`Installed 2 packages in 2.53s`），未装带 WebEngine 的完整 `PySide6` 包；`pip check` 退出码 `0`，`pip list --format=freeze` 共 33 行。

模型两个：定稿用 `models\faster-whisper-small`，临时字幕用 `models\faster-whisper-base`（第 1 批下载，6 个文件齐全）。

### 改动文件

| 文件 | 作用 |
|---|---|
| `src/liebad/ui/overlay.py` | `CaptionOverlay`：置顶窗口铺满屏幕工作区顶部，麦克风下拉、「开始」「停止」「导出」、状态行、大字临时字幕与定稿行；`preload=True` 时加载并预热两个模型 |
| `src/liebad/ui/session_worker.py` | `SessionWorker`：在 `QThread` 里先加载模型、再开麦克风建会话，把快照用 Qt 排队信号发回主线程；`partial_model_dir()` 解析临时字幕模型 |
| `src/liebad/ui/__init__.py`、`src/liebad/__main__.py` | 导出界面类；`python -m liebad` 启动，窗口先显示再由定时器加载模型 |
| `src/liebad/session.py` | 临时识别移到 `liebad-caption-inference` 线程（同语段只保留最新一次请求），定稿移到 `liebad-caption-final` 线程；`_freeze()` 冻结前缀只增不减；不足 `min_speech_ms` 的噪声瞬态不再定稿 |
| `src/liebad/contracts.py` | `CaptionOptions` 新增 `min_speech_ms: int = 300` |
| `src/liebad/audio/microphone.py` | 新增 `DEFAULT_GAIN = 6.0` 与限幅，`DEFAULT_MAX_QUEUE` 由 64 提到 512（约 11 s 缓冲） |
| `src/liebad/whisper_recognizer.py` | 新增 `cpu_threads` 参数与 `warm_up()`（空音频、`beam_size=1`、`temperature=0` 的单次推理） |
| `tests/unit/test_session.py` | 新增 4 个用例：`_freeze` 前缀只增不减、临时识别不阻塞采集、双模型分工、噪声瞬态不成字幕；共 25 个单测 |
| `pyproject.toml` | 依赖新增 `PySide6-Essentials==6.12.0` |

### 实施过程

1. 先装 `PySide6-Essentials==6.12.0`，`QT_QPA_PLATFORM=offscreen` 下确认 `pyside 6.12.0 qt 6.12.0 screens 1`；离屏截图布局正确，但无字体目录时中文显示成方块，真机用系统字体正常。
2. 首次端到端（真实麦克风、25 s）失败：30 s 内没有任何草稿、导出为空，直到 54 s 才冒出幻觉字幕 `字幕by索兰娅`。用 `temp\replay_session.py` 按实时喂 45 s 录音复现：同一段音频耗时 60.54 s，首个草稿在 8.30 s，之后每 3 s 才更新一次。
3. 根因是 `_update_partial` 在消费线程里同步跑 Whisper（`small` 单次约 2.85–3.0 s），把音频消费卡住，`MicrophoneSource` 的 PortAudio 队列必然溢出。改为两条专用线程：临时请求按语段去重只算最新一次，定稿串行计算，消费线程不再调用识别器。
4. 双模型基准（8 s 音频）：`small beam5 cpu_threads=0` 2.8 s/次、`small cpu_threads=1` 4.3 s、`base beam1` 0.65–0.69 s。于是定稿用 `small` + `cpu_threads=6`（2–2.8 s/次），临时字幕用 `base` + `beam_size=1` + `cpu_threads=2`（0.8–0.9 s/次），默认取主模型同级的 `faster-whisper-base`，可用 `LIEBAD_WHISPER_PARTIAL_MODEL` 覆盖。
5. 电平：WASAPI 说话时 RMS 0.005–0.008、静音 1e-5，低于默认门限 0.01。采集侧加 `DEFAULT_GAIN=6.0` 与限幅，界面把 `speech_rms_threshold` 提到 0.02（增益后静音约 0.011 不再触发），并新增 `min_speech_ms=300`：此前 12 ms 的噪声瞬态就会定稿成 `字幕by索兰娅`。
6. 首次出字：`base` 的第一次调用要 4.9 s（线程与算子预热），预热把这段开销挪到启动阶段；模型在点「开始」前加载好，麦克风等模型就绪后才打开，避免启动期音频在队列里积压（此前首字被拖到 20 s）。

### 结果

| 命令 / 场景 | 期望 | 实测 |
|---|---|---|
| `& $python -m unittest discover -s tests/unit` | 全过 | `Ran 25 tests in 1.076s`、`OK`，退出码 `0` |
| `& $python -m pip check` | 退出码 `0` | `No broken requirements found.` |
| 真实麦克风 25 s 会话（USB-C 耳机麦克风） | 出临时字幕与定稿 | 起声在采集域 4.52 s，首条草稿 6.5 s（**首字约 2.0 s**），草稿每 0.8 s 更新，定稿 1 段 `今天我们来验证本币 语音专写 算算段距和准确率`，退出码 `0` |
| 停止后导出 TXT | UTF-8、顺序与定稿一致 | 单段写入 `temp\audio\ui_live.txt`，内容 `今天我们来验证本币 语音专写 算算段距和准确率`，与界面定稿逐字相同 |
| 置顶 | 屏幕底部工作区顶部、始终置顶 | `window 1920x150 at 8,0`、`stay_on_top=True`，系统截图确认覆盖在桌面顶部 |
| 讲话时关闭窗口 | 能正常关闭并释放麦克风 | `close took 1.83s`，`visible=False thread=None`，随后重开同一设备 1 s 采到 12,629 个样本 |
| 连续两轮会话（WAV 回放） | 每轮只含本轮定稿 | 两轮各有 1 段，两份 TXT 都只含本轮文本，无上一轮残留 |

### 命令

```powershell
$python = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $python -m unittest discover -s tests/unit
$env:LIEBAD_WHISPER_MODEL = ".\models\faster-whisper-small"
$env:LIEBAD_WHISPER_PARTIAL_MODEL = ".\models\faster-whisper-base"  # 可省略，默认取同级目录
& $python -m liebad
```

### 结论与待办

- 12 项验收里可自动化的部分全部实测通过：置顶位置、开始/停止、导出 UTF-8、关闭后重开麦克风、连续两轮不串。
- 首字约 2.0 s（起声到首条临时字幕），临时字幕每 0.8 s 更新一次，定稿约 2.8 s/段；瓶颈是 `small` 的单次推理成本，再快需要换更小模型或加 VAD 缩短窗口。
- 识别质量仍是短板：本轮 22 字错 3 处（`本地` → `本币`、`转写` → `专写`、`看看断句` → `算算段距`），临时字幕用 `base` 时错字更多，还会因为冻结前缀只增不减而累积重复。
- 关闭窗口时 sounddevice 会打印 `can't open file for write !`（流关闭与回调的竞态），不影响退出和再次打开，待定位。
- 安装仍需一次性完全权限 `pip install -e .`；`uv pip install -e .` 仍因 0700 构建目录报 `PermissionError: [WinError 5]`。

## 第 5 批：应用音频回环

### 环境

| 项 | 实测值 |
|---|---|
| Windows | 11 25H2，构建号 `26200.9974`，x64 |
| 新增依赖 | `comtypes==1.5.0`（`pip check` 退出码 `0`），设备 `VAD\Process_Loopback` |
| 采集方式 | `ActivateAudioInterfaceAsync` + `PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE`，优先直接 16 kHz 单声道 PCM16 |
| 实测应用 | `msedge.exe`（pid 25744，B 站视频）与 `douyin.exe`（pid 25772，同时播放）；隔离对照另用两个 `powershell.exe` 播放器 `LIEBAD-AISHELL`、`LIEBAD-RECORDING` |
| 关闭复核 | 采集中关闭真实抖音（pid 19328）：44.5 s 提示「目标应用已退出，请重新选择音源后再开始」，刷新后列表 11 项且不再含 `douyin.exe`，「开始」恢复可用（`temp\close_probe.log`） |

### 改动文件

| 文件 | 改动 |
|---|---|
| `src/liebad/audio/process_catalog.py` | 新建。`AppSource(pid, process_name, window_title)`、`list_app_sources(*, exclude_pid)`，用 `EnumWindows` 取可见窗口、`QueryFullProcessImageNameW` 取进程名，按 pid 去重保留最长标题 |
| `src/liebad/audio/process_loopback.py` | 新建。`WasapiProcessLoopbackClient`、`ProcessLoopbackSource`、`_ProcessProbe`，comtypes 声明 `IAudioClient`、`IAudioCaptureClient`、激活 handler 与 `IAgileObject` |
| `src/liebad/audio/__init__.py` | 导出 `AppSource`、`ProcessLoopbackError`、`ProcessLoopbackSource`、`list_app_sources` |
| `src/liebad/ui/overlay.py` | 新增「麦克风 / 应用（进程回环）」音源下拉与刷新按钮，应用模式按 pid 采集，`APP_GAIN = 1.0`（实测应用混音接近满幅，放大 4 倍会削波）；目标退出时提示重新选择 |
| `src/liebad/session.py` | `_publish` 保留 `FAULTED` 的错误文本，避免收尾线程的发布把错误抹成空 |
| `tests/unit/test_process_loopback.py` | 新建 10 个用例：包转发与偏移、增益限幅、补静音、进程退出（无包/仍有包两种）、client 失败传播、停止、catalog 标签与去重 |
| `tests/unit/test_session.py` | 新增「故障错误在收尾线程发布后仍保留」的回归用例 |
| `pyproject.toml` | 依赖新增 `comtypes==1.5.0` |

### 实施过程

1. 按微软 ApplicationLoopback 示例用 comtypes 自行声明接口，`PROPVARIANT` 以 `VT_BLOB` 传 `AUDIOCLIENT_ACTIVATION_PARAMS`，handler 同时实现 `IAgileObject` 否则激活返回 `E_ILLEGAL_METHOD_CALL`。
2. 冒烟首次失败：`CoInitializeEx(COINIT_MULTITHREADED)` 报 `OSError: [WinError -2147417850]`。原因是 `liebad.audio` 先导入 `sounddevice`，PortAudio 已把主线程设为 STA；改为容忍 `RPC_E_CHANGED_MODE` 继续，并用 `PeekMessage` 泵消息等待 `ActivateCompleted`。
3. 隔离验收：浏览器与抖音同时播放，界面「应用」模式各选一次，导出两份 TXT。
4. 暂停定稿：暂停抖音播放后不再有语音帧，1.2 s 静音判定触发定稿，字幕在「采集中」状态下自行出现，无需点「停止」。
5. 关闭目标应用：初版只在「长时间没有音频包」时才查进程，关闭后静音包仍持续到达，导致界面一直显示采集中；改为每 0.5 s 主动查进程句柄并抛 `ProcessLoopbackError`。
6. 修完探测后发现界面仍显示「已完成，0 段」：`FAULTED` 快照的 `error` 被收尾线程后续的 `_publish` 覆盖成 `None`，`_publish` 改为在 `FAULTED` 状态保留错误文本。

### 结果

| 命令 / 场景 | 期望 | 实测 |
|---|---|---|
| `& $python -m unittest discover -s tests/unit` | 全过 | `Ran 36 tests in 1.116s`、`OK`，退出码 `0` |
| `& $python -m pip check` | 退出码 `0` | `No broken requirements found.` |
| 激活冒烟（`temp\loopback_smoke.py`） | 能打开并收包 | `open took 0.000s`，3 s 收 298 包、47,680 帧 |
| 浏览器与抖音同时播放，各选一次 | 只识别选中应用 | Edge：首字 3.0 s，`你看到西藏又有很大的不同…` / `完全不同的路线虽说不同但和西章式也是殊途同归`；抖音：首字 3.1 s，`数次熔断看到国家暴电康宝莱董事会四处寻找…` / `他表示自己愿意帮助康宝莱对付阿康宝`；两份导出互不包含 |
| 暂停抖音播放 | 语段自然定稿 | 采集电平在 58.22 s 落到 0.01 以下，62.67 s 出现第 1 条定稿、65.92 s 第 2 条，全程状态为「采集中」，未点「停止」；导出 `temp\audio\pause_probe.txt` 含这两段 |
| 定稿时延 | 可接受 | 12 s 语段用 `small` 定稿约 4–5 s（上例 4.4 s），与推理耗时一致 |
| 采集中关闭抖音（真实应用） | 报错并允许重选 | 采集 44.5 s 时状态变为 `错误：目标应用已退出，请重新选择音源后再开始`（当时已有 3 段定稿），1 s 内结束会话；刷新后应用列表 11 项且不再含 `douyin.exe`，「开始」恢复可用；`temp\close_probe.log` |

### 命令

```powershell
$python = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $python -m unittest discover -s tests/unit
& $python -m pip check
$env:LIEBAD_WHISPER_MODEL = ".\models\faster-whisper-small"
& $python -m liebad
```

人工验收：在浏览器和抖音桌面客户端同时播放两段不同语音，界面选「应用（进程回环）」，分别选中两个进程各跑一次，核对字幕与导出只含选中应用的内容。

### 结论与待办

- 进程回环在本机可用，`INCLUDE_TARGET_PROCESS_TREE` 下浏览器与抖音同时发声也能各自隔离，字幕与导出都只含所选进程；暂停播放后语段自动定稿，不需点「停止」。
- 关闭应用必须主动探测进程：WASAPI 在目标退出后仍可能送静音包，「无包」不能当退出信号。
- 定稿比说话晚约 4–5 s（12 s 语段 + `small` 推理），属于识别耗时，不是收尾阻塞；现场演示时最后一句会滞后几秒出现。
- 应用音频 `APP_GAIN=1.0`：真实应用混音峰值 0.67–0.99，放大 4 倍会削波并降低准确率，已实测改回。
- 关闭应用后会话以 `FAULTED` 收尾，界面提示「目标应用已退出，请重新选择音源后再开始」，「开始」恢复可用、列表已刷新，可直接重选；真实抖音关闭场景已复测通过。
- 待办：会话内无法向真实应用发送媒体暂停键（UIPI 拒绝 `PostMessage`，返回 `ERROR_ACCESS_DENIED`），暂停验收由人工操作完成；最小化窗口的应用不在 `list_app_sources()` 结果里（只枚举可见窗口），用户需把窗口恢复后刷新列表。
- 测试脚本层面的限制：本会话内 `taskkill` 无法终止沙箱内的子进程（`WaitForSingleObject` 仍超时），自动化改用 `Popen.terminate()`，不影响产品逻辑。

## 第 6 批：Whisper 与 wav2vec 2.0 对比

### 环境

| 项目 | 值 |
|---|---|
| 系统 | Windows 25H2 build `26200`，x64 |
| Python | 3.12.16（`.venv`），`uv pip install` 安装 |
| 新增依赖 | `torch==2.15.0+cpu`（`--index-url https://download.pytorch.org/whl/cpu`）、`transformers==5.24.1`、`safetensors==0.8.0`；`pip check` 退出码 `0` |
| 权重 | `jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn`（Apache-2.0，1,184,401 次下载），6 个文件共 1,276,350,040 B，放在 `models/wav2vec2-large-xlsr-53-chinese-zh-cn/` |
| Whisper 基线 | `models/faster-whisper-small`（CTranslate2，CPU INT8，`cpu_threads=6`） |
| 语料 | `temp/audio/aishell_sample.wav`（6.00 s，普通话）、`temp/audio/recording_2.wav`（13.53 s，中英混说） |

### 改动文件

| 文件 | 内容 |
|---|---|
| `src/liebad/replay_audio.py` | `ReplayAudioSource`：按原速交付 320 样本块，带 `start_sample`、可注入 `clock`/`sleep`、`gain` 限幅、`request_stop()` |
| `src/liebad/wav2vec_recognizer.py` | `Wav2VecRecognizer`：`AutoProcessor` + `AutoModelForCTC`，CTC 贪心解码后 `opencc` 繁转简，实现 `SpeechRecognizer` |
| `tools/asr_bench.py` | 读 `--manifest`（`audio`/`reference`/`language`/`speechStartSeconds`），每条样本按引擎各跑一次独立会话，统计首字延迟、草稿改写次数与 CER，写 `--out` CSV |
| `tests/unit/test_asr_bench.py` | 9 个用例：中英混排分词、归一化、编辑距离计分、回放分块与停止、增益限幅、非单声道拒绝、manifest 读取 |

### 实施过程

1. 经用户批准下载 `jonatasgrosman` 版权重与 `torch` CPU 轮子；`transformers` 一次性装好，`pip check` 无冲突。
2. 冒烟：`load 0.78s`、`warmup 1.75s`、319M 参数，6 s 音频 1.64–1.77 s（RTF 0.27–0.29）。
3. 标注起声：按 20 ms 帧 RMS 取峰值 25% 且连续 3 帧，`aishell_sample` 0.52 s、`recording_2` 1.68 s，写入 `temp/bench/manifest.csv`。
4. 基准：`tools/asr_bench.py` 以 `CaptionOptions(partial_interval_ms=400, pause_duration_ms=1200, speech_rms_threshold=0.02)` 跑两条样本 × 两个引擎，每条样本归一化到峰值 0.3 后按原速回放。

### 结果

| 样本 | 引擎 | 首字 (s) | 草稿次数 | 改写次数 | 定稿 CER | 会话时长 (s) |
|---|---|---|---|---|---|---|
| aishell_sample | whisper | 2.56 | 2 | 1 | 0.267（4/15） | 9.72 |
| aishell_sample | wav2vec | **1.28** | 8 | 7 | 0.400（6/15） | 8.20 |
| recording_2 | whisper | 4.21 | 3 | 2 | 0.296（8/27） | 15.38 |
| recording_2 | wav2vec | **1.05** | 11 | 10 | 0.778（21/27） | 13.89 |

定稿文本对照：

- 中文：参考「而 对 楼市 成交 抑制 作用 最 大 的 限 购」；whisper `而对面楼市成交一直作用最大的先购`；wav2vec `而对面楼是乘胶一支作用最大的限购`。
- 中英混说：参考「如果你是通过 API 调用 最稳妥按中文五百字 英文一千字 以内 来写」；whisper `如果你是通过API调用最文破坏中文500字英文1000次 以内来写`；wav2vec `果拟视通过黑批埃钓泳最文佛按充文无外此因文亦前次 伊内莱学`。

### 命令

```powershell
$python = (Resolve-Path .\.venv\Scripts\python.exe).Path
& uv pip install --python $python --index-url https://download.pytorch.org/whl/cpu torch
& uv pip install --python $python transformers
& $python -c "from huggingface_hub import snapshot_download; snapshot_download('jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn', local_dir='models/wav2vec2-large-xlsr-53-chinese-zh-cn')"
& $python -m unittest discover -s tests/unit
& $python .\tools\asr_bench.py --manifest .\temp\bench\manifest.csv --whisper-model .\models\faster-whisper-small --wav2vec-model .\models\wav2vec2-large-xlsr-53-chinese-zh-cn --out .\temp\bench\results.csv
```

### 结论与待办

- wav2vec 2.0 首字明显更快（1.05–1.28 s，约为 Whisper 的 40%），因为 CTC 帧同步、单次前向就能出字；Whisper 需要等更长上下文且单次 2.8 s。
- 但 wav2vec 2.0 定稿质量更差：中文 CER 0.400 对 0.267，中英混说 0.778 对 0.296；中英混说时 CTC 只输出汉字，英文全部丢失（`API`→`黑批埃`、`一千`→`亦前次`）。
- wav2vec 草稿次数多、改写也多（7–10 次），Whisper 草稿少（1–2 次改写）主要因为单次推理 2.8 s 跟不上 400 ms 的刷新间隔，不是稳定性更好。
- 建议：不把 wav2vec 2.0 作为定稿引擎；可考虑只做临时字幕的第二候选，届时需要接入 `pyctcdecode` + 语言模型来压低改写次数，并接受没有英文输出。

## 第 6 批（追加）：界面可选识别引擎

用户要求「用户能够在这两种模型中选择」，因此把两个引擎都做成悬浮窗可选项，而不是只保留对比脚本。

### 改动

| 文件 | 改动 |
|---|---|
| `src/liebad/engines.py` | 新增 `ENGINE_WHISPER` / `ENGINE_WAV2VEC` / `ENGINE_HYBRID`、`ENGINE_LABELS`、`normalize_engine()`、`wav2vec_model_dir()`（参数 → `LIEBAD_WAV2VEC_MODEL` → `models/wav2vec2-large-xlsr-53-chinese-zh-cn`）、`require_model_dir()` |
| `src/liebad/ui/session_worker.py` | `SessionWorker(..., engine=..., wav2vec_dir=...)`：`_build_recognizers()` 按引擎分派；wav2vec 分支懒导入 `Wav2VecRecognizer`、`warm_up()` 后单实例兼任定稿与草稿；混合分支用 `_make_wav2vec_partial()`（`torch_threads=2`）只出草稿、定稿仍用 Whisper `small`；新增 `capture_started` 信号（模型就绪、音源打开后发出） |
| `src/liebad/ui/overlay.py` | 工具栏新增「识别」下拉（`Whisper（定稿准）` / `wav2vec 2.0（首字快）` / `混合（wav2vec 草稿 + Whisper 定稿）`）；开始前校验所选引擎的模型目录；运行中禁用；首字延迟改从 `capture_started` 起算 |
| `tests/unit/test_engines.py` | 9 个用例：默认值、大小写与空白、未知引擎报错、三种引擎短名齐全、显式/环境/默认目录优先级、缺目录报错 |
| `tests/unit/test_session_worker.py` | 5 个用例：Whisper 保留注入的一对识别器、wav2vec 单实例、混合保留 Whisper 定稿 + 注入的草稿引擎、未知引擎在加载前报错、`_build_recognizers()` 不打开音源 |
| `src/liebad/ui/settings.py` | `OverlaySettings`（`QSettings` 封装：引擎、音源类型、麦克风 id、应用进程名、两个模型目录）与 `resolve_whisper_model()` / `resolve_wav2vec_model()`（参数 → 环境变量 → 上次选择 → 默认值）；设置文件默认 `%APPDATA%\Liebad\overlay.ini`，`LIEBAD_SETTINGS` 可覆盖，目录不可写时回退到工作目录 `.liebad-settings.ini` |
| `tests/unit/test_ui_settings.py` | 13 个用例：默认值、引擎/音源往返、未知值回退、模型目录只在存在时返回、跨实例持久化、两条解析优先级、`LIEBAD_SETTINGS` 与 `%APPDATA%` 的路径选择 |

### 结果

- 全量单测 `Ran 59 tests in 1.653s` / `OK`。
- 离屏整链（`temp\ui_engine_live.py`，把 `MicrophoneSource` 换成 `ReplayAudioSource(temp\audio\recording_2.wav, gain=15)`）：
  - 选 `wav2vec`：`已完成，2 段，首字 2.7 s，可导出`，草稿 `国尼` → `博拟室通过威` → `果你是通过黑批埃调勇最温佛`，导出 `temp\audio\engine_w2v.txt`。
  - 选 `hybrid`：先预加载 Whisper（状态 `就绪，模型已加载（faster-whisper-small + faster-whisper-base，wav2vec 2.0 可选）`），采集中草稿由 wav2vec 给出（`博尼市通过` → `博尼果你是通过批埃调泳` → `果你是通过黑批埃调泳最温佛案`），`已完成，2 段，首字 3.0 s`，导出 `temp\audio\engine_hybrid.txt`，正文与纯 Whisper 一致（`如果你是通过API调用最文破坏中文500字英文1000次`）。
  - 选 `whisper` 回归：`已完成，2 段，首字 5.6 s`，导出 `temp\audio\engine_whisper.txt` 与混合模式相同文本。
- 同一脚本第一次实测 `首字 11.9 s`，原因是把 5.8 s 的模型加载算进了延迟；加 `capture_started` 后改为 2.7–3.0 s。
- 排障教训：用普通函数连接 Qt 信号做记录会拿不到快照（必须用 `QObject` 的 `@Slot`），曾误判为「wav2vec 不出草稿」。
- 记住上次选择：`temp\settings_live.py` 离屏跑一次混合模式会话后，`QSettings` 文件里得到 `engine=hybrid`、`source/kind=mic`、`source/microphone=<编号>`、两个模型目录；另起一个 `OverlaySettings` 实例读取一致，重建窗口后引擎下拉、音源类型与麦克风都恢复到上次的值。本会话沙箱不允许写 `%APPDATA%`，路径检查自动回退到仓库根的 `.liebad-settings.ini`（已 gitignore）；另起进程读回 `hybrid / app / douyin.exe`，跨进程有效。全量单测 `Ran 72 tests in 1.404s` / `OK`。

### 限制

- wav2vec 权重 1.28 GB 与 `torch==2.15.0+cpu`、`transformers==5.24.1` 目前只装在 `.venv`，没有写进 `pyproject.toml`；安装与权重下载步骤已写进 [README 的可选引擎小节](../README.md)。
- 选 wav2vec 时 worker 内按需加载约 5.8 s，界面在此期间只显示「采集中…」，未做进度提示。
- 混合模式下 wav2vec 草稿（`torch_threads=2`）与 Whisper 定稿抢 CPU，草稿从每 0.5 s 一次降到约 2 s 一次；首字仍比纯 Whisper 快（3.0 s 对 5.6 s）。
- wav2vec 中英混说不输出英文，这一点没有随该选项改善。

## 2026-11-27 首版试用反馈复测

### Windows 启动与退出

- 用户桌面验收通过。通过 `start.cmd` 启动，按一次 Ctrl+C 后关闭浮窗并直接返回 PowerShell，无需输入 Y/N。
- 本机回归使用本地 Whisper，分别在预热中和就绪后向独立 Windows 控制台发送 Ctrl+C。两次均先退出应用，再返回 PowerShell 并执行下一条命令，期间未出现确认提示或 `KeyboardInterrupt`。状态栏的离屏绘制与终端输出均包含加载、预热和就绪状态。
- 在含空格的路径下复测正常关窗，并验证启动脚本传递退出码 `0` 和 `7`。实际采集过程中按 Ctrl+C 仍待桌面验证。
