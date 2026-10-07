# 重构施工记录（REFACTOR）

> 这是**施工日志**，不是计划：每一步做完就写一段，包含"改了什么 / 为什么 / 验收输出"。
> 验收尺子只有一把：`tests/run_all.py`（1015 项断言）+ `main.py selftest`，绿了才算完成。
> 出问题就回滚那一步的提交 —— 这是 Phase 0 先建 git 的目的。

---

## Phase 0 · 安全网（2026-10-07）

**问题**：项目目录里没有 `.git`，46 次历史只存在于远端，本地改坏了只能整包重下。

**做法**

```bash
git init -b main
git config core.autocrlf false      # ★ 关键：否则 Windows 上会把工作流 yml / .sh 的 LF 换成 CRLF
git add -A && git commit -m "baseline: 重构前的完整现状"
```

**验收**

| 项 | 输出 |
|---|---|
| 提交 | `979b2d4 baseline: 重构前的完整现状（21,248 行 Python / 97 文件 / 1015 项断言全绿）` |
| 纳入版本控制 | 97 个文件 |
| 基线断言 | 纯逻辑 778 + GUI 191 + 启动 27 + 全功能 19 = **1015 项全绿**，`main.py selftest` 通过 |

**`core.autocrlf=false` 这一条不是洁癖**：Windows 上默认 `autocrlf=true` 会把
`.github/workflows/*.yml`、`scripts/*.sh` 的换行改成 CRLF，而 CI 里的 shell 脚本
一旦带 CRLF 会直接 `bad interpreter`。工作区的 `.gitattributes` 只覆盖了
`.bat/.sh/.command`，没覆盖 yml，所以必须在仓库级关掉自动转换。

---

## Phase A · 结构收拢（进行中）

### A1 12 个一次性脚本搬进 `tools/`

**做法**：用 `git mv` 搬家（保留历史，`git status` 显示为 `R` 而不是"删除+新增"）。

```
diag_click/diag_latency/diag_login/diag_probe/diag_review{,-2,-3}.py  → tools/diag/
audit_wait_args.py、verify_memory.py                                  → tools/audit/
smoke_gui.py                                                          → tools/dev/
_t_e2e_full.py、_t_verify_shortcut.py                                 → tools/scratch/
```

**顺带修好的真问题**：这些脚本原来在仓库根，用
`ROOT = dirname(abspath(__file__))` 当仓库根；搬进 `tools/<组>/` 后这个式子会指错，
脚本会在错误的目录下找 `artifacts/` 和 `src/`。已逐个改为退三层（`parents[2]`），
并用脚本断言 12 个文件全部改到、改对。

### A2 6 个计划/审计文档搬进 `docs/`

`ARCHITECTURE_PLAN / EFFICIENCY_REPORT / MEMORY_AUDIT / UI_REDESIGN_PLAN /
MACOS_PORT / PROJECT_UNDERSTANDING`，并新增 `docs/README.md` 给每个文档打
**现行 / 历史归档**标签（历史文档不删、不美化，但明确"路径是旧的"）。

### A3 用真实提交历史生成 `CHANGELOG.md`

不去编"迭代故事"，直接用远端 46 条真实提交生成：46 条 / 3 天（其中 **40 条挤在
2026-10-04 一天**，同一句"修「点登录后鼠标转圈、主界面永远不出来」的根因"出现 4 次）。
这份记录本身就是"为什么需要这次重构"的证据。

### A4 根目录只留入口与说明

搬家后根目录从 30 个文件降到 11 个：

```
.gitattributes  .gitignore  README.md  CHANGELOG.md  pyproject.toml
main.py  run_gui.py  launcher.py  build.bat  启动.bat
requirements.txt  requirements-gui.txt
```

### A5 入口与运行环境合一（消灭"两套 venv + 写死解释器"）

**问题**：`启动.bat` / `start.bat` 各自写死 `C:\Python312\python.exe`，`build.bat` 写死
`C:\Users\Administrator\.workbuddy\...\3.13.12\python.exe`（这台开发机专属），
而且 GUI 用 `.venv312`、CLI 用 `.venv`，用户得记住哪个是哪个。

**做法**

* 把"挑解释器 + 建环境 + 装依赖"全部收进 `launcher.py`（跨平台，无写死路径）：
  * 当前解释器已满足 `import tkinter, playwright, PIL` → 直接用（不折腾）
  * 否则用**带 tkinter 的**基解释器建 `.venv`（venv 不复制 tkinter，基解释器必须有）
  * Windows 上还会用 `py -0p` 把本机所有解释器列出来逐个试 tkinter，
    避免 `py -3` 挑到没装 tk 的新版本就报"找不到环境"
* `.venv` **只有一个**，GUI 与 CLI 共用；依赖清单是 `requirements-gui.txt`。
* `启动.bat` 只剩"找 boot 解释器 → `launcher.py`"10 行；`start.bat` 与它重复，
  已删除（`git rm`）；`build.bat` 变成 `launcher.py --setup` + `main.py browsers`。

**验收**

```
$ python launcher.py --setup
环境就绪：C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe

$ python launcher.py cli selftest
        ✓ 主窗口 + 9 个页面全部构建成功
        ✓ 关窗通知到了外层（事件循环能退出）
  ✓ 核心依赖齐全，界面也能构造起来
exit=0
```

### A6 搬家后翻车一次 —— 以及为什么"每步必跑全量测试"是硬规矩

`tests/test_waiting.py:387` 有一句 `import audit_wait_args`（直接 import 根目录的开发脚本），
搬到 `tools/audit/` 后立刻 `ModuleNotFoundError`。

更值得记住的是：我搬家前的"引用排查"**漏了这一条**（grep 命中了文档里的提及，却没命中这行代码）。
是"改完就跑全量测试"当场把它抓出来的 —— 所以这条规矩不是流程洁癖，是唯一的兜底。
真实代码引用只有这一处，已改用 `tests/_support.add_tools_to_path()` 定位。

### A7 统一测试 runner（`tests/run_all.py`）

**问题**：CI 里把测试文件名**硬编码**在 yml 里逐个跑（9 个 + 3 个 GUI），
新增测试很容易忘了加进去，"测试全绿"这句话就不完整了。

**做法**：runner 自动发现 `tests/test_*.py`，逐个子进程跑，解析每个用例自己打印的
`通过 N 项，失败 M 项`，结合退出码判定；带 300 秒超时（挂了就杀，不让 CI job 挂到上限）；
每个用例的完整输出落到 `artifacts/logs/tests/<用例>.log`（该目录已被 .gitignore 忽略）。

**验收**

```
$ python tests/run_all.py
  统一测试 runner · 12 个用例 · 日志 ...\artifacts\logs\tests
  ✓ test_all_features_macos    通过 19   失败 0     6.7s
  ✓ test_configure_guard       通过 19   失败 0     0.1s
  ✓ test_fixes                 通过 66   失败 0     4.3s
  ✓ test_font_cache            通过 37   失败 0     0.1s
  ✓ test_gui_pages             通过 191  失败 0     1.3s
  ✓ test_memory                通过 44   失败 0     0.1s
  ✓ test_novel_split           通过 98   失败 0     0.0s
  ✓ test_portability           通过 136  失败 0     0.7s
  ✓ test_runplan               通过 94   失败 0     1.4s
  ✓ test_startup               通过 27   失败 0     2.0s
  ✓ test_waiting               通过 100  失败 0     3.8s
  ✓ test_word_check            通过 184  失败 0     0.2s
  合计断言 1015 项 · 用例 12/12 通过
```

> 顺带记一条经验：**不要用 `pwsh` 管道去判断子进程退出码**。
> 这次 `& python tests/x.py 2>&1 | Out-String` 把 11 个本来全绿的用例读成了 `exit=2`，
> 差点误判成"搬家搬坏了"。改用 runner 的 `subprocess.run(capture_output=True)` 后
> 一切正常 —— 这也是把 runner 做成正式产物的原因之一。

### A8 测试与文件布局解耦（Phase A2 完成）

**做法**

* 新增 `tests/_support.py` 作为"文件长在哪"的唯一接口。两个关键设计：
  * `PKG_NAME = "xyxbot" if (ROOT/"xyxbot").is_dir() else "src"` —— 改名当天自动跟随，
    测试不用动；
  * `resolve_legacy("src/ai.py")` —— 旧的 `src/...` / `ui/...` 写法统一映射到现位置，
    把"改名的成本"从 18 处调用点降到 1 处映射。
* 7 个测试文件的 21 处硬编码路径改走 `S.pkg_file() / S.ui_file() / S.pkg_py_files() /
  S.ui_py_files() / S.all_source_files()`。
* spec 断言从「必须出现 `"src"` 和 `"ui"`」改成「必须出现当前业务包名 `S.PKG_NAME`」——
  界面包收进业务包之后这条断言依然成立（这是原先最脆的一处：它把旧结构写进了断言）。
* `test_word_check.py` 的 `_read()` 辅助函数内部改走 `_support`，一处改动覆盖 3 处旧路径调用。

**验收**：`tests/run_all.py` → 12/12 用例通过、1015 项断言全绿。

### A9 两次翻车记录（都是"脚本改文件"惹的祸，留作教训）

**① 换行符被悄悄改成 CRLF。** 我用 Python 脚本改过的 21 个文件（7 个测试 +
12 个 tools 脚本 + CHANGELOG）整份变成 CRLF —— 因为 Windows 上
`Path.write_text()` 会把 `\n` 写成 `\r\n`，而 `read_text()` 又会把它读成 `\n`，
于是 git diff 显示"整文件重写"（5907 插入 / 5896 删除），跨平台协作也会出问题。

修法：写回 LF，并在 `.gitattributes` 里加 `* text=auto eol=lf` 从根上防止复发。

**② `.gitattributes` 规则顺序写反。** 我第一版把 `*.bat text eol=crlf` 写在
`* text=auto eol=lf` **前面** —— 但 .gitattributes 里**最后匹配的规则生效**，
结果 `*` 把 `*.bat` 的例外吃掉了，声明与实际行为不符。

修法：通用规则在前、具体例外在后（现在是：默认 LF → `*.bat/*.cmd` CRLF →
shell 脚本与二进制收尾）。用 `git check-attr eol -- <文件>` 逐个验证过。

> 结论写进规矩：**改文件要用脚本时，必须显式指定换行符**；
> 改完必须 `git status` / `git diff --stat` 看一眼改动规模是否合理 ——
> 这次的"5907 插入"就是最直接的报警信号。

## Phase B · 包重构（完成）

### B1 `src/` → `xyxbot/`，`ui/` → `xyxbot/ui/`

**为什么值得做**：`src` 是个"垃圾抽屉"名字，而界面与业务是两个平级包、互相 import，
读者看不出谁是产品。改成一个以产品命名的包（`xyxbot`），界面收进包内 ——
`import xyxbot.ui.theme` 一眼就知道归属，`python -m xyxbot` 也才顺理成章。

**做法**：`git mv` 两个目录（保留历史），然后按 **6 种形态**重写导入：

```
from src.X import Y   →  from xyxbot.X import Y        （220 处）
from src import X     →  from xyxbot import X
import src.X          →  import xyxbot.X
from ui.X import Y    →  from xyxbot.ui.X import Y     （ 25 处）
from ui import X      →  from xyxbot.ui import X
import ui.X           →  import xyxbot.ui.X
```

共 **44 个文件、253 行**。另外同步了 7 处配套引用：spec 的 `collect_submodules`、
CI 里构造信息文件的路径、审计工具的 glob 模式、以及测试里
"按旧相对路径做键/比较"的 4 处（改走 `_support.legacy_rel()`，历史断言不用重写）。

**过程中修掉两个真问题**：

1. `_support.resolve_legacy()` 里我写了 `lstrip("./")` —— 而 Python 的 `lstrip`
   收的是**字符集**不是前缀，于是 `.github/workflows/*.yml` 被削成 `github/...`，
   `test_portability` 两项直接红。改成显式判断前缀。
2. 界面收进包内后，`_support.all_source_files()` 把 `xyxbot/ui/**` 数了两遍
   （断言数变成 1016，比基线多 1）→ 用集合去重。

这两条都是**测试立刻抓出来的** —— 这也是为什么每一步都必须跑全量（1015 项）。

**验收**：`tests/run_all.py` → 12/12 用例通过、**1015 项断言全绿（与重构前基线一字不差）**。

### B2 CLI 归位，两种入口等价，版本单一真相源

| 改动 | 说明 |
|---|---|
| `main.py` → `xyxbot/cli.py` | 560 行 CLI 从根目录搬进包内 |
| 根 `main.py` | 变成 10 行薄壳：加 `sys.path` 后转交 `xyxbot.cli.main` |
| `xyxbot/__main__.py` | 新增，`python -m xyxbot <命令>` 与 `python main.py <命令>` 完全等价 |
| `xyxbot/version.py` | 新增，版本号**唯一真相源** |
| `xyxbot/_buildinfo.py` | 改成 `from xyxbot.version import VERSION`；CI 只覆盖 SHA/BUILT_AT（原来 CI 在这里又写死了一次 "1.0.0"） |
| `pyproject.toml` | 加 `[project.scripts] xyxbot = "xyxbot.cli:main"` |

**验收**

```
$ python main.py                    # 薄壳 → 列出命令，exit=1（无参数时的约定）
  可用命令: login, session, prepare, check, diag, selftest, recon, logout,
           books, open, ai, review, auto, batch, tasks, platforms, run, studio, browsers
$ python main.py selftest           # exit=0
$ python -m xyxbot selftest         # exit=0
$ python -c "from xyxbot import _buildinfo; print(_buildinfo.describe())"
  v1.0.0 build=dev at=dev
```

### C0 拆巨兽之前必须先做的事（完成）

**为什么**：`ai.py` / `theme.py` 这些文件一旦拆成子包，两类历史断言会立刻失效：

1. 直接读文件的：`S.ui_file("theme.py").read_text()`、`S.read(S.pkg_file("ai.py"))`
   —— 拆完之后路径上没这个文件了；
2. 切源码的：`源码.split("def A(")[1].split("def B(")[0]`
   —— 函数搬到别的文件就切不到了。

**做法**：在 `tests/_support.py` 加一个接口 `module_source(rel)`：

```python
module_source("ui/theme.py")   # 单文件模式 → 该文件内容
module_source("ui/theme.py")   # 拆分之后  → 包内所有 .py 的拼接（自动过滤 __future__ 行）
```

拼接时要过滤 `from __future__ import ...`：它必须位于文件开头，拼起来会变成语法错误，
而对静态检查毫无意义（这个是写完才发现、被 `ast.parse` 当场抓出来的）。

然后把 17 处断言迁到新接口：

* 整文件读 → `S.module_source(...)`（theme.py 4 处、ai.py 2 处、chapters.py 1 处）
* 切源码 → `S.function_source("A", "B")`（ai.py 3 处、theme.py 1 处、books.py 3 处）
* 动态导入 → `importlib.import_module(f"{S.PKG_NAME}.ai")`（不再假设 ai 是单个文件）
* **顺手收紧一处审计**：test_waiting 的"没有裸 `inner_text()`"原来只扫
  `PKG.glob("*.py")`（不含子目录），拆包后会漏掉新子包 → 改为 `S.pkg_py_files()`，
  现在连子包和 ui/ 一起审。

**验收**：`tests/run_all.py` → 12/12 用例通过、1015 项断言全绿。

## Phase C1 · 拆开 `xyxbot/ai.py`（5378 行 → 12 个子模块）

**结果**

```
xyxbot/ai/
├── __init__.py    64 行   按拓扑序全量再导出（100 个名字）
├── selectors.py  288 行   选择器与站点常量表（AI_SELECTORS 等 14 个）
├── elements.py   334 行   底层元素定位/点击/填写/取消标志（15 个）
├── dialog.py     367 行   续写弹窗与「残留结果页」
├── current.py     86 行   读取页面「当前值」（模型/档位/快捷指令/审稿要求）
├── model.py      414 行   模型、联想档位、剧情
├── shortcuts.py  492 行   快捷指令面板
├── relate.py     246 行   「关联最近 N 章」
├── body.py       308 行   正文编辑器与字数统计
├── generate.py   520 行   生成与等待
├── chapters.py   292 行   章节导航
├── review.py     914 行   AI 审稿
└── flows.py      953 行   对外流程：续写/审稿/一条龙/批量跑章
```

最大文件从 **5378 行降到 953 行**；对外接口零变化。

**做法（机械 + 可验证）**

1. 按 AST 取顶层语句，**按原始行区间整段搬运** —— 连注释、空行、"为什么这么写"的
   实测记录一起搬，不重排、不改写。
2. 一张「名字 → 目标模块」表分组（就是上面 12 个模块的职责划分）。
3. 为每条顶层语句算出它**引用了哪些顶层名字**（Name 读取，扣除参数/局部变量），
   据此得出模块间依赖，再做**拓扑排序**。依赖是客观事实，交给程序算比人拍脑袋可靠：
   ```
   selectors → elements → dialog → current → model → shortcuts → relate → body
             → generate → chapters → review → flows
   ```
4. `__init__.py` 按拓扑序全量再导出（含 `_visible` 这种私有名），
   所以外部 `from xyxbot import ai as AI; AI.xxx(...)` 一行都不用改。

**过程中抓到并解决的真问题（都是"手拆一定会踩"的）**

| # | 问题 | 表现 | 处理 |
|---|---|---|---|
| 1 | **循环依赖** | `shortcuts ↔ review`：`pick_shortcut→current_review_requirement`，`pick_review_requirement→pick_shortcut` | 把"读页面当前值"的读取器抽成 `ai/current.py`，依赖变单向 |
| 2 | **相对导入失效** | `from . import config as C` 原指 `xyxbot.config`，搬进子包后变成 `xyxbot.ai.config` → ImportError | 统一改成绝对导入 `from xyxbot import config as C` |
| 3 | **会被重新赋值的模块级状态** | `LAST_DECISION` 由 `ai_continue` 写入，UI 用 `AI.LAST_DECISION` 读 → star-import 只留导入时副本，UI 会读到**旧章的数据** | 用 PEP 562 模块级 `__getattr__` 转发到 `ai/flows.py`；实测改值后读到的立刻是当前值 |
| 4 | 测试里 4 处 `open(MOD.__file__).read()` | 拆包后 `__file__` 指向 64 行的 `__init__.py`，18 条断言全红 | 改用 `S.module_source("src/ai.py")` |

**验收**：`tests/run_all.py` → 12/12 用例通过、**1015 项断言全绿**；`python -m xyxbot selftest` → exit 0。

### C1 修正 · 第一次拆丢了 181 行注释（已修，现在 0 丢失）

第一版拆完，测试全绿、函数一个不少 —— 但我做了一次**注释审计**，结果很难看：

```
注释行：原 776 条，新包覆盖 595 条，丢失 181 条
   丢失: # ★★ 为什么要有这个（用户 2026-10-04 需求）
   丢失: # 所以这里做的是**协作式中止**：
   丢失: # 批量跑章动辄 100 章、几个小时。原来的界面**没有停止按钮** ……
```

原因：AST 给的 `lineno` 指向 `def/class/赋值` 那一行，**不含上方注释块**；
我按 `lineno..end_lineno` 整段搬运，于是所有"函数上方的说明"都被留在了原地。

修法：搬运前先把起点往上扩 —— 连续的空行和 `#` 注释都算这条语句的门牌，
但不越过上一条语句（`block_start()`）。另外原文件的**模块 docstring**
（那份"流程 + 每步实测选择器"的说明）也要留：现在放在 `ai/__init__.py` 的包文档开头。

修完复核：

```
注释行：原 776 条，新包覆盖 776 条，丢失 0 条
顶层函数/类 83 个，重复定义 无
def ai_auto_chapter( / def _visible( / def wait_generation( 各出现 1 次
```

> 教训：**"测试全绿"不等于"没丢东西"**。行为测试看不见注释，而注释正是这个项目
> 最贵的资产（每条"实测 15 秒白等"都是真机跑出来的）。所以拆完必须再做一次
> **文本级完整性比对**：注释覆盖率 + 代码行双向 diff + 顶层定义去重。

**验收**：`tests/run_all.py` → 12/12 用例通过、1015 项断言全绿。

> 第 3 条值得单独记一笔：它不会报错，只会让界面显示"上一章的字数与决策" ——
> 是最典型、也最难查的拆分副作用。用"会不会被重新赋值"来筛选需要转发的名字，
> 是从 `global` 声明反查出来的（全项目只有 `LAST_DECISION` 一个）。

---

## 路径对照表（给翻历史文档用）

| 历史文档/旧注释里的路径 | 现在的位置 |
|---|---|
| `src/*.py` | `xyxbot/*.py`（Phase B 之后；当前仍在 `src/`） |
| `ui/*.py` | `xyxbot/ui/*.py`（同上） |
| `diag_login.py`（根） | `tools/diag/diag_login.py` |
| `smoke_gui.py`（根） | `tools/dev/smoke_gui.py` |
| `PROJECT_UNDERSTANDING.md` 等（根） | `docs/PROJECT_UNDERSTANDING.md` 等 |
