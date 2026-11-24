# 技术架构

## 概览

采用 Python 开发 Windows 桌面程序，在本机完成音频采集、流式语音识别、字幕显示和文本导出。PySide6 界面在主线程运行，采集与识别在后台执行，通过字幕快照更新界面。

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

2026-11-24 实测（Windows 11 构建 `26200`、x64、CPU INT8）：Python 3.12.16，`faster-whisper` 1.2.1，CTranslate2 4.9.1，`onnxruntime` 1.32.0，`av` 15.1.0（19.x 与 1.2.1 不兼容，`decode_audio` 会抛 `TypeError`）。原型基线模型为 `Systran/faster-whisper-small`（本地目录 486 MB，离线加载），固定 `language="zh"`、`beam_size=5`、`vad_filter=False`；13.525 s 真人录音推理约 2.5 s（RTF 0.18–0.19，机器有负载时实测到 4.3 s），6.00 s 公开样本 RTF 约 0.36，首跑含线程预热更慢。`base` 模型中文只对约六成内容，已弃用。采集侧需要软件增益或 AGC：同一段低电平录音（峰值 0.020）乘 15 后，`最文破坏` 才修正为 `最稳妥`。简体输出已定：解码固定 `language="zh"`，输出后用 `opencc`（`t2s`）转简体，不采用提示词偏置。字形本身随音频在简体与繁体之间变化，加提示词能拉成简体但会拉低准确率，已实测否决。包结构已落地：`pyproject.toml` 用 setuptools 后端与 `src/liebad/` 布局，`pip install -e .` 与 8 个单测均通过，会话与导出接口集中在 `src/liebad/contracts.py`。数据见[测试记录](test-records.md)。

## 模型对比

用针对中文转写微调的 wav2vec 2.0 模型做对照，两套识别器复用同一个 Python 会话与计时逻辑。在同一台电脑上，以相同的速度向两套识别流程输入同一批中文和中英混说音频，记录从语音开始到首次出字的时间，并将各自的定稿与人工参考文本对照。模型与运行配置随测试结果一并记录。参考 [wav2vec 2.0 论文](https://arxiv.org/abs/2006.11477)。

## 已知边界

- 指定应用按进程树采集。同一浏览器的多个标签页可能进入同一个采集会话。
- 受保护的应用音频可能无法通过进程回环采集。
- Whisper 的临时字幕随新音频更新。首次出字时间和字幕稳定性需要结合音频窗口设置做实测。
- 本机实际的应用兼容性、识别准确率和延迟待测。

## 演进方向

后续可在音频采集层增加系统混音和本地音视频文件，通过相同的转换与识别链路生成字幕。
