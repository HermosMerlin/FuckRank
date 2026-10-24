"""Tests for c_helper.core module."""
import json
import time
from pathlib import Path

import pytest

from c_helper.core import (
    Answer,
    AnswerKind,
    Config,
    IconRenderer,
    State,
    StateMachine,
    parse_answer,
)


class TestConfig:
    def test_load_defaults(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}), encoding="utf-8")
        cfg = Config.load(config_path)
        assert cfg.base_url == ""
        assert cfg.model == ""
        assert cfg.typing_mode == "manual"
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
            "typing_mode": "auto",
            "typing_delay_ms": 50,
            "typing_jitter": False,
            "typing_jitter_range_ms": 10,
        }
        config_path.write_text(json.dumps(data), encoding="utf-8")
        cfg = Config.load(config_path)
        assert cfg.api_key == "sk-test"
        assert cfg.base_url == "http://localhost:11434/v1"
        assert cfg.typing_mode == "auto"
        assert cfg.typing_jitter is False
        assert cfg.typing_delay_ms == 50

    def test_load_missing_file_creates_default(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        assert not config_path.exists()
        cfg = Config.load(config_path)
        assert config_path.exists()  # 自动创建了模板
        assert cfg.api_key == ""  # 默认空值
        assert cfg.base_url == ""
        assert cfg.typing_mode == "manual"

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


class TestParseAnswer:
    def test_code_without_marker(self) -> None:
        raw = "int main() { return 0; }"
        answer = parse_answer(raw, "写一个C程序")
        assert answer is not None
        assert answer.kind is AnswerKind.CODE
        assert answer.text == raw

    def test_choice_single(self) -> None:
        answer = parse_answer("[[CHOICE:A]]", "以下说法正确的是")
        assert answer is not None
        assert answer.kind is AnswerKind.SINGLE
        assert answer.text == "A"
        assert answer.choices == ("A",)

    def test_choice_trailing_text_is_ignored(self) -> None:
        answer = parse_answer("[[CHOICE:B]] 因为选项 B 正确", "单选题")
        assert answer is not None
        assert answer.kind is AnswerKind.SINGLE
        assert answer.text == "B"

    @pytest.mark.parametrize(
        "raw",
        [
            "[[MULTI:AC]]",
            "[[MULTI:A]]",
            "[[MULTI:A,C]]",
            "[[MULTI:A、C]]",
            "[[ＭＵＬＴＩ：ＡＣ]]",
            "［［ＭＵＬＴＩ：ＡＣ］］",
            "[[CHOICE:AC]]",
            "[[CHOICE:AB]]",
        ],
    )
    def test_multi_is_unsupported(self, raw: str) -> None:
        assert parse_answer(raw, "多选题") is None

    def test_full_width_single_choice(self) -> None:
        answer = parse_answer("［［ＣＨＯＩＣＥ：Ａ］］", "单选题")
        assert answer is not None
        assert answer.kind is AnswerKind.SINGLE
        assert answer.text == "A"

    def test_lowercase_single_choice(self) -> None:
        answer = parse_answer("[[choice:b]]", "单选题")
        assert answer is not None
        assert answer.kind is AnswerKind.SINGLE
        assert answer.text == "B"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("[[BOOL:T]]", True),
            ("[[BOOL:TRUE]]", True),
            ("[[BOOL:正确]]", True),
            ("[[BOOL:√]]", True),
            ("[[BOOL:F]]", False),
            ("[[BOOL:FALSE]]", False),
            ("[[BOOL:错误]]", False),
            ("[[BOOL:×]]", False),
        ],
    )
    def test_boolean_variants(self, raw: str, expected: bool) -> None:
        answer = parse_answer(raw, "判断题")
        assert answer is not None
        assert answer.kind is AnswerKind.BOOLEAN
        assert answer.value is expected
        assert answer.text == ("正确" if expected else "错误")

    @pytest.mark.parametrize(
        "raw",
        [
            "[[CHOICE:E]]",
            "[[MULTI:AE]]",
            "[[CHOICE:]]",
            "[[BOOL:maybe]]",
            "[[UNSUPPORTED]]",
        ],
    )
    def test_invalid_payload_returns_none(self, raw: str) -> None:
        assert parse_answer(raw, "题目") is None

    def test_no_marker_choice_like_returns_none(self) -> None:
        question = "单选题\nA. 1\nB. 2\nC. 3\nD. 4"
        assert parse_answer("答案是 A", question) is None

    def test_no_marker_boolean_like_returns_none(self) -> None:
        question = "判断题：1+1=2"
        assert parse_answer("正确", question) is None

    def test_marker_on_later_line_is_treated_as_no_marker(self) -> None:
        question = "单选题\nA. 1\nB. 2\nC. 3\nD. 4"
        assert parse_answer("答案：\n[[CHOICE:A]]", question) is None

    def test_code_marker_is_stripped(self) -> None:
        raw = "[[CODE]]\nint main() { return 0; }"
        answer = parse_answer(raw, "写一个C程序")
        assert answer is not None
        assert answer.kind is AnswerKind.CODE
        assert answer.text == "int main() { return 0; }"

    def test_empty_response_returns_none(self) -> None:
        assert parse_answer("   ", "题目") is None


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


class TestIconRendererAnswerRow:
    SELECTED = (0x22, 0xC5, 0x5E)
    SOCKET = (0x47, 0x55, 0x69)
    CLOUD = (0x94, 0xA3, 0xB8)
    XS = (("A", 1), ("B", 5), ("C", 9), ("D", 13))

    @pytest.mark.parametrize("key,x", XS)
    def test_single_choice_positions(self, key: str, x: int) -> None:
        img = IconRenderer.render(
            State.READY,
            Answer(AnswerKind.SINGLE, key, choices=(key,)),
        )
        assert img.getpixel((x, 10))[:3] == self.SELECTED
        for other_key, other_x in self.XS:
            if other_key != key:
                assert img.getpixel((other_x, 10))[:3] == self.SOCKET

    def test_choice_dots_are_same_size(self) -> None:
        img = IconRenderer.render(
            State.READY,
            Answer(AnswerKind.SINGLE, "A", choices=("A",)),
        )
        for y in range(10, 13):
            for x in range(1, 4):
                assert img.getpixel((x, y))[:3] == self.SELECTED
            for x in range(5, 8):
                assert img.getpixel((x, y))[:3] == self.SOCKET

    def test_boolean_true_left_lit(self) -> None:
        img = IconRenderer.render(
            State.READY,
            Answer(AnswerKind.BOOLEAN, "正确", value=True),
        )
        assert img.getpixel((3, 9))[:3] == self.SELECTED
        assert img.getpixel((8, 9))[:3] == self.SOCKET

    def test_boolean_false_right_lit(self) -> None:
        img = IconRenderer.render(
            State.READY,
            Answer(AnswerKind.BOOLEAN, "错误", value=False),
        )
        assert img.getpixel((3, 9))[:3] == self.SOCKET
        assert img.getpixel((8, 9))[:3] == self.SELECTED

    def test_boolean_dots_are_same_size(self) -> None:
        img = IconRenderer.render(
            State.READY,
            Answer(AnswerKind.BOOLEAN, "正确", value=True),
        )
        for y in range(9, 14):
            for x in range(3, 8):
                assert img.getpixel((x, y))[:3] == self.SELECTED
            for x in range(8, 13):
                assert img.getpixel((x, y))[:3] == self.SOCKET

    def test_code_answer_keeps_status_dot(self) -> None:
        img = IconRenderer.render(
            State.READY,
            Answer(AnswerKind.CODE, "int main() {}"),
        )
        assert img.getpixel((1, 10))[:3] == self.CLOUD
        assert img.getpixel((12, 12))[:3] == (0x6B, 0xCB, 0x9F)

    def test_answer_row_only_in_ready(self) -> None:
        img = IconRenderer.render(
            State.REQUESTING,
            Answer(AnswerKind.SINGLE, "A", choices=("A",)),
        )
        assert img.getpixel((1, 10))[:3] == self.CLOUD
        assert img.getpixel((12, 12))[:3] == (0xD4, 0xA3, 0x73)

    def test_four_single_choices_are_unique(self) -> None:
        images = {
            IconRenderer.render(
                State.READY,
                Answer(AnswerKind.SINGLE, key, choices=(key,)),
            ).tobytes()
            for key in "ABCD"
        }
        assert len(images) == 4
