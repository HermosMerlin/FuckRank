# 单选题 / 判断题托盘答案（Phase 1）

Status: 已实现（V7）；真机 DPI、真实模型与“多选题软失败”验收待跑。
Related: [CONTEXT.md](../../CONTEXT.md), [ADR 0001](../adr/0001-tray-answer-dot-row.md), [ADR 0002](../adr/0002-choice-answers-are-advisory.md), [ADR 0003](../adr/0003-typed-answer-protocol.md).

图例：[tray-answer-v3b.png](../prototypes/tray-answer-v3b.png)

## 1. 目标与非目标

### 目标

- 识别单选题和判断题，并把答案显示在托盘图标上。
- 图标保持云朵主体、灰蓝色、16px 和小面积彩色；不使用字母。
- 单选题/判断题只显示，不自动点选、不提交、不把答案打进编辑器。
- 代码题行为完全不变。
- 模型输出不守格式时安全失败：不打字、不显示错误图案、可重试。

### 非目标

- 多选题（Phase 1 取消；遇到时软失败）。
- 5 个及以上选项（A–E / A–F）。
- 填空题、简答题、组合题。
- 自动点击、自动选中、自动提交。
- “复制答案”菜单或复制热键。
- HUD、悬浮窗、通知、第二个窗口。
- 对录屏隐身；托盘图标仍会被全屏录制拍到。
- 新增 `State` 枚举值。
- 现有 ERROR 状态的自动重试/健康检查逻辑；本 spec 只新增软失败路径，不改 API 失败处理。

## 2. 用户流程

### 2.1 单选题 / 判断题

1. 复制题目（含 A–D 四个选项，或判断题题干）。
2. 按一次 `Ctrl+Alt+G`。
3. 托盘显示 🟡 黄色状态点（REQUESTING）。
4. 成功后显示答案行，右下角状态点隐藏：
   - 单选题：四个点，亮绿点为答案。
   - 判断题：两个点，左对右错。
5. 用户自己在题目界面完成选择。
6. 换题：复制新题，再按一次 `Ctrl+Alt+G`。单选题/判断题状态下第二次热键是“重新请求”，不会打字。

### 2.2 代码题

保持现有流程：

1. 复制题目。
2. 第一次 `Ctrl+Alt+G` 请求，成功后显示 🟢 绿色状态点。
3. 第二次 `Ctrl+Alt+G` 进入 TYPING，逐字输出代码；完成后回到 🟢 绿色状态点。

## 3. 图标规格

### 3.1 基础图形

- 16×16 RGBA，Pillow 运行时生成。
- 云朵主体保持现有画法、灰蓝色 `#94A3B8`，轮廓不变。
- 答案行位于云朵下部：
  - 单选题：四个 `3×3` 点，横向位置 `x = 1, 5, 9, 13`，`y = 10..12`。
  - 判断题：两个 `5×5` 点，横向位置 `x = 3..7`、`x = 8..12`，`y = 9..13`。
- 空位颜色：`#475569`。
- 选中颜色：`#22C55E`。
- 选中点与空位点尺寸完全一致；不加白描边、不放大、不画白色底板。
- 不使用字母、数字、图标字体、动画、闪烁或每选项颜色。

### 3.2 映射表

| 答案 | 图案 |
|---|---|
| 单选 A | 四点；第 1 个亮绿，第 2–4 个深灰空位 |
| 单选 B | 四点；第 2 个亮绿 |
| 单选 C | 四点；第 3 个亮绿 |
| 单选 D | 四点；第 4 个亮绿 |
| 判断：正确/对 | 两点；左亮绿右深灰 |
| 判断：错误/错 | 两点；左深灰右亮绿 |
| 代码题就绪 | 仅 🟢 绿色状态点，无答案行 |
| 请求中 / 打字中 / 错误 / 空闲 | 原状态点，无答案行 |
| 多选题 / 5+ 选项 / 解析失败 | 🟢 绿色状态点，无答案行（软失败） |

### 3.3 状态优先级

按顺序判断：

1. `state != READY`：画原状态点，忽略答案。
2. `READY` 且答案为空：画 🟢 绿色状态点。
3. `READY` 且答案类型为 `CODE`：画 🟢 绿色状态点。
4. `READY` 且答案类型为 `SINGLE`：画四点答案行，不画状态点。
5. `READY` 且答案类型为 `BOOLEAN`：画两点答案行，不画状态点。
6. `READY` 但答案不可显示（多选 / 5+ / 解析失败）：画 🟢 绿色状态点。

答案行只在 `READY` 下有效。REQUESTING、TYPING、ERROR 永远不显示旧答案。

### 3.4 Tooltip 与菜单

- Tooltip 固定为 `C Helper — Ctrl+Alt+G`，不随状态变化，不包含答案、题型、选项或错误文本。
- 托盘菜单保持现状：`强制重置为空闲`、`退出`。
- 不增加“复制答案”菜单项。

## 4. 答案协议

### 4.1 协议指令

在 `AIClient.ask` 中，把固定指令追加到用户 `system_prompt` 之后（不改 `config.json`）：

```text
先判断题目类型，并严格按以下格式回答：
1. 单选题：第一行只输出 [[CHOICE:选项字母]]，例如 [[CHOICE:A]]。
2. 判断题（包括 A. 正确 / B. 错误 形式）：第一行只输出 [[BOOL:T]] 或 [[BOOL:F]]。
3. 多选题：不要作答，第一行只输出 [[UNSUPPORTED]]。
4. 代码题：不要输出任何类型标记，直接按用户要求输出代码。
只支持单选题的 A–D 四个选项；如果题目有 5 个及以上选项，也输出 [[UNSUPPORTED]]。
不要输出选项原文、解释或 Markdown 代码围栏。
```

- 追加顺序：先追加 `output_mode == "optimized"` 的 K&R 指令，再追加协议指令，让协议成为最后一条指令；不得覆盖用户 prompt。
- 代码题在 `optimized` 模式下仍按现有逻辑清洗 Markdown 围栏和末尾多余大括号；`raw` 模式保持现有原样返回行为。
- 不在请求里使用 `response_format`，以兼容不支持 JSON mode 的端点。

### 4.2 标记格式

| 题型 | 首行 | 示例 |
|---|---|---|
| 单选 | `[[CHOICE:字母]]` | `[[CHOICE:A]]` |
| 判断 | `[[BOOL:T]]` / `[[BOOL:F]]` | `[[BOOL:T]]` |
| 多选 / 5+ | `[[UNSUPPORTED]]` | `[[UNSUPPORTED]]` |
| 代码 | 无标记 | `#include <stdio.h>...` |

### 4.3 解析规则

解析函数建议命名为 `parse_answer(raw: str, question: str) -> Answer | None`，放在 `core.py`，保持纯函数、可单测。

1. 取响应中第一个非空行，去掉首尾空白。
2. 如果该行以 `[[CODE]]` 开头：剥离标记，剩余内容作为代码；剩余为空则软失败。
3. 对首个非空行做 NFKC 归一化（把全角字母、全角冒号、全角括号转成 ASCII）。如果归一化后以 `[[UNSUPPORTED]]` 开头，直接软失败（多选题 / 5+ 选项）。
4. 用正则匹配行首标记：
   ```text
   ^\[\[\s*(CHOICE|MULTI|BOOL)\s*:\s*([^\]]*?)\s*\]\]
   ```
   大小写不敏感；允许标记后还有文字（忽略）。
5. 没有匹配到标记：
   - 题目像判断题或选择题 → 返回 `None`（软失败）。
   - 否则 → 返回 `Answer(CODE, raw)`，保持现有代码行为。
6. `MULTI` 标记：直接返回 `None`。多选已取消，即使只给一个字母也不降级成单选。
7. `CHOICE`：
   - 从 payload 中提取所有字母（含全角 Ａ–Ｚ，先做 NFKC 归一化）。
   - 出现 A–D 之外的字母（E/F/…）→ 返回 `None`（5+ 不支持）。
   - 没有字母，或字母数不等于 1 → 返回 `None`（多选不支持）。
   - 恰好一个字母 → `Answer(SINGLE, 字母, choices=(字母,))`。
8. `BOOL`：
   - 归一化 payload（去空白、转大写、NFKC）。
   - 真值集合：`T`、`TRUE`、`对`、`正确`、`是`、`√`、`YES`、`Y`。
   - 假值集合：`F`、`FALSE`、`错`、`错误`、`否`、`×`、`NO`、`N`。
   - 命中真值 → `Answer(BOOLEAN, "正确", value=True)`；命中假值 → `Answer(BOOLEAN, "错误", value=False)`。
   - 其他 → `None`。
9. 标记存在但 payload 非法：返回 `None`（软失败），不要回退成代码。
10. 只解析第一个非空行；标记出现在第二行或更后时按“没有标记”处理。

### 4.4 本地启发式（仅用于兜底）

这些启发式只在“没有首行标记”时判断该不该软失败，不作为主分类器。

```python
_OPTION_LINE = re.compile(r"(?m)^\s*[A-DＡ-Ｄ]\s*[.．、):：）]")
_BOOL_OPTION = re.compile(
    r"(?m)^\s*[ABＡＢ]\s*[.．、):：）]\s*(正确|错误|对|错|true|false)",
    re.I,
)
```

- `looks_like_choice(text)`：至少 2 行以 A–D 加标点开头，或包含 `单选题`、`多选题`、`选择题` 关键词。
- `looks_like_boolean(text)`：包含 `判断题`、`对错题`，或出现 `A. 正确 / B. 错误` 这类选项。
- 先判 `looks_like_boolean`，再判 `looks_like_choice`。
- 代码题里如果注释恰好有两行以 `A.` / `B.` 开头，可能被误判为选择题并软失败；这是有意的保守失败：宁可不出答案，也不把答案文本打进编辑器。

### 4.5 兜底矩阵

| 情况 | 行为 |
|---|---|
| 标记合法，答案 A–D | 显示答案行 |
| `[[MULTI:...]]` 或多字母 `CHOICE` | 软失败（多选不支持） |
| `[[UNSUPPORTED]]` | 软失败 |
| 标记合法，答案含 E/F | 软失败 |
| 标记合法，payload 为空/非法 | 软失败 |
| 无标记，题目像选择题/判断题 | 软失败 |
| 无标记，题目像代码题 | 按代码处理 |
| 无标记，题目无法判断 | 按代码处理（保持现有行为） |
| `[[CODE]]` + 代码 | 剥离标记，按代码处理 |
| 代码题被模型误判为选择题 | 信任标记，显示答案行；用户可用“强制重置”回到空闲 |

### 4.6 软失败

- 清空 `_cached_answer` 和 `_answer`。
- 托盘保持 `READY`（🟢 绿色状态点），不显示答案行。
- 记录一条 WARNING：说明“解析失败/不可显示答案”，不记录完整答案正文。
- 绝不调用 `Typer`。
- 用户再次按 `Ctrl+Alt+G` 会重新请求。

## 5. 数据模型与实现建议

```python
class AnswerKind(Enum):
    CODE = auto()
    SINGLE = auto()
    BOOLEAN = auto()

@dataclass(frozen=True)
class Answer:
    kind: AnswerKind
    text: str                         # 代码正文，或 "A" / "正确" / "错误"
    choices: tuple[str, ...] = ()     # SINGLE: ("A",)
    value: bool | None = None         # BOOLEAN
```

- `Worker._cached_answer: str` 保留，作为代码正文/兼容现有测试。
- 新增 `Worker._answer: Answer | None` 保存类型和选项。
- `_cached_answer` 非空且 `_answer is None` 时，按代码处理（兼容旧测试和旧缓存）。
- 不新增 `State`；复用 `READY`。
- `TrayManager` 增加 `set_answer(answer)`；`set_state(state)` 用“当前 state + 当前 answer”渲染。
- `IconRenderer.render(state, answer=None)` 保持旧签名兼容；旧测试传一个参数仍然通过。

### 5.1 Worker 分支

```text
handle_hotkey:
  IDLE / REQUESTING / TYPING / ERROR -> 现有行为
  READY:
    answer 是 SINGLE / BOOLEAN -> _do_request()   # 重新请求，不打字
    _cached_answer 非空 -> 现有代码输出（manual / auto）
    否则 -> _do_request()
```

- 软失败后 `_answer is None`、`_cached_answer == ""`，所以下一次热键走 `_do_request()`。
- 多选同样返回 `None`，走软失败。

### 5.2 `_do_request`

1. 清空旧答案：`_cached_answer = ""`、`_answer = None`、`tray.set_answer(None)`。
2. 转 `REQUESTING`，托盘 🟡。
3. 读剪贴板、请求、清洗。
4. `parse_answer`：
   - `None` → 软失败：保持清空状态，转 `READY`，托盘 🟢，记 WARNING。
   - `Answer` → 保存 `_answer`、`_cached_answer = answer.text`、`tray.set_answer(answer)`，转 `READY`。
5. 异常 → 清空、转 `ERROR`、托盘 🔴（现有行为）。

### 5.3 代码输出完成

`_do_type` 的 `finally` 和 `_terminate_manual` 除了清空 `_cached_answer`，还要清空 `_answer` 并 `tray.set_answer(None)`，让托盘回到 🟢 状态点。

### 5.4 `force_reset`

清空 `_cached_answer`、`_answer`、手动模式字段，`tray.set_answer(None)`，回 `IDLE`。

## 6. 验收清单

### 6.1 图标

- [ ] 16×16 RGBA；云朵轮廓和灰蓝色不变。
- [ ] 单选题四个 3×3 点位于 `x = 1, 5, 9, 13`，`y = 10..12`。
- [ ] 判断题两个 5×5 点位于 `x = 3..7`、`x = 8..12`，`y = 9..13`。
- [ ] 空位 `#475569`，选中 `#22C55E`。
- [ ] 选中点与空位点尺寸完全一致；无白描边、无放大。
- [ ] 单选 A/B/C/D 各点亮正确位置，其余三个为空位。
- [ ] 判断正确：左亮右灰；判断错误：左灰右亮。
- [ ] READY + 代码答案：🟢 状态点，无答案行。
- [ ] REQUESTING / TYPING / ERROR / IDLE：原状态点，无答案行。
- [ ] 无字母、无动画、无每选项颜色。
- [ ] Tooltip 固定 `C Helper — Ctrl+Alt+G`。

### 6.2 解析

- [ ] `[[CHOICE:A]]` → SINGLE A。
- [ ] `[[CHOICE:B]]` / `[[choice:b]]` → SINGLE B。
- [ ] 全角 `［［ＣＨＯＩＣＥ：Ａ］］` → SINGLE A。
- [ ] `[[MULTI:AC]]` / `[[MULTI:A]]` / `[[CHOICE:AC]]` → `None`。
- [ ] `[[UNSUPPORTED]]` → `None`。
- [ ] `[[CHOICE:E]]` → `None`。
- [ ] `[[CHOICE:]]` → `None`。
- [ ] `[[BOOL:T]]` / `[[BOOL:TRUE]]` / `[[BOOL:正确]]` / `[[BOOL:√]]` → 正确。
- [ ] `[[BOOL:F]]` / `[[BOOL:FALSE]]` / `[[BOOL:错误]]` / `[[BOOL:×]]` → 错误。
- [ ] 无标记 + 四行 A–D 选项 → `None`（软失败）。
- [ ] 无标记 + `判断题` 题干 → `None`（软失败）。
- [ ] 无标记 + 代码正文 → CODE。
- [ ] `[[CODE]]` + 代码 → 剥离标记，CODE。
- [ ] 解析失败日志不含完整答案正文。

### 6.3 交互

- [ ] 单选题/判断题成功后，第二次 `Ctrl+Alt+G` 重新请求，不调用 `Typer`。
- [ ] 代码题第二次热键仍进入 manual/auto 输出。
- [ ] 多选题目/5+ 选项软失败后保持 READY，再次热键可重试。
- [ ] “强制重置为空闲”清除答案行并回 IDLE。
- [ ] 托盘菜单仍只有“强制重置为空闲”和“退出”。

### 6.4 手动验收（真机）

- [ ] 浅色任务栏、深色任务栏。
- [ ] 100%、125%、150%、200% DPI。
- [ ] 真实模型对 4 选项单选题、判断题分别返回正确标记。
- [ ] 代码题回归：`optimized` 和 `raw` 两种模式都能正常请求并在第二次热键输出代码。
- [ ] 故意让模型返回无标记/非法标记，确认软失败且没有键盘输出。
- [ ] 多选样题确认不显示猜测答案，只保持绿色就绪点。
- [ ] 5 选项样题确认不显示错误四点行，只保持绿色就绪点。
- [ ] 目标窗口全屏时确认托盘不可见（已知限制）。
- [ ] 全屏录制时确认图标仍被拍到（已知限制）。

## 7. 非目标与后续

- 多选题、5+ 选项的编码或交付路径。
- 复制答案菜单/热键。
- 填空、简答、组合题。
- 自动点击/选中/提交。
- 多尺寸 ICO 或按 DPI 预生成资源；Phase 1 继续运行时生成 16×16。
- 引导/图例 UI；Phase 1 只靠 README 和本 spec 的图例。
- 高对比度主题、RDP/VM 的额外适配。

## 8. 参考

- [CONTEXT.md](../../CONTEXT.md)
- [ADR 0001：托盘答案点行](../adr/0001-tray-answer-dot-row.md)
- [ADR 0002：只显示，不自动作答](../adr/0002-choice-answers-are-advisory.md)
- [ADR 0003：一次请求 + 首行标记](../adr/0003-typed-answer-protocol.md)
- [图标图例](../prototypes/tray-answer-v3b.png)
