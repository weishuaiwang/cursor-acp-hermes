"""
cursor-acp-hermes — Intelligent ACP adapter for Cursor Agent with model routing.

Bridges Cursor Pro models to Hermes Agent via the Agent Client Protocol (ACP),
with intelligent model selection based on task type, complexity, and cost.
"""

__version__ = "0.1.0"
__all__ = ["AcpAdapter", "call_agent", "select_model", "classify_task"]

from .acp_adapter import AcpAdapter
from .cursor_bridge import call_agent, check_available
from .model_router import select_model, classify_task, list_available_models
