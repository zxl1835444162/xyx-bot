# 架构改良规划（xyx-bot）

> 本文档记录：① 本轮**已完成的修复与重构**；② 后续**分阶段的架构改良计划**。
> 配套：`PROJECT_UNDERSTANDING.md`（项目完全理解报告）、`tests/test_fixes.py`（回归测试）。

---

## 一、已完成（Round 1 缺陷修复 + Round 2 架构改良）

### 1.1 缺陷修复（全部经回归测试验证）

回归测试：`tests/test_fixes.py` —— **47 项全部通过**。

| # | 缺陷 | 位置 | 修法 |
|---|---|---|---|
| G1 | ★★ `BrandButton` 的「禁用」不生效（忙碌时可重复点击） | `ui/theme.py` | 重写 `config()/configure()`，把 `state` 转发给 `set_enabled()`；`_run_guarded` 改用 `set_enabled()` 双保险 |
| G2 | ★★ 主线程直接 `App.stop()`（跨线程操作 Playwright） | `ui/main_window.py` | 新增 `_stop_app()`，把 `stop()` 投递到常驻线程；`_clear_session`/`_prepare_clear`/`_on_window_close` 统一走它 |
| G3 | ★★ `_ai_batch_go` 用陈旧的 `_ai_book_index` | `ui/main_window.py` | 抽出 `_parse_book_index()`，四个入口（续写/审稿/一条龙/批量）统一调用 |
| G4 | ★★ 单章续写不替换 `#@`（UI 却在教用户用 `#@`） | `ui/main_window.py` | 新增 `_resolve_current_chapter_no()`；`_ai_go`/`_ai_both_go`/`_update_tpl_preview` 全部传 `current=` |
| G5 | `_do_split` 后台线程读 tk 控件；`_prepare_save_now` 后台线程写日志 | `ui/main_window.py` | 主线程先取值再进 worker；`self.log` 改 `self.after(0, ...)` |
| G6 | `_prepare_clear` 重复定义（存根被静默覆盖） | `ui/main_window.py` | 删除重复份，统一委托 `_clear_session()` |
| G7 | 主窗口无关闭清理 → 残留浏览器进程 | `ui/main_window.py` | 绑定 `WM_DELETE_WINDOW` → `_on_window_close()` → `_stop_app()` |
| G8 | 「运行配置」页浏览器路径是死配置 | `ui/main_window.py` | 新增 `_browser_path_value` 持久字段 + `_browser_path_override()`，5 处 `App(...)` 全部接线；`_detect_browser` 同步 |
| G11 | `_run_guarded` 末尾不可达 `return True` | `ui/main_window.py` | 删除 |
| #1 | `ai_auto_chapter` 返回缺 `ok`/`reason` → 批量失败原因丢失 | `src/ai.py` | 统一返回契约，所有 return 路径都设 `ok`/`reason`；`ai_batch_chapters` 改读 `r["ok"]` 并打印失败原因 |
| #2 | `SLOW_MO` 是死配置（定义了没传） | `src/browser.py` | `launch(..., slow_mo=C.SLOW_MO)`，并在模块顶部导入 `config` |
| #7 | `prepare_session` 的 `ok` 虚高（可能沿用无效登录态） | `src/login.py` | `usable = saved or (info.saved and logged)`；`ok = logged and usable` |
| #8 | `is_logged_in` 第 3 路兜底过宽（`about:blank` 也判已登录） | `src/login.py` | 新增 `_is_site_url()`，要求 URL 确实在站点域名下 |
| #9 | `render_for_batch` 把未知代号静默当成「当前章」 | `src/novel.py` | 只转换**存在**的代号；未知代号原样保留 + 告警。新增 `_code_numbers()` |
| #10 | `_guess_account` 候选键与站点真实键不符 → 账号恒为空 | `src/session.py` | 候选键加入 `userStorage`（实测真实键名）+ 递归查找。**实测已能读出「公主请发财」** |
| #11 | `browser_detector` 重复探测 + 同路径当成两个浏览器 | `src/browser_detector.py` | 结果缓存；按优先级排序后去重（`_same_path`）；`PRIORITY_ORDER` 收口到类常量 |
| — | 死代码（0 引用的私有方法） | `ui/main_window.py`、`src/ai.py` | 删除 `_prepare_then_both`、`_run_on_pw_thread`、`_count_words`、`_preview_ai_plot`、`_close_tip_dialog` |

#### Round 2 追加修复（本轮后半段）

| # | 缺陷 | 位置 | 修法 |
|---|---|---|---|
| L1 | ★★ **多线程日志粘连乱码**（实测确认的真 bug） | `src/logging_redirect.py` | `print()` 会触发两次 `write`（正文+换行），原实现每次各自加锁写文件 → 8 线程 400 行只剩 **203 行有效**、出现 `t5-48t3-49` 这种粘连。改为**每线程行缓冲**，攒到换行再原子落盘；未换行片段在 `flush()/close()` 补写 |
| L2 | ★ **持锁调用 sink → 跨线程投递 / 潜在自死锁** | `src/logging_redirect.py` | sink 与终端改到**锁外**调用（GUI 的 sink 是 `root.after`；若 sink 反过来写日志会自死锁）。并只在有内容时送 sink（避免空行刷屏） |
| L3 | 日志文件每行 open/close 一次 | `src/logging_redirect.py` | 改为长期持有句柄；`restore()`/`close()` 负责关闭（可多次调用） |
| L4 | ★ `config.CDP_PORT` 未接线 → 文档承诺的「CDP 接管」**无入口** | `src/app.py`、`src/browser.py` | `App.start` 在未显式指定 `browser_path` 时读 `CDP_PORT` 并自动走接管模式；`open_browser` 在 `p=None` 时自行启动 playwright 实例（原来会 `AttributeError`） |

> 验证：日志相关 7 项已并入 `tests/test_fixes.py`（含并发 400 行完整性断言）；
> CDP 接线由静态检查 + `XYX_CDP_PORT=9222` 环境变量行为验证。

### 1.2 架构重构：抽出 `BrowserSession`

**问题**：`MainWindow` 自己养着常驻 Playwright 线程 + 任务队列 + 互斥锁（约 90 行），
夹在页面构建代码中间。后果是：

- 「Playwright 必须同线程」这条规则**只写在注释里**，没有机制强制 → 真的出现了跨线程调用（G2/G5）。
- 窗口类同时管界面、线程生命周期、任务互斥，职责混杂。
- 无法脱离 tkinter 单测线程逻辑。

**做法**：新建 `ui/browser_session.py`（211 行，**零 tkinter 依赖**）：

```python
class BrowserSession:
    submit(fn)                    # 投递到常驻线程串行执行
    ensure_app()                  # 惰性创建 App（只在常驻线程里调用）
    run_guarded(name, worker, on_done)  # 互斥 + 投递 + 完成释放
    stop(on_done)                 # ★ 线程安全关浏览器
    shutdown(wait)                # 结束常驻线程
    is_worker_thread() / busy / busy_name
```

`MainWindow` 侧只留薄封装（`_make_app` / `_session_log` / `_run_guarded`），
页面代码从 `self._pw_queue.put(worker)` 改为 `self.session.submit(worker)`（10 处）。

**收益**：
- 「所有浏览器操作走同一个线程」现在是**结构性保证**，不再依赖自觉。
- 线程/互斥逻辑**可单测**（`tests/test_fixes.py` 第 1 组共 15 项，全绿）。
- 异常不会让常驻线程退出（测试已覆盖）。

> ⚠️ 诚实说明：这一步是**架构改良的地基**，不是「让文件变小」。
> `ui/main_window.py` 从 3230 行变为 3268 行（去掉约 130 行死代码与重复，
> 但新增了带注释的薄封装与修复）。**真正的瘦身在下面第二阶段的计划里。**

### 1.3 架构重构（阶段二）：拆分 `ui/main_window.py`

**结果：3230 行 → 659 行（↓80%）**，页面与业务动作全部按「一块一模块」拆到 `ui/pages/`。

| 文件 | 行数 | 职责 |
|---|---:|---|
| `ui/main_window.py` | **659** | 只剩窗口骨架：顶栏 / 侧栏 / 滚动区 / 日志面板 / 状态栏、页面路由 `show_page`、浏览器生命周期、任务执行与互斥、关窗清理 |
| `ui/defaults.py` | 74 | ★ 新增：GUI 默认值单一出处（原来散在窗口模块顶部，拆页后会循环导入） |
| `ui/browser_session.py` | 211 | 常驻 Playwright 线程 + 队列 + 互斥（阶段一成果） |
| `ui/pages/content.py` | 592 | 「小说分章」页构建（最大页面） |
| `ui/pages/chapters.py` | 1025 | 分章、章节列表、指令模板、章节菜单、工程存取 |
| `ui/pages/ai_flow.py` | 632 | 续写 / 审稿 / 一条龙 / 批量跑章（界面侧编排） |
| `ui/pages/account.py` | 530 | 「星月账号」页 + 流程准备动作 |
| `ui/pages/books.py` | 250 | 「打开作品」页 + 同名候选 |
| `ui/pages/config_io.py` | 195 | workspace.json 的记住/回填 |
| `ui/pages/overview.py` | 93 | 「概览面板」页 + `MetricCard` |
| `ui/pages/settings.py` | 78 | 「运行配置」页 + 浏览器检测 |
| `ui/pages/tasks.py` | 52 | 「任务中心」页 |
| `ui/pages/about.py` | 48 | 「关于本机」页 |

**做法：mixin 组合**（不是独立函数）：

```python
class MainWindow(AboutPage, AccountPage, AiFlowMixin, BooksPage,
                 ChaptersMixin, ConfigIOMixin, ContentPage, OverviewPage,
                 SettingsPage, TasksPage, tk.Tk):
    ...
```

为什么是 mixin：页面方法大量读写 `self._xxx` 控件字段（约 200 个）。
改成独立函数就得传一堆积或引入上下文对象，改动面爆炸；
mixin 让方法继续以 `self` 访问，**原有调用点零改动**，
因此可以**一页一页迁**，每迁一页跑一次冒烟。

**顺带修掉的**：
- 契约不清晰 —— 现在每个页面模块的 docstring 明确标注它依赖哪些外部方法。
- `_page_overview` 原来重复调用 `_session_info()` 4 次（4 次磁盘读取）→ 改为只读一次。
- 提取后清理了 **24 个失效导入**（窗口模块不再需要的 `Card`/`DarkEntry`/`DEFAULT_*` 等）
  以及各页面模块里被过度复制的导入（共 13 处）。
- 原本重复定义在窗口模块顶部的 19 个默认值常量收口到 `ui/defaults.py`。

### 1.4 回归测试

| 文件 | 覆盖 | 项数 |
|---|---|---:|
| `tests/test_fixes.py` | `BrowserSession` 线程/互斥、`BrandButton` 禁用、`#@` 渲染、URL 判据、`slow_mo` 接线、**日志重定向并发完整性**、`ai_auto_chapter` 契约、账号提取、检测器缓存 | **55** |
| `tests/test_gui_pages.py` | 7 页构建、~25 个关键控件、mixin 归属（页面代码确实已拆出）、内容页核心逻辑 | **84** |

合计 **139 项，全绿**。两个文件都不依赖 pytest，直接 `python tests/xxx.py` 即可。

> 其中「日志并发完整性」是一条**实测发现的既有真 bug**：
> 8 线程各写 50 行，修复前日志文件里只有 203 行是有效独立行
> （其余被粘成 `t5-48t3-49t6-48` 这种乱码）。这也是「一条龙批量跑章
> 日志难读」的根因之一。

---

## 二、后续架构改良计划

### 2.1 现状评估

| 文件 | 行数 | 状态 |
|---|---:|---|
| `ui/main_window.py` | 659 | ✅ 已达标（原 3230） |
| `src/ai.py` | **3372** | ★ 剩余的唯一「上帝模块」 |
| `ui/pages/chapters.py` | 1025 | 尚可；后续可再拆「分章 / 模板 / 工程」三块 |
| `ui/theme.py` | 729 | 纯组件库，健康；缺尺寸常量体系 |
| 其余 | <650 each | 健康 |

**结论**：GUI 侧的臃肿已解决。**下一个、也是最后一个大头是 `src/ai.py`（3372 行）。**

### 2.2 阶段三：拆分 `src/ai.py`

**目标**：按「流程」分模块，公共选择器/原语下沉为 `_base`。

```
src/ai/
├── __init__.py      # 再导出全部公开函数（★ 保持向后兼容，调用方零改动）
├── selectors.py     ~250  AI_SELECTORS / MODEL_CARD_HINT / 锚点常量 / NUISANCE
├── primitives.py    ~500  _shot/_visible/_click_first/_fill_first/dismiss_dialogs
├── model.py         ~350  current_model/set_associate_level/select_model
├── shortcut.py      ~320  open/wait/pick/close shortcut panel
├── generate.py      ~400  gen_done 判定 / wait_generation / 字数决策 / 采纳
├── review.py        ~500  审稿抽屉全套（开/填/选要求/生成/等待/替换）
├── editor.py        ~250  正文编辑器 / 章节切换 / 全选
├── pipeline.py      ~600  ai_continue / ai_review / ai_auto_chapter / batch
└── (ensure_chapter 归 editor)
```

**关键约束**：`src/ai/__init__.py` 必须**再导出所有原公开名**，
保证 `main.py` / `ui` / `tasks` 的 `AI.xxx(...)` 调用**一个都不用改**。

```python
# src/ai/__init__.py
from .selectors import AI_SELECTORS, MODEL_CARD_HINT, LAST_DECISION  # noqa
from .pipeline import ai_continue, ai_review, ai_auto_chapter, ai_batch_chapters
from .editor import open_chapter, get_body_text, select_all_body, ensure_chapter
...
```

⚠️ 注意 `LAST_DECISION` 是**模块级可变全局**，被 `ai_continue` 写、GUI 读。
拆分后它必须**只定义一处**（`selectors.py` 或新的 `state.py`）并被子模块
`import` 使用，否则会变成两份互不相干的变量（静默失效）。
**建议顺手改成函数返回值 + 一个显式 getter**，消除这个隐患。

**验收**：`python main.py ai --help` 行为不变；回归测试全绿；
`grep -c "def " src/ai/*.py` 每个文件 < 700 行。

### 2.3 阶段四：清理剩余技术债

| 项 | 说明 |
|---|---|
| `ui/theme.py` 尺寸常量 | 现在所有宽高/radius/pad 都是调用点字面量。抽 `SIZE = {...}` 与间距体系，让 UI 可整体缩放 |
| 主题「集中」的漏洞 | `theme.py` 里仍有绕过 `COLOR` 的硬编码色（ghost hover `#262c36`、danger `#ff3742`、日志底 `#0b0f14`），`login_window.py` 也有 3 处。全部收进 `COLOR` |
| `shot.py` 无调用者 | 开发期工具，`ui/` 还依赖 Pillow 但未在任何 requirements 里声明 → 要么删、要么显式声明依赖 |
| `chapter_files.py` 全无调用者 | 移植自参考项目、GUI/CLI 都不用它（GUI 用 `novel.py`）。要么接进「内容资产」页，要么标注为 legacy |
| `_t_e2e_full.py` / `_t_verify_shortcut.py` | 硬编码作品名与章节，改名 `tests/e2e_manual_*.py` 并参数化（读环境变量） |
| `ai.py` 硬编码几何坐标 | `mouse.click(rb.x-120, rb.y-60)` 等 8 处。站点换分辨率即失效，应改为「按刻度标签 x 计算」为主路径、坐标仅最终兜底并**打印警告** |
| 静默吞异常 | 全项目 `except Exception: pass` 极多。至少给**关键判定**（模型回读、联想档位回读）加上「读不到 → 视为失败并截图」的语义，而不是当成已满足 |
| CDP 接管未接线 | `config.CDP_PORT` 无引用。要么接进 `App`/「运行配置」页，要么从文档里降级说明 |
| 任务中心与 GUI 配置脱节 | 任务只读 `XY_*` 环境变量，界面填的无效。建议让任务优先读 `workspace.json`，环境变量作为覆盖 |

### 2.4 建议顺序与工作量

| 阶段 | 内容 | 风险 | 工作量 | 状态 |
|---|---|---|---|---|
| 一 | 缺陷修复 + `BrowserSession` | 低 | 中 | ✅ 已完成 |
| 二 | 拆 `ui/main_window.py`（逐页 mixin） | 中 | 大 | ✅ 已完成 |
| 三 | 拆 `src/ai.py`（保持再导出兼容） | 中 | 大 | ⬜ 待做 |
| 四 | 技术债清理（可增量挑做） | 低 | 中 | ⬜ 待做 |

**建议**：阶段三单独占一轮，结束跑两个测试文件确保始终可运行。
不要在同一次改动里同时拆 GUI 和 AI（出问题难以定位）。

---

## 三、如何验证

```bat
:: 全量回归（139 项 = 55 + 84）
.venv312\Scripts\python.exe tests\test_fixes.py
.venv312\Scripts\python.exe tests\test_gui_pages.py

:: 语法编译
.venv312\Scripts\python.exe -m compileall -q src ui main.py tests

:: CLI 冒烟
.venv312\Scripts\python.exe main.py tasks
.venv312\Scripts\python.exe main.py session

:: GUI 窗口构建冒烟（不打开浏览器）
.venv312\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from ui.main_window import MainWindow; w=MainWindow(username='t'); w.withdraw(); [w.show_page(p) for p in ['overview','account','books','tasks','content','settings','about']]; print('OK'); w.destroy()"
```

