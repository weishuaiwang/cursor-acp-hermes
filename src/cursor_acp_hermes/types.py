"""
Type definitions for cursor-acp-hermes.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─── Task Classification ─────────────────────────────────────────────────────

from enum import Enum


class TaskCategory(str, Enum):
    """Classification of a coding task for model routing."""
    SIMPLE = "simple"             # Quick answers, simple Q&A
    CODE_GENERATION = "code_gen"  # Writing code from scratch
    CODE_REVIEW = "code_review"   # Code review and analysis
    DEBUGGING = "debugging"       # Debugging complex issues
    REFACTORING = "refactoring"   # Code refactoring
    ARCHITECTURE = "architecture" # System design, architecture
    EXPLORATION = "exploration"   # Research, learning, understanding
    PLANNING = "planning"         # Task planning, project organization


@dataclass
class ModelSpec:
    """Specification of a Cursor model's capabilities."""
    id: str
    name: str
    provider: str
    context_window: int
    cost_tier: int  # 1=cheapest, 5=most expensive
    speed_tier: int  # 1=fastest, 5=slowest
    strengths: List[str]
    best_for: List[TaskCategory]
    supports_thinking: bool = False
    max_output_tokens: int = 4096


# ─── ACP Protocol Types ──────────────────────────────────────────────────────

@dataclass
class JsonRpcRequest:
    jsonrpc: str = "2.0"
    method: str = ""
    params: Optional[Dict[str, Any]] = None
    id: Optional[int] = None


@dataclass
class JsonRpcResponse:
    jsonrpc: str = "2.0"
    id: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


# ─── Session ─────────────────────────────────────────────────────────────────

@dataclass
class Session:
    """Represents an active ACP session."""
    session_id: str
    model_id: str
    created_at: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    conversation: List[Dict[str, Any]] = field(default_factory=list)


# ─── Metrics ─────────────────────────────────────────────────────────────────

@dataclass
class UsageMetrics:
    """Token usage and timing for a prompt."""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    duration_ms: int = 0
    cost_estimate_usd: float = 0.0
