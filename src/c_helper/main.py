"""
main.py — AI客户端、剪贴板、键盘模拟、热键主循环

架构：
  主线程  → pynput keyboard.Listener（WH_KEYBOARD_LL，必须主线程）
  子线程A → pystray Icon.run()（托盘消息循环）
  子线程B → Worker（HTTP请求、键盘模拟，通过Queue接收任务）
"""
from __future__ import annotations

import ctypes
import logging
import queue
import random
import re
import signal
import sys
import threading
import time
from typing import Optional

import pyperclip
import pystray
import requests
from pynput import keyboard as pk
from pynput.keyboard import Controller, HotKey, Key, Listener
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from c_helper.core import Config, IconRenderer, State, StateMachine

log = logging.getLogger("c_helper")

# ---------------------------------------------------------------------------
# Windows API — 强制英文布局（避免中文IME干扰键盘模拟）
# ---------------------------------------------------------------------------
_EN_US_LAYOUT = 0x04090409
_user32 = ctypes.WinDLL("user32", use_last_error=True)


def _get_foreground_layout() -> int:
    hwnd = _user32.GetForegroundWindow()
    tid = _user32.GetWindowThreadProcessId(hwnd, None)
    return _user32.GetKeyboardLayout(tid)


def _set_foreground_layout(hkl: int) -> None:
    hwnd = _user32.GetForegroundWindow()
    _user32.PostMessageW(hwnd, 0x0050, 0, hkl)  # WM_INPUTLANGCHANGEREQUEST


# ---------------------------------------------------------------------------
# 剪贴板（带指数退避）
# ---------------------------------------------------------------------------
def safe_paste(retries: int = 5, base_delay: float = 0.05) -> str:
    """读取剪贴板文本，带重试。"""
    last_err: Exception | None = None
    for i in range(retries):
        try:
            text = pyperclip.paste()
            return text if isinstance(text, str) else ""
        except Exception as e:
            last_err = e
            time.sleep(base_delay * (2 ** i))
    log.error("读取剪贴板失败: %s", last_err)
    return ""


# ---------------------------------------------------------------------------
# AI 客户端
# ---------------------------------------------------------------------------
class AIClient:
    def __init__(self, config: Config):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        })
        # 连接超时5s，读超时60s；仅对特定状态码重试
        adapter = HTTPAdapter(
            max_retries=Retry(
                total=3,
                backoff_factor=1.0,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["POST"],
                respect_retry_after_header=True,
            ),
            pool_connections=4,
            pool_maxsize=4,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.base_url = config.base_url.rstrip("/")

    def ask(self, question: str) -> str:
        """发送非流式请求，返回清洗后的纯文本。"""
        system_content = self.config.system_prompt
        if self.config.output_mode == "optimized":
            system_content += (
                "\n\n格式要求：使用K&R风格大括号（左大括号不换行，紧跟在控制语句同一行末尾），"
                "输出代码时不要包含任何前导空格或缩进，所有代码顶格输出，让编辑器自动处理缩进。"
            )

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": question},
            ],
            "temperature": 0.2,
        }
        url = f"{self.base_url}/chat/completions"
        resp = self.session.post(url, json=payload, timeout=(5, 60))
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise ValueError("AI 返回空 choices")
        content = choices[0].get("message", {}).get("content", "")
        if self.config.output_mode == "raw":
            return content.strip()
        return self._sanitize(content)

    def health_check(self) -> tuple[bool, str]:
        """启动时检查 API 可用性。返回 (是否可用, 状态信息)。"""
        try:
            url = f"{self.base_url}/models"
            resp = self.session.get(url, timeout=(5, 10))
            if resp.status_code == 200:
                return True, "API 连接正常"
            elif resp.status_code == 401:
                return False, "API Key 无效或已过期"
            else:
                return False, f"API 返回状态码 {resp.status_code}"
        except requests.exceptions.ConnectionError:
            return False, "无法连接到 API 服务器，请检查网络或 base_url"
        except requests.exceptions.Timeout:
            return False, "API 连接超时"
        except Exception as e:
            return False, f"API 检查失败: {e}"

    @staticmethod
    def _sanitize(text: str) -> str:
        """
        清洗 AI 返回的 Markdown/网页编辑器污染：
        - 去掉 ```c / ``` 围栏标记
        - 删除末尾多余的孤立大括号（平衡检查）
        - 去掉尾部空行与反引号残留
        注意：缩进由 type_text 在输出时处理，此处不修改。
        """
        text = text.strip()

        # 1. 去掉 Markdown 围栏代码块标记
        text = re.sub(r"^```\w*\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)

        # 2. 去掉末尾空行和反引号残留
        lines = text.splitlines()
        while lines and lines[-1].strip() in ("", "```", "`"):
            lines.pop()

        # 3. 大括号平衡检查：从末尾逐个去掉导致不平衡的孤立 "}"
        while lines:
            stripped = lines[-1].strip()
            if stripped == "}":
                joined = "\n".join(lines)
                open_count = joined.count("{")
                close_count = joined.count("}")
                if close_count > open_count:
                    lines.pop()
                    continue
            break

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 键盘模拟（打字机效果 + 强制英文布局）
# ---------------------------------------------------------------------------
class Typer:
    def __init__(self, config: Config):
        self.config = config
        self.controller = Controller()

    def type_text(self, text: str) -> None:
        """
        在前台窗口模拟逐字输入，带延迟、随机抖动和智能停顿。

        停顿规则（模拟人类打字思考）：
        - 普通字符: base_delay + jitter
        - 空格: ×1.5（单词间思考）
        - 逗号/分号: ×2.0（短停顿）
        - 句号/右大括号/右括号: ×3.0（长停顿，语句结束）
        - 换行: ×4.0（段落停顿）
        """
        if not text:
            return

        # optimized 模式：去掉每行前导空格，让编辑器自动缩进接管
        if self.config.output_mode == "optimized":
            text = "\n".join(line.lstrip() for line in text.splitlines())

        base_delay = self.config.typing_delay_ms / 1000.0
        jitter = self.config.typing_jitter_range_ms / 1000.0 if self.config.typing_jitter else 0.0

        # 强制英文布局
        original = _get_foreground_layout()
        try:
            if original != _EN_US_LAYOUT:
                _set_foreground_layout(_EN_US_LAYOUT)
                time.sleep(0.05)

            for ch in text:
                self.controller.type(ch)

                # editor_auto_brace：输出 { 后删除编辑器自动补全的 }
                if ch == "{" and self.config.editor_auto_brace:
                    self.controller.press(Key.end)
                    self.controller.release(Key.end)
                    self.controller.press(Key.backspace)
                    self.controller.release(Key.backspace)

                delay = base_delay
                if jitter:
                    delay += random.uniform(-jitter, jitter)

                # 智能停顿：根据字符类型乘不同倍数
                if ch == "\n":
                    if self.config.long_pause_enabled and random.random() < self.config.long_pause_chance:
                        # 长思考：随机 3-12 秒（模拟停下来想代码结构）
                        long_ms = random.randint(
                            self.config.long_pause_min_ms,
                            self.config.long_pause_max_ms,
                        )
                        delay = long_ms / 1000.0
                        log.info("长思考停顿 %.1fs", delay)
                    else:
                        delay *= 6.0
                elif ch in ".}])":
                    delay *= 3.0
                elif ch in ",;":
                    delay *= 2.0
                elif ch == " ":
                    delay *= 1.5

                delay = max(0.01, delay)
                time.sleep(delay)
        finally:
            if original != _EN_US_LAYOUT:
                _set_foreground_layout(original)


# ---------------------------------------------------------------------------
# 托盘管理器
# ---------------------------------------------------------------------------
class TrayManager:
    def __init__(self, on_reset: Callable[[], None], on_quit: Callable[[], None]):
        self.icon: Optional[pystray.Icon] = None
        self._on_reset = on_reset
        self._on_quit = on_quit
        self._lock = threading.Lock()
        self._state = State.IDLE
        self._pending_state: Optional[State] = None

    def build(self) -> pystray.Icon:
        menu = pystray.Menu(
            pystray.MenuItem("强制重置为空闲", lambda _i, _it: self._on_reset()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda _i, _it: self._on_quit()),
        )
        self.icon = pystray.Icon(
            "c_helper",
            IconRenderer.render(State.IDLE),
            title="C Helper — Ctrl+Alt+G",
            menu=menu,
        )
        # 应用启动前缓存的状态
        with self._lock:
            if self._pending_state is not None:
                self.icon.icon = IconRenderer.render(self._pending_state)
                self.icon.title = f"C Helper — {self._pending_state.name}"
                self._pending_state = None
        return self.icon

    def set_state(self, state: State) -> None:
        with self._lock:
            if self._state == state:
                return
            self._state = state
            if self.icon is None:
                self._pending_state = state
                return
        self.icon.icon = IconRenderer.render(state)
        self.icon.title = f"C Helper — {state.name}"

    def run(self) -> None:
        # Windows 要求：Icon 创建和 run() 必须在同一线程
        self.build()
        if self.icon:
            self.icon.run()

    def stop(self) -> None:
        if self.icon:
            self.icon.stop()


# ---------------------------------------------------------------------------
# 工作线程
# ---------------------------------------------------------------------------
class Worker:
    def __init__(self, config: Config, state_machine: StateMachine, tray: TrayManager):
        self.config = config
        self.sm = state_machine
        self.tray = tray
        self.ai = AIClient(config)
        self.typer = Typer(config)
        self.q: queue.Queue[Callable[[], None]] = queue.Queue()
        self._cached_answer: str = ""
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def submit(self, task: Callable[[], None]) -> None:
        self.q.put(task)

    def _loop(self) -> None:
        while True:
            try:
                task = self.q.get(timeout=1)
                task()
            except queue.Empty:
                continue
            except Exception:
                log.exception("Worker 任务异常")

    # -----------------------------------------------------------------------
    # 业务动作
    # -----------------------------------------------------------------------
    def handle_hotkey(self) -> None:
        state = self.sm.state
        if state is State.IDLE:
            log.debug("正在检测 API，忽略热键")
        elif state is State.READY:
            if self._cached_answer:
                self._do_type()
            else:
                self._do_request()
        elif state is State.ERROR:
            log.debug("API 异常，等待自动重试或强制重置")
        elif state in (State.REQUESTING, State.TYPING):
            log.debug("当前 %s，忽略热键", state.name)

    def _do_request(self) -> None:
        if not self.sm.transition(State.REQUESTING):
            return
        self.tray.set_state(State.REQUESTING)

        try:
            text = safe_paste()
            if not text.strip():
                raise ValueError("剪贴板为空或无有效内容")

            answer = self.ai.ask(text)
            if not answer:
                raise ValueError("AI 返回空内容")

            self._cached_answer = answer
            self.sm.transition(State.READY)
            self.tray.set_state(State.READY)
            log.info("答案已就绪，长度 %d", len(answer))
        except Exception as e:
            log.error("请求失败: %s", e)
            self._cached_answer = ""
            self.sm.transition(State.ERROR)
            self.tray.set_state(State.ERROR)

    def _do_type(self) -> None:
        if not self.sm.transition(State.TYPING):
            return
        self.tray.set_state(State.TYPING)

        # 给输入法/焦点切换留出 2 秒缓冲，避免首字符丢失
        log.info("2 秒后开始输出...")
        time.sleep(2)

        try:
            text = self._cached_answer
            if text:
                self.typer.type_text(text)
            else:
                log.warning("缓存为空，无内容可输出")
        except Exception as e:
            log.error("键盘模拟失败: %s", e)
        finally:
            self._cached_answer = ""
            self.sm.transition(State.READY)
            self.tray.set_state(State.READY)
            log.info("输出完成，系统就绪")

    def force_reset(self) -> None:
        self._cached_answer = ""
        self.sm.force_reset()
        self.tray.set_state(State.IDLE)


# ---------------------------------------------------------------------------
# 热键管理器
# ---------------------------------------------------------------------------
class HotkeyManager:
    """
    Ctrl+G 全局热键。
    Windows WH_KEYBOARD_LL 必须在主线程运行，因此 Listener 在主线程阻塞。
    热键回调只做一件事：向 Worker Queue 投递轻量任务，绝不阻塞。
    """

    def __init__(self, worker: Worker, tray: TrayManager):
        self.worker = worker
        self.tray = tray
        self._listener: Optional[Listener] = None
        self._last_ms = 0.0
        self._debounce_ms = 300.0
        self._running = True

    def start(self) -> None:
        hotkey = HotKey(HotKey.parse("<ctrl>+<alt>+g"), self._on_combo)

        def on_press(key):
            if not self._running:
                return False
            hotkey.press(self._listener.canonical(key))

        def on_release(key):
            if not self._running:
                return False
            hotkey.release(self._listener.canonical(key))

        self._listener = Listener(on_press=on_press, on_release=on_release)
        self._listener.start()
        log.info("热键 Ctrl+Alt+G 已注册")
        self._listener.join()
        log.info("热键监听已结束")

    def stop(self) -> None:
        self._running = False
        if self._listener:
            self._listener.stop()

    def _on_combo(self) -> None:
        now = time.monotonic() * 1000
        if now - self._last_ms < self._debounce_ms:
            return
        self._last_ms = now
        log.debug("热键触发")
        self.worker.submit(self.worker.handle_hotkey)


# ---------------------------------------------------------------------------
# 应用入口
# ---------------------------------------------------------------------------
class App:
    def __init__(self, config_path: str = "config.json"):
        self.config = Config.load(config_path)
        self.sm = StateMachine()
        self.tray = TrayManager(on_reset=self._on_reset, on_quit=self._on_quit)
        self.worker = Worker(self.config, self.sm, self.tray)
        self.hotkey = HotkeyManager(self.worker, self.tray)

    def _on_reset(self) -> None:
        log.info("用户强制重置")
        self.worker.force_reset()

    def _on_quit(self) -> None:
        log.info("用户请求退出")
        self.tray.stop()
        self.hotkey.stop()
        sys.exit(0)

    def run(self) -> None:
        # 信号处理
        signal.signal(signal.SIGINT, lambda _s, _f: self._on_quit())
        signal.signal(signal.SIGTERM, lambda _s, _f: self._on_quit())

        # 状态变更联动托盘
        self.sm.set_on_change(self.tray.set_state)

        # 启动工作线程
        self.worker.start()

        # 启动托盘（子线程）—— build + run 在同一线程，符合 Windows 要求
        threading.Thread(target=self.tray.run, daemon=True).start()

        # 启动后台 API 健康检测
        threading.Thread(target=self._health_check_loop, daemon=True).start()

        log.info("C Helper 已启动，按 Ctrl+Alt+G 开始")
        # 主线程阻塞在 Listener（WH_KEYBOARD_LL 要求）
        self.hotkey.start()

    def _health_check_loop(self) -> None:
        """后台循环检测 API 状态，直到成功。"""
        while True:
            state = self.sm.state
            # 只在灰色(IDLE)或红色(ERROR)时执行检测，避免干扰业务
            if state not in (State.IDLE, State.ERROR):
                time.sleep(1)
                continue

            log.info("正在检测 API...")
            ok, msg = self.worker.ai.health_check()
            if ok:
                log.info("[OK] %s", msg)
                self.sm.transition(State.READY)
                break  # 成功退出循环，保持绿色就绪状态
            else:
                log.error("[FAIL] %s", msg)
                self.sm.transition(State.ERROR)
                log.info("10 秒后重新检测...")
                time.sleep(10)
                self.sm.transition(State.IDLE)  # 回到灰色重新检测


def main() -> None:
    try:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        App().run()
    except Exception as e:
        logging.getLogger("c_helper").error("Fatal error: %s", e, exc_info=True)
        input("\n[FATAL] Program crashed. Press Enter to exit...")
        raise


if __name__ == "__main__":
    main()
