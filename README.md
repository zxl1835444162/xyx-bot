# 赵氏集团 · 星月创作台（xyx-bot）

<p align="center">
  <img src="packaging/icons/icon-256.png" width="112" alt="星月创作台">
</p>

基于 **Python + Playwright** 的网文创作自动化工具：接管你自己电脑上的浏览器，替你在
[星月写作](https://xingyuexiezuo.com/) 上做**续写正文 → AI 审稿 → 逐章批量跑**这三件事，
带一个 tkinter 深色界面。

| | |
|---|---|
| 支持系统 | Windows / macOS（Apple Silicon + Intel）/ Linux |
| 运行依赖 | `playwright`（自动化）+ `Pillow`（截图与图标），**仅此两个** |
| 测试 | `python tests/run_all.py` → **1015 项断言 / 12 个用例** |
| 版本 | 见 `xyxbot/version.py`（唯一真相源） |
| 变更记录 | [`CHANGELOG.md`](CHANGELOG.md) |

> **它不做什么**：不代写、不生成文本、不替你登录。AI 生成的文字来自星月写作站点本身，
> 这个工具只负责**把你的指令准确地点进去、把结果准确地带回来**。

---

## 一、快速开始

### Windows

```bat
:: 双击 启动.bat 即可（首次会自动建 .venv 并装依赖，约 1-3 分钟）
启动.bat
```

### macOS / Linux

```bash
python3 launcher.py          # 会自动挑一个带 tkinter 的解释器，建 .venv、装依赖、开界面
```

### 命令行方式（两种写法等价）

```bash
python main.py selftest      # 环境自检（tkinter / 数据目录 / 浏览器 / 界面能否构造）
python -m xyxbot selftest    # 同上，包入口写法
```

> 首次启动若提示找不到 Python：装 [python.org 官方版](https://www.python.org/downloads/)
> 并勾选 **tcl/tk** 与 **Add python.exe to PATH**。`launcher.py` 会把本机所有解释器
> 列出来逐个试 tkinter，所以哪怕 `py -3` 挑到了没装 tk 的新版本也能自己纠正。

---

## 二、首次使用：登录一次，之后免登录

登录态用 Playwright 的 `storage_state` 存成一份 `state.json`，之后每次自动注入，
等同于"你已经登录过了"。

1. 界面左侧 →「**星月账号**」页 → 点「**登录星月账号**」（会打开你本机的 Edge/Chrome）
2. 在浏览器里扫码或输账号密码（有滑块也能手动过）
3. 确认已经登录进去了 → 回软件点「**我已登录，立即保存**」

登录态文件位置：

* Windows：`artifacts/storage/state.json`
* macOS：`~/Library/Application Support/XYXBot/artifacts/storage/state.json`

> 登录判定走**多路校验**（排除登录页 → 查 localStorage 票据 → 查已登录标志 → 兜底），
> 不依赖某一个选择器。判不出来时点「我已登录，立即保存」照样能存下来。

---

## 三、两种用法

### 3.1 图形界面（默认页「跑章」）

主界面左侧只有三项：**跑章 / 星月账号 / 更多**。默认页就是把一次完整任务需要的
东西从上到下摆好：

```
① 目标与版本      选作品（或输入项目名）→ 选章号区间
② 范围与节奏      起始章 / 结束章 / 缺章怎么办 / 失败要不要停
③ 提示词与细纲    快捷指令（提示词）、模型、联想档位、后续剧情（细纲）
④ 细纲来源        从本地 txt 导入细纲，按 `#@` 占位符逐章替换
⑤ 开跑            本地预检（不开浏览器）→ 深度预检（上站点核对）→ 开跑
⑥ 进度与结果      逐章进度、每章字数、失败章号一键复制/重试、导出 CSV
```

「**跑章**」= 逐章：**续写 → 审稿 → 替换正文**，三个动作全自动，失败按策略重试。

### 3.2 命令行

```bash
python main.py                 # 列出全部命令
python main.py login           # 登录一次，保存登录态
python main.py session         # 查看登录态详情
python main.py books           # 列出你在站点上的作品（带 ID）
python main.py open 书名       # 打开指定作品（同名可加 --index N）
python main.py ai 书名         # 只跑「AI 续写正文」
python main.py review 书名     # 只跑「AI 审稿」
python main.py auto 书名       # 一条龙：续写 → 审稿
python main.py batch 书名 ...   # 批量跑章（指定区间，逐章一条龙）
python main.py tasks / run <任务名> / platforms
python main.py selftest        # 环境自检
python main.py browsers        # 检测本机可用浏览器
python main.py diag            # 登录态诊断（打印 URL / cookie / localStorage / 判定结果）
```

完整参数与实测示例见 **[`docs/USAGE_DETAIL.md`](docs/USAGE_DETAIL.md)**（原 README，
里面保留了当年一条条真机验证的记录）。

---

## 四、项目结构

```
.
├── xyxbot/                     业务包（唯一入口包，`python -m xyxbot`）
│   ├── cli.py                  命令行 19 个子命令
│   ├── app.py  books.py  novel.py         主类 / 作品页交互 / 小说解析
│   ├── browser.py  browser_detector.py    CDP 接管 + 跨平台浏览器探测
│   ├── session.py  login.py              登录态存取与多路校验
│   ├── waiting.py             ★ 条件等待原语（wait_until / wait_gone / wait_visible）
│   ├── ai/                    ★ AI 流水线（原 5378 行单文件，已按职责拆分）
│   │   ├── selectors.py       选择器与站点常量表
│   │   ├── elements.py        底层元素定位/点击/填写/取消标志
│   │   ├── dialog.py  current.py  model.py  shortcuts.py  relate.py
│   │   ├── body.py  chapters.py  generate.py  review.py
│   │   └── flows.py           对外流程：续写 / 审稿 / 一条龙 / 批量跑章
│   ├── ui/                    界面
│   │   ├── main_window.py      主窗口 + 导航 + 卡片式滚动
│   │   ├── theme/              主题（原 1270 行单文件，已拆分）
│   │   │   ├── palette.py  fonts.py  redraw.py  scroll.py  widgets.py
│   │   ├── pages/              9 个页面（run 是主流程）
│   │   └── defaults.py  browser_session.py  shot.py
│   ├── platforms/  tasks/    平台注册表 / 任务注册表（一个站点一个类）
│   └── version.py            版本唯一真相源
├── tests/                      测试 + 统一 runner（run_all.py）
├── tools/                      开发与诊断脚本（diag / audit / dev / scratch）
├── docs/                       架构、移植、审计、使用手册
├── packaging/  scripts/        打包 spec 与应用图标 / 构建脚本
├── main.py                     命令行薄壳（→ xyxbot/cli.py）
├── run_gui.py                  界面入口（打包入口）
├── launcher.py                 环境入口：挑解释器、建 .venv、装依赖
└── 启动.bat / build.bat        Windows 一键启动 / 一键准备环境
```

---

## 五、开发

```bash
# 全部测试（自动发现 tests/test_*.py，带超时，日志落 artifacts/logs/tests/）
python tests/run_all.py

# 只要不依赖窗口的用例（打包前 CI 用这个）
python tests/run_all.py --quick

# 环境自检（含"主窗口真的显示出来了吗"）
python -m xyxbot selftest

# 打包
bash scripts/build_macos.sh          # macOS → dist/XYXBot.app
build.bat                            # Windows：准备环境 + 检测浏览器
```

* **测试与文件布局解耦**：所有"文件在哪"的问题统一走 `tests/_support.py`，
  拆分/改名不会让测试红一片（这是本仓库重构的第一原则）。
* **CI**：`.github/workflows/tests.yml` 在 Ubuntu / Windows / macOS 三平台跑
  `tests/run_all.py`；用例清单不再写死在 yml 里。
* **打包**：`.github/workflows/build-macos.yml` 产出自包含 `XYXBot.app`（含启动自检）。

---

## 六、常见问题

| 现象 | 处理 |
|---|---|
| macOS 提示"无法验证开发者" | 右键 App → 打开 → 再点「打开」；或 `xattr -dr com.apple.quarantine XYXBot.app` |
| 提示找不到带 tkinter 的 Python | 装 python.org 官方版（勾 tcl/tk）；或 `brew install python-tk` |
| 登录后仍提示未登录 | 「星月账号」页点「我已登录，立即保存」；还不行就 `python main.py diag` 看诊断输出 |
| 任务卡住不动 | 点「停止」（协作式取消，≤0.25 秒生效）；`tools/diag/diag_latency.py` 看是哪一步在等 |
| 站点改版导致元素找不到 | `python main.py recon` 侦察页面可见元素，把选择器更新到 `xyxbot/ai/selectors.py` |

---

## 七、说明

* 本工具**仅供学习与研究**，请遵守目标站点的使用条款，不要用于批量灌水或破坏性操作。
* 所有自动化都发生在**你自己电脑上的浏览器**里，登录态只保存在本地文件，
  不上传任何服务器。
* 本仓库做过一次结构性重构（包结构 / 文档 / CI / 巨兽文件拆分），
  施工记录见 [`docs/REFACTOR.md`](docs/REFACTOR.md)，体检报告见 [`docs/AUDIT.md`](docs/AUDIT.md)。
