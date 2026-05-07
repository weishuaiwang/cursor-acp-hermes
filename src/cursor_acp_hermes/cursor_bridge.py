"""
Bridge to the cursor-agent CLI.

Handles spawning cursor-agent with --print mode, parsing JSON output,
and extracting structured results with usage metrics.
"""

import json
import logging
import os
import shlex
import subprocess
import time
import shutil
from typing import Optional, Tuple

from .types import UsageMetrics

logger = logging.getLogger(__name__)

# Path to cursor-agent binary
CURSOR_AGENT_CMD = os.environ.get(
    "CURSOR_AGENT_PATH",
    shutil.which("cursor-agent") or os.path.expanduser("~/.local/bin/cursor-agent"),
)

# Timeout for cursor-agent calls (seconds)
DEFAULT_TIMEOUT = int(os.environ.get("CURSOR_AGENT_TIMEOUT", "120"))


def check_available() -> Tuple[bool, str]:
    """Check if cursor-agent is available and authenticated."""
    if not CURSOR_AGENT_CMD or not os.path.isfile(CURSOR_AGENT_CMD):
        return False, f"cursor-agent not found at {CURSOR_AGENT_CMD}"

    try:
        result = subprocess.run(
            [CURSOR_AGENT_CMD, "status"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            # Check for logged in status
            output = result.stdout + result.stderr
            if "logged in" in output.lower() or "signed in" in output.lower():
                return True, "cursor-agent available and authenticated"
            return True, "cursor-agent available (auth status unknown)"
        return False, f"cursor-agent status failed: {result.stderr.strip()}"
    except FileNotFoundError:
        return False, f"cursor-agent binary not found at {CURSOR_AGENT_CMD}"
    except subprocess.TimeoutExpired:
        return False, "cursor-agent status check timed out"


def list_models() -> list:
    """List available models from cursor-agent."""
    if not CURSOR_AGENT_CMD:
        return []

    try:
        result = subprocess.run(
            [CURSOR_AGENT_CMD, "--list-models"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            models = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if line and " - " in line and not line.startswith("Available"):
                    parts = line.split(" - ", 1)
                    if len(parts) == 2:
                        models.append({"id": parts[0].strip(), "name": parts[1].strip()})
            return models
        return []
    except Exception as e:
        logger.warning(f"Failed to list models: {e}")
        return []


def call_agent(
    prompt: str,
    model: str = "composer-2",
    workspace: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """
    Call cursor-agent with the given prompt and model.

    Args:
        prompt: The prompt/task to send
        model: Cursor model ID to use
        workspace: Optional workspace directory
        timeout: Max seconds to wait

    Returns:
        Dict with keys: success, result (str), error (str|None), metrics (UsageMetrics|None)
    """
    if not CURSOR_AGENT_CMD:
        return {
            "success": False,
            "result": "",
            "error": f"cursor-agent not found. Install from cursor.com",
            "metrics": None,
        }

    # Build command
    cmd = [
        CURSOR_AGENT_CMD,
        "--print",
        "-f",  # force/trust mode
        "--trust",  # trust workspace
        "--model", model,
        "--output-format", "json",
    ]

    if workspace:
        cmd.extend(["--workspace", workspace])

    logger.info(f"Running: {' '.join(cmd[:4])} ... --model {model}")

    start_time = time.time()

    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        if proc.returncode != 0:
            error_msg = proc.stderr.strip() or proc.stdout.strip()
            return {
                "success": False,
                "result": "",
                "error": f"cursor-agent exited code {proc.returncode}: {error_msg}",
                "metrics": UsageMetrics(
                    model=model,
                    duration_ms=duration_ms,
                ),
            }

        # Parse JSON output
        output = proc.stdout.strip()
        if not output:
            return {
                "success": False,
                "result": "",
                "error": "Empty response from cursor-agent",
                "metrics": UsageMetrics(model=model, duration_ms=duration_ms),
            }

        # Find JSON in output
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            json_match = __import__('re').search(r'\{.*\}', output, __import__('re').DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group())
                except json.JSONDecodeError:
                    parsed = None
            else:
                parsed = None

        if parsed and isinstance(parsed, dict):
            result_text = parsed.get("result", output)
            usage = parsed.get("usage", {})
            metrics = UsageMetrics(
                model=model,
                input_tokens=usage.get("inputTokens", 0),
                output_tokens=usage.get("outputTokens", 0),
                cache_read_tokens=usage.get("cacheReadTokens", 0),
                cache_write_tokens=usage.get("cacheWriteTokens", 0),
                duration_ms=parsed.get("duration_ms", duration_ms),
            )
            # Rough cost estimate (pricing is approximate)
            _estimate_cost(metrics)

            return {
                "success": True,
                "result": result_text,
                "error": None,
                "metrics": metrics,
            }

        # Plain text output
        return {
            "success": True,
            "result": output,
            "error": None,
            "metrics": UsageMetrics(model=model, duration_ms=duration_ms),
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "result": "",
            "error": f"cursor-agent timed out after {timeout}s",
            "metrics": UsageMetrics(model=model, duration_ms=timeout * 1000),
        }
    except Exception as e:
        return {
            "success": False,
            "result": "",
            "error": f"cursor-agent call failed: {e}",
            "metrics": UsageMetrics(model=model),
        }


# ─── Cost Estimation ─────────────────────────────────────────────────────────
# Approximate pricing per 1K tokens (USD) — Cursor Pro includes a fixed number
# of "fast requests" per month, then falls back to slower quota.
# These are rough estimates for cost-aware routing.

_COST_PER_1K_INPUT: dict = {
    # Tier 1 (fast/cheap)
    "composer-2-fast": 0.000,
    "gpt-5.4-nano": 0.00015,
    "gpt-5.4-mini": 0.00015,
    # Tier 2
    "gpt-5.3-codex-low": 0.0003,
    "composer-2": 0.000,
    "gpt-5.4": 0.0005,
    # Tier 3
    "gpt-5.3-codex": 0.001,
    "claude-4.6-sonnet-medium": 0.003,
    "gemini-3.1-pro": 0.0005,
    "kimi-k2.5": 0.001,
    # Tier 4
    "claude-4.5-opus-high-thinking": 0.015,
    "gpt-5.5-medium": 0.005,
    "grok-4.3": 0.003,
    # Tier 5
    "claude-opus-4-7-xhigh": 0.03,
    "claude-opus-4-7-thinking-xhigh": 0.03,
    "gpt-5.5-extra-high": 0.01,
}


def _estimate_cost(metrics: UsageMetrics) -> None:
    """Fill in estimated cost for the metrics."""
    input_rate = _COST_PER_1K_INPUT.get(metrics.model, 0.001)
    output_rate = input_rate * 4  # output typically costs more
    metrics.cost_estimate_usd = (
        (metrics.input_tokens / 1000) * input_rate
        + (metrics.output_tokens / 1000) * output_rate
    )
