# cursor-acp-hermes

智能 ACP 协议适配器，将 **Cursor Pro 订阅的模型能力** 桥接到 **Hermes Agent**，并具备**智能模型路由**功能。

## 架构

```
Hermes Agent (delegate_task)
        │ ACP 协议 (JSON-RPC 2.0 over stdio)
        ▼
cursor-acp-hermes
        │ 1. 任务分类（分析任务类型）
        │ 2. 模型选择（根据复杂度选最优模型）
        │ 3. 调用 cursor-agent 执行
        ▼
cursor-agent CLI (已登录 Cursor Pro)
        │
        ▼
Cursor 模型池 (Claude Opus 4.7, GPT-5.5, Codex 等)
```

## 安装

### 前置条件

1. 已安装 [Cursor](https://cursor.com) 并订阅 **Cursor Pro**
2. `cursor-agent` CLI 已登录：

```bash
cursor-agent status
# 应显示已登录状态
```

### 安装适配器

```bash
# 克隆
git clone git@github.com:weishuaiwang/cursor-acp-hermes.git
cd cursor-acp-hermes

# 安装
pip install -e .

# 验证安装
cursor-acp-hermes status
```

## 快速开始

### ACP 服务器模式（供 Hermes delegate_task 使用）

启动 ACP 服务器：

```bash
cursor-acp-hermes
```

在 Hermes 中通过 `delegate_task` 调用：

```python
delegate_task(
    goal="写一个 FastAPI 用户 CRUD",
    acp_command="cursor-acp-hermes",
)
```

Hermes 会自动启动适配器，将任务分类后选择合适的 Cursor 模型执行。

### 一键运行模式

```bash
# 自动选模型
cursor-acp-hermes run "写一个 Python 排序函数"

# 强制指定模型
cursor-acp-hermes run --model claude-opus-4-7-thinking "设计分布式系统架构"

# 从管道读取
echo "修复这个 bug..." | cursor-acp-hermes run
```

### 查看任务分类

```bash
# 查看某个任务会被分配到哪个模型
cursor-acp-hermes classify "调试应用启动崩溃问题"

# 输出 JSON
```

### 管理命令

```bash
# 查看所有可用模型
cursor-acp-hermes models

# 查看状态
cursor-acp-hermes status
```

## 模型路由策略

| 任务类型 | 示例 | 选派模型 | 层级 | 特点 |
|---------|------|---------|------|------|
| 简单问答 | "什么是 X？" | Composer 2 Fast | 1 | 最快，免费额度 |
| 代码生成 | "写一个函数..." | Codex 5.3 / Composer 2 | 2 | 代码质量好，成本低 |
| 调试 | "修复这个 bug..." | Codex 5.3 / Sonnet 4.6 | 3 | 推理能力强 |
| 架构设计 | "设计一个系统..." | GPT-5.5 / Opus 4.7 | 4-5 | 需深度推理 |
| 高难度任务 | "分析复杂问题..." | Claude Opus 4.7 Thinking | 5 | 最强可用模型 |

路由引擎根据 `goal` 文本自动判断：

- **关键词匹配**（"debug", "refactor", "design", "architecture"）
- **任务长度**（长任务 → 更强模型）
- **代码含量**（含代码块 → 代码优先模型）
- 受到 `CURSOR_ACP_MAX_TIER` 环境变量约束

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CURSOR_AGENT_PATH` | `which cursor-agent` | cursor-agent 二进制路径 |
| `CURSOR_AGENT_TIMEOUT` | `120` | 超时秒数 |
| `CURSOR_ACP_MODEL` | 自动路由 | 强制指定某个模型 |
| `CURSOR_ACP_MAX_TIER` | `5` | 最大成本层级（1=最便宜, 5=最强, 可限制开支） |

## 在 Hermes Agent 中使用

配合 hermes-agent 技能使用：

```python
# SKILL.md 中有完整说明
# 关键点：acp_args=["--acp", "--stdio"] 必须显式传递
delegate_task(
    goal="实现用户管理 API",
    acp_command="cursor-acp-hermes",
    acp_args=["--acp", "--stdio"],
)
```

### 大型任务拆分建议

单个 `delegate_task` 超时 120 秒。建议按垂直切片拆分：

```python
# 第1步：Model + Schema（约30-60秒）
delegate_task(goal="添加 BatchJob 模型和 Pydantic Schema...", ...)

# 第2步：API 路由（约60-90秒）
delegate_task(goal="创建批处理 API 端点...", ...)

# 第3步：前端页面（约60-120秒）
delegate_task(goal="创建批量生产前端页面...", ...)
```

### 前端修改验收

前端文件修改后，务必验证：

```bash
cd frontend && npx vue-tsc --noEmit
```

## 运行测试

```bash
# ACP 协议单元测试（无需 cursor-agent）
python3 tests/test_acp.py

# ACP 协议调试测试
python3 tests/test_debug2.py

# 完整集成测试（需要 cursor-agent 已登录）
python3 tests/test_integration.py
```

测试脚本是独立的 Python 脚本（非 pytest），直接运行即可。

## 项目结构

```
cursor-acp-hermes/
├── src/cursor_acp_hermes/
│   ├── __init__.py          # 包初始化，版本号
│   ├── __main__.py          # CLI 入口（acp server / run / classify）
│   ├── acp_adapter.py       # ACP 协议实现（JSON-RPC 2.0 over stdio）
│   ├── cursor_bridge.py     # cursor-agent CLI 桥接层
│   ├── model_router.py      # 任务分类 + 模型选择引擎
│   └── types.py             # 类型定义
├── tests/
│   ├── test_acp.py          # ACP 协议测试（7 个用例）
│   ├── test_debug2.py       # ACP 协议调试测试
│   └── test_integration.py  # 完整集成测试
├── pyproject.toml           # 项目配置
├── README.md                # 英文文档
├── README.zh.md             # 中文文档（本文件）
└── LICENSE                  # MIT License
```

## 环境要求

- **Python** 3.9+
- **cursor-agent** CLI（[安装 Cursor](https://cursor.com) 后自带）
- **Cursor Pro** 订阅
- **操作系统**：macOS / Linux / WSL2

## License

MIT
