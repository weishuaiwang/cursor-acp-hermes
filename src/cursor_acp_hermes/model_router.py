"""
Model Router — intelligently selects the best Cursor model for each task.

Strategy:
  - Classifies the task into categories based on prompt keywords, length, and patterns
  - Maps categories to optimal models balancing speed, cost, and capability
  - Supports explicit model override via task metadata
"""

import re
import logging
from typing import Dict, List, Optional, Tuple

from .types import ModelSpec, TaskCategory

logger = logging.getLogger(__name__)

# ─── Model Catalog ───────────────────────────────────────────────────────────
# Tier definitions (estimated relative costs within Cursor Pro):
#   Tier 1: fastest/cheapest models — compositor-2-fast, gpt-5.4-mini/nano
#   Tier 2: balanced models — gpt-5.3-codex-low, composer-2
#   Tier 3: capable coding models — gpt-5.3-codex, claude-sonnet-4.6, gemini-3.1-pro
#   Tier 4: high-capability models — claude-opus-4.5, gpt-5.5-medium, grok-4.3
#   Tier 5: max capability — claude-opus-4-7-thinking-xhigh/max

MODEL_CATALOG: Dict[str, ModelSpec] = {
    # ── Fast & Cheap ──
    "composer-2-fast": ModelSpec(
        id="composer-2-fast",
        name="Composer 2 Fast",
        provider="cursor",
        context_window=32000,
        cost_tier=1,
        speed_tier=1,
        strengths=["Simple Q&A", "Quick edits", "Light refactoring"],
        best_for=[TaskCategory.SIMPLE],
    ),
    "gpt-5.4-nano": ModelSpec(
        id="gpt-5.4-nano",
        name="GPT-5.4 Nano",
        provider="openai",
        context_window=32000,
        cost_tier=1,
        speed_tier=1,
        strengths=["Fast responses", "Simple tasks"],
        best_for=[TaskCategory.SIMPLE],
    ),
    "gpt-5.4-mini": ModelSpec(
        id="gpt-5.4-mini",
        name="GPT-5.4 Mini",
        provider="openai",
        context_window=64000,
        cost_tier=1,
        speed_tier=1,
        strengths=["Fast coding", "Lightweight tasks"],
        best_for=[TaskCategory.SIMPLE, TaskCategory.EXPLORATION],
    ),

    # ── Balanced — Code Generation ──
    "gpt-5.3-codex-low": ModelSpec(
        id="gpt-5.3-codex-low",
        name="Codex 5.3 Low",
        provider="openai",
        context_window=64000,
        cost_tier=2,
        speed_tier=2,
        strengths=["Efficient code gen", "Standard tasks"],
        best_for=[TaskCategory.CODE_GENERATION, TaskCategory.REFACTORING],
    ),
    "composer-2": ModelSpec(
        id="composer-2",
        name="Composer 2",
        provider="cursor",
        context_window=64000,
        cost_tier=2,
        speed_tier=2,
        strengths=["Balanced coding", "General tasks"],
        best_for=[TaskCategory.CODE_GENERATION, TaskCategory.REFACTORING,
                  TaskCategory.CODE_REVIEW, TaskCategory.EXPLORATION],
    ),
    "gpt-5.4": ModelSpec(
        id="gpt-5.4",
        name="GPT-5.4",
        provider="openai",
        context_window=128000,
        cost_tier=2,
        speed_tier=2,
        strengths=["General purpose", "Good reasoning"],
        best_for=[TaskCategory.CODE_GENERATION, TaskCategory.CODE_REVIEW,
                  TaskCategory.EXPLORATION, TaskCategory.PLANNING],
    ),

    # ── Capable – Primary Coding Models ──
    "gpt-5.3-codex": ModelSpec(
        id="gpt-5.3-codex",
        name="Codex 5.3",
        provider="openai",
        context_window=128000,
        cost_tier=3,
        speed_tier=3,
        strengths=["Excellent code generation", "Complex coding", "Refactoring"],
        best_for=[TaskCategory.CODE_GENERATION, TaskCategory.REFACTORING,
                  TaskCategory.CODE_REVIEW, TaskCategory.DEBUGGING],
    ),
    "claude-sonnet-4.6": ModelSpec(
        id="claude-4.6-sonnet-medium",
        name="Sonnet 4.6 1M",
        provider="anthropic",
        context_window=1_000_000,
        cost_tier=3,
        speed_tier=3,
        strengths=["100万上下文", "优秀编码", "长文档分析"],
        best_for=[TaskCategory.CODE_GENERATION, TaskCategory.CODE_REVIEW,
                  TaskCategory.DEBUGGING, TaskCategory.EXPLORATION],
    ),
    "gemini-3.1-pro": ModelSpec(
        id="gemini-3.1-pro",
        name="Gemini 3.1 Pro",
        provider="google",
        context_window=128000,
        cost_tier=3,
        speed_tier=2,
        strengths=["多模态", "长上下文", "推理"],
        best_for=[TaskCategory.CODE_GENERATION, TaskCategory.EXPLORATION,
                  TaskCategory.PLANNING],
    ),
    "kimi-k2.5": ModelSpec(
        id="kimi-k2.5",
        name="Kimi K2.5",
        provider="moonshot",
        context_window=128000,
        cost_tier=3,
        speed_tier=3,
        strengths=["中文优化", "代码能力", "长文本"],
        best_for=[TaskCategory.CODE_GENERATION, TaskCategory.CODE_REVIEW,
                  TaskCategory.EXPLORATION],
    ),

    # ── High Capability ──
    "claude-opus-4.5-thinking": ModelSpec(
        id="claude-4.5-opus-high-thinking",
        name="Opus 4.5 Thinking",
        provider="anthropic",
        context_window=200000,
        cost_tier=4,
        speed_tier=4,
        strengths=["深度推理", "复杂问题", "架构设计"],
        best_for=[TaskCategory.DEBUGGING, TaskCategory.ARCHITECTURE,
                  TaskCategory.PLANNING],
        supports_thinking=True,
    ),
    "gpt-5.5": ModelSpec(
        id="gpt-5.5-medium",
        name="GPT-5.5 1M",
        provider="openai",
        context_window=1_000_000,
        cost_tier=4,
        speed_tier=3,
        strengths=["百万上下文", "强大推理", "全栈能力"],
        best_for=[TaskCategory.DEBUGGING, TaskCategory.ARCHITECTURE,
                  TaskCategory.PLANNING, TaskCategory.CODE_GENERATION],
    ),
    "grok-4.3": ModelSpec(
        id="grok-4.3",
        name="Grok 4.3 1M",
        provider="xai",
        context_window=1_000_000,
        cost_tier=4,
        speed_tier=3,
        strengths=["百万上下文", "独特视角", "编码"],
        best_for=[TaskCategory.DEBUGGING, TaskCategory.EXPLORATION,
                  TaskCategory.ARCHITECTURE],
    ),

    # ── Max Capability ──
    "claude-opus-4-7": ModelSpec(
        id="claude-opus-4-7-xhigh",
        name="Opus 4.7 1M",
        provider="anthropic",
        context_window=1_000_000,
        cost_tier=5,
        speed_tier=5,
        strengths=["顶级推理", "百万上下文", "最大能力"],
        best_for=[TaskCategory.ARCHITECTURE, TaskCategory.DEBUGGING,
                  TaskCategory.PLANNING],
    ),
    "claude-opus-4-7-thinking": ModelSpec(
        id="claude-opus-4-7-thinking-xhigh",
        name="Opus 4.7 1M Thinking",
        provider="anthropic",
        context_window=1_000_000,
        cost_tier=5,
        speed_tier=5,
        strengths=["带思考的顶级能力", "最复杂问题", "深度架构"],
        best_for=[TaskCategory.ARCHITECTURE, TaskCategory.DEBUGGING,
                  TaskCategory.PLANNING],
        supports_thinking=True,
    ),
    "gpt-5.5-xhigh": ModelSpec(
        id="gpt-5.5-extra-high",
        name="GPT-5.5 Extra High",
        provider="openai",
        context_window=1_000_000,
        cost_tier=5,
        speed_tier=4,
        strengths=["顶级推理", "百万上下文", "全面能力"],
        best_for=[TaskCategory.ARCHITECTURE, TaskCategory.DEBUGGING,
                  TaskCategory.CODE_GENERATION, TaskCategory.PLANNING],
    ),
}


# ─── Task Classification ─────────────────────────────────────────────────────

# Keywords that signal task categories
_CATEGORY_SIGNALS: Dict[TaskCategory, List[str]] = {
    TaskCategory.SIMPLE: [
        "what is", "explain briefly", "quick", "simple", "trivial",
        "short", "一句话", "简单", "快速",
    ],
    TaskCategory.CODE_GENERATION: [
        "write", "implement", "create", "build", "develop", "generate",
        "add feature", "new function", "编写", "实现", "创建", "构建",
    ],
    TaskCategory.CODE_REVIEW: [
        "review", "audit", "inspect", "check for bugs", "code review",
        "security review", "审查", "检查", "审计",
    ],
    TaskCategory.DEBUGGING: [
        "bug", "fix", "error", "crash", "broken", "not working",
        "debug", "issue", "incorrect", "fails", "报错", "修复", "错误",
        "debug", "故障",
    ],
    TaskCategory.REFACTORING: [
        "refactor", "clean up", "improve", "optimize", "restructure",
        "reorganize", "重构", "优化", "整理", "改进",
    ],
    TaskCategory.ARCHITECTURE: [
        "architecture", "design", "system design", "component",
        "architecture decision", "trade-off", "架构", "设计", "系统设计",
    ],
    TaskCategory.EXPLORATION: [
        "explain", "how does", "what is", "understand", "learn",
        "research", "compare", "difference between", "解释", "理解",
        "学习", "比较", "区别",
    ],
    TaskCategory.PLANNING: [
        "plan", "roadmap", "milestone", "step", "strategy",
        "workflow", "todo", "计划", "步骤", "路线图",
    ],
}


def classify_task(prompt: str) -> Tuple[TaskCategory, float]:
    """
    Classify a task prompt into a category with confidence score.

    Returns:
        Tuple of (category, confidence: 0.0–1.0)
    """
    prompt_lower = prompt.lower()
    scores: Dict[TaskCategory, float] = {cat: 0.0 for cat in TaskCategory}

    # Score based on keyword matches
    for category, signals in _CATEGORY_SIGNALS.items():
        for signal in signals:
            if signal in prompt_lower:
                scores[category] += 1.0

    # Length-based heuristics
    word_count = len(prompt_lower.split())
    char_count = len(prompt)

    # Very short prompts → SIMPLE
    if word_count < 5:
        scores[TaskCategory.SIMPLE] += 2.0

    # Very long prompts with code patterns → CODE_GENERATION or DEBUGGING
    if "```" in prompt and word_count > 30:
        if any(w in prompt_lower for w in ["fix", "bug", "error", "not working"]):
            scores[TaskCategory.DEBUGGING] += 2.0
        else:
            scores[TaskCategory.CODE_GENERATION] += 1.5

    # Long prompts with architecture language
    if char_count > 2000 or word_count > 200:
        scores[TaskCategory.ARCHITECTURE] += 1.0
        scores[TaskCategory.PLANNING] += 0.5

    # Find best category
    best_cat = max(scores, key=scores.get)
    max_score = scores[best_cat]

    # Normalize confidence
    if max_score == 0:
        return TaskCategory.CODE_GENERATION, 0.3  # default fallback

    confidence = min(1.0, max_score / 5.0)
    return best_cat, confidence


def _estimate_context_size(prompt: str) -> int:
    """Rough estimate of context window needed (in chars)."""
    return len(prompt)


# ─── Model Selection ─────────────────────────────────────────────────────────

def select_model(
    prompt: str,
    preferred_model: Optional[str] = None,
    max_cost_tier: int = 5,
) -> str:
    """
    Select the best Cursor model for a given task prompt.

    Args:
        prompt: The task prompt to classify
        preferred_model: Explicit model override (if user specifies)
        max_cost_tier: Maximum acceptable cost tier (1-5)

    Returns:
        Model ID string to pass to cursor-agent --model
    """
    # Explicit override always wins
    if preferred_model and preferred_model in MODEL_CATALOG:
        spec = MODEL_CATALOG[preferred_model]
        if spec.cost_tier <= max_cost_tier:
            logger.info(f"Using explicitly requested model: {preferred_model}")
            return preferred_model

    # Classify the task
    category, confidence = classify_task(prompt)
    context_size = _estimate_context_size(prompt)
    logger.info(f"Task classified as: {category} (confidence={confidence:.2f}, "
                f"size={context_size} chars)")

    # Find models that match the category and are within budget
    candidates: List[Tuple[str, ModelSpec]] = []
    for mid, spec in MODEL_CATALOG.items():
        if spec.cost_tier > max_cost_tier:
            continue
        if category in spec.best_for:
            # Check context window fit
            if context_size > spec.context_window * 0.8:  # 80% threshold
                continue
            candidates.append((mid, spec))

    if not candidates:
        # Fallback: any model within budget, sorted by cost
        for mid, spec in sorted(MODEL_CATALOG.items(),
                                 key=lambda x: (x[1].cost_tier, x[1].speed_tier)):
            if spec.cost_tier <= max_cost_tier:
                candidates.append((mid, spec))
                break

    if not candidates:
        # Ultimate fallback
        logger.warning("No candidate models found, using default")
        return "composer-2"

    # Rank candidates by speed (lower = faster) within same cost tier
    candidates.sort(key=lambda x: (x[1].cost_tier, x[1].speed_tier))

    selected = candidates[0][0]
    logger.info(f"Selected model: {selected} ({MODEL_CATALOG[selected].name})")
    return selected


def get_model_spec(model_id: str) -> Optional[ModelSpec]:
    """Get the spec for a model ID."""
    return MODEL_CATALOG.get(model_id)


def list_available_models() -> Dict[str, str]:
    """Return a dict of model_id -> display_name for all catalog models."""
    return {mid: spec.name for mid, spec in MODEL_CATALOG.items()}
