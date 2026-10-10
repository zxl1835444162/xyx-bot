"""平台适配器：注册「星月写作」，并可继续扩展其它站点。

照着 FanqiePlatform 的写法，每加一个站点就在这里加一个类。
"""

from __future__ import annotations

from . import BasePlatform, register_platform


@register_platform
class XingyuePlatform(BasePlatform):
    """星月写作 —— AI 网文/剧本创作平台。"""

    name = "星月写作"
    url = "https://xingyuexiezuo.com/"
    login_hint = "首次登录一次（微信扫码 / 账号密码），之后自动复用登录态"

    def run(self, app) -> bool:
        """跑通「登录 -> 进创作台」的主流程。

        登录态已保存时，ensure_login 会直接复用，不会要求重新登录。
        """
        from xyxbot import actions as A
        from xyxbot import config as C
        from xyxbot.login import ensure_login

        if not ensure_login(app):
            print("未登录，终止")
            return False

        page = app.page
        app.goto(C.SITE["entry"])
        app.sleep(2)
        app.shot("xingyue-home")

        # ★★ 2026-10-10 实测修复（命令行 + 界面各复现一次）：
        #   站点首页经常**盖着一个活动弹窗**（实测：「邀请好友赚佣金大奖赛」，
        #   整页遮罩 + 排行榜；右上角还有「国庆特惠上线了」提示条）——
        #   见 artifacts/screenshots/xingyue-studio-*.png。
        #   按钮被遮住 ⇒ 点击找不到可见目标 ⇒ 日志里就是
        #   `[click] ✗ 找不到: 进入创作台`（候选名其实一直是对的）。
        #   所以先关掉活动弹窗，再点入口。
        try:
            from xyxbot.books import close_activity_modal

            close_activity_modal(page, verbose=False)
            app.shot("xingyue-home-cleaned")
        except Exception as e:
            print(f"[studio] 关活动弹窗失败（继续尝试点击）：{str(e).splitlines()[0]}")

        ok = A.click(page, ["text=立即开始创作", "text=开始创作"],
                     label="进入创作台", shot_on_fail=False)
        if not ok:
            # ★★ 2026-10-10 实测（截图 xingyue-home-cleaned-*.png 是现场）：
            #   站点改版后首页**本身就是创作台**（顶部三标签「作品 / 已归档 / 回收站」
            #   + 作品卡片列表 + 一张大的「新建作品」卡片），
            #   旧入口「立即开始创作」「开始创作」已经**不存在** ⇒ 点击必然失败。
            #   所以：只要看得见「新建作品」卡片，就算已经在创作台里（成功），
            #   不再去点半岛不存在的按钮（也不误触"新建作品"弹窗，只做判据）。
            try:
                from xyxbot.books import find_create_card

                if find_create_card(page):
                    print("[studio] ✓ 已经在创作台（首页即作品列表，站点已改版）")
                    ok = True
            except Exception as e:
                print(f"[studio] 判据异常：{str(e).splitlines()[0]}")
        if not ok:
            print("[studio] ⚠ 既没点到入口、也没看到创作台内容 —— "
                  "站点可能又改版了（已存截图 artifacts/screenshots/）")
        app.sleep(3)
        app.shot("xingyue-studio")
        print("当前 URL:", page.url)
        return bool(ok)


# 以后接别的站点，照抄上面这个类即可，例如：
#
# @register_platform
# class SomeOtherPlatform(BasePlatform):
#     name = "某某站"
#     url = "https://example.com/"
#     def run(self, app) -> bool:
#         ...
