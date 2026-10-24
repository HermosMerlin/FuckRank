"""
core.py — 状态机、托盘图标、配置加载
"""
from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str
    model: str
    typing_delay_ms: int
    typing_jitter: bool
    typing_jitter_range_ms: int
    long_pause_enabled: bool
    long_pause_chance: float
    long_pause_min_ms: int
    long_pause_max_ms: int
    output_mode: str
    editor_auto_brace: bool
    system_prompt: str
    typing_mode: str = "manual"

    _DEFAULT_CONFIG = {
        "api_key": "",
        "base_url": "",
        "model": "",
        "typing_delay_ms": 300,
        "typing_jitter": True,
        "typing_jitter_range_ms": 100,
        "long_pause_enabled": True,
        "long_pause_chance": 0.3,
        "long_pause_min_ms": 3000,
        "long_pause_max_ms": 12000,
        "output_mode": "optimized",
        "editor_auto_brace": True,
        "typing_mode": "manual",
        "system_prompt": (
            "你是一位C语言编程专家。用户会粘贴一道C语言题目，"
            "请直接给出完整、可编译的C语言代码作为答案。"
            "注意：代码中不要包含任何注释，不要包含解释说明，只输出纯代码。"
        ),
    }

    @classmethod
    def load(cls, path: Path | str = "config.json") -> "Config":
        p = Path(path)
        data: dict | None = None

        # 文件存在：尝试读取；空文件或损坏 JSON 稍后重写为模板
        if p.exists():
            try:
                with p.open("r", encoding="utf-8") as f:
                    raw = f.read()
                if raw.strip():
                    data = json.loads(raw)
            except json.JSONDecodeError as e:
                log.warning("配置文件 JSON 损坏，将重写为模板: %s (%s)", p, e)

        # 文件不存在、为空或损坏：自动生成默认配置模板
        if data is None:
            with p.open("w", encoding="utf-8") as f:
                json.dump(cls._DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
                f.write("\n")
            log.warning("已自动生成配置模板: %s", p.absolute())
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)

        return cls(
            api_key=data.get("api_key", ""),
            base_url=data.get("base_url", ""),
            model=data.get("model", ""),
            typing_delay_ms=data.get("typing_delay_ms", 300),
            typing_jitter=data.get("typing_jitter", True),
            typing_jitter_range_ms=data.get("typing_jitter_range_ms", 100),
            long_pause_enabled=data.get("long_pause_enabled", True),
            long_pause_chance=data.get("long_pause_chance", 0.3),
            long_pause_min_ms=data.get("long_pause_min_ms", 3000),
            long_pause_max_ms=data.get("long_pause_max_ms", 12000),
            output_mode=data.get("output_mode", "optimized"),
            editor_auto_brace=data.get("editor_auto_brace", True),
            typing_mode=data.get("typing_mode", "manual"),
            system_prompt=data.get(
                "system_prompt",
                cls._DEFAULT_CONFIG["system_prompt"],
            ),
        )


# ---------------------------------------------------------------------------
# 答案解析
# ---------------------------------------------------------------------------
class AnswerKind(Enum):
    CODE = auto()      # 代码题
    SINGLE = auto()    # 单选题
    BOOLEAN = auto()   # 判断题


@dataclass(frozen=True)
class Answer:
    """带类型的答案载体。text 为代码正文或规范化后的选项串。"""
    kind: AnswerKind
    text: str
    choices: tuple[str, ...] = ()
    value: bool | None = None


_MARKER_RE = re.compile(
    r"^\[\[\s*(CHOICE|MULTI|BOOL)\s*:\s*([^\]]*?)\s*\]\]",
    re.I,
)
_OPTION_LINE = re.compile(r"(?m)^\s*[A-DＡ-Ｄ]\s*[.．、):：）]")
_BOOL_OPTION = re.compile(
    r"(?m)^\s*[ABＡＢ]\s*[.．、):：）]\s*(正确|错误|对|错|true|false)",
    re.I,
)
_TRUE_VALUES = {"T", "TRUE", "对", "正确", "是", "√", "YES", "Y"}
_FALSE_VALUES = {"F", "FALSE", "错", "错误", "否", "×", "NO", "N"}


def _looks_like_boolean(text: str) -> bool:
    if "判断题" in text or "对错题" in text:
        return True
    return bool(_BOOL_OPTION.search(text))


def _looks_like_choice(text: str) -> bool:
    if len(_OPTION_LINE.findall(text)) >= 2:
        return True
    return any(keyword in text for keyword in ("单选题", "多选题", "选择题"))


def parse_answer(raw: str, question: str) -> Answer | None:
    """
    解析模型响应。

    - 首行标记合法 → 对应类型的 Answer。
    - 无标记且题目像选择题/判断题 → None（软失败，绝不打字）。
    - 无标记且题目不像选择题/判断题 → CODE，保持现有代码题行为。
    """
    if not raw or not raw.strip():
        return None

    lines = raw.splitlines()
    first = next((line.strip() for line in lines if line.strip()), "")
    if not first:
        return None

    # 可选 [[CODE]] 标记：剥离后按代码处理
    if first.startswith("[[CODE]]"):
        idx = raw.find("[[CODE]]")
        code = raw[idx + len("[[CODE]]"):].lstrip("\r\n")
        return Answer(AnswerKind.CODE, code) if code.strip() else None

    normalized_first = unicodedata.normalize("NFKC", first)
    if normalized_first.startswith("[[UNSUPPORTED]]"):
        return None
    match = _MARKER_RE.match(normalized_first)
    if match is None:
        if _looks_like_boolean(question) or _looks_like_choice(question):
            return None
        return Answer(AnswerKind.CODE, raw)

    marker = match.group(1).upper()
    payload = unicodedata.normalize("NFKC", match.group(2))

    if marker == "MULTI":
        # 多选已取消；即使只给一个字母也不支持
        return None

    if marker == "BOOL":
        value = payload.strip().upper().replace(" ", "")
        if value in _TRUE_VALUES:
            return Answer(AnswerKind.BOOLEAN, "正确", value=True)
        if value in _FALSE_VALUES:
            return Answer(AnswerKind.BOOLEAN, "错误", value=False)
        return None

    # CHOICE：只接受恰好一个 A–D 字母
    letters: list[str] = []
    for char in payload.upper():
        if "A" <= char <= "Z":
            if char not in "ABCD":
                return None
            if char not in letters:
                letters.append(char)
    if len(letters) != 1:
        return None

    text = letters[0]
    return Answer(AnswerKind.SINGLE, text, choices=(text,))


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------
class State(Enum):
    IDLE = auto()       # 空闲（灰色）
    REQUESTING = auto() # 请求中（黄色）
    READY = auto()      # 已就绪（绿色）
    TYPING = auto()     # 输出中（蓝色）
    ERROR = auto()      # 错误（红色）


class StateMachine:
    """
    线程安全的状态机（v3）。

    状态语义：
      IDLE(灰)    = 正在检测 API（启动或重试）
      REQUESTING(黄)= 正在向 AI 请求答案（业务请求）
      READY(绿)   = 系统就绪 / 答案已缓存
      TYPING(蓝)  = 正在输出答案
      ERROR(红)   = API 检测失败 / 请求失败

    流转规则：
      IDLE --(检测成功)--> READY
      IDLE --(检测失败)--> ERROR --(重试)--> IDLE
      READY --(热键)--> REQUESTING --(成功)--> READY
      READY --(热键,有缓存)--> TYPING --(完成)--> READY
      REQUESTING --(失败)--> ERROR --(重试)--> IDLE
      任意状态 --(强制重置)--> IDLE
    """

    _TRANSITIONS: dict[State, tuple[State, ...]] = {
        State.IDLE: (State.READY, State.ERROR),
        State.REQUESTING: (State.READY, State.ERROR),
        State.READY: (State.REQUESTING, State.TYPING),
        State.TYPING: (State.READY,),
        State.ERROR: (State.IDLE,),
    }

    def __init__(self, on_change: Callable[[State], None] | None = None):
        self._state = State.IDLE
        self._lock = threading.Lock()
        self._on_change = on_change

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    def transition(self, target: State) -> bool:
        """尝试状态转换，成功返回 True。"""
        with self._lock:
            allowed = self._TRANSITIONS.get(self._state, ())
            if target not in allowed:
                log.debug("无效转换: %s -> %s", self._state.name, target.name)
                return False
            self._state = target
            log.info("状态切换: %s", target.name)

        if self._on_change:
            self._on_change(target)

        return True

    def set_on_change(self, callback: Callable[[State], None] | None) -> None:
        self._on_change = callback

    def force_reset(self) -> None:
        """强制回到 IDLE（灰色，重新检测）。"""
        with self._lock:
            old = self._state
            self._state = State.IDLE
        log.info("强制重置: %s -> IDLE", old.name)
        if self._on_change:
            self._on_change(State.IDLE)


# ---------------------------------------------------------------------------
# 图标渲染器（Pillow 动态生成）
# ---------------------------------------------------------------------------
class IconRenderer:
    """
    托盘图标渲染器 — 伪装成云盘后台应用。

    设计：
      - 主体：固定浅灰蓝色云朵（像 OneDrive/坚果云）
      - 状态：右下角 5px 彩色圆点 + 白色描边，使用者能清晰辨识
      - 答案：READY + 单选题/判断题时，在云朵下部画同尺寸点，只变颜色；隐藏状态点
      - 第三者视角：只是一个普通的云同步后台图标
    """

    _CLOUD_COLOR = "#94A3B8"  # 浅灰蓝，类似常见云盘图标
    _ANSWER_SELECTED = "#22C55E"  # 选中点：亮绿，只变颜色不放大
    _ANSWER_SOCKET = "#475569"    # 空位：深石板灰，让亮绿选中点更明显
    _CHOICE_Y = 10
    _CHOICE_X = (1, 5, 9, 13)
    _CHOICE_SIZE = 3
    _BOOL_Y = 9
    _BOOL_X = (3, 8)
    _BOOL_SIZE = 5

    _DOT_PALETTE = {
        State.IDLE:       "#475569",  # 深灰 — 检测 API 中
        State.REQUESTING: "#D4A373",  # 暗沙金 — 请求中
        State.READY:      "#6BCB9F",  # 薄荷绿 — 就绪
        State.TYPING:     "#8D99AE",  # 灰蓝 — 输出中
        State.ERROR:      "#E07A5F",  # 砖红 — 错误
    }

    _SIZE = 16

    @classmethod
    def render(cls, state: State, answer: Answer | None = None) -> Image.Image:
        img = Image.new("RGBA", (cls._SIZE, cls._SIZE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        cls._draw_cloud(draw)

        if state is State.READY and answer is not None:
            if answer.kind is AnswerKind.SINGLE and answer.choices:
                cls._draw_single_choice_row(draw, answer.choices[0])
                return img
            if answer.kind is AnswerKind.BOOLEAN and answer.value is not None:
                cls._draw_boolean_row(draw, answer.value)
                return img

        cls._draw_status_dot(draw, state)
        return img

    @classmethod
    def _draw_cloud(cls, draw: ImageDraw.ImageDraw) -> None:
        """绘制云朵主体（3 个重叠圆模拟）。"""
        cloud = cls._CLOUD_COLOR
        # 底部宽椭圆
        draw.ellipse((1, 8, 15, 14), fill=cloud)
        # 左凸起
        draw.ellipse((2, 5, 8, 11), fill=cloud)
        # 右凸起
        draw.ellipse((6, 5, 12, 11), fill=cloud)
        # 顶部小凸起
        draw.ellipse((4, 3, 10, 9), fill=cloud)

    @classmethod
    def _draw_status_dot(cls, draw: ImageDraw.ImageDraw, state: State) -> None:
        """右下角状态圆点（带 1px 白色描边，增加辨识度）。"""
        dot_color = cls._DOT_PALETTE.get(state, cls._DOT_PALETTE[State.IDLE])
        cx, cy, r = 12, 12, 3
        # 白色描边
        draw.ellipse((cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1), fill="#FFFFFF")
        # 彩色圆点
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=dot_color)

    @classmethod
    def _draw_single_choice_row(cls, draw: ImageDraw.ImageDraw, selected: str) -> None:
        """单选题答案行：四个同尺寸点，只有选中的那个变亮绿色。"""
        selected = selected.upper()
        for key, x in zip("ABCD", cls._CHOICE_X):
            color = cls._ANSWER_SELECTED if key == selected else cls._ANSWER_SOCKET
            draw.rectangle(
                (
                    x,
                    cls._CHOICE_Y,
                    x + cls._CHOICE_SIZE - 1,
                    cls._CHOICE_Y + cls._CHOICE_SIZE - 1,
                ),
                fill=color,
            )

    @classmethod
    def _draw_boolean_row(cls, draw: ImageDraw.ImageDraw, value: bool) -> None:
        """判断题答案行：两个同尺寸点，左 = 正确，右 = 错误。"""
        left, right = cls._BOOL_X
        left_color = cls._ANSWER_SELECTED if value else cls._ANSWER_SOCKET
        right_color = cls._ANSWER_SOCKET if value else cls._ANSWER_SELECTED
        for x, color in ((left, left_color), (right, right_color)):
            draw.rectangle(
                (
                    x,
                    cls._BOOL_Y,
                    x + cls._BOOL_SIZE - 1,
                    cls._BOOL_Y + cls._BOOL_SIZE - 1,
                ),
                fill=color,
            )
