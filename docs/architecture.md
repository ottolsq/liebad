# 技术架构

## 概览

采用 Python 开发 Windows 桌面程序，在本机完成音频采集、流式语音识别、字幕显示和文本导出。PySide6 界面在主线程运行，采集与识别在后台执行，通过字幕快照更新界面。

Whisper 在启动时由界面线程加载并预热，各阶段开始前刷新状态栏并输出到终端。Ctrl+C 由 Python 信号处理器登记关闭请求，Qt 事件循环随后走浮窗的关闭流程。

## 组件

| 组件 | 职责 | 边界 |
|---|---|---|
| 悬浮窗 | 在屏幕上沿置顶，提供音源选择、开始、停止和导出操作，呈现当前状态及字幕 | 通过会话状态更新界面 |
| 音频采集 | 采集麦克风、抖音桌面客户端或浏览器的声音，输出连续的音频块 | 麦克风模式按输入设备采集，应用模式按选定进程及其子进程采集 |
| 音频转换 | 将输入转换为模型要求的采样率、声道数和样本格式 | 只处理音频格式 |
| 实时识别 | 用 `faster-whisper` 在本机运行多语言 Whisper，定期转写音频并返回识别结果 | 字幕何时固定、更新和定稿由会话处理 |
| 会话与导出 | 固定临时字幕中连续识别一致的开头，更新其余文字，累积定稿 | 停止时完成识别收尾，按顺序将定稿导出为 UTF-8 文本，每个片段一行 |

## 数据流

```text
麦克风或指定应用音频 → 音频采集 → 音频转换 → Whisper 分段识别
                                                  ├→ 临时与定稿结果 → 悬浮窗
                                                  └→ 按顺序保留定稿 → 停止后导出 .txt
```

每次「开始」创建单一音源的识别会话。麦克风按选定的输入设备取音。抖音桌面客户端和浏览器按选定进程及其子进程取音，应用采集的实现参考微软的官方示例。连续无音频包时按经过的时间补静音，使会话能在应用停止播放后检测到停顿。采集失败时显示来源和错误状态。[Windows 进程音频采集示例](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/)

## 字幕更新与定稿

说话期间，识别模块定期更新同一待定稿语段的结果。会话比较同一语段连续两轮识别结果的开头，把相同部分暂时固定在悬浮窗里，只替换后面的临时文字。检测到停顿时完成该语段的识别，按顺序加入会话定稿。设计参考 [AppLiveCaption](https://github.com/EnderDragonEP/AppLiveCaption)。

点「停止」时先结束采集，再将已采集但尚未定稿的音频送入识别器完成最后一段识别。会话用最终结果替换该语段的临时字幕，把同一语段的定稿写入一次，随后开放 UTF-8 `.txt` 导出。

## 外部依赖

| 候选 | 用途 | 验证点 |
|---|---|---|
| PySide6 | Windows 桌面置顶悬浮窗 | 验证麦克风使用时和切换至抖音桌面客户端或浏览器后的显示 |
| `sounddevice` 与 WASAPI | 枚举并采集所选麦克风 | 验证设备选择、断开和重新开始 |
| `comtypes` 与 Windows 进程回环 | 采集所选应用进程树的声音 | 验证抖音桌面客户端与浏览器同时发声时的音频隔离 |
| PyAV | 有状态地将采集流转换为 16 kHz 单声道浮点音频 | 验证分块连续性与停止时的转换收尾 |
| `faster-whisper` 与 CTranslate2 | 从本地目录加载多语言 Whisper，先验证 CPU INT8 | 实测首次出字延迟、临时字幕改动、中文和中英混说效果，以及停止时的定稿收尾 |

Python 与依赖版本、Whisper 模型规格和音频窗口参数以原型实测为准。参考 [Qt 窗口标志](https://doc.qt.io/qtforpython-6/PySide6/QtCore/Qt.html)、[sounddevice 的 WASAPI 文档](https://python-sounddevice.readthedocs.io/en/latest/api/platform-specific-settings.html)、[PyAV 音频转换文档](https://pyav.basswood.io/docs/stable/api/audio.html)及 [faster-whisper 官方示例](https://github.com/SYSTRAN/faster-whisper#usage)。

### 已验证基线

2026-11-24 实测（Windows 11 构建 `26200`、x64、CPU INT8）：Python 3.12.16，`faster-whisper` 1.2.1，CTranslate2 4.9.1，`onnxruntime` 1.32.0，`av` 15.1.0（19.x 与 1.2.1 不兼容，`decode_audio` 会抛 `TypeError`）。原型基线模型为 `Systran/faster-whisper-small`（本地目录 486 MB，离线加载），固定 `language="zh"`、`beam_size=5`、`vad_filter=False`；13.525 s 真人录音推理约 2.5 s（RTF 0.18–0.19，机器有负载时实测到 4.3 s），6.00 s 公开样本 RTF 约 0.36，首跑含线程预热更慢。`base` 模型中文只对约六成内容，仅用于临时字幕，定稿由 `small` 承担。采集侧需要软件增益或 AGC：同一段低电平录音（峰值 0.020）乘 15 后，`最文破坏` 才修正为 `最稳妥`。简体输出已定：解码固定 `language="zh"`，输出后用 `opencc`（`t2s`）转简体，不采用提示词偏置。字形本身随音频在简体与繁体之间变化，加提示词能拉成简体但会拉低准确率，已实测否决。包结构已落地：`pyproject.toml` 用 setuptools 后端与 `src/liebad/` 布局，`pip install -e .` 与 8 个单测均通过，会话与导出接口集中在 `src/liebad/contracts.py`。第 3 批接通了采集与识别：`sounddevice==0.5.6` 经 WASAPI 采集（本机两个输入设备，USB-C 耳机麦克风为默认），`Pcm16kConverter` 用同一个 PyAV `AudioResampler` 分块转出 16 kHz 单声道，分块与整块逐样本一致；`WhisperRecognizer` 复用同一 `WhisperModel` 实例，集成测试从 `LIEBAD_TEST_MODEL`、`LIEBAD_TEST_WAV`、`LIEBAD_TEST_KEYWORD` 读素材并断言关键词。WASAPI 语音段峰值约 0.05、RMS 0.005–0.008，低于会话默认的 `speech_rms_threshold=0.01`，识别前需归一化或加增益；真实采集 8.5 s 语音推理 2.78 s（RTF 0.33），静音时电平在 1e-5 量级属正常门限行为，WDM-KS 通道带 50–56 Hz 底噪，不作为默认。第 4 批落地的界面与调度基线：`PySide6-Essentials==6.12.0`，置顶窗口铺满屏幕工作区顶部（实测 1920x150，位置 8,0），`SessionWorker` 在 `QThread` 里先加载模型再开麦克风；会话内临时字幕与定稿分两条线程（`liebad-caption-inference`、`liebad-caption-final`），临时字幕用 `faster-whisper-base`（`beam_size=1`、`cpu_threads=2`，0.8–0.9 s/次）、定稿用 `faster-whisper-small`（`beam_size=5`、`cpu_threads=6`，2–2.8 s/次），预热与预加载把首次调用开销移出采集期；采集侧 `DEFAULT_GAIN=6.0`、界面门限 0.02、`min_speech_ms=300`，静音幻觉与噪声瞬态不再成为字幕。真实麦克风首字约 2.0 s，关闭窗口 1.83 s 内释放麦克风。第 5 批的应用音频基线：`comtypes==1.5.0` 通过 `ActivateAudioInterfaceAsync` 与 `PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE` 打开 `VAD\Process_Loopback`，优先直接申请 16 kHz 单声道 PCM16，失败才退回 `GetMixFormat` + `Pcm16kConverter`；STA 线程必须泵消息才能收到 `ActivateCompleted`，`CoInitializeEx(MTA)` 遇到 `RPC_E_CHANGED_MODE` 视为可用继续。进程退出不能只靠「长时间无包」判断——关闭应用后静音包仍可能持续到达，改为每 0.5 s 主动查一次进程句柄，否则要等用户点停止才报错；界面按「麦克风 / 应用（进程回环）」切换。应用混音已接近满幅（实测峰值 0.67–0.99），`APP_GAIN=1.0` 不再额外放大，否则会削波；12 s 语段用 `small` 定稿约 4–5 s，暂停播放后字幕在 4–5 s 内出现。数据见[测试记录](test-records.md)。
第 6 批的对比基线：`tools/asr_bench.py` 用 `ReplayAudioSource` 按原速回放同一批音频，`Wav2VecRecognizer` 经 `transformers` 加载 `jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn`（Apache-2.0，319M 参数，CPU RTF 0.28，`torch==2.15.0+cpu`）。CTC 帧同步带来更快的首字（1.05–1.28 s 对 Whisper 的 2.56–4.21 s），但定稿 CER 为 0.400（普通话）与 0.778（中英混说），明显差于 Whisper 的 0.267 与 0.296，且只输出汉字、英文词全部丢失。结论：定稿仍用 Whisper，wav2vec 2.0 只作为临时字幕的候选，接入前需补解码器与语言模型。当前实现把两者都暴露为界面可选项（`src/liebad/engines.py` 的 `ENGINE_WHISPER` / `ENGINE_WAV2VEC` / `ENGINE_HYBRID`）：Whisper 仍是 `small` 定稿 + `base` 临时字幕，选了 wav2vec 2.0 就由 worker 线程按需加载、预热并以同一实例兼任定稿与临时字幕，`LIEBAD_WAV2VEC_MODEL` 可改权重目录；「混合」用 wav2vec 2.0（`torch_threads=2`）只出临时字幕、定稿交给 Whisper `small`，实测首字 3.0 s 而导出文本与纯 Whisper 一致。首字延迟改从音频开始流动（`SessionWorker.capture_started`）起算，避免把按需加载时间算进用户可见的响应。窗口用 `QSettings`（`src/liebad/ui/settings.py`）记住上次的引擎、音源与模型目录，下次启动按「参数 → 环境变量 → 上次选择 → 默认值」恢复；设置文件默认在 `%APPDATA%\Liebad\overlay.ini`，`LIEBAD_SETTINGS` 可覆盖，目录不可写时回退到工作目录的 `.liebad-settings.ini`。

## 模型对比

用针对中文转写微调的 wav2vec 2.0 模型做对照，两套识别器复用同一个 Python 会话与计时逻辑。在同一台电脑上，以相同的速度向两套识别流程输入同一批中文和中英混说音频，记录从语音开始到首次出字的时间，并将各自的定稿与人工参考文本对照。模型与运行配置随测试结果一并记录。参考 [wav2vec 2.0 论文](https://arxiv.org/abs/2006.11477)。

## 已知边界

- 指定应用按进程树采集。同一浏览器的多个标签页可能进入同一个采集会话。
- 受保护的应用音频可能无法通过进程回环采集。
- Whisper 的临时字幕随新音频更新。首次出字时间和字幕稳定性需要结合音频窗口设置做实测。
- 本机实际的应用兼容性、识别准确率和延迟待测。

## 演进方向

后续可在音频采集层增加系统混音和本地音视频文件，通过相同的转换与识别链路生成字幕。
