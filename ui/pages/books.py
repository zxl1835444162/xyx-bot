"""「打开作品」页。

从 ui/main_window.py 拆出的独立页面（架构改良阶段二）。

包含：作品名输入 → 打开；同名时列候选让用户挑；查看全部作品。
"""

from __future__ import annotations

import tkinter as tk

from ..theme import COLOR, F, BrandButton, Card, DarkEntry, DimLabel, TitleLabel


class BooksPage:
    """「打开作品」页。"""

    def _page_books(self, parent):
        self._page_header(parent, "打开作品", "输入小说名称，点一下，进入那本小说")

        card = Card(parent)
        card.pack(fill="x")
        b = card.body

        tk.Label(b, text="小说名称", font=F(9), bg=COLOR["bg_card"],
                 fg=COLOR["text_dim"]).pack(anchor="w")

        self._book_entry = DarkEntry(b, placeholder="输入小说名称，例如：新建作品1",
                                     icon="▣", width=520, height=44)
        self._book_entry.pack(anchor="w", pady=(6, 0))

        # 回车 = 点按钮
        try:
            self._book_entry.entry.bind("<Return>", lambda e: self._open_book())
        except Exception:
            pass

        row = tk.Frame(b, bg=COLOR["bg_card"])
        row.pack(anchor="w", pady=(14, 0))

        self._btn_open_book = BrandButton(
            row, "打开这本小说", width=170, height=42,
            bg=COLOR["bg_card"], command=self._open_book)
        self._btn_open_book.pack(side="left")

        BrandButton(row, "查看全部作品", width=140, height=42, style="ghost",
                    bg=COLOR["bg_card"],
                    command=self._list_all_books).pack(side="left", padx=(10, 0))

        # 状态提示
        self._book_hint = DimLabel(b, "输入名称后点「打开这本小说」，"
                                      "浏览器会自动打开对应作品",
                                   size=9)
        self._book_hint.pack(anchor="w", pady=(14, 0))

        # ---- 同名时的候选列表（默认隐藏，只有重名才出现）----
        self._book_alt_card = Card(parent)
        self._book_alt_box = self._book_alt_card.body
        self._book_alt_head = TitleLabel(self._book_alt_box, "有同名作品，请点一个")
        self._book_alt_head.pack(anchor="w")
        self._book_alt_hint = DimLabel(self._book_alt_box, "", size=9)
        self._book_alt_hint.pack(anchor="w", pady=(3, 10))
        self._book_rows = tk.Frame(self._book_alt_box, bg=COLOR["bg_card"])
        self._book_rows.pack(fill="x")
        # 不调用 pack，等需要时再显示

        self._book_hits = []

    # -------------------------------------------------- 一步到位：打开作品

    def _open_book(self):
        """★ 主入口：读输入框 → 打开作品。重名才让用户选。"""
        import threading

        kw = self._book_entry.get().strip()
        if not kw:
            self.log("请先输入小说名称", "warn")
            self.status.set_status("请输入小说名称", "warn")
            self._book_hint.config(text="请先输入小说名称")
            self._book_entry.focus()
            return

        self._hide_alts()
        self.log(f"正在打开《{kw}》…", "brand")
        self.status.set_status("打开中…", "warn")
        self._book_hint.config(text=f"正在查找并打开《{kw}》…")

        # 按钮进入「进行中」状态
        try:
            self._btn_open_book.set_text("打开中…")
        except Exception:
            pass

        def worker():
            try:
                from src import books as B

                page = self._ensure_page()
                if not B.goto_books(page):
                    raise RuntimeError("无法进入作品列表页")

                books = B.list_books(page)
                hits = B.match_books(books, kw)

                if not hits:
                    self.after(0, self._on_open_fail,
                               f"没有找到叫《{kw}》的小说")
                    return

                if len(hits) == 1:
                    # ★ 唯一命中 —— 直接打开，一步到位
                    #   注意：必须在**同一个线程**里操作 page（Playwright 同步
                    #   API 对象绑定线程），所以这里直接调用而非再起线程
                    self._open_in_thread(hits[0])
                else:
                    # 同名 —— 让用户挑一个
                    self.after(0, self._show_alts, hits, kw)
            except Exception as e:
                self.after(0, self._on_open_fail, str(e))

        self.session.submit(worker)

    def _open_in_thread(self, bk: dict):
        """真实打开（在已持有 page 的线程里调用）。"""
        from src import books as B

        title = bk.get("title")
        bid = bk.get("book_id")
        try:
            page = self._ensure_page()
            ok = B.open_book(page, bid or title, wait=3.0)
            if ok:
                self.after(0, self._on_open_ok, title)
            else:
                self.after(0, self._on_open_fail, f"打开《{title}》失败")
        except Exception as e:
            self.after(0, self._on_open_fail, str(e))

    def _do_open(self, bk: dict):
        """从 UI 线程点击候选条目时调用 —— 投递到常驻 Playwright 线程执行。"""
        self.log(f"正在打开《{bk.get('title')}》…", "brand")
        self.status.set_status("打开中…", "warn")
        # ★ 投递常驻线程（避免跨线程操作浏览器）
        self.session.submit(lambda: self._open_in_thread(bk))

    def _on_open_ok(self, title: str):
        self._reset_open_btn()
        self._hide_alts()
        self._book_hint.config(text=f"已打开《{title}》✓")
        self.log(f"已打开《{title}》✓", "ok")
        self.status.set_status(f"已打开：{title}", "ok")

    def _on_open_fail(self, msg: str):
        self._reset_open_btn()
        self._book_hint.config(text=f"打开失败：{msg}")
        self.log(f"打开失败：{msg}", "err")
        self.status.set_status("打开失败", "err")

    def _reset_open_btn(self):
        try:
            self._btn_open_book.set_text("打开这本小说")
        except Exception:
            pass

    # -------------------------------------------------- 同名候选

    def _hide_alts(self):
        self._book_alt_card.pack_forget()
        for w in self._book_rows.winfo_children():
            w.destroy()

    def _show_alts(self, hits: list, kw: str):
        """同名时列出候选，点一下就打开。"""
        self._reset_open_btn()
        self._book_hits = hits
        self._book_alt_hint.config(
            text=f"有 {len(hits)} 本同名小说，点一个打开")
        self._book_hint.config(text=f"有 {len(hits)} 本同名小说，请在下方选择")

        for w in self._book_rows.winfo_children():
            w.destroy()

        colors = [COLOR["brand"], COLOR["accent"], COLOR["success"], COLOR["warning"]]

        for i, bk in enumerate(hits):
            row = tk.Frame(self._book_rows, bg=COLOR["bg_card_hi"],
                           highlightbackground=COLOR["border"],
                           highlightthickness=1, cursor="hand2")
            row.pack(fill="x", pady=3)

            inner = tk.Frame(row, bg=COLOR["bg_card_hi"])
            inner.pack(fill="x", padx=12, pady=10)

            tk.Label(inner, text=str(i + 1), font=F(11, True),
                     bg=COLOR["bg_card_hi"],
                     fg=colors[i % len(colors)], width=3).pack(side="left")

            info = tk.Frame(inner, bg=COLOR["bg_card_hi"])
            info.pack(side="left", fill="x", expand=True)
            tk.Label(info, text=bk.get("title") or "（无标题）",
                     font=F(10, True), bg=COLOR["bg_card_hi"],
                     fg=COLOR["text"], anchor="w").pack(anchor="w")
            meta = f"ID {bk.get('book_id') or '-'}"
            if bk.get("created"):
                meta += f"   创建于 {bk['created']}"
            tk.Label(info, text=meta, font=F(8), bg=COLOR["bg_card_hi"],
                     fg=COLOR["text_mute"], anchor="w").pack(anchor="w")

            # 点整行即打开
            def _click(e, b=bk):
                self._do_open(b)
            for w in (row, inner, info):
                w.bind("<Button-1>", _click)

            # 也放一个明确的按钮
            BrandButton(inner, "打开", width=70, height=30,
                        bg=COLOR["bg_card_hi"],
                        command=lambda b=bk: self._do_open(b)).pack(side="right")

        self._book_alt_card.pack(fill="x", pady=(10, 0))

    # -------------------------------------------------- 查看全部

    def _list_all_books(self):
        """后台线程：列出全部作品，点一个即打开。"""
        import threading

        self.log("正在读取作品列表 …", "brand")
        self.status.set_status("读取中…", "warn")

        def worker():
            try:
                from src import books as B

                page = self._ensure_page()
                B.goto_books(page)
                books = B.list_books(page)

                self.log(f"共 {len(books)} 部作品：", "info")
                for bk in books:
                    self.log(f"    {bk['title']}  ({bk['words']})", "info")

                self.after(0, self._show_alts, books, "")
                self.after(0, self.status.set_status,
                           f"共 {len(books)} 部作品", "ok")
            except Exception as e:
                self.after(0, self._on_open_fail, str(e))

        self.session.submit(worker)
