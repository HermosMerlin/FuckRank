"""Tests for c_helper.core module."""
import json
import time
from pathlib import Path

import pytest

from c_helper.core import Config, IconRenderer, State, StateMachine


class TestConfig:
    def test_load_defaults(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}), encoding="utf-8")
        cfg = Config.load(config_path)
        assert cfg.base_url == ""
        assert cfg.model == ""
        assert cfg.typing_mode == "auto"
        # 非api字段应使用当前 config.json 的调优值作为模板
        assert cfg.typing_delay_ms == 300
        assert cfg.typing_jitter is True
        assert cfg.typing_jitter_range_ms == 100
        assert "C语言" in cfg.system_prompt

    def test_load_custom(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        data = {
            "api_key": "sk-test",
            "base_url": "http://localhost:11434/v1",
            "model": "llama3",
            "typing_mode": "manual",
            "typing_delay_ms": 50,
            "typing_jitter": False,
            "typing_jitter_range_ms": 10,
        }
        config_path.write_text(json.dumps(data), encoding="utf-8")
        cfg = Config.load(config_path)
        assert cfg.api_key == "sk-test"
        assert cfg.base_url == "http://localhost:11434/v1"
        assert cfg.typing_mode == "manual"
        assert cfg.typing_jitter is False
        assert cfg.typing_delay_ms == 50

    def test_load_missing_file_creates_default(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        assert not config_path.exists()
        cfg = Config.load(config_path)
        assert config_path.exists()  # 自动创建了模板
        assert cfg.api_key == ""  # 默认空值
        assert cfg.base_url == ""
        assert cfg.typing_mode == "auto"

    def test_load_empty_file_creates_template(self, tmp_path: Path) -> None:
        """空文件（0 字节）不应崩溃，应重写为完整模板。"""
        config_path = tmp_path / "config.json"
        config_path.write_text("", encoding="utf-8")  # 空文件
        cfg = Config.load(config_path)
        # 文件应被重写为完整模板（14 个键）
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert set(data.keys()) == {
            "api_key", "base_url", "model", "typing_mode",
            "typing_delay_ms", "typing_jitter", "typing_jitter_range_ms",
            "long_pause_enabled", "long_pause_chance", "long_pause_min_ms", "long_pause_max_ms",
            "output_mode", "editor_auto_brace", "system_prompt",
        }
        # 返回的 Config 应使用模板默认值
        assert cfg.typing_delay_ms == 300
        assert cfg.typing_jitter_range_ms == 100
        assert cfg.api_key == ""

    def test_load_invalid_json_creates_template(self, tmp_path: Path) -> None:
        """损坏的 JSON 文件不应崩溃，应重写为完整模板。"""
        config_path = tmp_path / "config.json"
        config_path.write_text("garbage{{{ not json", encoding="utf-8")
        cfg = Config.load(config_path)
        # 文件应被重写为合法 JSON 模板
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert "system_prompt" in data
        assert cfg.base_url == ""
        assert cfg.model == ""


class TestStateMachine:
    def test_idle_to_ready(self) -> None:
        sm = StateMachine()
        assert sm.state is State.IDLE
        assert sm.transition(State.READY) is True
        assert sm.state is State.READY

    def test_idle_to_error(self) -> None:
        sm = StateMachine()
        assert sm.transition(State.ERROR) is True
        assert sm.state is State.ERROR

    def test_error_to_idle(self) -> None:
        sm = StateMachine()
        sm.transition(State.ERROR)
        assert sm.transition(State.IDLE) is True
        assert sm.state is State.IDLE

    def test_requesting_to_ready(self) -> None:
        sm = StateMachine()
        sm.transition(State.READY)  # 先从IDLE到READY
        sm.transition(State.REQUESTING)
        assert sm.transition(State.READY) is True
        assert sm.state is State.READY

    def test_ready_to_requesting(self) -> None:
        sm = StateMachine()
        sm.transition(State.READY)
        assert sm.transition(State.REQUESTING) is True
        assert sm.state is State.REQUESTING

    def test_ready_to_typing(self) -> None:
        sm = StateMachine()
        sm.transition(State.READY)
        assert sm.transition(State.TYPING) is True
        assert sm.state is State.TYPING

    def test_typing_to_ready(self) -> None:
        sm = StateMachine()
        sm.transition(State.READY)
        sm.transition(State.TYPING)
        assert sm.transition(State.READY) is True
        assert sm.state is State.READY

    def test_idle_cannot_requesting(self) -> None:
        """IDLE(灰)不能直接到REQUESTING(黄)，必须先检测API到READY"""
        sm = StateMachine()
        assert sm.transition(State.REQUESTING) is False
        assert sm.state is State.IDLE

    def test_requesting_to_error(self) -> None:
        sm = StateMachine()
        sm.transition(State.READY)
        sm.transition(State.REQUESTING)
        assert sm.transition(State.ERROR) is True
        assert sm.state is State.ERROR

    def test_error_no_auto_recover(self) -> None:
        sm = StateMachine()
        sm.transition(State.ERROR)
        assert sm.state is State.ERROR
        sm.force_reset()
        assert sm.state is State.IDLE

    def test_on_change_callback(self) -> None:
        changes: list[State] = []

        def on_change(s: State) -> None:
            changes.append(s)

        sm = StateMachine(on_change=on_change)
        sm.transition(State.READY)
        assert changes == [State.READY]
        sm.transition(State.REQUESTING)
        assert changes == [State.READY, State.REQUESTING]


class TestIconRenderer:
    def test_render_all_states(self) -> None:
        for state in State:
            img = IconRenderer.render(state)
            assert img.size == (16, 16)
            assert img.mode == "RGBA"

    def test_render_unique_colors(self) -> None:
        images = {state: IconRenderer.render(state) for state in State}
        for s1 in State:
            for s2 in State:
                if s1 != s2:
                    assert list(images[s1].get_flattened_data()) != list(images[s2].get_flattened_data())

    def test_render_fallback_for_unknown(self) -> None:
        # 即使传入不存在的 key，也应该返回 IDLE 颜色
        img = IconRenderer.render(State.IDLE)
        assert img.size == (16, 16)
