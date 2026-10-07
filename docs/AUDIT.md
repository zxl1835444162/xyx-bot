# 项目体检报告（AUDIT）

> 对象：`xyx-bot`（赵氏集团 · 星月创作台）
> 体检时间：2026-10-07　体检人：代码侧完全重走了一遍（不是读文档得出的结论）
> 结论一句话：**功能是齐的、测试是绿的，但"工程形状"确实是边用边改堆出来的** ——
> 下面每一条都带硬数据，不是感觉。

---

## 一、先说好消息（不是重写，是"整理 + 加固"）

| 指标 | 实测 |
|---|---|
| 代码规模 | **77 个 `.py` 文件 / 28,411 行**（其中非空行 24,129） |
| 测试安全网 | **1015 项断言全绿**（纯逻辑 778 + GUI 191 + 启动 27 + 全功能 19）+ `main.py selftest` 通过 |
| 依赖健康 | 只有 `playwright` + `Pillow`，无私有依赖、无网络服务依赖 |
| 平台覆盖 | Windows / macOS / Linux 三平台 CI 已在跑（`.github/workflows/tests.yml`） |
| 打包链路 | Windows bat + macOS PyInstaller spec + GitHub Actions 自动打包，**链路是通的** |

> 行数口径说明：本表数字是"文件总行数"（`splitlines()`）。体检第一版我用了
> PowerShell 的 `Measure-Object -Line`，它不数空行，于是把 28,411 行报成了 21,248 行、
> 把 `ai.py` 报成 3,955 行（实际 5,378）。已全部更正。

所以这次不是"推倒重来"，而是**把已经跑得动的东西，整理成一个真正的工程**。

---

## 二、"纸糊感"的六个硬来源

### 1. 没有版本控制，改坏只能靠记忆

体检时项目目录里**没有 `.git`** —— 46 次历史提交只存在于远端，本地这份是"下载下来的快照"。
后果：任何重构都无法回滚、无法 diff、无法定位"哪次改动引入的问题"，只能整体重下。
**这是"纸糊"的第一因，也是我第一个修的。**

### 2. 测试把"文件布局"焊死了 —— 一改就崩，于是没人敢改

全项目 **32 处**测试直接拼路径或读源码文本做断言，例如：

```python
ai_src = (ROOT / "src" / "ai.py").read_text(encoding="utf-8")      # test_waiting.py:179
_vis_src = ai_src.split("def _visible(")[1].split("def _present(")[0]   # test_word_check.py:618
_src = (ROOT / "ui" / "theme.py").read_text(encoding="utf-8")      # test_configure_guard.py:123
and '"src"' in _spec and '"ui"' in _spec                            # test_portability.py:163
```

这不是"测试"，是**把函数顺序和文件名写进断言**：
把 `ai.py` 拆成两个文件、把 `_visible` 挪个位置，测试立刻红 —— 即使行为完全没变。
**这就是为什么这个项目只能"往上加"，不能"往里改"。** 重构第一步必须先拆掉这个焊点。

### 3. 一天 40 次提交、同一个 bug 反复修

远端 46 次提交里，**40 次挤在 2026-10-04 一天**，而且同一个问题连续出现：

```
★★★ 修「点登录后鼠标转圈、主界面永远不出来」的根因：字体解析每次都…
★★★ 修真根因：mainloop 嵌套 —— macOS 上「点登录后…」
★★★ 真根因确认并修复：macOS 上第 2 个 tk.Tk() 的事件循环不工作
★★★ 修复 macOS「点登录后鼠标转圈、主界面永远不出来」的直接原因：
```

这是典型的"用户报一个 → 猜一个原因 → 改 → 还在 → 再猜"。不是能力问题，是**缺少定位手段**：
当时没有"启动可见性探测"、没有崩溃现场落盘。这些后来补上了（很好），但补的过程本身
把临时调试脚本留在了仓库根目录。

### 4. 根目录是草稿纸：30 个文件里 12 个是一次性脚本

重构前根目录：

```
diag_click.py  diag_latency.py  diag_login.py  diag_probe.py
diag_review.py diag_review2.py  diag_review3.py       ← 同一件事的三个版本
audit_wait_args.py  verify_memory.py  smoke_gui.py
_t_e2e_full.py  _t_verify_shortcut.py                 ← 下划线开头的临时验证脚本
＋ 6 个计划/审计文档（223 KB）：ARCHITECTURE_PLAN / EFFICIENCY_REPORT /
  MACOS_PORT / MEMORY_AUDIT / PROJECT_UNDERSTANDING / UI_REDESIGN_PLAN
＋ 3 个 bat（start.bat / 启动.bat 几乎是同一个东西）+ 3 个 py 入口
```

`diag_review2.py` / `diag_review3.py` 这种"同一脚本的第 2、3 版"直接在文件名里体现迭代过程 ——
它就是"纸糊"的物证。

### 5. 入口与环境有三套说法

| 现象 | 具体 |
|---|---|
| 三个 py 入口 | `main.py`(560 行 CLI) / `run_gui.py`(GUI) / `launcher.py`(挑解释器) |
| 两个 venv | `.venv312`（GUI，带 tkinter）/ `.venv`（CLI）—— 用户得记住哪个是哪个 |
| bat 里写死解释器 | `start.bat`/`启动.bat`：`C:\Python312\python.exe`；`build.bat`：`C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe`（**这台开发机专属路径，别人机器上必挂**） |
| README 1283 行 | 产品说明 + 迭代日记 + 命令行速查 + 大段实测输出混在一起，章节编号出现"八点五/八点六/八点七/八点八/八点九" |

### 6. 几个巨石文件吃掉了全部改动

| 文件 | 行数 | 问题 |
|---|---|---|
| `xyxbot/ai.py` | **5,378** | AI 续写 / 审稿 / 一条龙 / 批量跑章 / 元素定位 / 等待策略 全在一个文件（100 个顶层定义） |
| `xyxbot/ui/pages/run.py` | 1,286 | 一个页面塞了所有流程的界面逻辑 |
| `xyxbot/ui/theme.py` | 1,270 | 主题 + 字体 + 卡片 + 重绘守卫 |
| `xyxbot/books.py` | 961 | 作品页交互 |
| `xyxbot/ui/main_window.py` | 902 | 主窗口 + 导航 |
| `xyxbot/novel.py` | 854 | 小说解析 |
| `xyxbot/ui/pages/ai_flow.py` | 727 | 与 `ai.py` 职责重叠 |
| `xyxbot/cli.py` | 560 | 原根目录 `main.py`，已搬进包内（根目录只剩 10 行薄壳） |

另有重复定义：`main()` 15 份（每个脚本自己一套）、`say()` 6 份（diag 脚本各自复制）、
`_shot()` 2 份、`create_book` 2 份；全项目 30 处 TODO/FIXME。

---

## 三、目标形态（对齐 `ma-c` / 寒山那套产品结构）

```
xyx-bot-main/
├── README.md              产品说明书（<300 行）        ← 现在 1283 行
├── CHANGELOG.md           变更记录（真实提交历史生成）  ← 新增
├── pyproject.toml         版本/依赖/入口（单一真相源）  ← 新增
├── xyxbot/                唯一业务包                   ← 由 src/ 改名
│   ├── __main__.py        python -m xyxbot 统一入口     ← 新增
│   ├── version.py         版本只有一处                 ← 新增
│   ├── core/              配置/路径/日志/工作区/计划
│   ├── browser/           浏览器/会话/登录/等待
│   ├── content/           小说/书籍/章节/AI（拆分后）
│   ├── platforms/ tasks/  平台与任务注册表
│   └── ui/                界面（原 ui/，含 pages/）
├── tools/                 开发与诊断脚本               ← 12 个脚本从根目录搬入
│   ├── diag/ audit/ dev/ scratch/
├── docs/                  架构/移植/审计/界面方案       ← 6 个文档从根目录搬入
├── tests/                 13 个用例 + 统一 runner       ← runner 新增
├── scripts/ packaging/    构建脚本与应用图标
└── main.py / 启动.bat     薄壳入口（真正的逻辑都在包里）
```

---

## 四、施工方案与验收方式

每一步都以**同一把尺子**验收：先跑 `tests/run_all.py`（1015 项断言），再跑
`main.py selftest`。绿了才进下一步，红了就回滚那一步的提交。

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 0 | `git init` + 基线提交（安全网） | ✅ 完成 |
| Phase A | 结构收拢：docs/、tools/、CHANGELOG、pyproject、入口与 venv 合一、统一测试 runner | ✅ 完成 |
| Phase A2 | **测试与文件布局解耦**（`tests/_support.py` + 21 处迁移，已验收全绿） | ✅ 完成 |
| Phase B | 包重构：`src`→`xyxbot`、`ui`→`xyxbot/ui`、`python -m xyxbot`、spec/CI 同步 | ✅ 完成 |
| Phase C | 拆巨兽：`main.py`(560→10 行薄壳) / `ai.py`(5378→12 子模块) / `ui/theme.py`(1270→5 子模块)；`ui/pages/run.py` **决定不拆**（一个页面的完整逻辑，理由见 REFACTOR） | ✅ 完成 |
| Phase D | CI 改用统一 runner（用例清单不再写死）+ README 重写为产品说明书 + 推送到 GitHub | ✅ 完成 |

> 施工细节与每步的验收输出见 `docs/REFACTOR.md`。

---

## 五、没有动的地方（有意保留）

* **业务行为一律不变**：不修改任何站点选择器、等待时长、风控规避策略、AI 提示词 ——
  这些东西是用户一点点试出来的经验，重构不得擅动。
* **`docs/` 里的 6 份历史文档照原样保留**（含里面的实测输出），只做归档与索引，
  因为它们是"当时为什么这么改"的唯一记录。
* **诊断脚本保留**（只是搬进 `tools/`）：它们解决的是真问题，只是不该躺在产品根目录。
