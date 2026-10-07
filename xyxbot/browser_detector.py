"""浏览器路径检测模块（macOS / Windows 双平台）。

原版 browser_detector.py 只读 Windows 注册表、只探测 .exe 路径，在 macOS 上
完全失效。本模块保持对外接口（BrowserDetector 的六个方法名与返回类型）不变，
内部按运行平台选择探测策略：

  * Windows：沿用原版注册表 + 默认安装路径逻辑；
  * macOS  ：探测 /Applications 下的 Chrome / Edge / Chromium / Brave / Vivaldi，
             以及用户目录 ~/Applications 的安装；返回 .app 包内的可执行文件路径。

返回值语义与原版一致：可直接传给 playwright 的 `executable_path`，
或用于 `--remote-debugging-port` 启动浏览器分身。
"""
import os
import sys
import platform
from typing import List, Optional, Dict

IS_MAC = sys.platform == 'darwin'
IS_WIN = sys.platform.startswith('win')


def _same_path(a: str, b: str) -> bool:
    """两个路径是否指向同一个文件（大小写与分隔符无关）。

    用于检测去重：Windows 上 'Edge Dev' 的注册表键与 'Edge' 相同，
    会解析出同一个 msedge.exe。
    """
    if not a or not b:
        return False
    na = os.path.normcase(os.path.normpath(str(a).replace("/", os.sep)))
    nb = os.path.normcase(os.path.normpath(str(b).replace("/", os.sep)))
    return na == nb


# ---------------------------------------------------------------------------
# macOS：.app 包内的可执行文件名与候选安装位置
# ---------------------------------------------------------------------------
MAC_BROWSERS = {
    'Chrome': {
        'bundle': 'Google Chrome.app',
        'exe': 'Contents/MacOS/Google Chrome',
        'roots': ['/Applications', os.path.expanduser('~/Applications')],
    },
    'Edge': {
        'bundle': 'Microsoft Edge.app',
        'exe': 'Contents/MacOS/Microsoft Edge',
        'roots': ['/Applications', os.path.expanduser('~/Applications')],
    },
    'Edge Dev': {
        'bundle': 'Microsoft Edge Dev.app',
        'exe': 'Contents/MacOS/Microsoft Edge Dev',
        'roots': ['/Applications', os.path.expanduser('~/Applications')],
    },
    'Chromium': {
        'bundle': 'Chromium.app',
        'exe': 'Contents/MacOS/Chromium',
        'roots': ['/Applications', os.path.expanduser('~/Applications')],
    },
    'Brave': {
        'bundle': 'Brave Browser.app',
        'exe': 'Contents/MacOS/Brave Browser',
        'roots': ['/Applications', os.path.expanduser('~/Applications')],
    },
    'Vivaldi': {
        'bundle': 'Vivaldi.app',
        'exe': 'Contents/MacOS/Vivaldi',
        'roots': ['/Applications', os.path.expanduser('~/Applications')],
    },
}

# ---------------------------------------------------------------------------
# Windows：与原版一致的注册表键与默认路径
# ---------------------------------------------------------------------------
WIN_BROWSERS = {
    'Chrome': {
        'registry_paths': [
            'Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\chrome.exe',
            'SOFTWARE\\Clients\\StartMenuInternet\\Google Chrome\\shell\\open\\command',
        ],
        'default_paths': [
            'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
            'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
            '%LOCALAPPDATA%\\Google\\Chrome\\Application\\chrome.exe',
        ],
    },
    'Edge': {
        'registry_paths': [
            'Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\msedge.exe',
            'SOFTWARE\\Clients\\StartMenuInternet\\Microsoft Edge\\shell\\open\\command',
        ],
        'default_paths': [
            'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
            'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
            'C:\\Program Files (x86)\\Microsoft\\Edge Dev\\Application\\msedge.exe',
            'C:\\Program Files\\Microsoft\\Edge Dev\\Application\\msedge.exe',
        ],
    },
    'Edge Dev': {
        'registry_paths': [
            'Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\msedge.exe',
        ],
        'default_paths': [
            'C:\\Program Files (x86)\\Microsoft\\Edge Dev\\Application\\msedge.exe',
            'C:\\Program Files\\Microsoft\\Edge Dev\\Application\\msedge.exe',
        ],
    },
    'Chromium': {
        'registry_paths': [
            'Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\chromium.exe',
        ],
        'default_paths': [
            'C:\\Program Files\\Chromium\\Application\\chromium.exe',
            'C:\\Program Files (x86)\\Chromium\\Application\\chromium.exe',
        ],
    },
}

class BrowserDetector:
    """跨平台浏览器路径检测器。"""

    BROWSER_REGISTRY_PATHS = WIN_BROWSERS if IS_WIN else {}
    BROWSER_MAC_PATHS = MAC_BROWSERS

    # 浏览器推荐优先级（★ 只在类里定义一处，避免与 get_recommended_browser 重复）
    PRIORITY_ORDER = ['Edge Dev', 'Edge', 'Chrome', 'Chromium', 'Brave', 'Vivaldi']

    # 检测结果缓存（避免同一次会话里反复扫盘/读注册表）
    _cache: Optional[Dict[str, str]] = None

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _expand_environment_variables(path: str) -> str:
        """展开环境变量（Windows 的 %VAR%、类 Unix 的 $VAR 都支持）。"""
        return os.path.expandvars(os.path.expanduser(path))
    @staticmethod
    def _check_file_exists(file_path: str) -> bool:
        """检查文件是否存在且可执行（macOS 下不要求 .exe 后缀）。"""
        if not file_path:
            return False
        file_path = BrowserDetector._expand_environment_variables(file_path)
        if not os.path.isfile(file_path):
            return False
        if os.name == 'nt':
            return file_path.lower().endswith('.exe')
        return os.access(file_path, os.X_OK)

    @staticmethod
    def _read_registry_value(key_path: str, value_name: str = ''):
        """读取 Windows 注册表值；非 Windows 平台直接返回 None。"""
        if not IS_WIN:
            return None
        try:
            import winreg  # noqa: WPS433  仅在 Windows 上可用
        except ImportError:
            return None
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
            value = winreg.QueryValueEx(key, value_name)[0]
            winreg.CloseKey(key)
        except OSError:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
                value = winreg.QueryValueEx(key, value_name)[0]
                winreg.CloseKey(key)
            except OSError:
                return None
        # 注册表里存的可能是 `"C:\path\chrome.exe" -- "%1"` 这种命令串
        if isinstance(value, str) and '"' in value:
            parts = value.split('"')
            if len(parts) > 1 and parts[1]:
                value = parts[1]
        elif isinstance(value, str) and value.lower().endswith('.exe') is False:
            first = value.split(' ')[0].strip()
            if first:
                value = first
        return value

    # ------------------------------------------------------------- detection

    @staticmethod
    def detect_browser_path(browser_name: str) -> Optional[str]:
        """检测指定浏览器的可执行文件路径，找不到返回 None。"""
        if IS_WIN:
            info = WIN_BROWSERS.get(browser_name)
            if not info:
                return None
            for reg_path in info['registry_paths']:
                path = BrowserDetector._read_registry_value(reg_path, '')
                if path and BrowserDetector._check_file_exists(path):
                    print(f'从注册表找到 {browser_name}: {path}')
                    return path
            for default_path in info['default_paths']:
                if BrowserDetector._check_file_exists(default_path):
                    print(f'从默认路径找到 {browser_name}: {default_path}')
                    return BrowserDetector._expand_environment_variables(default_path)
            return None

        info = MAC_BROWSERS.get(browser_name)
        if not info:
            return None
        for root in info['roots']:
            candidate = os.path.join(root, info['bundle'], info['exe'])
            if BrowserDetector._check_file_exists(candidate):
                print(f'在 {root} 找到 {browser_name}: {candidate}')
                return candidate
        return None

    @staticmethod
    def detect_all_browsers(use_cache: bool = True) -> Dict[str, str]:
        """检测所有可用的浏览器，返回 {名称: 可执行文件路径}。

        ★ 修复（重复探测）：`get_browser_info()` 原本先调一次本函数，
          再调 `get_recommended_browser()`（内部又调一次）→ 整个磁盘/注册表
          探测跑两遍、日志也打两轮。现在结果**缓存**，默认复用。
          需要强制重扫时传 `use_cache=False`。
        """
        cache = getattr(BrowserDetector, "_cache", None)
        if use_cache and cache is not None:
            return dict(cache)

        available_browsers = {}
        names = (list(WIN_BROWSERS) if IS_WIN else list(MAC_BROWSERS))
        # ★ 按推荐优先级排序后再检测 → 同一路径的去重会自然保留优先级更高的名字
        order = {n: i for i, n in enumerate(BrowserDetector.PRIORITY_ORDER)}
        names.sort(key=lambda n: order.get(n, len(order)))
        print('开始检测可用的浏览器...')
        for browser_name in names:
            path = BrowserDetector.detect_browser_path(browser_name)
            if not path:
                print(f'✗ 未找到 {browser_name}')
                continue
            # ★ 修复（重复路径）：实测 Windows 上 'Edge Dev' 的注册表键与 'Edge'
            #   完全相同，于是同一个 msedge.exe 会被同时报成 Edge 和 Edge Dev，
            #   日志误导、优先级判断也失真。这里去重：同一路径只保留**首个**
            #   （即优先级更高的）名字。
            dup_of = next((n for n, p in available_browsers.items()
                           if _same_path(p, path)), None)
            if dup_of:
                print(f'· {browser_name} 与 {dup_of} 指向同一个文件，跳过')
                continue
            available_browsers[browser_name] = path
            print(f'✓ 找到 {browser_name}: {path}')
        BrowserDetector._cache = dict(available_browsers)
        return available_browsers

    @staticmethod
    def get_recommended_browser(use_cache: bool = True) -> Optional[str]:
        """按优先级推荐一个浏览器路径。"""
        available_browsers = BrowserDetector.detect_all_browsers(use_cache=use_cache)
        for browser_name in BrowserDetector.PRIORITY_ORDER:
            if browser_name in available_browsers:
                recommended_path = available_browsers[browser_name]
                print(f'推荐使用 {browser_name}: {recommended_path}')
                return recommended_path
        print('未找到任何可用的浏览器')
        return None

    @staticmethod
    def get_browser_info() -> str:
        """返回人类可读的检测结果。"""
        # ★ 用缓存结果，避免与 get_recommended_browser 重复探测
        available_browsers = BrowserDetector.detect_all_browsers()
        if not available_browsers:
            return '未检测到任何可用的浏览器\n请手动配置浏览器路径'
        info = ''
        for browser_name, path in available_browsers.items():
            info += f'  {browser_name}: {path}\n'
        recommended = BrowserDetector.get_recommended_browser()
        if recommended:
            info += f'\n推荐使用: {recommended}'
        return info

def test_browser_detection():
    """测试浏览器检测功能。"""
    print('=== 浏览器路径检测测试 ===')
    print(f'平台: {platform.system()} {platform.machine()}')
    print(BrowserDetector.get_browser_info())
    print('=== 测试完成 ===')

if __name__ == '__main__':
    test_browser_detection()
