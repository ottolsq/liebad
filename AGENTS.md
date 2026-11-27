# AGENTS.md — Liebad

## 协作约定

- 明确、可回滚的局部修正直接做并验证；范围、架构边界或验收条件变化先讨论。已经确认的批次不重复报批。
- 一个可独立验证、可回滚的行为对应一笔提交，相关实现、测试和文档可同批。用 `git add -- <文件>` 或按块暂存，提交前核对 `git diff --cached`，不夹带其他改动。提交信息用英文 Conventional Commits。满足本批完成定义后可本地提交，远程推送由用户执行。

## 命令

- 从仓库根目录执行；Windows PowerShell 中用 `$python = (Resolve-Path .\.venv\Scripts\python.exe).Path` 选择项目环境，模型配置见 [README](README.md)。
- 查看仓库状态：`git status --short --untracked-files=all`。
- 开发安装：`& $python -m pip install --no-build-isolation --no-index -e .`（离线，用 `.venv` 里的 setuptools；默认隔离构建会联网下载构建依赖，慢网下像卡住）。运行 `.\start.cmd` 启动置顶悬浮窗，关窗或按 Ctrl+C 后收尾退出并返回终端提示符，不要求确认，见 [README](README.md#快速开始)。
- 单元测试：`& $python -m unittest discover -s tests/unit`。配置 README 所列的素材变量后，运行 `& $python -m unittest discover -s tests/integration`；跳过不算通过实际模型验证。
- 文档校验：用可用的 Python 运行仓库外 `buildhelper` 的 `scripts/check_docs.py -root . -stage milestone`；追加 `--inventory` 查看文档归属。

## 禁止事项

- 本项目用仓库外的 `buildhelper` 校验文档，不把它安装到 Codex 或引入项目依赖。共享文档不写个人目录、设备标识、原始日志或凭据值。
- 目标、技术架构和里程碑分别维护在各自的规范文档中，保持单一归属。

## 仓库结构与运行要求

- 首版基线为 Windows x64 与 Python 3.12。`src/liebad/audio/` 负责采集与 PCM 转换，`src/liebad/session.py` 管理临时字幕和定稿，`src/liebad/ui/` 负责显示与交互；引擎与音源通过协议接入会话。
- 麦克风、抖音桌面客户端和浏览器的采集兼容性、悬浮窗置顶效果和首次出字延迟均以本机实测为准。

## 完成定义

- 修缺陷时保留最小复现，修复后以相同输入复测。文档改动后执行对应阶段的 `buildhelper` 检查，核对扫描范围和退出码。
- 阶段或关键改动需要独立只读审查时，按已有授权安排；审查者不编辑、不提交，主 agent 核对证据和未测项。
- 有可体验的改动，先自测，再给用户一条完整流程、预期结果和反馈项。只将用户确实试过且符合预期的场景记为通过；未实测标为「已实现，待实际验证」。首版验收以 [目标与范围](docs/goal.md) 为准。
- 组件职责、数据流或依赖发生变化时同步 [技术架构](docs/architecture.md)。
