# Liebad

Liebad 为 Windows 上的现场讲话、抖音桌面客户端和浏览器视频生成实时字幕。

## 状态

项目处于立项阶段。首版计划以麦克风、抖音桌面客户端和浏览器为音源，用本地 Whisper 识别，在屏幕顶部的置顶悬浮窗显示字幕，并导出 UTF-8 `.txt`。

## 快速开始

可运行版本尚未实现，界面与麦克风采集在第 3 批接入。当前已验证包可以安装、单元测试可以运行（Windows、PowerShell，仓库根目录执行，解释器为 uv 装的 Python 3.12 建出的 `.venv`）：

```powershell
$python = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $python -m pip install -e .
& $python -m unittest discover -s tests/unit
```

构建测试和启动命令将随原型完成补全。

## 文档

| 文档 | 内容 |
|---|---|
| [目标与范围](docs/goal.md) | 使用场景、首版范围和验收方式 |
| [技术架构](docs/architecture.md) | 音频采集、流式识别、显示和导出设计 |
| [项目计划](docs/plan.md) | 当前里程碑、完成标准和验收方式 |
| [项目协作约定](AGENTS.md) | 项目命令和完成定义 |

## 许可

待项目维护者确定。
