# 效率调试报告：真机实测 + 修复一个「每章白等 300 秒」的严重 bug

> 用户 2026-10-04：
> 「你可以进行一下调试，来实际看一下这些功能的延迟之类的，因为现在你修改的
>   我还是不太满意」
>
> 上一轮我交的是一份**基于源码的静态估算**（"单章省 40 秒"），并且明确写了
> 「这是估算，不是实测」。这一轮我不再估算 —— 我写了 6 个真机诊断脚本，
> 打开浏览器，把每一段等待都量了一遍。
>
> **结果：我上一轮的改动里有一个严重 bug，它让每一章多等 300 秒。**
> 这就是你"不太满意"的真正原因。

---

## 一、先说结论（真机实测数字）

测法：`diag_latency.py` 在真实站点上完整走一遍「一章」的 UI 操作
（开续写弹窗 → 选模型 → 填剧情 → 关联章节 → 关弹窗 → 开审稿抽屉 →
选审稿要求 → 填待审文本 → 全选正文 → 关审稿抽屉），**全程不点"生成"**，
所以不消耗任何 AI 额度、不改动任何正文。

| 步骤 | 修复前 | 修复后（首次） | 修复后（后续章） |
|---|---:|---:|---:|
| ① 开续写弹窗 | 0.41s | 0.40s | 0.85s |
| ② 选模型（细腻版） | 2.72s | 2.81s | **0.01s**（已选→跳过） |
| ③ 填后续剧情 | 0.11s | 0.12s | 0.11s |
| ④ 关联最近10章 | 0.51s | 0.50s | **0.02s**（已选→跳过） |
| ⑤ 截图 ai_ready | 0.07s | 0.06s | 0.08s |
| ⑥ 关续写弹窗 | 0.01s | 0.01s | 0.01s |
| ⑦ 开审稿抽屉 | **5.80s** | **0.91s** | **0.90s** |
| ⑧ 选审稿要求 | **29.39s** | **1.72s** | **0.02s** |
| ⑨ 填待审文本 | 1.76s | 0.63s | 0.67s |
| ⑩ 全选正文 | **4.21s** | **0.73s** | **0.72s** |
| ⑪ 关审稿抽屉 | **3.41s** | **0.77s** | **0.73s** |
| **单章 UI 开销合计** | **45.5 ~ 48.6s** | **8.70s** | **4.05 ~ 4.12s** |

汇总指标：

| 指标 | 修复前 | 修复后 |
|---|---:|---:|
| **单章 UI 开销（稳态）** | **45.5s** | **4.1s** → **11 倍** |
| 固定 sleep 白等 | 61.80s / 584 次 | **4.30s / 9 次** |
| 条件等待总耗时 | 42.94s / 503 轮询 | **2.38s / 76 轮询** |
| 被测函数总耗时 | 283.28s | **37.76s** |
| `current_associate_level` | 45.03s / 3 次 | **0.01s / 3 次** |
| `open_review_pane` | 8.5s / 次 | **0.90s / 次** |
| `_click_first` | 2.26s / 次 | **0.58s / 次** |
| `relate_chapters` | 3.5s / 7.9s / … | 0.5s 首次，**0.02s 后续** |

> **注意**：这些是**自动化 UI 开销**，不含 AI 生成本身。
> 你日志里那次「生成 9 秒 + 审稿 29 秒」是站点真实耗时，改不动也不该改。

---

## 二、★ 最严重的发现：我上一轮把"等生成完成"改坏了

### 症状

你自己那两次真机运行的日志，是最好的证据：

```
artifacts/logs/run-20261004-100453.log   ← 我改之前跑的，一切正常
    [ai] --- 等待生成完成（最多 300s）---
    [ai] ✓ 生成完成（约 9s，字数 220）        ← 9 秒就检测到了

artifacts/logs/run-20261004-102205.log   ← 我改之后跑的
    [ai] --- 等待生成完成（最多 300s）---
    [ai]   已等 20s …（等待结果页）           ← 卡住了，日志到此为止
```

`src/waiting.py` 的写入时间是 **10:19:10**；你的两次运行分别是 10:04 和 10:22。
10:22 那次跑完第 7 章就卡在"等生成完成"上不动了。

### 根因：谓词签名写错，异常被静默吞掉

我上一轮把 `wait_generation` 写成了：

```python
def gen_finished(page) -> bool: ...          # ← 需要 page 参数
...
res = wait_until(gen_finished, timeout=300, ...)   # ✗ 漏了 lambda
```

而 `wait_until` 的实现是：

```python
try:
    val = cond()
except Exception:
    val = None        # ← 当成"条件还没满足"，继续等
```

于是 `cond()` **每一轮都抛 `TypeError: missing 1 required positional
argument`**，被吞成"未满足" → **等待必然超时**。而且日志里一个字都不说。

后果：每一章都要**干等满 300 秒**才判"生成失败"，然后 `ai_auto_chapter`
中止本章。生成其实 9 秒就好了。

**实测证实**（不经浏览器）：

```
wait_until(gen_finished)      → ok=False  elapsed=0.40s polls=5   （0.4s 是测试超时）
wait_until(review_pane_open)  → ok=False  elapsed=0.40s polls=5
```

同一个错误也出现在 `open_review_pane`（`wait_until(review_pane_open, ...)`），
导致每章白等 8.5 秒。

> 为什么上一轮没发现：我上一轮的验证是**静态的**——数源码里 sleep 的字面量。
> 这个 bug 不增加任何 sleep，反而"用上了条件等待"，静态检查完全看不出来。
> 这正是我这次改用真机实测的原因。

### 修复

1. `src/ai.py`：两处都包上 lambda
   ```python
   res = wait_until(lambda: gen_finished(page), ...)
   if wait_until(lambda: review_pane_open(page), ...).ok:
   ```
2. **`src/waiting.py` 加固** —— 让这类错误**不可能再静默**：
   - 谓词第一次抛异常就打印 `[waiting] ✗ 谓词调用失败：…`；
   - 若是 `TypeError`，额外提示"这像是**签名写错**"，并给出正确写法；
   - 超时的 `detail` 里带上最后一次的异常类型和内容。
   - 判据：**DOM 没渲染好只会让谓词返回 False，不会抛 TypeError。**
     所以 TypeError 基本可断定是写错了。
3. 新增 **`audit_wait_args.py`**：全项目审计每一个
   `wait_until/wait_gone` 调用点，做**作用域解析**，找出"裸名字谓词但需要参数"
   的情况（当前 39 个文件，0 问题）。
4. 新增**行为级回归测试**（用假 page 把真实的等待函数跑起来）：
   断言 `wait_generation` 在条件满足后 **< 1 秒**返回。做了**变异测试**验证
   它真的能抓到：把 bug 塞回去 → 4 项失败（含 `6.00s « 6s 超时`）；修好 → 99 项全过。

---

## 三、这一轮真机调试还抓到的其他问题

### 1. 「15 秒黑洞」：一个裸 `inner_text()` = 白等 15 秒

`browser.py` 里设了 `context.set_default_timeout(15000)`。所以
`loc.first.inner_text()`（不传 timeout）在**元素不存在**时不会马上失败，
而是一直等到 15 秒：

```
locator('.__nope__').first.inner_text()            → 15009ms
locator('.__nope__').first.inner_text(timeout=150) →   157ms
locator('.__nope__').first.is_visible()            →     2ms
```

`current_associate_level` 就是这么写的，而 `[class*=association-level]`
**只在滑块浮层打开时才存在**，它在 `select_model` 里是**打开浮层之前**调用的：

```
AI.current_associate_level(page)   15006.9ms    ← 每章白等 15 秒
```

修复：新增 `_text_of(loc, timeout=300)`（先 `count()` 再带超时读），
并把 `src/` 下**所有**裸 `inner_text()` 都加上显式超时（现在 0 处）。
成效：`current_associate_level` **45.03s → 0.01s**。

### 2. 「残留遮罩」：所有长超时点击都必然白等满

`diag_click.py` 拆解 `_click_first`：

```
loc.click(timeout=4000)        → 4096ms 抛异常（每次都失败）
loc.evaluate('e=>e.click()')   →    6ms 成功
_click_first 整段              → 4222ms（3 轮完全一致）
```

原因：站点**关掉弹窗后仍留着一个全屏遮罩** `.n-modal-mask`
（实测 1440×900、`visibility:visible`、`opacity:1`、`pointer-events:auto`）。
Playwright 的命中测试认为目标"没接收指针事件"，于是重试到超时；
而 JS 点击不走命中测试，直接派发 click 事件，Vue 照样收到。

项目里散布着 `click(timeout=4000/5000)`（全选、审稿要求下拉、章节项、
模型卡片、关抽屉…），每章累计白等 20~30 秒。

修复：新增 `_safe_click(loc)`，**三档降级**：
短超时原生点击（600ms）→ JS 点击 → force 长超时兜底。
最坏情况仍等于旧行为，只会更快。成效：`_click_first` **2.26s → 0.58s**；
`select_all_body` 4.21s → 0.73s。

### 3. `relate_chapters` 从第 2 章起**静默失效**（内容质量事故，不只是慢）

真机 DOM 抓取（`artifacts/diag/relate-group-*.html`）显示按钮组真实结构是：

```
[清空] [最近3章] [最近N章 ⌄] [选择章节]
                 ↑ 当前档位就写在按钮文字上（默认「最近5章」，选了10就变「最近10章」）
```

而旧代码用 `.n-modal button` 过滤 `has_text="最近5章"` 去定位按钮组 ——
**那个文字只在当前档位正好是 5 章时才存在**：

- 会话里第一次跑（默认 5 章）→ 侥幸命中，看起来正常
- **之后每一章**（按钮已变成「最近10章」）→ 找不到 → 白等 2s+4s → 返回 False

而调用方**忽略返回值**，于是第 2 章起**静默丢失「关联章节」**：模型看不到前文，
内容连贯性下降，日志里只有一行 `✗ 找不到章节数按钮组`。

你 10:04 那次的日志正是这个现象：

```
第5章： [ai] 展开章节数菜单 …                       ← 命中
        [ai] ✓ 已选「最近10章」
第6章： [ai] ✗ 找不到章节数按钮组（关联章节区没展开？）  ← 静默失败，流程照跑
```

另外旧代码结尾用 `wait_gone(text=最近10章)` 等菜单收起 —— 选完之后
**按钮自己的文字就是「最近10章」**，所以这个等待**每次必定超时 3 秒**。

修复：

- `_relate_dropdown()`：按 class（`overflow-hidden`）区分下拉按钮和「最近3章」，
  不再依赖会变的文字；
- `current_relate_count()`：回读当前档位；
- **幂等**：已经是目标档位就直接成功，**0 点击 0 等待**；
- 成败判据改成**回读按钮文字**（不再用必然超时的"等菜单收起"）；
- `ai_continue` 里**检查返回值并醒目告警**（不再静默）。

成效：`relate_chapters` 首次 0.50s，**后续章 0.02s**，且**永远不会再静默失效**。

### 4. `wait_shortcut_loaded` 的 20 秒死等

它只判断"行数稳定"，**不判断面板是否存在**。面板没打开时就一直数到
`timeout=20s`。实测 `pick_review_requirement` 因面板没打开，
3 次调用白等 **57.9 秒**（579 次 0.1s 轮询）。

修复：先判断面板在不在，短暂等待后仍不在就立刻返回 0 并告警。

### 5. 每章固定 sleep（7.5s）

| 函数 | 原固定 sleep | 改法 |
|---|---:|---|
| `accept_result` | **3.0s** | 等"采纳生效"（弹窗关闭或正文变化），命中即走 |
| `start_generate` | **2.0s** | 等"生成真的启动"（出现停止生成/结果页） |
| `ai_auto_chapter` 的 `settle` | **2.0s** | 有上限的非阻塞等待（正文一变就继续） |
| `open_review_pane` | 0.6s + 8×0.5s | 一次条件等待 |
| `start_review` | 0.5s | 等"审稿生成中"状态 |
| `open_chapter` | 0.7s/轮 | 轮询 **且**判据更严（等正文**真的换了章**，避免读到上一章） |
| `fill_plot` | 0.8s | 回读 textarea 确认内容已落 |
| `open_shortcut_panel` | 0.4s | 删掉（后面有面板条件等待兜住） |
| `close_shortcut_panel` | 0.6s | 等面板真的消失 |
| `wait_shortcut_loaded` | 1.0s | 短间隔连续两次计数稳定 |
| `_fill_first` | — | 原来的 `click()` 必然被遮罩拦住白等；改成直接 `fill`（Playwright 的 fill 自己会聚焦） |

### 6. 顺手修掉一个"日志一落盘就崩"的坑

`⚠`(U+26A0) 不在 GBK 里。输出被重定向到文件/管道时 Python 用系统代码页，
于是 `print("⚠ …")` 直接崩：

```
$ python tests/test_fixes.py > out.txt
UnicodeEncodeError: 'gbk' codec can't encode character '\u26a0'
→ 退出码 1（测试没跑完就死了）
```

新增 `src/console.py: enable_utf8()`（UTF-8 + `errors="replace"`），
在 `main.py` / `run_gui.py` / 3 个测试 / 所有诊断脚本里都调用。
另外 3 个测试脚本原来在 `os._exit()` 前不 flush，重定向时**测试结果整个丢失**
（这是我这次实际踩到的），已修。

---

## 四、验证

```bat
:: 语法
.venv312\Scripts\python.exe -m compileall -q src ui main.py tests audit_wait_args.py

:: 3 个测试套件（共 238 项）
.venv312\Scripts\python.exe tests\test_fixes.py       :: 55
.venv312\Scripts\python.exe tests\test_gui_pages.py   :: 84
.venv312\Scripts\python.exe tests\test_waiting.py     :: 99   ← 本轮 46 → 99

:: 谓词签名审计（全项目 39 个文件）
.venv312\Scripts\python.exe audit_wait_args.py

:: CLI
.venv312\Scripts\python.exe main.py tasks

:: 真机诊断（会打开浏览器，不消耗 AI 额度）
.venv312\Scripts\python.exe diag_latency.py
```

**本轮全部通过**：compileall exit 0、**238/238**、审计 0 问题、CLI 正常。

新增的 99 项里，**D 节是行为级回归**（用假 page 把真实等待函数跑起来），
这是本轮最有价值的测试 —— 它直接断言"条件满足时必须立刻返回，
而不是等满超时"，也就是**上一轮那个 bug 的正面克星**。
C7 节则是全项目的谓词签名审计。

---

## 五、诚实的边界

1. **我确实打开了浏览器做了真机实测**，但**只做 UI 操作**：开/关弹窗、
   展开下拉、读 DOM、截图。**从未点击"开始 AI 续写"或"生成"**，
   因此没有消耗你的 AI 额度，也没有改动任何章节正文。
2. **`wait_generation` 的修复没有走真机端到端验证**（那需要真的生成一章，
   会花额度）。它的验证来自：静态审计 + 假 page 行为测试 + 变异测试。
   你实跑一章即可确认（日志里应看到 `✓ 生成完成（约 Ns，字数 M）`，
   而不是 `✗ 等了 300s 还没生成完`）。
3. **单章 4.1s 是"UI 开销"，不是"整章耗时"。** 整章还要加上站点的
   生成时间（你日志里约 9~63s）和审稿时间（约 29s）。这些是站点的
   AI 推理时间，不是自动化能省掉的部分。
4. 剩下 4.30s 的固定 sleep 主要是**每次运行的启动成本**
   （`login.open_site_page` 2.5s、`close_activity_modal` 1.2s），
   不是每章都发生的。

---

## 六、还没做 / 建议你决定的

| 项 | 说明 |
|---|---|
| `pick_shortcut` 找不到提示词时**静默沿用当前值** | 可能跑完一整章才发现用错提示词。建议改成明确告警 —— 要不要改由你定 |
| `platforms/adapters.py` / `tasks/adapters.py` 的一次性 8s | 只在你点"登录/准备"时发生一次，收益小 |
| `src/ai.py` 已 3990 行 | 是最后一个"上帝模块"（拆分方案见 `ARCHITECTURE_PLAN.md`） |
| `close_review_pane` 每次 0.73s | 里面最多试 3 轮 × 6 个选择器。可以按"最常命中的那个"提前短路 |
| **建议你先实跑 1 章确认** | 重点看日志里 `等待生成完成` 那一段是否秒回，以及 `关联最近10章` 是否打印「已是…跳过」 |

---

## 附：本轮新增的调试工具（都保留在仓库里）

| 文件 | 用途 |
|---|---|
| `diag_latency.py` | ★ 主诊断：完整走一遍单章 UI 流程 + 函数耗时/sleep/轮询/往返成本四张表 |
| `diag_probe.py` | 定点探针：SLOW_MO=80 vs 0 对比，量"裸 inner_text 15 秒"等 |
| `diag_click.py` | 拆解 `_click_first`：证明"原生点击必然被遮罩拦住、JS 点击 6ms 成功" |
| `diag_review.py` / `diag_review2.py` / `diag_review3.py` | 定位审稿抽屉那 8.5 秒到底花在哪（最终揪出谓词签名 bug） |
| `audit_wait_args.py` | 全项目审计 `wait_until/wait_gone` 谓词签名（防止再犯同一个错） |
| `artifacts/diag/*.txt` | 上述脚本的原始输出，可复查 |
| `artifacts/diag/relate-group-*.html` | 关联章节按钮组的真实 DOM（写选择器的依据） |
