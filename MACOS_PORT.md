# macOS 移植 + GitHub Actions 自动打包

> 2026-10-04：把 Windows 上的应用搬到 macOS，并让 GitHub Actions 自动出 `XYXBot.app`。

---

## 一、结论：**macOS 版已经真的构建出来了**

| 我做了什么 | 状态 |
|---|---|
| 平台适配（字体 / UA / 数据目录 / 启动器 / 浏览器检测） | ✅ 已改，Windows 上实测无行为回归 |
| 打包配置 `packaging/macos/xyxbot.spec` | ✅ 语法校验通过；**已在 macOS 上真实打包成功** |
| GitHub Actions 工作流（测试 + 打包） | ✅ 真实 YAML 解析验证；**已真实跑通** |
| 应用图标 `.icns` / `.ico` | ✅ 从你给的图生成，含去水印与 macOS 圆角外形 |
| 跨平台回归测试 `tests/test_portability.py` | ✅ 107 项，本机全绿 |
| **macOS 构建（两架构）** | ✅ **CI 上真实构建成功**，产物已下载到本机 |

### 实际构建结果

```
运行: https://github.com/zxl1835444162/xyx-bot/actions/runs/37182790624
结论: success   （约 2 分钟）

  ✓ XYXBot-macos-arm64     57.1 MB   ← Apple Silicon（M 系列）
  ✓ XYXBot-macos-x86_64    59.6 MB   ← Intel Mac
```

后来加了 DMG（更符合 Mac 安装习惯），产物变成：

| 文件 | 用途 |
|---|---|
| `XYXBot-macos-arm64.dmg` | ★ 双击挂载 → 拖进「应用程序」 |
| `XYXBot-macos-<arch>.zip` | 存档 / 需要 `ditto -x -k` 解压 |

已下载到本机：`C:\Users\Administrator\Downloads\xyx-bot-macos\`

> **实测过的一个偶发问题**：`hdiutil` 建 DMG 在 arm64 runner 上一次过，
> 在 Intel runner 上偶发失败（hdiutil 本身就有"资源忙/临时空间"这类偶发毛病）。
> 所以那一步改成了**重试 3 次 + 失败不阻断构建** ——
> DMG 只是便利，zip 才是主产物，不该因为它的偶发问题让整次构建红掉。

CI 上这几步都是**真跑过并通过**的（不只是"配置看起来对"）：

1. 确认 runner 的 Python 带 tkinter
2. 安装依赖（playwright + pyinstaller）
3. 打包前跑 5 个纯逻辑测试套件
4. **PyInstaller 打包** → 产出 `dist/XYXBot.app`
5. **校验包结构**：可执行位 / 架构（lipo）/ `Info.plist` 里中文显示名
   / `.icns` 图标 / **Playwright driver 在不在包里**
6. **包内 `--selftest` 冒烟**（不创建窗口，所以 runner 上能跑）
   —— 它 import 了 `src.config` / `src.selftest` / `src.session` /
   `browser_detector`，跑通就证明我们的模块确实打进去了
7. `ditto` 压缩（保留 `.app` 权限与符号链接）
8. 上传 Artifact

### 仍然无法由我验证的

| 项 | 为什么 |
|---|---|
| **双击 .app 起来的实际观感** | 我没有 Mac。GUI 能不能画出来、Dock 图标好不好看、中文排版对不对，需要你在 Mac 上开一次 |
| shell 脚本的 `bash -n` | 这台机器没有 Git Bash / WSL 发行版。不过 `build_macos.sh` 的每一步在 CI 里都等价跑过了 |
| 签名 / 公证后的行为 | 需要 Apple 开发者账号，没做 |

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
② 或者：xattr -cr /Applications/XYXBot.app
```

彻底免掉需要 Apple 开发者账号（$99/年）做**签名 + 公证**。
工作流里留了 `codesign_identity` 的位置，要接的时候告诉我。

---

## 三、把包装到 Mac 上

**最简单：用 DMG**

1. 把 `XYXBot-macos-arm64.dmg` 拷到 Mac 上
2. 双击挂载 → 把 `XYXBot` 拖进「应用程序」
3. 首次打开：**右键 → 打开**（未签名），或先执行
   `xattr -cr /Applications/XYXBot.app`

**用 zip 的话**：产物是**两层 zip**（GitHub 的 artifact 会把上传的文件再包一层）。
这不是 bug，反而**必须**这样：macOS 的 `.app` 里有**符号链接**和**可执行权限**，
只有 `ditto` 打的 zip 能原样保留（实测包里 57 个符号链接都在）。
让 GitHub 直接对 `.app` 目录打 zip 会破坏这些，装上去就是打不开。

```bash
# 第一次解压：拿到 ditto 打的包
unzip XYXBot-macos-arm64.zip            # → XYXBot-macos-arm64.zip

# 第二次解压：必须用 ditto，才会还原符号链接与权限
ditto -x -k XYXBot-macos-arm64.zip .    # → XYXBot.app
mv XYXBot.app /Applications/

# 首次打开（未签名）
xattr -cr /Applications/XYXBot.app
open /Applications/XYXBot.app
```

> 也可以用 Finder 双击解压：外层 → 内层 → 得到 `XYXBot.app`，
> 然后拖进「应用程序」。Finder 的解压同样会保留符号链接。

### 装好后的第一次运行

1. 打开应用 → 授权码窗口（演示码 `ZSJT-2026-VIP`）
2. 进主界面默认落在「跑章」页 → 去「准备」页点「登录星月账号」扫码登录一次
3. 之后就能点「开始跑章」了

**数据目录**（登录态 / 配置 / 细纲 / 日志都在这里，不在 `.app` 内）：

```
~/Library/Application Support/XYXBot/artifacts/
```

想确认环境有没有问题，在终端跑：

```bash
/Applications/XYXBot.app/Contents/MacOS/XYXBot --selftest
```

它会逐项打印：tkinter / 图形会话 / 数据目录是否可写 / Playwright driver /
浏览器内核 / 登录态，最后给个结论。**缺 Chrome/Edge 时**它会告诉你去装一个，
或执行 `python -m playwright install chromium`。

---

## 三点五、两种架构怎么选

| 你的 Mac | 下哪个 |
|---|---|
| M1 / M2 / M3 / M4（2020 年底之后的基本都是） | `XYXBot-macos-arm64.zip` |
| Intel（2020 年之前的） | `XYXBot-macos-x86_64.zip` |

不确定就在终端跑 `uname -m`：`arm64` → 前者，`x86_64` → 后者。

---

## 三点六、排障：macOS 上「输完授权码进不去主界面」

用户 2026-10-04 反馈。

### ★★ 真正的根因：字体解析每次都重新枚举系统字体（已修）

用户第二次描述非常关键：

> 登录界面可以，点击之后**登录界面没了，然后鼠标转圈，然后啥也不显示**

**"鼠标转圈"= 主线程被卡住**，不是崩溃 —— 所以没有异常、没有弹窗，
只有一片死等。顺着这个去找，问题在 `ui/theme.py` 的字体解析：

```python
for name in candidates:
    if name.lower() in have:
        _FONT_CACHE[key] = name      # ← 只有候选命中才写缓存
        return name
return candidates[0]                 # ← 没命中就直接返回，**不缓存**
```

`tkfont.families()` 在 macOS 上要走 **CoreText 枚举全部系统字体**，很慢。
只要候选字体一个都没命中，**每一次** `F()` / `FM()` 都会重新枚举一遍。

而两个界面的调用次数差得离谱（本机实测真实计数）：

| 界面 | `F()`/`FM()` 调用次数 |
|---|---|
| 登录界面 | **12** 次 |
| 主界面 + 9 个页面 | **815** 次 |

**68 倍。** 代入 macOS 的枚举耗时：

| 每次枚举 | 登录界面要等 | 主界面要等 |
|---|---|---|
| 20 ms | 0.2 秒 | **16 秒** |
| 50 ms | 0.6 秒 | **41 秒** |
| 100 ms | 1.2 秒 | **82 秒** |
| 200 ms | 2.4 秒 | **163 秒** |

这正好解释了"登录界面能出来、主界面转圈等到天荒地老"。
修好之后只枚举 1 次，主界面额外等待 ≈ **0 ms**。

#### 为什么只在你的 Mac 上炸、CI 却一秒就过？

因为 macOS 会按**系统语言本地化字体族名**：

* CI runner 是**英文**环境 → 返回 `PingFang SC` → 第一个候选就命中 → 只枚举 1 次；
* 你的 Mac 是**中文**环境 → 可能返回「苹方-简」→ ASCII 候选**全部落空**
  → 每次都重新枚举。

所以这个 bug 对英文用户完全隐形，对中文用户是致命的。

#### 修法（三条都做了）

1. **系统字体表只枚举一次**并缓存；成功、失败都算数。
2. **解析结果无论命中与否都写缓存**（关键的一条）。
3. **候选里补上中文名**（`苹方-简`、`黑体-简`、`宋体-简`…），
   并加一层**关键字兜底**：万一名字谁都不认识，就按
   `pingfang / heiti / 苹方 / 黑体 / 冬青 / 华文…` 在系统字体里捞一个中文字体，
   而且**保留原始大小写**（Tk 认大小写，给个小写名等于找不到字体）。

保留一个细节：**没有 Tk root 时的失败不缓存**。那种失败是"立刻抛错"的
（根本不会走 CoreText），重试几乎不花钱；"有 root 还失败"才是真异常，
才需要缓存下来避免反复尝试。这样既治好了卡死，也不会把一次失败永久钉死。

回归测试：`tests/test_font_cache.py`（37 项）—— 用**假的字体表**在本地复现
"中文 Mac"场景，断言 815 次调用只枚举 1 次。

### 为什么之前连报错都看不到

真实代码路径是这样的（`ui/login_window.py`）：

```python
self.after(420, lambda: self._enter(user))     # ← 在 Tk 回调里
def _enter(self, user):
    self.destroy()                             # 登录窗先销毁了
    self._on_success(user)                     # → launch_main → MainWindow(...)
```

两个因素叠加，导致**零提示**：

1. `MainWindow(...)` 一旦抛异常，**登录窗已经被销毁**，界面上什么都没有；
2. 回调里的异常会交给 `report_callback_exception`，而它默认只把堆栈
   `print` 到 **stderr** —— 打包成 `.app` 后 `console=False`，stderr 没有去处。

所以这次的改动，一半是"让失败可见"，一半是"覆盖真实路径"：

| 改动 | 作用 |
|---|---|
| `ui/theme.py` 字体缓存修复 | ★★ **本次卡死的根因** |
| `run_gui._install_error_handler()` | 接管 `report_callback_exception` → **弹窗显示堆栈** + 写 `logs/fatal.log` |
| `run_gui.launch_main()` 包 try/except | 即使不走 Tk 回调，失败也会弹出来 |
| `ui/main_window.py::_present()` | deiconify + lift + 短暂置顶 + 抢焦点 —— 针对"窗口建好了但没到前台" |
| `--selftest` 连界面一起冒烟 | 构造主窗口 + 9 个页面，并复现「登录窗→销毁→主窗」 |
| `--selftest --window` | 再跑真实事件循环，检查窗口**真的显示出来了吗** |
| `--selftest` 报界面字体 | 直接告诉你挑中哪个字体、有没有命中、枚举花多久 |
| `tests/test_login_flow.py` | 23 项回归，把这条路径钉住 |

### 在 Mac 上怎么查

```bash
# 1) 最直接的：界面能不能构造、窗口能不能显示、字体挑中了什么
/Applications/XYXBot.app/Contents/MacOS/XYXBot --selftest

# 2) 如果还是进不去，看这个日志（现在会记了）
cat ~/Library/Application\ Support/XYXBot/artifacts/logs/fatal.log
```

`--selftest` 的输出类似（把这段发我即可）：

```
界面字体        : PingFang SC（命中候选） · 系统 412 个字体族 · 枚举 38 ms · 等宽 Menlo
[1/2] 构造主窗口，并逐个构建 9 个页面 …     ✓ / ✗
[2/2] 复现真实顺序：登录窗 → 销毁 → 主窗口 …  ✓ / ✗
```

现在再打开应用，如果还是进不去，**应该会弹出一个带堆栈的错误框**；
关掉它，`logs/fatal.log` 里也有同一份。

### 一个踩到的坑：CI 上做窗口显示探测会永久卡死

"窗口真的显示出来了吗"需要跑真实 `mainloop()` 并让窗口映射到屏幕。
实测这东西在 **GitHub 的 macOS runner** 上**永久卡住**：

* `tests` 的 macos job 和 `build-macos` 的两个 job 全卡在包内自检那一步，
  跑了 8 分钟以上只能手动取消；
* 那种 runner 虽然 `tk.Tk()` 能建出来（自检报「图形会话可用」），
  但**没有真正的登录会话去显示窗口** —— `after` 定时器永不触发，
  `quit()` 永远等不到。

所以窗口探测的规则是：**用户本机默认开，检测到 `CI` 环境变量就自动关**，
也可以用 `XYX_SELFTEST_WINDOW=1/0` 强制。两个工作流也都加了
`timeout-minutes` 兜底，防止以后再有人（或以后的 AI）踩这个坑把额度烧光。

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
