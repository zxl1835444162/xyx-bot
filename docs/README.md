# 文档索引（docs/）

本目录是**历史记录 + 现行规范**两类文档的归档处。看之前先认一下标签：

| 文档 | 标签 | 还准吗 | 讲什么 |
|---|---|---|---|
| [`AUDIT.md`](AUDIT.md) | **现行** | ✅ | 项目体检报告：结构问题的硬数据、"纸糊感"的六个来源、目标形态与施工分期 |
| [`REFACTOR.md`](REFACTOR.md) | **现行** | ✅ | 施工记录：每一步改了什么、验收到什么输出、为什么这么做 |
| [`ARCHITECTURE_PLAN.md`](ARCHITECTURE_PLAN.md) | 历史归档 | ⚠️ 部分 | 最早的分包设想（`src/` + `ui/` 的来源）；结论已被 AUDIT 取代 |
| [`UI_REDESIGN_PLAN.md`](UI_REDESIGN_PLAN.md) | 历史归档 | ⚠️ 部分 | 界面从 7 项导航收敛为 3 项的设计过程 |
| [`MACOS_PORT.md`](MACOS_PORT.md) | 历史归档 | ✅ 参考价值高 | macOS 移植全过程：Tk/NSApp 崩溃根因、打包、签名、DMG、排障 |
| [`EFFICIENCY_REPORT.md`](EFFICIENCY_REPORT.md) | 历史归档 | ⚠️ 部分 | 等待策略与效率实测（含各选择器的实测耗时），仍可当"实测数据库"查 |
| [`MEMORY_AUDIT.md`](MEMORY_AUDIT.md) | 历史归档 | ⚠️ 部分 | 内存与卡顿审计（`<Configure>` 自激那段） |
| [`PROJECT_UNDERSTANDING.md`](PROJECT_UNDERSTANDING.md) | 历史归档 | ⚠️ 部分 | 一份很长的"项目理解"笔记，夹带大量当时的命令行实测输出 |

**怎么用这个目录**

* 想了解**现在**的结构与规矩 → 只看 `AUDIT.md` + 项目根的 `README.md`。
* 想查**当时为什么这么改**（尤其是 macOS 那些崩溃、效率那些实测数字）→ 翻对应的历史归档，
  里面的实测输出照原样保留，没有美化。
* 历史归档里的**代码路径是旧的**（当时 `src/` `ui/` 还在，脚本还在根目录），
  迁移到新路径的方法见 `REFACTOR.md` 的"路径对照表"。

开发与诊断脚本在 [`../tools/`](../tools/)：
`tools/diag/`（登录态/点击/延时/探针/复审）、`tools/audit/`（等待参数审计、内存校验）、
`tools/dev/`（GUI 冒烟）、`tools/scratch/`（一次性验证脚本，保留供追溯）。
