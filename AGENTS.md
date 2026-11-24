# AGENTS.md — Liebad

## 命令

- 查看仓库状态：`git status --short --untracked-files=all`。
- 文档校验使用仓库外的 `buildhelper`，用可用的 Python 运行其 `scripts/check_docs.py -root . -stage founding`。追加 `--inventory` 查看文档归属。
- 项目处于立项阶段，构建、测试和启动命令待实现并实测。

## 禁止事项

- 本项目通过仓库外的 `buildhelper` 副本执行文档校验。
- 目标、技术架构和里程碑分别维护在各自的规范文档中，保持单一归属。

## 环境事实

- 首个验证平台为 Windows。立项时本机实查为 Windows 25H2，系统构建号 `26200`。
- 麦克风、抖音桌面客户端和浏览器的采集兼容性、悬浮窗置顶效果和首次出字延迟均以本机实测为准。

## 完成定义

- 文档改动后执行对应阶段的 `buildhelper` 检查，核对扫描范围和退出码。
- 首版验收以 [目标与范围](docs/goal.md) 的成功标准为准。
- 组件职责、数据流或依赖发生变化时同步 [技术架构](docs/architecture.md)。
