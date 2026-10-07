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

        A.click(page, ["text=立即开始创作", "text=开始创作"],
                label="进入创作台", shot_on_fail=False)
        app.sleep(3)
        app.shot("xingyue-studio")
        print("当前 URL:", page.url)
        return True


# 以后接别的站点，照抄上面这个类即可，例如：
#
# @register_platform
# class SomeOtherPlatform(BasePlatform):
#     name = "某某站"
#     url = "https://example.com/"
#     def run(self, app) -> bool:
#         ...
