"""Launch a normal Chrome process and attach Playwright over CDP."""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager


def _find_chrome():
    candidates = [
        shutil.which("chrome"),
        os.path.join(os.environ.get("PROGRAMFILES", ""),
                     "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""),
                     "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    raise RuntimeError("未找到 Google Chrome，请先安装 Chrome。")


def _reserve_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_debug_port(process, port, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Chrome 在调试接口就绪前退出。")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("等待 Chrome 调试接口超时。")


@contextmanager
def fresh_chrome_context(playwright, headless=False, user_data_dir=None):
    """Yield a fresh Chrome context launched without Playwright launch flags.

    user_data_dir 为 None 时使用临时 profile（退出即删）；
    传入真实 profile 路径时保留该目录（用于复用 WAF/UEBA 设备指纹与登录态）。
    """
    if user_data_dir:
        profile_dir = user_data_dir
        cleanup_profile = False
    else:
        profile_dir = tempfile.mkdtemp(prefix="exam-bypass-chrome-")
        cleanup_profile = True
    port = _reserve_port()
    command = [
        _find_chrome(),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=2560,1440",
        "about:blank",
    ]
    if headless:
        command.insert(1, "--headless=new")

    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # CREATE_NEW_PROCESS_GROUP 让 Chrome 子进程与主进程在同一进程组，
        # 退出时可一次性 taskkill /T 杀掉整个进程树，避免渲染/GPU 子进程残留
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    browser = None
    try:
        _wait_for_debug_port(process, port)
        browser = playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{port}"
        )
        if not browser.contexts:
            raise RuntimeError("Chrome 未创建默认浏览器上下文。")
        yield browser.contexts[0]
    finally:
        if browser is not None:
            try:
                browser.close()  # CDP 关闭，触发 Chrome 优雅退出（flush cookie/localStorage）
            except Exception:
                pass
        if process.poll() is None:
            process.terminate()  # 向进程组发终止信号
            try:
                process.wait(timeout=8)  # 给 Chrome 时间优雅退出与 flush
            except subprocess.TimeoutExpired:
                # 进程组超时仍未退出 → taskkill /T /F 递归杀整个 Chrome 进程树，
                # 避免子进程（renderer/GPU/utility）残留导致 profile 锁/状态损坏
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
                try:
                    process.wait(timeout=5)
                except Exception:
                    pass
        if cleanup_profile:
            shutil.rmtree(profile_dir, ignore_errors=True)
