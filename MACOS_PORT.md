# macOS 移植 + GitHub Actions 自动打包

> 2026-10-04：把 Windows 上的应用搬到 macOS，并让 GitHub Actions 自动出 `XYXBot.app`。

---

## 一、先说清楚：我做了什么、**哪些我验证不了**

| 我做了什么 | 状态 |
|---|---|
| 平台适配（字体 / UA / 数据目录 / 启动器 / 浏览器检测） | ✅ 已改，**在 Windows 上实测没有行为回归** |
| 打包配置 `packaging/macos/xyxbot.spec` | ✅ 已写，语法校验通过（`compile()`） |
| GitHub Actions 工作流（测试 + 打包） | ✅ 已写，**用真实 YAML 解析器验证过**，矩阵/标签都对 |
| 环境自检 `--selftest`（不开窗口，CI 与排障共用） | ✅ 已实现，**本机实测退出码 0** |
| 跨平台回归测试 `tests/test_portability.py` | ✅ 87 项，**本机全绿** |

**我验证不了的（必须由 macOS + CI 来完成）：**

1. **我无法在 Windows 上跑 macOS 二进制。** PyInstaller 不能跨平台编译 ——
   `.app` 只能在 macOS 上打。所以"打出来的包能不能双击起来"这件事，
   只有 CI 跑过一次才知道。
2. **我无法执行 shell 脚本**（这台机器没有 Git Bash / WSL 发行版），
   所以 `scripts/*.sh` 只做了逐行审查，没跑过 `bash -n`。
3. **我无法运行 GitHub Actions**（这台机器**没装 git**，也没有仓库和凭据）。

所以下面第二节是**你要做的一步**，做完 CI 就会给你答案。

---

## 二、GitHub 仓库与授权：**已完成**

这台机器上没装 git，但我发现你的 `.gitconfig` 里指着一个 **PortableGit**
（`~/.workbuddy/binaries/PortableGit/...`，git 2.55.0），里面还带
**Git Credential Manager**。

检查后发现：**你的 GitHub 凭据本来就已经存在**（登录名 `zxl1835444162`，
令牌权限 `gist, repo, workflow`）—— 所以**不需要再弹授权窗口**，直接就能推。

已经做完的事：

| 步骤 | 结果 |
|---|---|
| `git init -b main` | ✓ 仓库级 user.name/email（**没改你的全局配置**） |
| 提交 | ✓ `121a6f2` … 后续还有修复提交，共 94 个文件 / 5.06 MB |
| 敏感文件检查 | ✓ **没有** `artifacts/`（含明文登录票据）被提交 |
| 建仓库 | ✓ https://github.com/zxl1835444162/xyx-bot （**private**） |
| 推送 | ✓ `main` 分支已推上去 |
| 工作流 | ✓ 两个都已注册、状态 `active` |
| Actions | ✓ `tests` 已在跑；`build-macos` 手动触发 |

### 仓库为什么建成 private

代码是私有的更稳妥。**代价是 macOS 构建额度有限**：

* GitHub 免费账户每月 2000 分钟；**macOS runner 按 10 倍计费**
* 本项目两个架构并行 ≈ 每个 8 分钟 → 一次构建计费约 **160 分钟**
* 所以 private 大约能跑 **每月 12 次**

如果你希望**不限次数免费**，在仓库 Settings → General → 最下面
"Change repository visibility" 改成 **public** 就行（一处点击，随时可改回）。
你现有的 `novel-publisher-mac` 就是 public，所以这大概也符合你的习惯。

---

## 二点五、应用图标

你的图标已经接进去了：

| 文件 | 用途 |
|---|---|
| `packaging/icons/source-icon.png` | 你给的原始 2048×2048（**原样保留**） |
| `packaging/icons/icon.icns` | macOS 应用图标（10 个尺寸，含 Retina） |
| `packaging/icons/icon.ico` | Windows 图标（16/24/32/48/64/128/256） |
| `packaging/icons/icon-1024.png` | 参考 / Linux 用 |
| `packaging/icons/icon-256.png` | 同上 |

生成脚本：`python scripts/make_icons.py`（可重跑，参数都在文件顶部）

### 我对源图做了两处处理，都不是"美化"，是必要的

1. **去掉了右下角的「即梦AI」水印。**
   把别人工具的 logo 打进自己的应用图标不合适，而且小尺寸下它就是一坨模糊亮斑。
   做法：那块背景是近乎纯色的深蓝（标准差 <3），所以直接用**同一行左侧 470px
   处的真实背景像素**覆盖（保留渐变与噪点），边界 6px 羽化。
   想保留水印就设环境变量 `XYX_KEEP_WATERMARK=1` 重新生成。

2. **套了 macOS 的圆角外形。**
   源图是满幅正方形，直接放进去会是"一个方块夹在一堆圆角图标中间"。
   做法：缩到 880×880，套一个**超椭圆**遮罩（`|x|^n+|y|^n=1`，n=5，接近
   Apple 的连续圆角），居中贴到 1024×1024 透明画布。
   实测你的作品只占 16.6%~78% 的范围，所以 72px 的边距**不会切到任何图形**。
   Windows 的 `.ico` 保持满幅方形（Windows 习惯如此）。

> 想看效果：`packaging/icons/icon-1024.png`。
> 我这边已经用 Pillow 打开核对过：四角透明、中间不透明、水印框里没有亮像素。

---

## 二点六、一个 GitHub Actions 的坑（已踩并修好）

第一版工作流是这么写的：

```yaml
on:
  push:
    tags: ["v*"]          # ← 和下面的 paths 是「与」关系！
    paths: ["packaging/**"]
```

GitHub 的过滤条件是**与**：于是变成"既要是 `v*` 标签、又要改动这些文件"，
**普通分支推送永远不会触发**。实测现象就是：`tests` 一直在跑，
`build-macos` 一次都没触发。

已改成：

```yaml
on:
  workflow_dispatch:            # 手动触发（平时拿包用这个）
  push:
    branches: ["main"]
    paths: ["packaging/**", "scripts/build_macos.sh", ".github/workflows/build-macos.yml"]
  release:
    types: [published]          # 发布 Release 时自动挂包
```

并且把这条坑写进了 `tests/test_portability.py` 的回归检查
（用真实 YAML 解析器判断 `push` 下有没有同时写 `tags` 和 `paths`）。

---

## 三、三种用法

### 1) 在 macOS 上从源码跑（改代码时用）

```bash
bash scripts/run_macos.sh            # 图形界面
bash scripts/run_macos.sh cli books  # 命令行模式
```

前提：装 **python.org 官方版 Python**（自带 tkinter）或 `brew install python-tk`。

### 2) 在 macOS 上本地打包

```bash
bash scripts/build_macos.sh
# 产物：dist/XYXBot.app 和 dist/XYXBot-macos-<arch>.zip
```

### 3) 用 GitHub Actions 打包（推荐，不占你本机）

到 https://github.com/zxl1835444162/xyx-bot/actions ：
选 **build-macos** → **Run workflow** → 等几分钟 →
在该次运行的页面底部 **Artifacts** 下载
`XYXBot-macos-arm64.zip`（Apple Silicon）或 `XYXBot-macos-x86_64.zip`（Intel）。

### 未签名的 .app，第一次打开会被 Gatekeeper 拦

这是 macOS 的正常行为（没买 Apple 开发者账号签名的应用都这样）：

```
① Finder 里【右键 → 打开】→ 弹窗里再点【打开】（只需一次）
② 或者：xattr -cr /path/to/XYXBot.app
```

彻底免掉需要 Apple 开发者账号（$99/年）做**签名 + 公证**。
工作流里留了 `codesign_identity` 的位置，要接的时候告诉我。

---

## 四、平台适配清单（改了什么）

| 位置 | 改动 | 为什么 |
|---|---|---|
| `src/config.py` | **新增 `DATA_ROOT`**：打包后数据落到 `~/Library/Application Support/XYXBot/artifacts/` | ★★ **最关键的一条**。`.app` 是**只读**的（签名/公证后更严格），往里写登录态、配置、细纲会失败。不改这个，打出来的包"能打开但记不住任何东西" |
| `ui/theme.py` | 字体按平台挑：macOS `PingFang SC`、Windows `Microsoft YaHei UI`、Linux `Noto Sans CJK SC`；用 `tkfont.families()` 挑真的装了的；支持 `XYX_UI_FONT` 覆盖 | 原来写死"微软雅黑"，macOS 上这个字体**不存在**，Tk 会静默回退 → 中文可能极细或出现方块 |
| `src/browser.py` | UA 跟着平台走（Mac→Macintosh、Win→Windows、Linux→X11）；`XYX_USER_AGENT` 可覆盖 | 在 mac 上跑真 Chrome 却自称 Windows，**UA 和内核不一致本身就是指纹信号** |
| `src/browser.py` | 浏览器缺失时把 `Executable doesn't exist` 翻译成人话 + 给出可照抄的命令 | 打包分发后最常见的报错，原文很难懂 |
| `launcher.py` | 按平台找解释器（POSIX 是 `bin/python3`），新增 Homebrew/系统 python3 候选，**优先用当前解释器** | 原来只认 `Scripts\python.exe`，macOS 上永远找不到 |
| `main.py` | 新增 `selftest` 命令；`diag` 在打包版给出替代方案 | 打包后 `diag_login.py` 不在包里，原来会抛 FileNotFoundError |
| `run_gui.py` | 支持 `--selftest`（不建窗口） | CI 才能在无图形会话的 runner 上验证打包产物 |
| `src/selftest.py` | **新文件**：环境自检 | CI 冒烟 + 用户排障（macOS 双击没反应时能看到到底缺什么） |
| `tests/test_gui_pages.py`、`smoke_gui.py` | 没有窗口服务器时**优雅 SKIP**（退出码 0） | CI runner 没有图形会话，否则一片红但没意义 |
| `.gitignore` | 忽略 `build/`、`dist/`、`.venv-mac/` | 打包产物不提交 |

> `src/browser_detector.py` **原来就是双平台的**（macOS 分支、`/Applications` 探测、
> 非 Windows 不读注册表），这次只加了回归测试，没改逻辑。

---

## 五、GitHub Actions 里两个工作流

### `.github/workflows/tests.yml`

三平台（ubuntu / windows / **macos-15**）跑测试。GUI 测试在没有窗口服务器的
runner 上会自动 SKIP；跨平台逻辑由 `tests/test_portability.py` 保证。

### `.github/workflows/build-macos.yml`

矩阵构建两个架构：

| runner | 架构 | 说明 |
|---|---|---|
| `macos-15` | **arm64** | Apple Silicon（M 系列），现在的主流 |
| `macos-15-intel` | **x86_64** | Intel Mac，GitHub 承诺支持到 **2027-08** |

> **为什么不用 `macos-13` / `macos-14`**：`macos-13` 已于 2025-12 退役；
> `macos-14` 正在退役（2026-10 公告，官方建议迁到 `macos-15`）。
> 工作流里的标签是按**当前有效**的来选的，并且加了自动化检查
> （`test_portability.py` 会断言没有用到已退役标签）。
> 参考：[macOS 13 关闭通知](https://github.blog/changelog/2025-09-19-github-actions-macos-13-runner-image-is-closing-down/)、
> [macOS 14 退役通知](https://github.blog/changelog/2026-10-01-github-actions-macos-14-runner-image-retirement/)、
> [macos-15-intel 说明](https://github.com/actions/runner-images/issues/13045)、
> [macOS 26 GA](https://github.blog/changelog/2026-02-26-macos-26-is-now-generally-available-for-github-hosted-runners/)

每个架构的步骤：装依赖 → 跑纯逻辑测试 → PyInstaller 打包 → **校验产物**
（可执行位 / 架构 / **Playwright driver 在不在包里** / 我们的 `src`、`ui` 在不在）
→ **`--selftest` 冒烟** → `ditto` 压缩 → 上传 Artifact（打标签时挂 Release）。

---

## 六、打包的两个设计决定

### 1. 浏览器内核**不**打包

Playwright 自带的 Chromium 有 150MB+，而且它下载在
`~/Library/Caches/ms-playwright`，塞进 `.app` 不合适。所以：

* 优先用系统已装的 **Chrome / Edge**（`browser_detector` 会在 `/Applications` 和
  `~/Applications` 下找）—— 顺带说，**真实浏览器指纹对风控更友好**；
* 都没有时，程序会明确提示装一个，或执行
  `python -m playwright install chromium`。

但 Playwright 的 **driver**（那个 node 可执行文件）必须打进包里，否则连启动
浏览器都做不到 —— spec 里用 `collect_all("playwright")` 处理，
CI 也会**断言 driver 确实在包里**。

预期 `.app` 体积：**约 120~200MB**（大头是 Python + Tk + Playwright driver）。

### 2. 数据目录搬出 `.app`

```
~/Library/Application Support/XYXBot/artifacts/
├── storage/    登录态 state.json、工作区配置 workspace.json、细纲 last_project.json
├── logs/       运行日志
└── screenshots/ 出问题的截图
```

想清空重来就删这个目录；想指定别处就设 `XYX_DATA_DIR=/some/path`。

> ⚠️ **Windows 上已有的登录态/配置不能直接搬到 macOS 用**：
> 路径不同，而且换了平台重新登录一次更稳妥（`state.json` 里的 cookie
> 往往和 UA/指纹绑定）。到 macOS 上第一次打开时点一下「准备 → 登录星月账号」即可。

---

## 七、已知限制 / 还没做的

| 项 | 说明 |
|---|---|
| 应用图标 | 没有 `.icns`，所以 Dock 里是 Python 默认图标。给我一个 1024×1024 的 PNG，我就能生成 `.icns` 并接进 spec |
| 签名 / 公证 | 未做。需要 Apple 开发者账号；工作流里留了 `codesign_identity` 的位置 |
| Intel 支持期限 | `macos-15-intel` 到 2027-08。之后只能出 arm64 包，或你自己买 Intel 机器打 |
| macOS 原生菜单栏 | Tk 应用在 macOS 顶栏会有个默认菜单（About/Quit），没做中文化 |
| GUI 测试在 CI 上 | 有窗口服务器就跑，没有就 SKIP（不视为失败）。真正的 GUI 视觉验证还是要在真机上看 |
| 自动更新 | 没做。现在是"下载 zip → 替换 .app" |

---

## 八、怎么自己验证一下

```bash
# 在 macOS 上（源码方式）
python main.py selftest                   # 环境自检：tkinter / 数据目录 / driver / 浏览器
python tests/test_portability.py          # 87 项跨平台回归
python tests/test_gui_pages.py            # GUI 回归（有窗口会话时）

# 打包后
./dist/XYXBot.app/Contents/MacOS/XYXBot --selftest
```

在 Windows 上（本次已跑过，全绿）：

```
python tests/test_portability.py   87 项
python tests/test_gui_pages.py    192 项
python main.py selftest           退出码 0
```
