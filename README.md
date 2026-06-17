# C语言题目后台助手

后台常驻桌面小工具，全局快捷键触发，托盘颜色直观反馈状态，AI 辅助生成 C 语言答案。

## 部署

```powershell
# 1. 克隆
gh repo clone HermosMerlin/FuckMati
cd FuckMati

# 2. 创建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

# 3. 第一次运行会自动生成 config.json，编辑填入你的 api_key
notepad config.json
```

## 使用

```powershell
# 前台运行（看日志）
.\run.bat

# 后台静默运行
.\start-hidden.vbs
```

按 **Ctrl+Alt+G** 循环触发：检测 API → 读取剪贴板 → 请求 AI → 模拟键盘输出答案。托盘右键可强制重置或退出。
