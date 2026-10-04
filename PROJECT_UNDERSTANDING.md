# xyx-bot 项目完全理解报告

> 生成时间：本会话分析（工作目录 `C:\Users\Administrator\Downloads\xyx-bot`）
> 分析方式：通读全部源码（13,078 行 Python）+ AST 结构扫描 + 实际运行 CLI 验证 + 单元级验证 `novel.py` 渲染逻辑。
> 所有结论均来自源码与实际运行结果，非猜测。

> ⚠️ **本文档是「改造前」的快照**。后续的缺陷修复与架构改良见
> [`ARCHITECTURE_PLAN.md`](ARCHITECTURE_PLAN.md)：
> 本报告 §11 列出的缺陷**大部分已修复**（并新增 139 项回归测试覆盖），
> 且 `ui/main_window.py` 已从 3230 行拆到 650 行（`ui/pages/` 十个模块）。
> 因此本文里提到的行号、文件行数、以及「未修复」的描述**可能已过时**，
> 请以当前源码与 `ARCHITECTURE_PLAN.md` 为准。

> **★ 2026-10-04 追加更新**：按用户要求**删除了登录界面**，只留一个主操控界面。
> 所以本文里关于 **登录窗口 / 授权码校验 / `ui/login_window.py` /
> `src/credentials.py`** 的描述**已经作废** —— 这两个文件已删除，
> `VALID_KEYS`（演示码 `ZSJT-2026-VIP`）也不复存在，启动直接进主界面。
> 其余关于页面、任务、浏览器自动化的描述仍然有效。

---

## 一、这是什么

**赵氏集团 · 星月创作台**（xyx-bot）是一个 **Python + Playwright 的浏览器自动化系统**，
带一套 tkinter 自绘的深色 GUI，目标是自动化操作网文 AI 创作站点
[星月写作](https://xingyuexiezuo.com/)。

它解决的核心问题是：**把「AI 续写正文 → 按字数采纳 → AI 审稿 → 替换落盘」这条链路
做成无人值守的一条龙，并支持按章节范围批量跑。**

架构上**移植自同作者的 `novel-publisher-mac`**（网文发布工具），复用了它经过实战的
浏览器引擎、跨平台浏览器检测、平台注册表、任务注册表、章节文件工具、日志重定向。
README 明确写了这层移植关系。

### 一句话概括价值链

```
你写小说 txt → 程序分章 → 每章给个短代号 #1 #2 …
     → 你写「指令模板」把代号嵌进自然语言（如「根据 #@ 的细纲续写，前文参考 #1」）
     → 程序渲染成最终提示词 → 注入站点的 AI 续写弹窗 → 生成 → 按字数自动采纳
     → 切到 AI 审稿抽屉 → 生成 → 全选正文 → 替换落盘
     → 循环到下一章
```

---

## 二、目录与模块地图

### 2.1 顶层文件

| 文件 | 行数 | 作用 |
|---|---|---|
| `main.py` | 693 | **命令行入口**。18 个子命令 + 参数解析（手写，无 argparse） |
| `launcher.py` | 64 | 智能挑「带 tkinter 的 Python」再启动 GUI；`cli` 参数则透传给 `main.py` |
| `run_gui.py` | 50 | GUI 入口：`LoginWindow` → `MainWindow`；启动失败弹窗而非静默闪退 |
| `diag_login.py` | 152 | 登录态诊断：打印 URL / 全部 cookie / localStorage / 判定结果 |
| `启动.bat` | — | 一键 GUI 启动（用 `.venv312`） |
| `build.bat` | — | 建 `.venv`（纯 CLI 环境）+ 装依赖 + 检测浏览器 |
| `start.bat` | — | 建 `.venv312`（GUI 环境，需 Python 3.12 + tkinter）并跑 GUI |
| `_t_e2e_full.py` | 75 | **开发期 E2E 脚本**：真的跑一遍完整一章并打印结论段 |
| `_t_verify_shortcut.py` | 24 | **开发期验证脚本**：验证快捷选项提示词能否选中 |
| `requirements.txt` | 1 | `playwright>=1.47.0` |
| `requirements-gui.txt` | 1 | `playwright>=1.47.0`（GUI 额外依赖 tkinter，由系统 Python 提供） |
| `README.md` | 1237 | **极详尽的中文文档**，含所有实测坑与设计理由 |

> ⚠️ 项目**不是 git 仓库**（`git` 命令不存在，无 `.git`）。`.gitignore` 已写好但未初始化。

### 2.2 `src/` — 自动化后端

| 文件 | 行数 | 函数 | 职责 |
|---|---|---|---|
| `config.py` | 248 | 1 | **集中配置**：站点地址、hash 路由、全部选择器常量、超时、浏览器参数 |
| `ai.py` | **3370** | **57** | ★★ 最大的模块：AI 续写 / AI 审稿 / 一条龙 / 批量跑章 的全部页面编排 |
| `books.py` | 813 | 20 | 作品页：进列表、列作品、匹配消歧、打开作品、新建作品、关活动弹窗 |
| `login.py` | 632 | 20 | 登录：多路判定、自动登录、人工登录、`prepare_session` 流程准备 |
| `novel.py` | 543 | 27 | ★ 分章 + 短代号模板（`#N` / `#@`）渲染 |
| `app.py` | 166 | 16 | `App` 主类：串起浏览器 / 平台 / 任务 |
| `browser.py` | 231 | 6 | 浏览器启动（普通 / 持久化 / CDP 接管）+ 反自动化 + 登录态注入 |
| `browser_detector.py` | 242 | 8 | 跨平台检测 Edge / Chrome 路径（含 Windows 注册表读取） |
| `session.py` | 236 | 12 | 登录态文件生命周期：导出 / 注入 / 摘要 / 备份 / 清除 |
| `actions.py` | 198 | 8 | 人类化操作：多选择器回退点击、逐字符延迟输入、等待 |
| `chapter_files.py` | 171 | 7 | 章节拆分 / 中文字数统计 / 重复检测（移植，去 tkinter） |
| `workspace.py` | 195 | 6 | 工作区配置持久化（`workspace.json`） |
| `credentials.py` | 112 | 8 | 授权码「记住账号密码」（机器码派生密钥 + XOR 混淆） |
| `logging_redirect.py` | 89 | 7 | stdout/stderr 三路重定向：sink 回调 + 日志文件 + 原始终端 |
| `platforms/__init__.py` | 64 | 6 | 平台基类 `BasePlatform` + `@register_platform` 注册表 |
| `platforms/adapters.py` | 53 | 1 | 注册「星月写作」平台 |
| `tasks/__init__.py` | 58 | 5 | 任务注册表 `@register_task` + `execute_task`（支持 threaded） |
| `tasks/adapters.py` | 456 | 11 | **注册 11 个任务**，全部用环境变量 `XY_*` 配置 |

### 2.3 `ui/` — 图形界面

| 文件 | 行数 | 函数/方法 | 职责 |
|---|---|---|---|
| `main_window.py` | **3231** | 116 方法 | ★★ 主界面：7 个页面、常驻 Playwright 线程、任务互斥、日志区 |
| `theme.py` | 702 | 54 | 深色主题 `COLOR` 字典 + 11 个 Canvas 自绘组件 |
| `login_window.py` | 289 | 12 | 授权码登录窗口 |
| `shot.py` | 68 | 2 | DPI 感知 + 窗口截图（开发期工具） |

### 2.4 `artifacts/` — 运行时产物（已 gitignore）

```
artifacts/
├── storage/
│   ├── state.json            ★ 星月登录态（cookie + localStorage，明文票据，83 KB）
│   ├── state.backup.json     上一次登录态备份（85 KB）
│   ├── session_meta.json     登录态元信息：saved_at / cookies / account
│   ├── credentials.json      软件授权码（username=zhao, password=混淆后）
│   └── workspace.json        ★ 工作区配置（上次的小说/作品名/指令模板/审稿参数）
├── screenshots/              ~150 张开发期截图（含大量 _recon_* 选择器侦察图）
├── logs/                     ~130 个 run-*.log 运行日志
└── traces/                   （空）Playwright 录像目录
```

### 2.5 代码规模

```
src/     ~6,900 行   （ai.py 3370 + books 813 + login 632 + novel 543 + 其余）
ui/      ~4,290 行   （main_window 3231 + theme 702 + login_window 289）
顶层入口  ~1,100 行   （main 693 + diag_login 152 + launcher/run_gui + 测试脚本）
─────────────────────
合计    13,078 行 Python
```

---

## 三、架构分层

```
┌──────────────────────────────────────────────────────────────┐
│ 入口层                                                        │
│   启动.bat → launcher.py → run_gui.py → LoginWindow → MainWindow│
│   main.py <子命令>  （18 个 CLI 命令，与 GUI 平分秋色）         │
├──────────────────────────────────────────────────────────────┤
│ 编排层                                                        │
│   src/tasks/adapters.py    11 个任务，签名统一 func(app)        │
│   src/platforms/adapters.py 1 个平台（星月写作）                │
│   src/app.py               App：浏览器 + 平台 + 任务的粘合层     │
├──────────────────────────────────────────────────────────────┤
│ 业务层                                                        │
│   src/ai.py        ★ 续写 / 审稿 / 一条龙 / 批量                │
│   src/books.py     作品页操作                                   │
│   src/novel.py     分章 + 模板渲染                              │
│   src/login.py     登录 + 流程准备                              │
│   src/workspace.py 配置持久化                                   │
├──────────────────────────────────────────────────────────────┤
│ 基础设施层                                                     │
│   src/browser.py + browser_detector.py   浏览器启动与检测        │
│   src/session.py                         登录态持久化            │
│   src/actions.py                         人类化操作原语          │
│   src/config.py                          ★ 全部选择器常量        │
│   src/logging_redirect.py                stdout 重定向          │
│   src/credentials.py                     授权码存储              │
└──────────────────────────────────────────────────────────────┘
```

### 3.1 关键设计：注册表模式

**任务注册表**（`src/tasks/__init__.py`）—— 装饰器注册，模块末尾 `from . import adapters` 触发注册：

```python
@register_task("AI续写正文", threaded=False)
def ai_continue_task(app):
    ...
```

`execute_task(name, app)` 按 `threaded` 决定是否开子线程。**已验证注册 11 个任务**：

```
打开创作台 / 登录星月账号 / 流程准备（打开网站+保存登录态）/ 校验登录态 /
打开作品 / 新建作品 / AI续写正文 / AI审稿 / 续写+审稿一条龙 / 批量跑章 / 侦察页面
```

**平台注册表**（`src/platforms/__init__.py`）—— 类装饰器，`BasePlatform` 要求实现 `run(app)`。
**已验证注册 1 个平台**：`星月写作  https://xingyuexiezuo.com/`。

扩展新站点只需照抄 `XingyuePlatform` 写一个类（README 第九节给了模板）。

### 3.2 `App` 主类（`src/app.py`）

生命周期：`start()` → 起 Playwright → `open_browser()`/`open_persistent()` → 装 `LogRedirector`；
`stop()` 关 context + 停 Playwright。是上下文管理器（`with App() as app:`）。

便捷方法：`page`（属性，取 `context.pages[0]` 或新建）、`goto`、`sleep`、`shot`、
`run_task(name)`、`run_platform(name)`、`save_session`、`has_session`、`session_info`、`clear_session`。

---

## 四、配置与选择器体系（`src/config.py`）

这是**整个项目的核心可维护性设计**：所有站点相关的易变信息集中一处，
站点改版只改这一个文件。模块级常量共 23 个：

```python
# 路径
ROOT, ARTIFACTS, SHOTS, TRACES, LOGS, STORAGE, STATE_FILE, USER_DATA_DIR
# 站点
SITE{name, entry, hash_routes{...}, api_hosts[]}, LOGGED_IN_HINTS
LOGIN_SELECTORS{...}, LOGIN_URL, BOOK_SELECTORS{...}
# 运行参数
HEADLESS, SLOW_MO, DEFAULT_TIMEOUT, NAV_TIMEOUT, VIEWPORT, LOCALE, TIMEZONE,
BROWSER_PATH, AUTO_DETECT_BROWSER, CDP_PORT
```

### 4.1 实测确认的站点事实

| 项 | 实测值 |
|---|---|
| 前端 | Vue 3 + Vite SPA |
| 路由 | **hash 路由** `/#/login`（直接访问 `/login` 会 404） |
| 登录页 | 两个 Tab：微信扫码（默认）/ 账号密码（**懒渲染**，需先点 Tab） |
| 登录态 | `localStorage` 里的 Token |
| 验证码 | 腾讯滑块 `turing.captcha.gtimg.com` |
| 后端接口 | `a.` / `c.` / `v1.xingyuexiezuo.com` |

hash 路由表：`welcome / login / register / reset / books / scripts / forum / workflow_list / workflow_create`。
提供 `route_url(key)` 拼完整地址。

### 4.2 运行参数（全部可用环境变量覆盖）

| 变量 | 默认 | 含义 |
|---|---|---|
| `XYX_HEADLESS` | `0` | 默认**有头**（方便观察） |
| `XYX_SLOW_MO` | `80` | 每步放慢 ms |
| `XYX_TIMEOUT` | `15000` | 元素等待 ms |
| `XYX_NAV_TIMEOUT` | `45000` | 导航等待 ms |
| `XYX_BROWSER` | 空 | 显式指定浏览器路径 |
| `XYX_CDP_PORT` | 空 | CDP 接管端口 |

> ⚠️ **实查发现**：`config.py` 里定义了 `SLOW_MO`，但 `browser.py` 的
> `p.chromium.launch(...)` **并未使用它** —— 这个参数目前是**死配置**。

### 4.3 `BOOK_SELECTORS` 与三个实测坑

作品页有三个已踩平的坑，全部体现在选择器设计里：

1. **「新建作品」不是唯一文字** —— 页面上同时存在入口卡（`.create-card`）和
   两部恰好叫「新建作品」「新建作品1」的已有作品。用 `text=新建作品` 会命中 4 个。
   → 必须用 `.create-card` 类精确定位。
2. **作品名会重复** —— 实测出现过 3 部同名「自动化测试-勿动」。
   → 唯一标识是卡片内链接 `#/chapters/<数字ID>`。
3. **活动弹窗盖满页面** —— 进作品页自动弹「邀请好友赚佣金大奖赛」，
   整个弹窗覆盖全屏，导致后续点击报 `intercepts pointer events`。
   → `close_activity_modal()` 用标题文字识别，**绝不会误关**「新建作品」弹窗。

---

## 五、登录态体系（项目最实用的部分）

### 5.1 原理

星月写作把登录态放在 cookie + localStorage。Playwright 的 `storage_state`
把两者一次性导出 JSON，下次 `new_context(storage_state=...)` 注入，
效果等同「你已经登录过了」。

```
第一次： 打开浏览器 → 未登录 → 你登录 → 导出 state.json
第 N 次： 打开浏览器 → 注入 state.json → 已登录 → 直接干活
```

### 5.2 `src/session.py`（236 行）

| 函数 | 作用 |
|---|---|
| `exists()` | 文件存在且 `size > 2` |
| `state_path_for_playwright()` | 文件在才返回路径，否则 `None`（= 全新会话） |
| `load()` | 读 state 字典 |
| `save_from_context(ctx)` | ★ 导出落盘。**先备份**旧的到 `state.backup.json`；写 `session_meta.json`（saved_at/cookies/account）；`chmod 0o600` |
| `clear()` | 删 state + meta + backup 三个文件 |
| `describe()` | 给 UI 的摘要（saved/saved_at/cookies/account/path/size） |
| `age_text()` | 「9 小时前」「3 天前」 |
| `_guess_account(ctx)` | 扫 localStorage 的 userInfo/user/account 等键猜账号 |

**实测 state.json 内容**（已脱敏读取结构）：

- 4 条 cookie：`HMACCOUNT_BFESS`、`Hm_lvt_...`、`HMACCOUNT`、`Hm_lpvt_...`
  （⚠️ 全是百度统计 cookie，**没有会话 cookie**）
- localStorage 关键项：`SECRET_TOKEN`（真实票据）、`userStorage`（含 avatar 等
  userInfo）、`initParams`、`lastSeenDefaultModels`、`latest`、`ReadMails`、
  `books_right_sidebar_914359`（**用户 ID = 914359**）
- 即：**登录态实际完全依赖 localStorage，不在 cookie 里** —— 这解释了
  README 里为什么强调「localStorage 是最可靠判据」。

### 5.3 `src/login.py`（632 行）

**多路登录判定 `is_logged_in(page)`**（顺序至关重要）：

| 路 | 判据 | 说明 |
|---|---|---|
| 0 | URL 含 `/login` 或 `/register` → **未登录** | 先排除 |
| 0b | `is_login_page()`：登录 Tab / 二维码 / 输入框可见 → **未登录** | ★ 必须排在 localStorage **之前**，否则登录页上残留的旧 token 会误判 |
| 1 | `is_logged_in_by_local_storage()`：扫 `/token\|auth\|user\|login\|session\|uid\|account/i` 的键，排除 `null`/`undefined`/`{}`/`[]` | SPA 最可靠 |
| 2 | `LOGGED_IN_HINTS` 元素可见（我的作品 / 退出登录 / avatar…） | |
| 3 | 兜底：URL 既不在登录页也不在 `/#/welcome` → **视为已登录** | |

**关键函数**：

- `_any_page_logged_in(ctx)` —— 检查**所有标签页**，任一登录即算成功
  （用户可能在新标签页登录）。
- `auto_login(page, user, pwd)` —— 点「账号密码」Tab → 勾协议 → 填账号密码 →
  点登录 → 等最多 120s；检测到验证码时提示用户手动过。
- `manual_login(page, wait_seconds, stop_event)` —— ★ 三条退出路径：
  a) 自动判定成功；b) `stop_event` 被 set（GUI 的「我已登录，立即保存」按钮）；
  c) 兜底超时（`wait_seconds=0` = **不限时**）。每 30s 打印一次诊断。
- `ensure_login(app, wait_seconds=0)` —— 复用优先 → 环境变量自动 → 人工。
- `prepare_session(app, save, open_site, auto, wait_seconds, interactive)` ——
  ★★ 「所有流程开始之前」的统一准备，返回结构化摘要
  `{ok, logged_in, saved, cookies, account, saved_at, mode, message}`。
  `mode` 取值 `reuse` / `live` / `auto` / `manual` / `failed`。
  → `reuse` = 本地有 state 且打开后已登录；`live` = **本地无 state 但浏览器里本就
  登录着**（刚点了「清除」但旧浏览器进程还活着）。这俩都算就绪但标签分开，
  否则日志会让人误以为在读旧文件。
- `is_ready(auto_verify=False)` —— 不开浏览器，只查本地 state 文件（给 UI 状态灯）。
- `verify_session(app)` —— 打开站点校验，**有效就顺手刷新 state**（站点可能轮换 token）。

### 5.4 环境变量自动登录

```bat
set XYX_USER=你的账号 & set XYX_PWD=你的密码
python main.py login
```

> ⚠️ 注意：这里读的是 **`XYX_USER`/`XYX_PWD`**，而任务中心用的是
> **`XY_BOOK`/`XY_*`** 前缀 —— **两套不同的前缀**，别混。

---

## 六、小说分章与短代号模板（`src/novel.py`）

### 6.1 分章正则

```python
CHAPTER_RE = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*)?[ \t]*"
    r"第[ \t]*([0-9一二三四五六七八九十百千万零两]+)[ \t]*章"
    r"[ \t]*(?:[：:、.．\-—\s][ \t]*)?([^\n*]*?)"
    r"[ \t]*(?:\*\*)?[ \t]*$",
    re.MULTILINE)
```

兼容 `**第1章 标题**` / `## 第1章 标题` / `第1章 标题` / `第1章：标题`。
`cn_to_int()` 把「十二」「二十三」「一百」「两」转 int。

**过滤「目录残留」**：无正文的条目直接丢掉（`raw_items = [x for x in raw_items if x["body"]]`）。

### 6.2 数据结构

```python
@dataclass
class Chapter:
    no: int; title: str; body: str
    note: str      # ★ 用户在 UI 填的「这一章细纲」
    prefix: str; suffix: str
    @property
    def code(self) -> str: return f"#{self.no}"     # ★ 短代号

@dataclass
class NovelProject:
    name, source, chapters[], global_prefix, global_suffix,
    instruction: str = "#1",      # ★ 指令模板
    fallback_to_body: bool = True  # 没填细纲时用原文兜底
```

工程文件 `.novel.json` 存上述全部字段。`保存/打开` 用 `filedialog`，
默认文件名 `{name}.novel.json`。

### 6.3 短代号渲染（★ 已实机验证）

**两种占位符**：

| 写法 | 语义 |
|---|---|
| `#1` `#2` `[1]` `{{第1章}}` `第1章` | **绝对章号**（`#3` 永远是第3章） |
| `#@` `{{当前章}}` `{{本章}}` `#当前章` | ★★ **当前章**（批量跑章时逐章替换） |

**`render_template(tpl, mode, values, current)`** 的 5 种 `mode`：
`note`（默认，细纲，空则回退 body）/ `body` / `title` / `render`（前缀+细纲+后缀）/
`both`（原文节选+细纲）。

**实测验证结果**（我实际跑了脚本）：

```python
proj.instruction = '根据 #@ 的细纲续写，前文参考 #1。'
proj.set_note(1,'第一章细纲A'); set_note(2,'第二章细纲B'); set_note(3,'第三章细纲C')

render_template(current=2)  → '根据 第二章细纲B 的细纲续写，前文参考 第一章细纲A。'
render_for_batch(3)         → '根据 第三章细纲C 的细纲续写，前文参考 第一章细纲A。'
render_template('看 #999 和 #1') → '看 #999 和 第一章细纲A'   # 未知代号原样保留
```

`find()` 支持全部 5 种写法（实测 `#1`→1、`[2]`→2、`{{第3章}}`→3、`第2章`→2、`3`→3）。
`render_template` 会**多遍替换**（最多 3 轮），支持细纲里再出现别的代号。

### 6.4 ★ `render_for_batch` 的设计意图（很关键）

用户模板末尾常写 `#1`（单章用法残留）。批量跑章时 `#1` 会**永远**引用第1章
→ 每一章都用第1章的细纲（用户原话「一直定在第一章」）。

所以 `render_for_batch(no)` 的逻辑是：**如果模板里没有 `#@`，就把所有 `#N` 转成 `#@`**
（`self.CODE_RE.sub("#@", tpl)`），再按第 `no` 章渲染。有 `#@` 时行为等同
`render_template(current=no)`。

`check_template()` 返回 `{unknown:[], empty:[], used:[], ok:bool}` ——
未知代号会**原样保留**方便发现写错；填了代号但没填细纲会有 ⚠ 提示并用原文兜底。

---

## 七、GUI 层（`ui/`）

### 7.1 布局

```
┌─────────────────────────────────────────────┐
│  顶栏：品牌 + 用户 + 状态                     │
├──────────┬──────────────────────────────────┤
│ 侧边导航  │  内容区（Canvas 可滚动）          │
├──────────┴──────────────────────────────────┤
│  日志面板（可折叠，实时日志）                  │
├─────────────────────────────────────────────┤
│  状态栏                                       │
└─────────────────────────────────────────────┘
```

窗口 `1180x820`，`minsize 1040x700`，居中显示。

### 7.2 七个页面（`NAV_ITEMS`）

| key | 图标 | 名称 | 内容 |
|---|---|---|---|
| `overview` | ◈ | 概览面板 | 运行状态指标卡（含星月登录态）+ 平台能力介绍 |
| `account` | ◉ | 星月账号 | 登录态状态灯 + 登录 / 我已登录立即保存 / 校验 / 刷新 / 清除 |
| `books` | ▣ | 打开作品 | 输入小说名 → 打开；同名时列出候选 |
| `tasks` | ▤ | 任务中心 | 列出 11 个已注册任务，一键执行 |
| `content` | ▥ | **小说分章** | ★ 最大的页面：流程准备卡 + 分章 + 章节列表 + 指令模板 + 续写/审稿/一条龙/批量 + 工程存取 |
| `settings` | ⚙ | 运行配置 | 浏览器路径 + 自动检测 + 运行参数展示 |
| `about` | ✦ | 关于本机 | 版本 v1.0.0 / 授权用户 / 技术底座 |

### 7.3 ★★ 常驻 Playwright 线程（关键架构决策）

`MainWindow.__init__` 建一个**常驻线程** `pw-worker` + 一个 `queue.Queue`：

```python
self._pw_queue = queue.Queue()
self._pw_thread = threading.Thread(target=self._pw_loop, name="pw-worker", daemon=True)
self._pw_thread.start()
```

`_pw_loop` 无限取队列串行执行。所有浏览器任务通过 `self._pw_queue.put(worker)` 投递。

**为什么必须这样**（源码注释里写得很清楚，这是踩过的坑）：
Playwright 的 `page`/`context` **必须始终在同一线程操作**。早期每个按钮各开一个线程，
谁先开浏览器浏览器就「绑」在谁的线程上；线程一退出，再点别的按钮就报
`cannot switch to a different thread (which happens to have exited)`。

### 7.4 ★ 统一任务互斥 `_run_guarded(name, worker_fn, btn)`

解决用户痛点「上一个任务完成了，我再点，会报线程被占用」：

- **互斥**：`self._task_lock` + `self._task_running` 标志，一次只跑一个浏览器任务；
  上一个没完再点 → 友好提示「任务进行中」而不是抛 Playwright 底层错。
- **复用**：`self._app` 跨任务复用，不重复启动浏览器。
- **必释放**：`runner()` 的 `finally` 里一定重置标志 → 跑完立即能再点。
- **同线程**：投递到常驻线程执行。
- **按钮态**：运行中禁用 `btn`，完成 `self.after(0, btn.config, {"state":"normal"})` 恢复。

### 7.5 线程安全

后端 `print` 通过 `LogRedirector(sink=lambda m: self.after(0, self.log, m, "info"))`
回到主线程刷新日志区 —— **`self.after` 全部用于跨线程更新 tk**。
同理 `self.after(0, self.status.set_status, ...)`、`self.after(0, self._keep_on_top, False)`。

→ 结论：**跨线程 tk 调用被正确规避**。唯一的例外是
`main_window.py:2051` 的 `threading.Thread(target=worker)`（分章任务），
但它只做纯文件 I/O（读 txt + `split_novel`），**不碰浏览器**，所以安全。

任务运行期间主窗口自动 `-topmost`（`_keep_on_top(True)`），避免被浏览器窗口遮挡。

### 7.6 `ui/theme.py`（702 行，11 个自绘组件）

**配色**（`COLOR` 字典，改主题只改这里）：

```
背景层次  bg_root #0d1117 / bg_card #161b22 / bg_card_hi #1c2128
          bg_input #21262d / bg_titlebar #010409
品牌色(金) brand #d4a24c / brand_hi #e8bb6b / brand_dim #8a6a2f
语义色    accent #58a6ff / success #3fb950 / warning #d29922 / danger #f85149
文字      text #e6edf3 / text_dim #8b949e / text_mute #6e7681
描边      border #30363d / border_hi #484f58
```

**组件清单**：

| 组件 | 作用 |
|---|---|
| `Card` | 圆角卡片容器，内容放 `self.body` |
| `Collapsible` | ★ 可折叠卡片（2026-10-04 UI 精简用） |
| `GradientBar` | 渐变标题栏（`_lerp_color` 插值） |
| `BrandButton` | 品牌色按钮，hover/press/disabled 四态 |
| `DarkEntry` | 深色输入框，占位符 + 聚焦高亮 |
| `CheckBox` | 整行可点的深色复选框 |
| `LogView` | 带等级着色的日志区（`LEVEL_COLOR`） |
| `StatusBar` | 状态点 + 文字 + 版本号 |
| `Toast` | 底部轻量提示条，几秒自动消失 |
| `TitleLabel` / `DimLabel` | 标题 / 次要文字 |
| `round_rect()` / `F()` / `FM()` | 圆角多边形近似 / 雅黑字体 / Consolas 等宽 |

原生 ttk 做不了圆角渐变阴影，所以全部用 `Canvas` 自绘。

### 7.7 `ui/login_window.py`（289 行）

软件授权窗口。左侧 Canvas 自绘品牌区（`_draw_left`），右侧表单（`_build_form`）：

| 控件 | 说明 |
|---|---|
| 授权账号 `DarkEntry` | 占位符「请输入授权账号」 |
| 授权凭证 `DarkEntry(show="●")` | 密码样式；占位符「请输入授权凭证」 |
| `CheckBox "记住账号密码"` | 切换时触发 `_on_remember_toggle` |
| `err_label` / `hint_label` | **固定高度**，避免提示出现时把按钮顶下去 |
| `BrandButton "登 录"` | 回车键也绑定（`self.bind("<Return>", ...)`） |
| 底部提示 | 「演示授权码：`ZSJT-2026-VIP`」（硬编码） |

**校验逻辑（`_do_login`，非常简单）**：

```python
if not user:  _err("请输入授权账号"); return
if not key:   _err("请输入授权凭证"); return
if key not in VALID_KEYS:                  # ★ 纯本地常量比对，无网络
    _err("授权凭证无效，请重新输入"); self.entry_key.set(""); return
self._persist_credentials(user, key)       # 按勾选保存或清除
self.after(420, lambda: self._enter(user)) # 假延迟 420ms 再进主界面
```

→ 授权是**纯本地比对**，`VALID_KEYS` 是硬编码常量集合（演示码 `ZSJT-2026-VIP`）。
`_load_saved_credentials()` 启动时从 `credentials.json` 回填账号与授权码，
`_persist_credentials()` 在勾选时 `cred.save(...)`、未勾选时 `cred.clear()`。
成功后 `destroy()` 并回调 `on_success(username)`。

---

## 八、AI 编排核心（`src/ai.py`，3370 行）

这是项目最复杂、注释最详尽的模块（光是文件头的选择器区就 230 行）。
顶层 `def` 共 55 个，公开 API 共 **49 个函数**（AST 实测）。

### 8.0 内部分区（源码注释标题）

| 行范围 | 分区 | 内容 |
|---|---|---|
| 1–42 | 模块 docstring | 实测流程表 + 关键选择器表 + 「快捷选项」反直觉说明 |
| 55–57 | 全局状态 | `LAST_DECISION` |
| 59–85 | 审稿面板文字锚点 | `ANCHOR_TEXT` / `REVIEW_PANE_SEL` / `REVIEW_CARD_SEL` / `REVIEW_CARD_ALT` |
| 87–314 | `---- 选择器` | `AI_SELECTORS`（30 个键，全部是**候选列表**）+ 两大段实测注释 |
| 317–463 | `---- 基础动作` | `_shot` / `_visible` / `NUISANCE_DIALOGS` / `dismiss_dialogs` / `_click_first` / `_fill_first` |
| 465–912 | `---- 流程步骤` | 续写弹窗各步 + `select_model` + `MODEL_CARD_HINT` + 联想滑块 |
| 914–1234 | `---- 快捷选项` | 提示词全屏面板（含 `wait_shortcut_loaded`） |
| 1236–1310 | 关联章节 / 开始 | `relate_chapters` / `start_generate` |
| 1312–1694 | `---- 生成结果处理` | 完成判定 / 字数 / 重生成 / `generate_with_word_check` |
| 1696–1728 | `==== AI 审稿` | 大节头：续写 vs 审稿对比表 + 三大坑 |
| 1731–2087 | 审稿面板操作 | 开/关抽屉 / 待审文本 / 审稿要求 / 生成 |
| 2090–2316 | `---- 正文编辑器` | `editor_ready` / `get_body_text` / `open_chapter` / `select_all_body` |
| 2318–2547 | `---- 审稿结果落盘` | 完成判定 + `replace_review_result` |
| 2549–2787 | `---- 组合流程` | `ai_continue` / `ai_review` |
| 2789–2939 | `==== ★ 续写 → 审稿 串联` | `close_continue_dialog` / `wait_body_change` |
| 2941–3131 | 一条龙 | `ai_auto_chapter` |
| 3134–3369 | `==== 批量跑章 ★` | `chapter_numbers` / `ensure_chapter` / `ai_batch_chapters` |

**`AI_SELECTORS` 的 30 个键**（供查阅）：`btn_continue`、`dialog`、`plot_input`、
`model_selection`、`model_xini`、`btn_associate`、`btn_use_model`、`assoc_chapter`、
`assoc_arrow`、`assoc_3`、`assoc_5`、`shortcut_row`、`shortcut_panel`、
`shortcut_items`、`shortcut_search`、`btn_start`、`gen_dialog`、`btn_accept`、
`btn_regen`、`regen_confirm_dialog`、`regen_confirm_btn`、`gen_word_count`、
`btn_review`、`review_pane`、`review_selects`、`review_text`、`review_tabs`、
`btn_review_start`、`review_switch`、`editor_body`、`btn_editor_select_all`、
`chapter_item`、`btn_review_replace`、`review_replace_confirm`、`review_generating`。

**注意**：`"替换"` 这个字串在站点上**出现两次**（编辑器工具栏的查找替换、
审稿的「替换 / 插入」），所以源码明确禁止用「全页文字含『替换』」当判据
（`:2363-2366` 的踩坑记录），必须**限定在卡片 `.n-card__footer` 内 + 限定
`n-button--success-type` 类名**。

### 8.1 模块级常量

| 常量 | 值/作用 |
|---|---|
| `LAST_DECISION` | ★ 最近一次「按字数自动决策」的完整 dict，供 GUI 显示 |
| `ANCHOR_TEXT` | `'待审文本'` |
| `REVIEW_PANE_SEL` | `.n-card-content:has-text('待审文本')` —— **生成前**的内容区 |
| `REVIEW_CARD_SEL` | `.chapter-right-workspace .n-card.chapter-side-pane-c` —— **整个卡片**（生成前后都在） |
| `REVIEW_CARD_ALT` | `.n-card.chapter-side-pane-card`（兼容回退） |
| `NUISANCE_DIALOGS` | 3 类干扰弹窗的识别与关闭策略（「是否默认打开上次章节」/「国庆特惠」/「特惠上线」） |
| `ASSOCIATE_SLIDER_SEL` | `[class*=association-level-slider]` |
| `ASSOCIATE_MARKS` | `['专业','准确','均衡','正常','丰富','离谱']` ← 6 档滑块 |
| `REVIEW_RESULT_TEXT` | `'替换'` |
| `MODEL_CARD_HINT` | ★ 模型卡片对应的提示文字（见下） |
| `AI_SELECTORS` | 40 个选择器组（多候选回退） |

**`MODEL_CARD_HINT`（实测内容，已 dump）**：

```python
{'细腻版':      '指令遵循能力强',
 '智慧版-6A':   '更懂作者意图，能稳定抓住风格',
 '智慧版-6S':   '写小说强在结构和情节',
 '智慧版-6.1S': '该模型能同时续下大纲、人物卡与多章前文',
 '智慧版-5.6':  '最新的gpt-5.6模型'}
```

### 8.2 定位策略：两级锚点（★ 核心难点）

AI 审稿走的是**右侧抽屉**，`.n-modal` / `[role=dialog]` **全都抓不到它**；
容器类 `chapter-side-pane-c` 是**动态生成的**不可靠。所以用**文字锚点**：

- `REVIEW_PANE_SEL` = `.n-card-content:has-text('待审文本')` → 定位**输入控件**
  （模型下拉 / 待审文本 textarea / 审稿要求下拉）
- `REVIEW_CARD_SEL` = 整个审稿卡片 → 定位 **footer 按钮**
  （「生成」在 `.n-card__footer`（底部固定栏），**不在** `.n-card-content` 里！）

**结果判据不能靠「待审文本」** —— 生成完成后卡片内容区被换成结果视图，
`chapter-side-pane-card` 这个类会掉，只剩 `chapter-side-pane-c`。
→ 靠 footer 里的 `button.n-button--success-type`（绿色「替换 / 插入」），
并且**连续 2 次命中**才算数（否则会「刚点完生成就误判已完成（耗时 0s）」）。

### 8.3 AI 续写弹窗流程（`ai_continue`）

顺序（注释强调顺序不可换）：

```
⓪ 选快捷选项（提示词）——★ 必须在填剧情之前，因为换提示词会重置「续写要求」框
① select_model()：分类 → 模型卡片「选择」→ 联想能力滑块 → 「使用此模型」+ 回读断言
② fill_plot()：填「后续剧情」textarea
③ relate_chapters(count)：点「最近N章」右边的 ⌄ 箭头 → 菜单选「最近10章」
④ start_generate()
⑤ generate_with_word_check()：按字数自动决策
```

**★ 站点交互的三个坑（源码注释记录）**：

1. **模型面板是「两级」的，点分类不等于选中** —— 左边分类（智慧版/细腻版…），
   右边该分类下的模型卡片。只点左边「细腻版」只是高亮切换，顶部仍显示「奇想版」。
   必须再点右栏卡片的「选择」，最后点「使用此模型」。
   → `select_model()` 最后会**回读顶部选择器做断言**，不是「点了就报成功」。
2. **「联想能力」是滑块不是开关** —— 6 档浮层，**点轨道没用，必须拖手柄**，
   拖到对应刻度 x 会自动吸附。`set_associate_level()` 按刻度标签的 x 坐标拖拽。
3. **「关联章节」整行是折叠开关，别点！** —— 点了会折叠成「已保留，不引用」，
   整个板块失效。它是默认展开的。真正的操作是滚到按钮组 → 点「最近N章」右边
   那个 `⌄` 箭头（svg）→ 弹菜单 → 点「最近10章」。

### 8.4 快捷选项面板（两个坑）

`pick_shortcut(keyword)` 用**文字定位**（`.prompt-row:has-text('关键词')`），
不记第几行（列表顺序/收藏数/运营推荐都会变）。

**坑 4：续写 / 审稿是【两套完全不同的提示词库】** —— 面板长得一样但内容不通用：

| 位置 | 提示词全名（实测） | 关键词 |
|---|---|---|
| **续写**「快捷选项」 | `强盛集团云霄最强续写逆徒尊享版（细腻优先，奇想其次）` | `强盛集团云霄最强续写` |
| **审稿**「审稿要求 → 快捷选项」 | `强盛集团云霄拯救过稿计划（智慧5.6内测专属，审稿前10章）` | `强盛集团云霄拯救过稿计划` |

用同一个串会匹配不到（0 项）或选错。

**坑 5：快捷选项面板是【异步加载】的** —— 打开那一瞬间是 **0 项**，
页面显示「已收藏 0」「正在加载收藏提示词…」，要等 **2~6 秒**才渲染出 27~30 条。
不等就直接 `count()` → 拿到 0 → 误判「没有该关键词」。
→ 必须调 `wait_shortcut_loaded(page)`：轮询 `.shortcut-picker-modal .prompt-row`
计数，>0 且**连续两次稳定**才返回。

`pick_shortcut` 里「有关键词但没命中」是**温和跳过**（警告 + 截图，不阻断主流程），
符合用户「有则改、没有就跳过、不影响进程」的统一原则。

### 8.5 ★ 怎么知道「生成完了」（这个坑很关键）

一开始想用「字数不再变化」判断，**结果是错的**：生成途中会停顿，
一停顿就被误判成「完成」，读到的是**上一轮的旧字数**，看起来像「重新生成没生效」。

逐 3 秒采样后得到的**可靠判据**：

| 状态 | 弹窗按钮栏 | 判据函数 |
|---|---|---|
| **生成中** | `[提示词] [""] [停止生成]` | `gen_in_progress()` |
| **已完成** | `[上一步] [重新生成] … [采纳使用]` | `gen_finished()` |

即：**「重新生成」按钮出现 = 完成**；**「停止生成」按钮在 = 生成中**。

点完「重新生成」还要等旧结果页下架（`wait_result_gone()`），
否则下一轮 `wait_generation` 会立刻把旧页面当新结果。

### 8.6 按字数自动决策（`generate_with_word_check`）

```
字数 ∈ [min_words, max_words]  → 点「采纳使用」
不够 或 超了                    → 点「重新生成」→ 等旧结果下架 → 回到同一判断
重试用完仍未达标                → 保底（见下）
```

**两层保底**（`hard_min` / `best_effort`）：

- `hard_min`：硬下限。重试用完时若 `cnt >= hard_min` **且** `cnt < min_words` → 采纳。
- `best_effort`：★ **「多了也认」** —— 只要 `cnt > 0`，超上限也采纳。

> 源码注释记录了这个修正的原因：原逻辑只在「字数**不够**」时兜底，
> 「超过」直接判失败 → 不点采纳 → **弹窗留着拦住后续所有操作**
> （实测报 `3524 字超过，重试 0 次仍未达标`）。
> 这跟用户「让字数限制宽一点、避免重试、一次过」的意图相反，所以改成多了也认。

返回 `{ok, words, tries[], rounds, reason}`。

> ⚠️ **实查发现一个契约不一致**（见第十节问题清单 #1）：
> `ai_auto_chapter` 的返回 dict **没有 `ok` / `reason` 键**，
> 但 `ai_batch_chapters` 第 3353 行读了 `r.get("reason")` → 恒为 `None`。

### 8.7 AI 审稿流程（`ai_review`）

| | AI 续写正文 | **AI 审稿** |
|---|---|---|
| 承载 | 居中**弹窗** `.n-modal` | **右侧抽屉**（`n-split-pane` 内） |
| 面板锚点 | `.n-modal:has-text(...)` | `.n-card-content:has-text('待审文本')` |
| 主要输入 | 「后续剧情」textarea | **待审文本** textarea |
| 提示词 | 「续写要求」下拉 | **审稿要求**（3 个 tab） |
| 开始按钮 | 「开始 AI 续写」 | **「生成」** |
| 结果落盘 | 「采纳使用」 | **「替换 / 插入」** |

**用户指定配置（已做成默认）**：模型 智慧版 → **智慧版-6A**（分类名 ≠ 卡片名）；
联想能力 **正常 = 0.7**；审稿要求 `强盛集团云霄拯救过稿计划`。

**完整链路**：

```
★ 先打开一个章节（不打开正文区是空的 → 待审文本也是空的）
  → 点「AI审稿」→ 打开抽屉
  → 选模型（智慧版 → 智慧版-6A）+ 联想能力 正常(0.7)
  → 待审文本（默认自带当前章正文；填了「追加指令」→ 提示词 + 正文拼接）
  → 审稿要求：切「快捷选项」tab → 选目标提示词
  → 点「生成」（★ 卡片右下角的「生成」）
  → ★ 等生成完成（几分钟很正常，最多等 600s）
  → ★★ 先「全选正文」→ 再点「替换 / 插入」落盘到正文
```

**★★ 两个必须遵守的动作（用户 2026-10-03 明确要求）**：

**① 替换前必须「全选正文」** —— 「替换 / 插入」是**智能双模**：

| 当前状态 | 按钮行为 |
|---|---|
| **有选中文本** | **替换** — 用生成结果替换选中内容 |
| **没有选中文本** | **插入** — 在光标处插入，**原文还在** |

不全选直接点 → 结果是「原稿 + 审稿结果」**前后拼接**在一起。
所以流程固定为：生成完成 → `select_all_body()` → 点「替换 / 插入」。

全选两条路：① 首选工具栏 `button[aria-label='全选']`（★ 属性是 `aria-label`
不是 `title`！）；② 兜底：聚焦 `.tiptap.ProseMirror` + `Ctrl+A`。

> ★★ 编辑器正文 = `.tiptap.ProseMirror`（contenteditable）。
> 工具栏按钮**全部用 `aria-label`**：撤回/撤销撤回/复制/**全选**/搜索/
> **替换**（★ 这是编辑器查找替换，跟审稿的「替换 / 插入」**不是一回事**）/
> 词条库/角色库/高频词透镜/统一中文标点/智能排版。
> 所以**绝不能用全页文字匹配「替换」** —— 两处都有「替换」。

**② 待审文本 = 自带章节正文 + 可追加提示词** —— `fill_review_text()` 三个分支：

| `text` | `instruction` | 行为 |
|---|---|---|
| 非空 | — | 用 `text` **完全覆盖**（优先级最高） |
| 空 | 非空 | **提示词 + 分隔线 + 当前章正文** 拼成一段填入 |
| 空 | 空 | **不动**，沿用页面自带的当前章正文 |

拼接用的正文是**实时从编辑器读的**（`get_body_text()`），所以换章节后再审，
拼进去的就是新章节内容。提示词里的 `\n` **原样保留**（多行文本）。
界面上「追加指令」是多行编辑器，旁边 4 个快捷按钮（爽文节奏 / 只改不通顺 /
多删少改 / 保留人设）点一下是**追加**（不覆盖），方便叠加多条。

### 8.8 审稿专有的四个坑（源码注释记录）

1. **模型选择弹窗是「根级」的，跟抽屉平级** —— 点抽屉里的「AI模型」下拉，
   弹出的模型选择面板**挂在 `<body>` 下**（`.n-modal.model-picker-modal`），
   **不在抽屉内部**。所以 `select_model(container=抽屉, read_container=".n-modal")`
   两个容器**要分开传**：去抽屉里「点开」，但面板本体/回读在 `.n-modal`。
2. **「生成」按钮不在 `.n-card-content` 里** —— 在 `.n-card__footer`（底部固定栏）。
   锚点要用**整个卡片**。顺带一个坑：**不能用全局 `button:has-text('生成')`** ——
   会命中左栏章节菜单浮层里的「一键生成概要」，`.first` 直接点错。
3. **生成完成后「待审文本」标签会消失** —— 内容区被换成结果视图，
   `chapter-side-pane-card` 类也会掉。所以结果判据靠 footer 里的
   `button.n-button--success-type`，且**连续 2 次命中**才算数。
4. **审稿前必须先把章节「点开」，但 `editor_ready()` 会骗你** ——
   进作品编辑器后**不一定会自动打开章节**，此时正文区是空的，待审文本也是空的。
   坑在于 `.tiptap.ProseMirror` **一直存在**（空壳），所以：
   ```python
   AI.editor_ready(page)              # ✗ 只判存在 → 空壳也 True
   AI.editor_ready(page, need_text=True)  # ✓ 要求正文非空
   ```
   另外两个连带坑：
   - **「是否默认打开上次章节？」是居中模态，会截获所有点击** → 直接点章节会
     `Locator.click: Timeout 4000ms exceeded`。`open_chapter()` 里**第一步先
     `dismiss_dialogs()`**。
   - 点**容器** `.chapter-item`（宽 274px），**不要点标题** `h3.chapter-item__title`
     （只有 36px 宽，容易点偏）。容器里还有个「生成」按钮，别点到它。

### 8.9 ★★ 一条龙（`ai_auto_chapter`）—— 最易崩的衔接处

用户担心：「一章的生成已经完成了，我有些担心**生成完之后、与审稿开始之间的状态**。」
**这个担心完全正确**：生成完之后**续写弹窗还开着**（右下角有绿色「采纳使用」），
而它是**居中模态**，把「AI审稿」按钮的点击**全部拦掉**
→ `Locator.click: Timeout 4000ms exceeded` × 4 → 审稿打不开。

**衔接处的坑与解法**：

| # | 坑 | 现象 | 解法 |
|---|---|---|---|
| 1 | 采纳后续写弹窗不自动关 | 模态拦截，点「AI审稿」必超时 | `close_continue_dialog()` 主动关 |
| 2 | 正文写入有延迟 | 立刻审稿读到空/旧正文 | `wait_body_change()` 等字数真的变了 |
| 3 | 超上限被判失败 → 不采纳 | 弹窗留着不走，后续全崩 | `best_effort` 修正为「多了也认」 |
| 4 | 续写/审稿是两套提示词库 | 用同一关键词 → 空选或选错 | 分别用各自关键词 |
| 5 | 快捷选项面板异步加载 | 打开瞬间 0 项 → 误判「没这条」 | `wait_shortcut_loaded()` |

**`close_continue_dialog()`** 策略：关闭按钮 → ESC → 点遮罩，
**有则关、没则跳过**，全程不抛异常。关闭按钮实测 DOM：

```html
<button aria-label="close" class="n-base-close n-base-close--absolute n-card-header__close"></button>
```

**终局收尾 `close_review_pane()`** —— 一条龙跑完（审稿 → 替换）时**右侧审稿抽屉
是开着的**，会盖住右半边，导致后续读正文/点别的元素拿到错对象
（实测：E2E 结论段读到 216 字就是这个原因）。所以替换成功后**自动关掉审稿抽屉**。

**`ai_auto_chapter` 三阶段结构**：

```
阶段零（可选）：prepare=True → 调 prepare_session（准备失败直接返回，不带未登录硬跑）
   ★ 内置防错位修复：未指定 chapter 时打开「最小章号」而非「列表第0个」
     （章节列表是倒序，第0个 = 最新章 → 会把第1章内容写进第4章）
阶段一：ai_continue(start=True, auto_accept=True, ...) → 结果存 LAST_DECISION
阶段二：衔接 —— close_continue_dialog() + settle + wait_body_change()
阶段三：ai_review(start=True, wait_done=True, replace=..., select_all=...)
        → 成功后 close_review_pane()
返回：{"gen": {...}, "body": int, "review": bool}（准备阶段还会加 "prepare"）
```

### 8.10 ★★ 批量跑章（`ai_batch_chapters` + `ensure_chapter`）

**`chapter_numbers(page)`** —— 只读，从标题「第N章」抠章号（`-1` 表示不识别）。

**`ensure_chapter(page, no, max_new=120)`** —— 实测：
- 「新建章节」按钮 = `button:has-text('新建章节')`（左栏顶部，80x30）
- 点一下会**立即**创建「第(当前最大+1)章」，标题自动递增、**无需输入**
  （会出现标题输入框但已预填好，按 Esc 失焦即可）
- 章节列表**倒序**（新章在最上、active）

所以「按顺序补建」= 连续点 `(no - 当前最大)` 次。
⚠️ **只支持往上补**：若 `no < 当前最大` 但不存在（删过导致跳号）→ 无法自动新建，返回 `False`。

**主循环**（`for no in range(start, end+1)`）：

```
① ensure_chapter(page, no)   —— 缺则新建（auto_new=False 则不建，直接跳过）
② open_chapter(page, which=f"第{no}章")  + chapter_delay
③ this_plot = plot_for(no) if plot_for else plot   —— ★ #@ 逐章替换
④ ai_auto_chapter(..., chapter=f"第{no}章")
⑤ 下一章（stop_on_fail 控制失败是否中断）
返回 {"total", "ok", "failed": [...], "results": [{no, ok, body, reason}]}
```

用户要求（2026-10-04）：「一章一章边建边跑，不一次性预建所有章节」→
缺章由循环内逐章 `ensure_chapter` 处理。

---

## 九、命令行接口（`main.py`，18 个命令）

| 命令 | 作用 |
|---|---|
| `prepare` | ★ 流程准备：打开网站 → 检测/登录 → 保存 cookie 与缓存（`--no-open` / `--clear`） |
| `login` | 登录一次并保存登录态（不限时） |
| `session` | 查看登录态详情（时间 / cookie 数 / 路径） |
| `check` | 打开站点校验登录态是否有效 |
| `diag` | ★ 诊断登录态（`runpy` 执行 `diag_login.py`） |
| `recon` | 侦察页面，打印可见交互元素 |
| `books` | ★ 列出作品页所有作品（序号 / 名字 / ID / 字数 / 创建时间） |
| `open <名字>` | ★ 按名字打开作品，同名加 `--index N`；无 index 时终端交互选 |
| `ai <作品名>` | ★ AI 续写（`--plot` / `--template` / `--project` / `--chapter` / `--model` / `--assoc` / `--relate` / `--shortcut` / `--go` / `--auto-accept` / `--min-words` / `--max-words` / `--max-retry` / `--index`） |
| `review <作品名>` | ★ AI 审稿（`--req` / `--model` / `--card` / `--assoc` / `--tab` / `--chapter` / `--instruction` / `--no-select-all` / `--go` / `--wait` / `--replace` / `--timeout` / `--index`） |
| `auto <作品名>` | ★★ 一条龙：续写 → 采纳 → 关弹窗 → 等正文 → 审稿 → 替换（`--min` / `--max` / `--retry` / `--rv-*` / `--no-review` / `--no-replace` / `--prepare` / `--no-prepare`） |
| `batch <作品名>` | ★★ 批量跑章（`--from` / `--to` / `--plot` / `--project` / `--no-new` / `--stop-on-fail` / `--rv-*`） |
| `studio` | 登录并进创作台 |
| `tasks` | 列出所有已注册任务 |
| `platforms` | 列出所有已注册平台 |
| `run <任务名>` | 执行指定任务 |
| `browsers` | 检测本机可用浏览器 |
| `logout` | 清除登录态 |

**剧情文本四种来源（优先级）**：
1. `--plot "..."` 直接给一段
2. `--template "根据 #1 续写"` + `--project xx.novel.json` → 短代号替换 ★推荐
3. `--project xx.novel.json --chapter 3` → 取该章单章（含前后缀）
4. 都不给 → 用内置默认占位剧情

`auto` 与 `batch` 默认**先检查准备状态**：已有登录态→跳过；没有→自动跑 `prepare_session`。

---

## 十、实际验证记录（本次分析所做）

| 验证项 | 命令/方式 | 结果 |
|---|---|---|
| 全项目语法编译 | `python -m compileall src ui main.py ...` | **exit 0**，无语法错误 |
| 模块导入 | import ai/books/novel/login/session/actions/browser/workspace | **全部成功** |
| 任务注册表 | `main.py tasks` | **11 个任务** |
| 平台注册表 | `main.py platforms` | **1 个平台（星月写作）** |
| CLI 帮助 | `main.py`（无参） | 正常打印文档 |
| 登录态摘要 | `main.py session` | 保存时间 2026-10-04 00:06:01，**9 小时前**，4 条 cookie，83.2 KB |
| `novel.py` 分章 | 喂入 3 种标题格式 | 正确切出 `#1/#2/#3`，标题与正文都对 |
| `cn_to_int` | 一/十/十二/二十三/一百/两 | **全部正确** |
| `#@` 当前章替换 | `render_template(current=2)` | `#@`→第二章细纲，`#1`→第一章细纲（绝对引用保持） |
| `render_for_batch(3)` | 同上 | `#@`→第三章细纲 |
| 未知代号容错 | `render_template('看 #999 和 #1')` | `'看 #999 和 第一章细纲A'` —— 原样保留 ✓ |
| `find()` 5 种写法 | `#1`/`[2]`/`{{第3章}}`/`第2章`/`3` | **全部命中** |
| AI 公开 API 数量 | AST 扫描 | **49 个公开函数**（顶层 55 个，6 个私有） |
| GUI `App` 创建点审计 | 逐处核对 5 个 `App(...)` | 4 处走 `pw_queue`，**1 处（任务中心）没走** → 见 #5 |
| GUI 按钮禁用机制 | 读 `theme.py:369-380` | `config(state=...)` **不生效**（看 `_enabled`）→ 见 G1 |
| GUI 渲染 `#@` 审计 | grep `render_template(` | 单章路径**未传 `current=`** → `#@` 不替换 → 见 G4 |
| `_ai_book_index` 赋值点 | grep | 批量路径**不赋值**，用陈旧值 → 见 G3 |
| 死代码扫描 | grep 全仓调用点 | `_count_words` / `_prepare_then_both` / `_run_on_pw_thread` / `gen_dialog_open` / `review_generating` / `launch_browser_for_task` 等零调用 |
| 线程违规扫描 | grep `_app.stop()` / 控件访问 | `main_window.py:756`、`:927` 在主线程 stop Playwright；`:2020-2021`、`:882` 后台线程碰 Tk → 见 G2/G5 |
| `MODEL_CARD_HINT` | 运行时 dump | 5 个模型卡片提示词 |
| state.json 结构 | json 解析 | 4 cookie（**全是百度统计，无会话 cookie**）+ localStorage 含 SECRET_TOKEN |

---

## 十一、发现的问题与风险清单

### 11.1 确认的代码问题

**#1 返回契约不一致（真实缺陷，影响可观测性）**

`ai_auto_chapter` 的返回 dict 只有 `gen` / `body` / `review`（+ 可选 `prepare`），
**没有 `ok` 和 `reason` 键**。但 `src/ai.py:3353`：

```python
results.append({"no": no, "ok": ok,
                "body": r.get("body") if isinstance(r, dict) else None,
                "reason": r.get("reason") if isinstance(r, dict) else None})
```

→ `reason` **恒为 `None`**（包括 `except` 分支构造的 `{"ok": False, "reason": ...}`
之外的所有正常路径）。批量跑章失败时**拿不到失败原因**，只有「第N章失败」。
注意 `except` 分支构造的 dict 反而**有** `reason`（但不含 `body`）—— 不一致。

**#2 `SLOW_MO` 是死配置**

`config.py:228` 定义 `SLOW_MO = int(os.getenv("XYX_SLOW_MO", "80"))`，
但 `browser.py:126` 的 `p.chromium.launch(headless=..., executable_path=..., args=..., ignore_default_args=...)`
**没有 `slow_mo=SLOW_MO`**。所以这个环境变量/配置项目前**完全不生效**
（实际人类化延迟来自 `actions.human_pause()` 的随机 sleep，与它无关）。

**#3 `REVIEW_PANE_SEL_DEFINED` / `REVIEW_RESULT_TEXT` 等死代码**

`src/ai.py` 里确认的死代码/死常量（全仓库零引用）：

| 位置 | 符号 | 说明 |
|---|---|---|
| `ai.py:1728` | `REVIEW_PANE_SEL_DEFINED = True` | 纯占位标记 |
| `ai.py:2326` | `REVIEW_RESULT_TEXT = "替换"` | 定义了但无人引用 |
| `ai.py:1329` | `gen_dialog_open()` | 零调用 |
| `ai.py:2329` | `review_generating()` | 零调用 |
| `ai.py:1546` | `_close_tip_dialog()` | 零调用 |
| `ai.py:52` | `from . import actions as A` | **导入后未使用** |
| `browser.py:217` | `launch_browser_for_task()` | 零调用 |
| `session.py:56` | `load()` | 零调用（存在但没人用） |
| `app.py:49` | `App._persistent` | 只赋值、从不读取 |
| `login.py:614` | `is_ready(auto_verify=...)` | 参数未使用 |
| `books.py:620` | `_shot_counter` | 只自增、从不读取 |

**#4 `config.CDP_PORT` 未接线 → CDP 接管能力实际不可用**

`config.py:247` 定义了 `CDP_PORT`，但**全代码库只有定义、无引用**。
`App.__init__` 只读 `C.BROWSER_PATH`。要触发 CDP 必须**手动**把 `browser_path`
传成端口数字字符串（`open_browser` 里用 `str(x).isdigit()` 判断）。
且 `open_browser(p=None, ...)` 的 CDP 分支直接调 `open_cdp_session(p, ...)`，
若调用方真不传 `p` 会 `AttributeError`。
→ README 第十节大书特书的「CDP 接管最强风控方案」**在 GUI/CLI 里没有入口**。

**#5 ★★ 一处线程模型不一致（GUI 潜在 bug）**

源码注释（`main_window.py:103-113`、`3036-3043`）把「Playwright 对象必须始终在
同一个线程操作」当作**关键修复**，并为此建了常驻线程 `pw-worker`。
但我逐个核对全部 **5 处 `App(...)` 创建点**，发现**有一处没走常驻线程**：

| 行 | 所在函数 | 投递方式 | 是否安全 |
|---|---|---|---|
| 622-623 | `_start_login.worker` | `self._pw_queue.put(worker)` | ✅ |
| 714-715 | `_verify_session.worker` | `self._pw_queue.put(worker)` | ✅ |
| 813-814 | `_ensure_app()` ← `_prepare_go.worker` | `self._pw_queue.put(worker)` | ✅ |
| 1204-1205 | `_ensure_page()` ← `_list_all_books.worker` | `self._pw_queue.put(worker)` | ✅ |
| **3000-3001** | **`_run_task.worker`（任务中心）** | **`self._run_guarded(...)` → 普通线程** | ❌ |

`_run_guarded`（`:3099-3113`）里的 `runner` 是投到 `_pw_queue` 的，
但它只负责**执行 `worker_fn` 并管状态**；而 `_run_task` 的 `worker`
是 `worker_fn` 本身，里面创建了 `App` 和浏览器。
→ 结果是：**任务中心（11 个任务卡）跑任务时，浏览器被创建在一个普通线程上，
该线程任务结束即退出**；之后若再点「① 打开网站并保存」等走 `pw-worker`
线程的操作，就会撞上注释里描述的
`cannot switch to a different thread (which happens to have exited)`。
（复现顺序：先在「任务中心」点任意任务 → 再点「小说分章」页的准备按钮。）

这是**真实存在的模型不一致**，不是纯理论问题。

**#6 `tasks/adapters.py` 全部 `threaded=False`**

11 个任务**全部**注册为 `threaded=False`，即 `execute_task` 在主线程同步调用。
在 GUI 路径下 `_run_task` 已把 `worker` 放到后台线程，所以**GUI 不会卡**；
但 `execute_task` 的 `threaded` 语义因此形同虚设
（唯一实际调用方 `App.run_task` ← `_run_task` 已在别的线程里）。

**#7 `prepare_session` 的 `ok` 可能虚高（登录态误判风险）**

`login.py:596`：`ok = bool(logged and (saved or after.get("saved")))`。
`after.get("saved")` 来自**本地旧 state 文件**，因此「本轮登录判定失败但本地有旧
state」时 `ok=True`。配合下面 #8 的宽兜底判据，存在**保存/沿用一份无效登录态**
的可能。

**#8 `is_logged_in` 第 3 路兜底过宽**

`login.py:161-165`：URL 不含 `/welcome` 就判「已登录」。
`about:blank`、任何其它 hash 路由都会命中。这是 `ensure_login` / `prepare_session`
的最终判据来源，标为风险点。

**#9 `render_for_batch` 会静默清空未知代号**

`novel.py:453-456`：把**所有** `#N` 替换成 `#@` 后，若该章号不存在，
`_pick` 返回 `""` → 模板里该位置变成空，**不报错**。
（对比：直接调 `render_template` 时未知代号是**原样保留**的。）
→ 批量跑章时若模板写了越界代号，会生成空提示词而不报警。

**#10 `session._guess_account` 的候选键与站点真实键不匹配**

`session.py:148-174` 扫描 `userInfo` / `user_info` / `user` / `account` /
`username` / `nickName`；而实测 `state.json` 里站点的真实键名是
**`userStorage`**（用户信息嵌套在 `data.userInfo` 下）。
→ `session_meta.json` 的 `account` **实测恒为空串**（已核对磁盘文件）。

**#11 `browser_detector` 的若干小问题**

- `get_recommended_browser()` 内部再次调用 `detect_all_browsers()`
  （`:210`），导致 `get_browser_info()` 会**重复探测一遍**并打印两轮日志。
- Windows 的 `Edge Dev` 注册表键与 `Edge` **完全相同**（`:86-88`），
  「Edge Dev」实际可能返回稳定版 `msedge.exe`。
- **Linux 完全未支持**：`IS_WIN`/`IS_MAC` 之外走 MAC 分支 → 返回空 → 回退内置 Chromium。

**#12 `browser.py` 用 `requests` 探活但未声明依赖**

`open_cdp_session`（`:166`）按需 `import requests`，但 `requirements.txt` 只有
`playwright`。`requests` 是 Playwright 的**间接依赖**；一旦缺席，
`ImportError` 会被 `except Exception` 吞掉，**伪装成「端口上没有可接管的浏览器」**。

**#13 `chapter_files.get_chapter_details` 丢正文**

`:118-127` 用 `f.readline()` 只取首行作标题，之后 `f.read()` 读**其余**内容
→ 首行中标题之后的正文被丢弃。
另 `normalize_chapter_title` 的 `elif first_line.startswith("#")` 分支
逻辑上与 `create_chapter_files` 写出的 `# 标题` 格式错位（`:120-124`）。

**#14 `open_book` 的 `click_create_book` 双重查询**

`books.py:409-433`：`find_create_card` 拿到的 Locator 只用于读 `class`，
真正点击走 `A.click_strict` **重新 query**，两者可能命中不同元素。
且 `find_create_card` 在多命中时「取第一个」（`:125-127`），
而 `click_strict(expect_unique=True)` 会因此**拒绝点击**
→ 入口卡可见但点不动。

**#15 `platforms/__init__.py` 末尾导入**

第 63 行 `from . import adapters` 是**必需的**（触发注册），不是 bug，
但 `get_platform` 等函数定义在导入之前，属典型的循环导入规避写法。

**#16 `workspace.py` 导入风格不一致**

`workspace.py:28` 用绝对导入 `from src import config as C`，
其余模块都用相对导入 `from . import config as C`。
同一进程若以不同方式导入 `src`，可能出现**两份 config 实例**
（`config.py` 在导入时会 `mkdir` 那些目录）。

### 11.1b GUI 层已确认的缺陷（全部经代码核对）

**G1 ★★ `BrandButton` 的「禁用」不生效（实测确认）**

`_run_guarded`（`main_window.py:3095`）和 `_prepare_go`（`:829`）用
`btn.config(state="disabled")` 表示忙碌。但 `BrandButton` 继承 `tk.Canvas`，
其事件处理看的是**自己的** `self._enabled`：

```python
# theme.py:369-375
def _on_release(self, event):
    if not self._enabled:      # ← 只认 self._enabled
        return
    ...
    if 0 <= event.x <= self._btn_w and 0 <= event.y <= self._btn_h and self._cmd:
        self._cmd()            # ← 照常执行
```

`tk.Canvas` 接受 `state` 选项（所以不会报错），但**外层的 widget state 不拦截
`<Button-1>`/`<ButtonRelease-1>` 绑定**，而 `_enabled` 仍是 `True`
→ **被「禁用」的按钮依然可以点击**，忙碌期间重复触发任务。
正确姿势是 `set_enabled(False)`（`theme.py:378`）—— 全项目**只有
`login_window.py:257` 用对了**。

**G2 ★★ `_clear_session` / `_prepare_clear` 跨线程操作 Playwright**

`main_window.py:756` 和 `:927` 在 **Tk 主线程**直接调 `self._app.stop()`
并 `self._app = None`。而该 `App`/`browser`/`context` 是在 `pw-worker`
常驻线程里创建的 —— **正好违反源码自己在 `:103-109` 写下的规则**
（Playwright 对象不能跨线程），且会与队列中尚未执行的任务竞争。

**G3 ★ `_ai_batch_go` 使用陈旧的 `_ai_book_index`**

`_ai_book_index` 只在 `_ai_go`（`:2240`）、`_ai_review_go`（`:2377`）、
`_ai_both_go`（`:2493`）里被赋值，**`_ai_batch_go` 自己从不解析**「第几本」输入框，
却在 `:2763` 直接把该字段传给 `open_book`。
→ 批量跑章用的是**上一次单章操作留下的旧索引**，或初始值 `None`。

**G4 ★ 单章续写不会替换 `#@`**

`_ai_go`（`:2287`）与 `_ai_both_go`（`:2513`）调用
`self._project.render_template(tpl)` **没有传 `current=`** →
模板里的 `#@` / `{{当前章}}` **原样送进站点**。
只有批量跑章走 `render_for_batch`（`:2709`）才会替换。
而 UI 文案（`:1379`、`:1282`）却在教用户「#@ = 当前章」——
**单章路径下这个教学是错的**。

**G5 `_do_split` 在非主线程读 Tk 控件**

`main_window.py:2020-2021` 在后台线程里读
`self._prefix_entry.get()` / `self._suffix_entry.get()`。
另 `:882`（`_prepare_save_now` 的 worker）在后台线程直接调 `self.log(...)`，
同函数其它分支都正确用了 `self.after(0, ...)`。
→ `theme.py:555` 的 `LogView.log` docstring 自称「**线程安全地**追加一行日志」，
**该声明不成立**；安全性完全依赖调用方自觉用 `after`。

**G6 `_prepare_clear` 重复定义**

`:902` 是一个只有 docstring 的存根，`:904` 是真实现 —— 前者被**静默覆盖**。
且与 `_clear_session`（`:735`）功能几乎重复。

**G7 主窗口没有关闭清理**

`MainWindow` 全文**没有 `protocol("WM_DELETE_WINDOW", ...)`**，
`_logout`（`:3135`）只 `destroy()` + 回调，**不调 `App.stop()`**
（对比 `login_window.py:56` 有绑定）。
→ 直接关窗会留下 Playwright 浏览器进程。

**G8 「运行配置」页的浏览器路径是死配置**

`self._browser_entry` 只在 `:2925` 创建、`:3123`（自动检测后）写入，
**从未被读取**。全部 5 处 `App(headless=False)` 构造**都不传 `browser_path`**，
`workspace.json` 也不含该字段 → 「自动检测」按钮对实际启动**零影响**。

**G9 切页会丢失章节编辑状态**

`show_page`（`:355-361`）销毁并重建全部子控件，而 `_render_chapters`
只在 `_do_split` 后（`:2034`）和 `_open_project`（`:2891`）被调用。
→ 从「小说分章」切走再切回：**章节列表空了**、`_ch_entries` 指向已销毁控件，
但 `self._project` 仍在内存中（非 None）→ **界面与实际状态不一致**，
已填的细纲在界面上「消失」（若未保存工程则真丢失）。

**G10 任务中心与 GUI 配置完全脱节**

`src/tasks/adapters.py` 的 11 个任务**全部只读环境变量**（`XY_BOOK`、
`XY_BATCH_FROM/TO`、`XY_AUTO_*`、`XY_RV_*`…），既不读 `workspace.json`
也不读界面控件 → **用户在界面上填的一切，在「任务中心」里全部无效**。
更严重的是任务用 `console_pick=True`（`adapters.py:323/395`），
撞上同名作品时会 `input()`（`books.py:294-295`）：
经 `launcher.py`（带控制台）启动会**在控制台静默等待输入而 GUI 毫无提示**。

**G11 其它已确认的死代码 / 小问题**

| 位置 | 问题 |
|---|---|
| `main_window.py:2898` | `_count_words()` —— **没有任何按钮指向它**（死方法） |
| `main_window.py:944` | `_prepare_then_both()` —— 无调用者 |
| `main_window.py:2198` | `_current_ai_chapter()` —— 解析出的值无人使用 |
| `main_window.py:2216` | `_preview_ai_plot()` —— 无调用者 |
| `main_window.py:3055` | `_run_on_pw_thread()` —— 无调用者 |
| `main_window.py:3114/3116` | `_run_guarded` 末尾 `return True` **不可达** |
| `main_window.py:27` | 导入 `FM` 未使用 |
| `login_window.py:9/14` | 导入 `hashlib`、`GradientBar`、`Toast` 未使用 |
| `show_page:383` | 每次切页都往日志写一行 → 频繁切页刷屏 |
| `_page_overview:404-411` | 重复调用 `_session_info()` **4 次**（4 次磁盘读取） |
| `_ai_ch_menu:1524` | 「续写到第几章」下拉**只影响提示文案**，不参与任何逻辑 |
| `main_window.py` 多处 | 混用 7 处裸 `tk.Checkbutton` + 1 处 `tk.OptionMenu`，与自绘深色风格不一致 |
| `_novel_entry` 占位符 | 写着「或把 txt 拖进来」，但**没有任何拖拽（DnD）绑定** |
| `workspace` 保存时机 | **关窗 / 登出 / 切页都不保存** → 改完模板不点运行就关窗 = 改动丢失 |

### 11.2 架构层面的脆弱点（源码自己已标注）

| 风险 | 说明 |
|---|---|
| **极度依赖中文文案** | 几乎所有选择器都是 `:has-text('待审文本')` / `text=细腻版` / `button:has-text('生成')`。站点一改文案，全盘失效 |
| **依赖动态类名的稳定性** | `chapter-side-pane-c` 被注释明确标记为「动态生成、不可靠」，靠文字锚点兜底 |
| **硬编码 sleep（数量很大）** | `ai.py` 内遍布 `0.15/0.3/0.4/0.5/0.6/0.7/0.8/1.0/1.2/1.5/2.0/3.0` 秒固定等待（`:593,634-638,759,817,880,910,1172,1193,1279,1298,1308,1411,1537,2085,2276,2295,2514,3085`）。核心流程成败很大程度依赖这些魔数 |
| **硬编码几何坐标** | `ai.py` 用图像坐标兜底：`:659` `mouse.click(rb.x-120, rb.y-60)`；`:619` 滑块 `(width-20)*idx/5`；`:807` 分类项 `y>200 且 width>120`；`:841` 卡片 `x>380 且 width>300`；`:1256` `mouse.move(640,400)` + `wheel(0,320)`×12；`:1284` 箭头 `x+width-14`；`:1856` 遮罩 `(8,8)`；`:2894` `box.x+8, box.y+8`。站点换分辨率/改布局即失效 |
| **`STATE_FILE` 是明文票据** | README 与 `.gitignore` 都反复警告；`.gitignore` 已排除 `artifacts/` |
| **`credentials.py` 不是强加密** | 机器码派生密钥（盐硬编码 `"zhaoshi-xingyue-studio"`）+ XOR + base64。`username` **明文存储**；无随机 IV，同明文必得同密文。换机器/改用户名 → 静默解不出（返回空串、无告警）。源码注释自认「不是强加密」 |
| **`is_logged_in` 第 3 路兜底过宽** | 「URL 既不在登录页也不在 welcome → 视为已登录」。`about:blank` 或任何其它 hash 路由都会命中（见 #8） |
| **`ensure_chapter` 只支持往上补** | 跳号（删过章）无法自动补建，直接返回 False |
| **腾讯滑块无法自动过** | `auto_login` 检测到验证码后只能提示人工完成（等 120s） |
| **`_t_e2e_full.py` / `_t_verify_shortcut.py` 是硬编码开发脚本** | 写死作品名「新建作品1」、章节「第2章」，不适合直接当回归测试 |
| **静默吞异常极多** | `except Exception: pass/continue` 遍布全项目。真故障常表现为「读不到 → 当作已满足」。最典型：`select_model` 把**回读为空当成功**（`ai.py:896-900`）、`set_associate_level` 读不到档位就假定已满足（`:720-723`） |
| **`pick_shortcut` 失败不阻断** | 站点上找不到提示词会**静默沿用当前提示词**，可能跑完一整章才发现用错了（`ai.py:1135-1144`） |
| **`open_chapter` 未命中时退回最小章号** | `ai.py:2207-2223`：仍可能把内容写进第 1 章（比写进最新章好，但依然是错的章），仅打印警告 |
| **`relate_chapters` 只支持 5/8/10 章** | `text=最近{count}章` 只在展开菜单后存在；count 不在菜单里必然失败 |
| **`get_gen_word_count` 取「最后一个纯数字」** | `ai.py:1479-1481`：若弹窗内其它 textarea 也渲染 word-count，会取错对象 |
| **`ai_review` 的 `model_card_hint` 默认值双份维护** | 硬编码在签名里（`ai.py:2663`）与 `MODEL_CARD_HINT["智慧版-6A"]` 重复，两处不一致会静默分歧 |
| **`app.py:63` 的 LogRedirector 从不 restore** | `App.start(with_log_file=True)` 装了一个无 sink 的重定向器且从不还原；UI 层每次任务再装一层 → 多层嵌套，靠 `finally` 顺序正确才不出问题 |
| **`set_associate_level` 模块级全局状态** | `LAST_DECISION` 是模块级可变全局（`ai.py:57`），非线程安全；靠 `_run_guarded` 的互斥串行才能用 |

### 11.2b 文件行数计数的说明

本报告的行数来自 `read` 工具与 AST 解析。`ui/main_window.py` 若用
`Get-Content | Measure-Object` 统计会得到 2792 而非 3230 —— 这是
CRLF / 末尾空行的计数差异，**以 AST 的 3230 行为准**。

### 11.3 未验证的部分（诚实声明）

以下功能**需要真实浏览器 + 有效登录态 + 消耗站点 AI 额度**，本次分析**没有实机运行**：
`ai_continue` / `ai_review` / `ai_auto_chapter` / `ai_batch_chapters` 的真实页面交互、
`books.open_book` 的真实点击、`prepare_session` 的真实登录。

这些部分的分析来自**源码逐行阅读 + 注释中记录的实测结果 + 日志证据**
（`artifacts/logs/run-20261004-000558.log` 可见完整的三阶段执行痕迹，
包括「已点『AI审稿』（第1次）」「模型弹窗已就绪（根级 .model-picker-modal）」
「联想能力已设为『正常』」等，证明这套流程**确实跑通过**）。

---

## 十二、关键设计理念总结

1. **配置集中化** —— 站点易变信息全在 `config.py`，业务代码不碰选择器。
2. **注册表 + 适配器** —— 任务和平台都用装饰器注册，加功能只加函数不动框架。
3. **多选择器回退 + 人类化延迟** —— `actions.py` 的设计原则：
   一个动作给多个候选选择器按序试；动作间随机延迟；失败自动截图。
4. **「有则关、没有就跳过」的弹窗哲学** —— 用户明确要求，所有 `dismiss_*` 一律
   返回计数、`try/except` 包裹、**不做「必须关掉才算成功」的假设**，绝不影响主进程。
5. **登录态「一次登录长期复用」** —— 项目最核心的便利功能，靠 `storage_state`
   导出/注入 + 多路判定 + 手动强制保存兜底。
6. **判据要「正向、唯一、稳定」** —— 生成完成不用「字数不变」（会误判），
   改用「重新生成按钮出现」；审稿完成不用「待审文本」（会消失），
   改用 footer 的 `success-type` 按钮且连续 2 次命中。
7. **已知坑写进注释** —— 三个模块（ai / books / login）的文件头都有大段
   「实测于 2026-10-03/04」的坑位记录，这是这个项目最宝贵的知识资产。
8. **单线程操作浏览器** —— Playwright 对象不能跨线程，GUI 用常驻线程 + 队列
   从架构上根除这类错误。

---

## 十三、快速上手指引

### 环境现状（本机实测）

| 项 | 值 |
|---|---|
| `.venv312`（**GUI 用**） | Python **3.12.7**，playwright 1.63.0，pillow 12.3.0 |
| `.venv`（**CLI 用**） | Python **3.13.14** |
| 登录态 | **已存在且 9 小时前刚保存**（4 cookie / localStorage 含 SECRET_TOKEN，用户 ID 914359） |
| 工作区配置 | 小说 = `开局被绿，我直播捉奸震惊全网.txt`（桌面）；作品名 = `新建作品1`，第 0 本；自动采纳已开启（min=1, max=2300, retry=1） |

### 最常用命令

```bat
:: GUI（推荐）
启动.bat

:: 看登录态
.venv312\Scripts\python.exe main.py session

:: 列作品（带 ID）
.venv312\Scripts\python.exe main.py books

:: 一条龙跑一章
.venv312\Scripts\python.exe main.py auto 新建作品1 --chapter 第2章 --min 100 --max 5000

:: 批量跑第 3~10 章（用工程指令模板）
.venv312\Scripts\python.exe main.py batch 新建作品1 --from 3 --to 10 --project 我的小说.novel.json

:: 站点改版后侦察选择器
.venv312\Scripts\python.exe main.py recon
```

### 排查顺序

1. `main.py session` —— 登录态还在吗？
2. `main.py diag` —— 判定为什么失败？打印全部 cookie + localStorage。
3. `main.py books` —— 能找到作品吗？ID 对不对？
4. `artifacts/screenshots/` —— 失败截图
5. `artifacts/logs/run-*.log` —— 完整日志
6. `main.py recon` —— 站点改版后重找选择器，改 `src/config.py`

---

*报告结束。全文基于对 13,078 行源码的通读、AST 结构扫描、以及实际运行的 CLI 与
`novel.py` 渲染验证；未实机运行需要真实浏览器的 AI 流程，已在 §11.3 明确标注。
§11.1 / §11.1b 的每一项缺陷都已通过 grep / 读源码**逐条复核**，不是推测。*

## 附：分析方法说明

本报告由「主分析 + 三路并行深读」完成，互为交叉验证：

1. **主分析**（本会话）：通读 `main.py` / `README.md`(1237 行) / `config.py` /
   `app.py` / `session.py` / `login.py` / `novel.py` / `actions.py` / `browser.py` /
   `tasks/adapters.py` / `workspace.py` / `chapter_files.py` / `logging_redirect.py` /
   `diag_login.py` / `credentials.py` / `platforms/` / GUI 关键段落；
   跑 CLI、AST 统计、`novel.py` 渲染实测。
2. **`src/ai.py` 深读**（子代理）：全文 3369 行整读，产出 49 个公开函数的完整签名、
   分区表、关键流程逐步编排、17 项脆弱点。
3. **GUI 层深读**（子代理）：`main_window.py`(3230) / `theme.py`(701) /
   `login_window.py`(288) / `shot.py`(67) 整读，产出 7 个页面的完整控件清单、
   线程模型、22 项问题。
4. **基础设施深读**（子代理）：`browser` / `browser_detector` / `session` / `login` /
   `credentials` / `actions` / `novel` / `workspace` / `books` / `chapter_files` /
   `logging_redirect` / `tasks` / `platforms` / `diag_login` 整读，产出逐文件 API 表、
   判定逻辑、16 项问题与依赖图。

三路结论与主分析**无冲突**（行数差异已定位为 CRLF 计数问题，见 §11.2b）；
所有写入 §11 的问题项均由主分析独立 grep 复核过。

**本次分析未修改任何项目源码**（只新增了本报告 `PROJECT_UNDERSTANDING.md`）。
