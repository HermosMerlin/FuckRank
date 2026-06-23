"""Integration tests for c_helper.main module."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from c_helper.core import Config, State
from c_helper.main import AIClient, App, HotkeyManager, TrayManager, Typer, Worker


class TestAIClient:
    @patch("c_helper.main.requests.Session")
    def test_ask_success(self, mock_session_cls) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "  int main() {}  "}}]
        }
        mock_session.post.return_value = mock_resp

        config = Config(
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
            typing_delay_ms=80,
            typing_jitter=True,
            typing_jitter_range_ms=20,
            long_pause_enabled=False,
            long_pause_chance=0.0,
            long_pause_min_ms=3000,
            long_pause_max_ms=12000,
            output_mode="optimized",
            editor_auto_brace=False,
            system_prompt="test",
        )
        client = AIClient(config)
        result = client.ask("hello")
        assert result == "int main() {}"
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        assert call_args[1]["json"]["model"] == "gpt-4"
        assert call_args[1]["timeout"] == (5, 60)

    @patch("c_helper.main.requests.Session")
    def test_ask_empty_choices(self, mock_session_cls) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": []}
        mock_session.post.return_value = mock_resp

        config = Config(
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
            typing_delay_ms=80,
            typing_jitter=True,
            typing_jitter_range_ms=20,
            long_pause_enabled=False,
            long_pause_chance=0.0,
            long_pause_min_ms=3000,
            long_pause_max_ms=12000,
            output_mode="optimized",
            editor_auto_brace=False,
            system_prompt="test",
        )
        client = AIClient(config)
        with pytest.raises(ValueError, match="空 choices"):
            client.ask("hello")


class TestTyper:
    @patch("c_helper.main._get_foreground_layout")
    @patch("c_helper.main._set_foreground_layout")
    @patch("c_helper.main.Controller")
    def test_type_text(self, mock_controller_cls, mock_set, mock_get) -> None:
        mock_get.return_value = 0x04090409  # 已经是英文布局
        mock_controller = MagicMock()
        mock_controller_cls.return_value = mock_controller

        config = Config(
            api_key="",
            base_url="",
            model="",
            typing_delay_ms=10,
            typing_jitter=False,
            typing_jitter_range_ms=0,
            long_pause_enabled=False,
            long_pause_chance=0.0,
            long_pause_min_ms=3000,
            long_pause_max_ms=12000,
            output_mode="optimized",
            editor_auto_brace=False,
            system_prompt="",
        )
        typer = Typer(config)
        typer.type_text("ab")
        assert mock_controller.type.call_count == 2
        mock_controller.type.assert_any_call("a")
        mock_controller.type.assert_any_call("b")

    @patch("c_helper.main._get_foreground_layout")
    @patch("c_helper.main._set_foreground_layout")
    @patch("c_helper.main.Controller")
    def test_type_text_switches_layout(self, mock_controller_cls, mock_set, mock_get) -> None:
        mock_get.return_value = 0x08040804  # 非英文布局
        mock_controller = MagicMock()
        mock_controller_cls.return_value = mock_controller

        config = Config(
            api_key="",
            base_url="",
            model="",
            typing_delay_ms=10,
            typing_jitter=False,
            typing_jitter_range_ms=0,
            long_pause_enabled=False,
            long_pause_chance=0.0,
            long_pause_min_ms=3000,
            long_pause_max_ms=12000,
            output_mode="optimized",
            editor_auto_brace=False,
            system_prompt="",
        )
        typer = Typer(config)
        typer.type_text("x")
        # 应该切换布局两次：开始切到英文，结束恢复
        assert mock_set.call_count == 2
        mock_set.assert_any_call(0x04090409)


class TestWorker:
    @patch("c_helper.main.safe_paste")
    @patch("c_helper.main.AIClient")
    @patch.object(TrayManager, "set_state")
    def test_do_request_success(self, mock_set_state, mock_ai_cls, mock_paste) -> None:
        config = Config(
            api_key="sk",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
            typing_delay_ms=80,
            typing_jitter=True,
            typing_jitter_range_ms=20,
            long_pause_enabled=False,
            long_pause_chance=0.0,
            long_pause_min_ms=3000,
            long_pause_max_ms=12000,
            output_mode="optimized",
            editor_auto_brace=False,
            system_prompt="test",
        )
        sm = MagicMock()
        sm.state = State.IDLE
        sm.transition.return_value = True
        tray = TrayManager(on_reset=lambda: None, on_quit=lambda: None)
        worker = Worker(config, sm, tray)

        mock_paste.return_value = "题目内容"
        mock_ai = MagicMock()
        mock_ai.ask.return_value = "int main() {}"
        mock_ai_cls.return_value = mock_ai
        worker.ai = mock_ai

        worker._do_request()
        mock_paste.assert_called_once()
        mock_ai.ask.assert_called_once_with("题目内容")
        assert worker._cached_answer == "int main() {}"
        assert sm.transition.call_count >= 2  # REQUESTING + READY

    @patch("c_helper.main.safe_paste")
    @patch.object(TrayManager, "set_state")
    def test_do_request_empty_clipboard(self, mock_set_state, mock_paste) -> None:
        config = Config(
            api_key="sk",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
            typing_delay_ms=80,
            typing_jitter=True,
            typing_jitter_range_ms=20,
            long_pause_enabled=False,
            long_pause_chance=0.0,
            long_pause_min_ms=3000,
            long_pause_max_ms=12000,
            output_mode="optimized",
            editor_auto_brace=False,
            system_prompt="test",
        )
        sm = MagicMock()
        sm.state = State.IDLE
        sm.transition.return_value = True
        tray = TrayManager(on_reset=lambda: None, on_quit=lambda: None)
        worker = Worker(config, sm, tray)

        mock_paste.return_value = "   "
        worker._do_request()
        assert worker._cached_answer == ""
        sm.transition.assert_any_call(State.ERROR)

    @patch("c_helper.main.time.sleep")
    @patch("c_helper.main.Typer")
    @patch.object(TrayManager, "set_state")
    def test_do_type(self, mock_set_state, mock_typer_cls, mock_sleep) -> None:
        config = Config(
            api_key="sk",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
            typing_delay_ms=80,
            typing_jitter=True,
            typing_jitter_range_ms=20,
            long_pause_enabled=False,
            long_pause_chance=0.0,
            long_pause_min_ms=3000,
            long_pause_max_ms=12000,
            output_mode="optimized",
            editor_auto_brace=False,
            system_prompt="test",
        )
        sm = MagicMock()
        sm.transition.return_value = True
        tray = TrayManager(on_reset=lambda: None, on_quit=lambda: None)
        worker = Worker(config, sm, tray)
        worker._cached_answer = "printf('hello');"

        mock_typer = MagicMock()
        mock_typer_cls.return_value = mock_typer
        worker.typer = mock_typer

        worker._do_type()
        mock_typer.type_text.assert_called_once_with("printf('hello');")
        assert worker._cached_answer == ""
        sm.transition.assert_called_with(State.READY)


class TestAppInitialization:
    @patch("c_helper.main.Config.load")
    @patch("c_helper.main.TrayManager.build")
    @patch("c_helper.main.Worker.start")
    def test_app_init(self, mock_worker_start, mock_tray_build, mock_config_load) -> None:
        mock_config = Config(
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
            typing_delay_ms=80,
            typing_jitter=True,
            typing_jitter_range_ms=20,
            long_pause_enabled=False,
            long_pause_chance=0.0,
            long_pause_min_ms=3000,
            long_pause_max_ms=12000,
            output_mode="optimized",
            editor_auto_brace=False,
            system_prompt="test",
        )
        mock_config_load.return_value = mock_config

        app = App("config.json")
        assert app.config.api_key == "sk-test"
        assert app.sm.state == State.IDLE


class TestTypeTextAdvanced:
    @patch("c_helper.main._get_foreground_layout")
    @patch("c_helper.main._set_foreground_layout")
    @patch("c_helper.main.Controller")
    def test_type_text_zero_indent_optimized(self, mock_controller_cls, mock_set, mock_get) -> None:
        """optimized 模式下 type_text 应去掉每行前导空格"""
        mock_get.return_value = 0x04090409
        mock_controller = MagicMock()
        mock_controller_cls.return_value = mock_controller

        config = Config(
            api_key="", base_url="", model="",
            typing_delay_ms=10, typing_jitter=False,
            typing_jitter_range_ms=0,
            long_pause_enabled=False, long_pause_chance=0.0,
            long_pause_min_ms=3000, long_pause_max_ms=12000,
            output_mode="optimized", editor_auto_brace=False,
            system_prompt="",
        )
        typer = Typer(config)
        typer.type_text("    int a;\n        int b;")
        # 不应输出前导空格（空格会被 lstrip 掉）
        calls = [c[0][0] for c in mock_controller.type.call_args_list]
        # 检查 "int a;" 的字符序列存在（不检查连续，因为可能分散在多个调用中）
        assert "i" in calls
        assert "n" in calls
        assert "t" in calls
        # 不应有大量前导空格调用
        space_count = calls.count(" ")
        assert space_count < 4  # 最多几个单词间空格，不应有4个连续缩进空格
        # 检查 "int b;" 的字符也存在
        assert "b" in calls

    @patch("c_helper.main._get_foreground_layout")
    @patch("c_helper.main._set_foreground_layout")
    @patch("c_helper.main.Controller")
    def test_type_text_preserves_indent_raw(self, mock_controller_cls, mock_set, mock_get) -> None:
        """raw 模式下 type_text 应保留前导空格"""
        mock_get.return_value = 0x04090409
        mock_controller = MagicMock()
        mock_controller_cls.return_value = mock_controller

        config = Config(
            api_key="", base_url="", model="",
            typing_delay_ms=10, typing_jitter=False,
            typing_jitter_range_ms=0,
            long_pause_enabled=False, long_pause_chance=0.0,
            long_pause_min_ms=3000, long_pause_max_ms=12000,
            output_mode="raw", editor_auto_brace=False,
            system_prompt="",
        )
        typer = Typer(config)
        typer.type_text("    int a;")
        calls = [c[0][0] for c in mock_controller.type.call_args_list]
        # raw 模式下保留空格，应有 4 个空格字符调用
        assert calls.count(" ") >= 4

    @patch("c_helper.main._get_foreground_layout")
    @patch("c_helper.main._set_foreground_layout")
    @patch("c_helper.main.Controller")
    def test_type_text_auto_brace(self, mock_controller_cls, mock_set, mock_get) -> None:
        """editor_auto_brace=True 时，输出 { 后应发送 End + Backspace"""
        mock_get.return_value = 0x04090409
        mock_controller = MagicMock()
        mock_controller_cls.return_value = mock_controller

        config = Config(
            api_key="", base_url="", model="",
            typing_delay_ms=10, typing_jitter=False,
            typing_jitter_range_ms=0,
            long_pause_enabled=False, long_pause_chance=0.0,
            long_pause_min_ms=3000, long_pause_max_ms=12000,
            output_mode="optimized", editor_auto_brace=True,
            system_prompt="",
        )
        typer = Typer(config)
        typer.type_text("if (1) {\n    int a;\n}")

        # 验证 press/release Key.end 被调用
        from pynput.keyboard import Key
        mock_controller.press.assert_any_call(Key.end)
        mock_controller.release.assert_any_call(Key.end)
        mock_controller.press.assert_any_call(Key.backspace)
        mock_controller.release.assert_any_call(Key.backspace)

    @patch("c_helper.main._get_foreground_layout")
    @patch("c_helper.main._set_foreground_layout")
    @patch("c_helper.main.Controller")
    def test_type_text_no_auto_brace(self, mock_controller_cls, mock_set, mock_get) -> None:
        """editor_auto_brace=False 时，不应发送 End + Backspace"""
        mock_get.return_value = 0x04090409
        mock_controller = MagicMock()
        mock_controller_cls.return_value = mock_controller

        config = Config(
            api_key="", base_url="", model="",
            typing_delay_ms=10, typing_jitter=False,
            typing_jitter_range_ms=0,
            long_pause_enabled=False, long_pause_chance=0.0,
            long_pause_min_ms=3000, long_pause_max_ms=12000,
            output_mode="optimized", editor_auto_brace=False,
            system_prompt="",
        )
        typer = Typer(config)
        typer.type_text("if (1) {\n    int a;\n}")

        from pynput.keyboard import Key
        # 不应调用 Key.end 或 Key.backspace
        for call in mock_controller.press.call_args_list:
            assert call[0][0] != Key.end
        for call in mock_controller.release.call_args_list:
            assert call[0][0] != Key.backspace
    def test_sanitize_removes_markdown_fence(self) -> None:
        raw = "```c\nint main() {}\n```"
        assert AIClient._sanitize(raw) == "int main() {}"

    def test_sanitize_fixes_extra_braces(self) -> None:
        """末尾有多余大括号时自动去掉，只保留平衡的闭合"""
        raw = """#include <stdio.h>

int main() {
        int a = 1;
        return 0;
}
}
}"""
        result = AIClient._sanitize(raw)
        assert result.count("{") == result.count("}")
        assert result.endswith("}")
        # 末尾不应残留多余大括号
        lines = result.splitlines()
        assert lines[-1].strip() == "}"
        assert lines[-2].strip() == "return 0;"

    def test_sanitize_preserves_indent(self) -> None:
        """_sanitize 只负责去围栏和平衡大括号，不处理缩进"""
        raw = "int main() {\n        int a;\n        if (1) {\n                int b;\n        }\n}"
        result = AIClient._sanitize(raw)
        lines = result.splitlines()
        # 缩进保持不变（由 type_text 在输出时处理）
        assert lines[1] == "        int a;"
        assert lines[3] == "                int b;"


class TestTyperTypeChar:
    @patch("c_helper.main.Controller")
    def test_type_char_single(self, mock_controller_cls) -> None:
        mock_controller = MagicMock()
        mock_controller_cls.return_value = mock_controller
        config = Config(
            api_key="", base_url="", model="",
            typing_delay_ms=10, typing_jitter=False,
            typing_jitter_range_ms=0,
            long_pause_enabled=False, long_pause_chance=0.0,
            long_pause_min_ms=3000, long_pause_max_ms=12000,
            output_mode="optimized", editor_auto_brace=False,
            system_prompt="",
            typing_mode="auto",
        )
        typer = Typer(config)
        typer.type_char("a")
        mock_controller.type.assert_called_once_with("a")

    @patch("c_helper.main.Controller")
    def test_type_char_auto_brace(self, mock_controller_cls) -> None:
        mock_controller = MagicMock()
        mock_controller_cls.return_value = mock_controller
        config = Config(
            api_key="", base_url="", model="",
            typing_delay_ms=10, typing_jitter=False,
            typing_jitter_range_ms=0,
            long_pause_enabled=False, long_pause_chance=0.0,
            long_pause_min_ms=3000, long_pause_max_ms=12000,
            output_mode="optimized", editor_auto_brace=True,
            system_prompt="",
            typing_mode="auto",
        )
        typer = Typer(config)
        typer.type_char("{")
        mock_controller.type.assert_called_once_with("{")
        from pynput.keyboard import Key
        mock_controller.press.assert_any_call(Key.end)
        mock_controller.release.assert_any_call(Key.end)
        mock_controller.press.assert_any_call(Key.backspace)
        mock_controller.release.assert_any_call(Key.backspace)

    @patch("c_helper.main.Controller")
    def test_type_char_no_delay(self, mock_controller_cls) -> None:
        mock_controller = MagicMock()
        mock_controller_cls.return_value = mock_controller
        config = Config(
            api_key="", base_url="", model="",
            typing_delay_ms=10, typing_jitter=False,
            typing_jitter_range_ms=0,
            long_pause_enabled=False, long_pause_chance=0.0,
            long_pause_min_ms=3000, long_pause_max_ms=12000,
            output_mode="optimized", editor_auto_brace=False,
            system_prompt="",
            typing_mode="auto",
        )
        typer = Typer(config)
        with patch("c_helper.main.time.sleep") as mock_sleep:
            typer.type_char("a")
            mock_sleep.assert_not_called()


class TestWorkerManualMode:
    def test_handle_hotkey_manual_starts_session(self) -> None:
        config = Config(
            api_key="sk", base_url="https://api.openai.com/v1", model="gpt-4",
            typing_delay_ms=80, typing_jitter=True, typing_jitter_range_ms=20,
            long_pause_enabled=False, long_pause_chance=0.0,
            long_pause_min_ms=3000, long_pause_max_ms=12000,
            output_mode="optimized", editor_auto_brace=False,
            system_prompt="test", typing_mode="manual",
        )
        sm = MagicMock()
        sm.state = State.READY
        sm.transition.return_value = True
        tray = TrayManager(on_reset=lambda: None, on_quit=lambda: None)
        worker = Worker(config, sm, tray)
        worker._cached_answer = "abc"

        worker.handle_hotkey()

        sm.transition.assert_called_with(State.TYPING)
        assert worker._manual_active is True
        assert worker._manual_answer == "abc"
        assert worker._manual_idx == 0

    def test_type_next_char_advances_and_exhausts(self) -> None:
        config = Config(
            api_key="sk", base_url="https://api.openai.com/v1", model="gpt-4",
            typing_delay_ms=80, typing_jitter=True, typing_jitter_range_ms=20,
            long_pause_enabled=False, long_pause_chance=0.0,
            long_pause_min_ms=3000, long_pause_max_ms=12000,
            output_mode="optimized", editor_auto_brace=False,
            system_prompt="test", typing_mode="manual",
        )
        sm = MagicMock()
        tray = TrayManager(on_reset=lambda: None, on_quit=lambda: None)
        worker = Worker(config, sm, tray)
        worker._manual_active = True
        worker._manual_answer = "abc"
        worker._manual_idx = 0
        worker._cached_answer = "abc"

        with patch.object(worker.typer, "type_char") as mock_type_char:
            worker._type_next_char()
            assert worker._manual_idx == 1
            mock_type_char.assert_called_with("a")

            worker._type_next_char()
            assert worker._manual_idx == 2
            mock_type_char.assert_called_with("b")

            worker._type_next_char()
            mock_type_char.assert_called_with("c")

            # auto-terminate resets state
            assert worker._manual_active is False
            assert worker._manual_answer == ""
            assert worker._cached_answer == ""
            assert worker._manual_idx == 0
            sm.transition.assert_called_with(State.READY)

    def test_type_next_char_fast_typing(self) -> None:
        config = Config(
            api_key="sk", base_url="https://api.openai.com/v1", model="gpt-4",
            typing_delay_ms=80, typing_jitter=True, typing_jitter_range_ms=20,
            long_pause_enabled=False, long_pause_chance=0.0,
            long_pause_min_ms=3000, long_pause_max_ms=12000,
            output_mode="optimized", editor_auto_brace=False,
            system_prompt="test", typing_mode="manual",
        )
        sm = MagicMock()
        tray = TrayManager(on_reset=lambda: None, on_quit=lambda: None)
        worker = Worker(config, sm, tray)
        worker._manual_active = True
        worker._manual_answer = "abc"
        worker._manual_idx = 0
        worker._cached_answer = "abc"

        with patch.object(worker.typer, "type_char") as mock_type_char:
            worker._type_next_char()
            worker._type_next_char()
            worker._type_next_char()

            assert mock_type_char.call_count == 3
            mock_type_char.assert_any_call("a")
            mock_type_char.assert_any_call("b")
            mock_type_char.assert_any_call("c")
            assert worker._manual_active is False
            assert worker._manual_idx == 0

    def test_handle_hotkey_auto_mode_unchanged(self) -> None:
        config = Config(
            api_key="sk", base_url="https://api.openai.com/v1", model="gpt-4",
            typing_delay_ms=80, typing_jitter=True, typing_jitter_range_ms=20,
            long_pause_enabled=False, long_pause_chance=0.0,
            long_pause_min_ms=3000, long_pause_max_ms=12000,
            output_mode="optimized", editor_auto_brace=False,
            system_prompt="test", typing_mode="auto",
        )
        sm = MagicMock()
        sm.state = State.READY
        sm.transition.return_value = True
        tray = TrayManager(on_reset=lambda: None, on_quit=lambda: None)
        worker = Worker(config, sm, tray)
        worker._cached_answer = "abc"

        with patch.object(worker, "_do_type") as mock_do_type:
            worker.handle_hotkey()
            mock_do_type.assert_called_once()
            assert worker._manual_active is False


class TestHotkeyManagerEventFilter:
    def _make_manager(self, typing_mode="manual", state=State.TYPING):
        config = Config(
            api_key="sk", base_url="https://api.openai.com/v1", model="gpt-4",
            typing_delay_ms=80, typing_jitter=True, typing_jitter_range_ms=20,
            long_pause_enabled=False, long_pause_chance=0.0,
            long_pause_min_ms=3000, long_pause_max_ms=12000,
            output_mode="optimized", editor_auto_brace=False,
            system_prompt="test", typing_mode=typing_mode,
        )
        sm = MagicMock()
        sm.state = state
        tray = TrayManager(on_reset=lambda: None, on_quit=lambda: None)
        worker = Worker(config, sm, tray)
        hm = HotkeyManager(worker, tray)
        hm._listener = MagicMock()
        return hm

    def test_filter_suppresses_az_in_manual_typing(self) -> None:
        hm = self._make_manager()
        data = SimpleNamespace(vkCode=0x41, flags=0, scanCode=0, time=0, dwExtraInfo=0)
        with patch.object(hm.worker, "submit") as mock_submit:
            result = hm._event_filter(256, data)
            mock_submit.assert_called_once_with(hm.worker._type_next_char)
            hm._listener.suppress_event.assert_called_once()
            assert result is None

    def test_filter_esc_terminates(self) -> None:
        hm = self._make_manager()
        data = SimpleNamespace(vkCode=0x1B, flags=0, scanCode=0, time=0, dwExtraInfo=0)
        with patch.object(hm.worker, "submit") as mock_submit:
            result = hm._event_filter(256, data)
            mock_submit.assert_called_once_with(hm.worker._terminate_manual)
            hm._listener.suppress_event.assert_called_once()
            assert result is None

    def test_filter_enter_passes_through(self) -> None:
        hm = self._make_manager()
        data = SimpleNamespace(vkCode=0x0D, flags=0, scanCode=0, time=0, dwExtraInfo=0)
        with patch.object(hm.worker, "submit") as mock_submit:
            result = hm._event_filter(256, data)
            mock_submit.assert_not_called()
            hm._listener.suppress_event.assert_not_called()
            assert result is None

    def test_filter_other_keys_pass_through(self) -> None:
        hm = self._make_manager()
        for vk in (0x08, 0x27):
            data = SimpleNamespace(vkCode=vk, flags=0, scanCode=0, time=0, dwExtraInfo=0)
            with patch.object(hm.worker, "submit") as mock_submit:
                result = hm._event_filter(256, data)
                mock_submit.assert_not_called()
                hm._listener.suppress_event.assert_not_called()
                assert result is None

    def test_filter_skips_injected(self) -> None:
        hm = self._make_manager()
        data = SimpleNamespace(vkCode=0x41, flags=0x10, scanCode=0, time=0, dwExtraInfo=0)
        with patch.object(hm.worker, "submit") as mock_submit:
            result = hm._event_filter(256, data)
            mock_submit.assert_not_called()
            hm._listener.suppress_event.assert_not_called()
            assert result is None

    def test_filter_noop_in_auto_mode(self) -> None:
        hm = self._make_manager(typing_mode="auto", state=State.TYPING)
        data = SimpleNamespace(vkCode=0x41, flags=0, scanCode=0, time=0, dwExtraInfo=0)
        with patch.object(hm.worker, "submit") as mock_submit:
            result = hm._event_filter(256, data)
            mock_submit.assert_not_called()
            hm._listener.suppress_event.assert_not_called()
            assert result is None

    def test_filter_noop_when_not_typing(self) -> None:
        hm = self._make_manager(typing_mode="manual", state=State.READY)
        data = SimpleNamespace(vkCode=0x41, flags=0, scanCode=0, time=0, dwExtraInfo=0)
        with patch.object(hm.worker, "submit") as mock_submit:
            result = hm._event_filter(256, data)
            mock_submit.assert_not_called()
            hm._listener.suppress_event.assert_not_called()
            assert result is None

    def test_win32_event_filter_kwarg_is_required(self) -> None:
        """回归：pynput 在 Windows 上要求 event_filter 使用 win32_ 前缀。

        不带前缀的 event_filter kwarg 会被 _base.Listener.__init__ 静默丢弃
        （只保留以 win32_ 开头的 kwargs 到 _options），导致 _event_filter
        永远是默认 lambda，event_filter 回调从不被调用，按键抑制完全失效。
        """
        from pynput.keyboard import Listener

        def custom_filter(msg, data):
            return None

        # 带前缀：自定义 filter 被正确存储
        l = Listener(on_press=lambda k: None, win32_event_filter=custom_filter)
        assert l._event_filter is custom_filter

        # 不带前缀：被静默丢弃，_event_filter 是默认 lambda
        l2 = Listener(on_press=lambda k: None, event_filter=custom_filter)
        assert l2._event_filter is not custom_filter
        assert "event_filter" not in l2._options
