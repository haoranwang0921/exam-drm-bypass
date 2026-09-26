"""Launch / attach Chrome over CDP, with support for a detached persistent session.

两种用法：
  fresh_chrome_context() — 启动临时/专用 Chrome，退出时随进程一起关闭（旧逻辑）
  open_chrome()          — 优先 attach 到 login.py 启动的常驻已登录 Chrome；
                           无常驻会话时退回到 fresh_chrome_context()

常驻会话的端口 / PID 记录在 SESSION_FILE（.browser_session.json）。
"""

import os
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import ctypes
from contextlib import contextmanager

SESSION_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".browser_session.json"
)


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


def _cdp_port_alive(port, timeout=0.5):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _pid_alive(pid):
    """Windows 下用 OpenProcess 检测进程是否存在（不能用 os.kill(pid,0)，
    那在 Windows 上等价于 TerminateProcess，会真的杀掉进程）。"""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return False


# ═══════════════════════════════════════════════════════════════
# 常驻会话状态文件
# ═══════════════════════════════════════════════════════════════

def write_session(port, pid, user_data_dir):
    data = {
        "port": port,
        "pid": pid,
        "user_data_dir": user_data_dir,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    tmp = SESSION_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SESSION_FILE)


def read_session():
    """返回有效的常驻会话 dict；状态文件缺失或端口已失效则返回 None
    （端口失效时顺手清理状态文件）。"""
    if not os.path.isfile(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            info = json.load(f)
        port = int(info["port"])
    except Exception:
        clear_session()
        return None
    if _cdp_port_alive(port):
        return info
    clear_session()
    return None


def clear_session():
    try:
        os.remove(SESSION_FILE)
    except OSError:
        pass


# ═══════════════════════════════════════════════════════════════
# 进程树终止
# ═══════════════════════════════════════════════════════════════

def _terminate_process_tree(process):
    """终止 Popen 启动的 Chrome：先 terminate 优雅退出，超时再 taskkill /T /F。"""
    if process.poll() is not None:
               return
    process.terminate()
    try:
        process.wait(timeout=8)
        return
    except subprocess.TimeoutExpired:
        pass
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


def terminate_pid_tree(pid):
    """按 PID 关闭整棵 Chrome 进程树：先 taskkill（不带 /F，发 WM_CLOSE
    让 Chrome 优雅退出并 flush profile），失败或超时再强杀。"""
    if not _pid_alive(pid):
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8,
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and _pid_alive(pid):
            time.sleep(0.3)
    except Exception:
        pass
    if _pid_alive(pid):
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# 启动 detached 常驻 Chrome（login.py 使用）
# ═══════════════════════════════════════════════════════════════

def launch_detached_chrome(user_data_dir, headless=False, start_url="about:blank"):
    """启动一个不随调用进程退出的 Chrome，写入会话状态文件。
    返回 (process, port)。调用方负责在登录失败时终止它。"""
    os.makedirs(user_data_dir, exist_ok=True)
    port = _reserve_port()
    command = [
        _find_chrome(),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
        "--proxy-server=direct://",
        "--proxy-bypass-list=*",
        start_url,
    ]
    if headless:
        command.insert(1, "--headless=new")

    # CREATE_NEW_PROCESS_GROUP：login.py 退出后 Chrome 继续作为独立进程组存活。
    # CREATE_BREAKAWAY_FROM_JOB(0x01000000)：从调用方所在的 Job Object 脱离，
    # 这样即使启动 login.py 的宿主进程被强制终止，Chrome 仍能常驻。
    if sys.platform == "win32":
        try:
            process = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | 0x01000000,
            )
        except OSError:
            # 外层 Job 不允许 breakaway，退回普通进程组
            process = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
    else:
        process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    _wait_for_debug_port(process, port)
    write_session(port, process.pid, user_data_dir)
    return process, port


# ═══════════════════════════════════════════════════════════════
# 旧逻辑：随进程生灭的 Chrome
# ═══════════════════════════════════════════════════════════════

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
        "--start-maximized",
        "--proxy-server=direct://",
        "--proxy-bypass-list=*",
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
                browser.close()  # CDP 断开，触发 Chrome 优雅退出（flush cookie/localStorage）
            except Exception:
                pass
        _terminate_process_tree(process)
        if cleanup_profile:
            shutil.rmtree(profile_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════
# 统一入口：优先 attach 常驻 Chrome，否则启动新的
# ═══════════════════════════════════════════════════════════════

@contextmanager
def open_chrome(playwright, headless=False, user_data_dir=None):
    """yield (context, persistent)：
      persistent=True  — 已 attach 到 login.py 的常驻 Chrome，复用登录态；
                         退出时只断开 CDP 连接，浏览器继续运行；
      persistent=False — 新启动的 Chrome（旧逻辑），退出时关闭并清理。
    """
    info = read_session()
    if info:
        browser = playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{info['port']}"
        )
        try:
            if not browser.contexts:
                raise RuntimeError("常驻 Chrome 无可用浏览器上下文。")
            print(f"已连接常驻浏览器 (CDP 端口 {info['port']})，复用登录态。")
            yield browser.contexts[0], True
        finally:
            # connect_over_cdp 模式下 browser.close() 仅断开连接，不关闭浏览器
            try:
                browser.close()
            except Exception:
                pass
        return

    with fresh_chrome_context(
        playwright, headless=headless, user_data_dir=user_data_dir
    ) as context:
        yield context, False
