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

---

## 路径对照表（给翻历史文档用）

| 历史文档/旧注释里的路径 | 现在的位置 |
|---|---|
| `src/*.py` | `xyxbot/*.py`（Phase B 之后；当前仍在 `src/`） |
| `ui/*.py` | `xyxbot/ui/*.py`（同上） |
| `diag_login.py`（根） | `tools/diag/diag_login.py` |
| `smoke_gui.py`（根） | `tools/dev/smoke_gui.py` |
| `PROJECT_UNDERSTANDING.md` 等（根） | `docs/PROJECT_UNDERSTANDING.md` 等 |
