# cursor-acp-hermes

Intelligent ACP adapter for Cursor Agent — bridges Cursor Pro models to Hermes Agent via the Agent Client Protocol (ACP) with **smart model routing**.

## How It Works

```
Hermes Agent (delegate_task)
        │ ACP protocol (JSON-RPC 2.0 over stdio)
        ▼
cursor-acp-hermes
        │ 1. Classifies task type
        │ 2. Selects optimal Cursor model
        │ 3. Calls cursor-agent --print
        ▼
cursor-agent CLI (Cursor Pro)
        │
        ▼
Cursor models (Claude Opus 4.7, GPT-5.5, Codex, etc.)
```

## Model Routing

The adapter classifies each task and selects the best model:

| Task Type | Example | Selected Model | Tier | Cost |
|-----------|---------|---------------|------|------|
| Simple Q&A | "What is X?" | Composer 2 Fast | 1 | Free |
| Code Generation | "Write a function..." | Codex 5.3 / Composer 2 | 2 | Low |
| Debugging | "Fix this bug..." | Codex 5.3 / Sonnet 4.6 | 3 | Medium |
| Architecture | "Design a system..." | GPT-5.5 / Opus 4.7 | 4-5 | High |
| Deep Reasoning | "Analyze complex..." | Claude Opus 4.7 Thinking | 5 | Highest |

## Installation

```bash
# Clone and install
git clone git@github.com:weishuaiwang/cursor-acp-hermes.git
cd cursor-acp-hermes
pip install -e .

# Ensure cursor-agent is logged in
cursor-agent status
```

## Usage

### ACP Server Mode (for Hermes delegate_task)

```bash
cursor-acp-hermes
```

Use with Hermes via `delegate_task`:
```python
# Hermes will spawn this automatically
delegate_task(
    goal="Write a FastAPI CRUD for users",
    acp_command="cursor-acp-hermes",
)
```

### One-Shot Tasks

```bash
# Auto-select model based on task
cursor-acp-hermes run "Write a sorting function in Python"

# Override model selection
cursor-acp-hermes run --model claude-opus-4-7-thinking "Design a distributed system"

# Pipe input
echo "Fix this bug: ..." | cursor-acp-hermes run
```

### Task Classification

```bash
# See which model would be selected
cursor-acp-hermes classify "Debug why my app crashes on startup"

# JSON output with confidence scores
```

### Management

```bash
# Check status
cursor-acp-hermes status

# List all available models
cursor-acp-hermes models
```

## Architecture

```
src/cursor_acp_hermes/
├── __init__.py      # Package init, version
├── __main__.py      # CLI entry point
├── acp_adapter.py   # ACP protocol (JSON-RPC over stdio)
├── cursor_bridge.py # cursor-agent CLI bridge
├── model_router.py  # Task classification + model selection
└── types.py         # Type definitions
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CURSOR_AGENT_PATH` | `which cursor-agent` | Path to cursor-agent binary |
| `CURSOR_AGENT_TIMEOUT` | `120` | Timeout in seconds |
| `CURSOR_ACP_MODEL` | (auto) | Force a specific model |

## Requirements

- Python 3.9+
- cursor-agent CLI (logged in with Cursor Pro)
- macOS, Linux, WSL2

## License

MIT
