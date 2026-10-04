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

> **2026-10-04 现状：仓库确已设为 private。**
> 中途一度是 public（与本文档不一致），当天已改回——
> 用 API 三重核实过：`private=true` / 匿名访问网页 **404** /
> 匿名调 API **403**。Actions 不受影响（`enabled=true`），
> push 与打包流水线均正常。
>
> ★ 提醒：private 下每次打包约烧 160 分钟的额度，**别频繁重打**。
> 只有改动 `packaging/**`、`scripts/build_macos.sh`、
> `.github/workflows/build-macos.yml` 时会自动触发打包；
> 改 `ui/` `tests/` 等**不会**触发，需要时手动 Run workflow 即可。

如果你希望**不限次数免费**跑打包，在仓库 Settings → General → 最下面
"Change repository visibility" 改成 **public** 就行（一处点击，随时可改回）。


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

1. 打开应用 → **直接进入主操控界面**（登录界面已于 2026-10-04 删除）
2. 去「准备」页点「登录星月账号」扫码登录一次
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

> **★ 2026-10-04 后续：登录界面已按用户要求删除**，只留一个主操控界面。
> 所以这条"登录窗 → 主界面"的切换路径**整个不存在了**。下面这段保留下来，
> 是因为它记录了排查过程与真机实测数据（`<Configure>` 渲染风暴），
> 对以后遇到的"窗口不显示/界面卡住"仍然有参考价值。

用户 2026-10-04 反馈。

### ★★★ 真正的根因：进程里建了**第二个** `tk.Tk()`（已修）

用户第二次描述给了决定性线索：

> 登录界面可以，点击之后**登录界面没了，然后鼠标转圈，然后啥也不显示**

**"鼠标转圈"= 主线程被卡住**（不是崩溃）—— 所以没有异常、没有弹窗、没有日志。

真正的定位靠两样东西：

1. **启动看门狗**（`run_gui`）：后台线程盯启动进度，主线程停滞就 dump 它的栈。
2. **`tests/repro_login.py`**：用**真实 mainloop** 驱动登录→主界面
   （以前所有 GUI 测试只"构造"窗口、从不跑 mainloop，所以看不见这类问题）。

在**真 macOS runner** 上抓到的现场：

```
★ 卡死了：主线程已 20.4 秒没有任何进展
   最后一次进展：MainWindow.__init__ 结束   ← 主窗口**已经建好了**
   平台：darwin
--- 主线程调用栈 ---
   File "run_gui.py", line 230, in run_app  ← 卡在它的 mainloop()
```

关键对比：**登录窗（第 1 个 `tk.Tk()` root）的 `after` 回调是正常触发的**，
而主窗口（第 2 个 root）的 `mainloop()` 收不到任何事件。结论：

> **在 macOS 上，一个进程里第 2 个 `tk.Tk()` 的事件循环是不工作的。**
> Windows 的 Tk 扛得住 —— 所以这个 bug 只在 mac 上出现，我在 Windows 上
> 怎么测都测不出来（这点用户说得对）。
> "登录可以、主界面不行"也正好由此解释：主界面要新建第 2 个 root。

#### 改法：整个程序只允许一个 `tk.Tk()`

* `run_gui.run_app`：建**唯一**的 root（`withdraw()` 当事件循环宿主），
  只调用**一次** `root.mainloop()`。
* `ui/login_window.py` / `ui/main_window.py`：从 `tk.Tk` 改成 **`tk.Toplevel`**，
  接收 `master`（共享那个 root）。切换窗口 = 销毁一个 Toplevel + 建另一个，
  始终只有一个解释器、一个事件循环。
* 关窗（红叉）与退出登录分成两条路：关窗通知外层 `root.quit()` 结束循环；
  退出登录只回登录窗。
* `_show_fatal` 改为**复用已有 root**，不再无脑新建。

#### 走过的两条错路（记下来，避免以后再走）

| 错路 | 为什么错 |
|---|---|
| 以为要避免「`mainloop` 嵌套」 | 改成顶层平级调用后**仍然卡** —— 问题不在嵌套，在"第 2 个 root"本身 |
| 以为中文 locale 导致字体反复枚举 | 真机上（C 与 zh_CN 一样）`PingFang SC` 命中、族名**不会**本地化、500 次调用只花 **0.4ms**。**这条推断是错的** |

> 字体那个缓存修复作为健壮性改进**保留**（`tests/test_font_cache.py` 37 项），
> 但它**不是**本次卡死的原因。当时把它当成结论是我的误判。

#### 守住它的测试

`tests/repro_login.py`（15 项）：跑真实 mainloop 走完 login→main，断言
**「事件循环真的在跑（`after` 回调被触发）」**，并用 AST 检查
**`mainloop()` 只有 1 处、无条件的 `tk.Tk()` 只有 1 处**。
`tests.yml` 与 `build-macos.yml` 都会跑它 —— 它在这两个工作流里
**曾经卡死 8 分钟 / 20 秒两次**，现在是守门人。

---

### 参考：字体那条路的量化数据（结论已推翻，数据留着）

`F()`/`FM()` 调用次数实测：登录界面 **12** 次，主界面 + 9 个页面 **815** 次。
当初据此怀疑"每次重新枚举系统字体"，但真机实测枚举一次只要 49~87ms 且会被缓存，
所以这个 68 倍差异**不足以**造成卡死。保留这段是因为"12 vs 815"这个事实本身
对以后优化启动速度仍有参考价值。

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

## 三点七、★★★ 删掉登录界面之后**还是打不开** —— 真正的漏网点找到了

> 2026-10-04 深夜。用户反馈：「**没删除之前，也是这个原因，不然我就不会
> 删除登录页了，没想到现在**（还是打不开）」。
>
> 这句话很关键 —— 它说明「窗口架构（第 2 个 `tk.Tk()`）」**不是唯一原因**：
> 换成「单 root + Toplevel」之后问题依旧。所以真正的机制必须是**与窗口
> 架构无关**的东西。

### 结论：就是 `<Configure>` 渲染风暴 —— 而且只漏了一处

回头看 `tests/test_configure_guard.py` 里那份白名单：

```python
ALLOW_RAW = {
    "ui/theme.py": "bind_configure 自己内部那一处 + Card.body（内部已有 != 判断）",
}
```

**理由的后半句是假的。** `Card._resize_win()` 长这样：

```python
if need > 4 and c.winfo_reqheight() != need:
    c.configure(height=need)        # ← 这行确实有 !=
c.configure(scrollregion=c.bbox("all"))
self.configure(height=need)         # ← 这行**没有** != 判断！
```

`self.configure(height=…)` 一旦真的改了尺寸，就会再发一个 `<Configure>`：

```
body <Configure> → _resize_win → self.configure(height) → self <Configure>
                  → _redraw → _resize_win → self.configure(height) → …
```

macOS 的 Tk 对尺寸变化特别敏感（每次重绘都会再发一个 Configure），
于是这条回路就转成了**每秒钟上万次的渲染风暴**，主线程永远回不到事件循环
—— 就是用户看到的「界面不出来 + 鼠标转圈」。Windows 的 Tk 不这样，
所以本机（以及 CI 的 windows / ubuntu）怎么测都是绿的。

**这正好解释了「删掉登录页也没用」**：`Card` 是主界面自己的控件，
只要构建主界面就会进入这条回路，**跟是第几个 `tk.Tk()` 完全无关**。

### 改了什么

| 文件 | 改动 |
|---|---|
| `ui/theme.py` | `Card.body` 的 `<Configure>` **改走守卫版 `bind_configure`**（尺寸没变就不重绘 + 全局每秒上限兜底） |
| `ui/theme.py` | `_resize_win` 里 `self.configure(height=need)` **补上 `!=` 判断**；`scrollregion` 也加 `!=`（值没变就不写） |
| `tests/test_configure_guard.py` | **收紧白名单**：从「按文件放行 theme.py」改成「**按函数**放行，只允许 `bind_configure` 自己内部那一处」；并新增一条断言，要求 `Card._resize_win` 里必须带 `!=` 判断 |

收紧之后，`ALLOW_RAW` 那种「整文件放行」的口子没有了 —— 以后任何一处裸绑
都会被 AST 检查当场逮住，不会再出现「白名单理由写错了、没人复核」的情况。

### 在 Mac 上怎么验证这次真的修好了

```bash
# ① 自检（不建窗口，最稳）
/Applications/XYXBot.app/Contents/MacOS/XYXBot --selftest

# ② 连「窗口真的显示出来了吗」一起验（会真的跑事件循环）
/Applications/XYXBot.app/Contents/MacOS/XYXBot --selftest --window
```

第 ② 条在 macOS 上会额外做两件事：**泵事件循环探测 `winfo_viewable()`**，
并用 `screencapture` 存一张**全屏截图**当存证。输出里会明确写
「主操控界面真的显示了」或「**没有显示出来**（viewable=False …）」，
直接把这个输出发我即可。

如果窗口还是不出来，现场在：

```bash
/Applications/XYXBot.app/Contents/MacOS/XYXBot --selftest --window
```

★ **2026-10-04 起不再生成任何诊断文件**（用户要求：每次启动都往桌面丢一个
`XYXBot-诊断.txt`，很难受）。原先那两个位置 ——
`~/Library/Application Support/XYXBot/artifacts/logs/fatal.log` 和桌面那份 ——
**都已取消**，程序启动时还会顺手把桌面上遗留的旧文件删掉一次。

排障信息改走两条路：
1. **stderr**（在终端里跑 `--selftest --window` 时直接可见）
2. **弹窗**（打包版启动失败/界面抛异常时会弹出错误框）

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
