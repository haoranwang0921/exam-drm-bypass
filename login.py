"""第一步：手动登录并保持浏览器常驻，供后续抓取脚本复用。

为什么需要它：
  XJTLU SSO 带深信服 UEBA 风控（鼠标轨迹指纹），自动登录会被拦截；
  且 SSO 会话 Cookie 是会话级的，Chrome 关闭后重启无法靠 profile 恢复。
  因此本脚本启动一个 detached 常驻 Chrome，由真人手动登录；登录成功后
  Chrome 保持运行，batch_capture.py / capture_canvas.py 会通过 CDP 自动连接。

用法:
  python login.py            # 启动常驻 Chrome 并手动登录（已运行则校验登录态）
  python login.py --status   # 查看常驻浏览器状态
  python login.py --close    # 关闭常驻 Chrome
"""

import argparse
import sys

# 修复 Windows GBK 终端编码问题
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from playwright.sync_api import sync_playwright

from browser_session import (
    read_session,
    clear_session,
    launch_detached_chrome,
    terminate_pid_tree,
)
from capture_canvas import BASE_URL, SPECIAL_PROFILE, login


def _connect(playwright, port):
    return playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")


def _first_page(context):
    page = context.pages[0] if context.pages else context.new_page()
    return page


def _check_logged_in(page):
    """导航到首页，检测是否已登录。"""
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    return bool(page.get_by_text("Past Exam Papers", exact=True).count())


def do_login():
    info = read_session()
    if info:
        # 已有常驻实例：校验登录态，避免重复启动
        print("检测到常驻浏览器已在运行，校验登录态...")
        with sync_playwright() as p:
            browser = _connect(p, info["port"])
            try:
                page = _first_page(browser.contexts[0])
                if _check_logged_in(page):
                    print("登录态有效，可直接运行: python batch_capture.py <课程代码>")
                    return
                print("常驻浏览器存在但登录态已失效，先关闭它，请重新运行 login.py。")
            finally:
                browser.close()
        do_close()
        sys.exit(1)

    # 启动新的常驻 Chrome，启动标签直接打开系统首页（不先显示空白页）
    process, port = launch_detached_chrome(SPECIAL_PROFILE, start_url=BASE_URL)
    print(f"已启动常驻 Chrome (CDP 端口 {port}, PID {process.pid})")
    try:
        with sync_playwright() as p:
            browser = _connect(p, port)
            try:
                page = _first_page(browser.contexts[0])
                login(page)  # 等待真人手动登录，最多 5 分钟
            finally:
                # 仅断开 CDP 连接；Chrome 作为 detached 进程继续运行
                browser.close()
        print("\n登录完成，浏览器保持运行。")
        print("下一步: python batch_capture.py <课程代码>")
        print("用完关闭: python login.py --close")
    except Exception as e:
        print(f"登录未完成: {e}")
        print("正在关闭常驻浏览器...")
        terminate_pid_tree(process.pid)
        clear_session()
        sys.exit(1)


def do_status():
    info = read_session()
    if not info:
        print("无常驻浏览器会话。可运行 python login.py 启动并手动登录。")
        return
    print("常驻浏览器运行中:")
    print(f"  CDP 端口: {info['port']}")
    print(f"  PID:      {info['pid']}")
    print(f"  Profile:  {info['user_data_dir']}")
    print(f"  启动时间: {info.get('started_at', 'unknown')}")
    print("校验登录态: python login.py")


def do_close():
    info = read_session()
    if not info:
        print("没有运行中的常驻浏览器。")
        return
    pid = int(info["pid"])
    print(f"正在关闭常驻 Chrome (PID {pid})...")
    terminate_pid_tree(pid)
    clear_session()
    print("已关闭。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="手动登录并保持 Chrome 常驻，供抓取脚本复用"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="查看常驻浏览器状态")
    group.add_argument("--close", action="store_true", help="关闭常驻浏览器")
    args = parser.parse_args()

    if args.status:
        do_status()
    elif args.close:
        do_close()
    else:
        do_login()
