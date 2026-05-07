"""
CLI entry point for cursor-acp-hermes.

Usage:
  # Start ACP server (for Hermes delegate_task)
  cursor-acp-hermes

  # Run a one-shot task with model routing
  cursor-acp-hermes run "Write a Python function..."
  cursor-acp-hermes run --model claude-opus-4-7-thinking "Design the architecture for..."

  # List available models
  cursor-acp-hermes models

  # Check status
  cursor-acp-hermes status
"""

import argparse
import json
import logging
import os
import sys
import textwrap

from .acp_adapter import AcpAdapter
from .cursor_bridge import call_agent, check_available, list_models
from .model_router import classify_task, select_model, list_available_models, MODEL_CATALOG
from . import __version__

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False):
    """Configure logging to stderr (stdout is reserved for ACP protocol)."""
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        "[%(levelname)s] %(name)s: %(message)s"
    ))
    root = logging.getLogger("cursor_acp_hermes")
    root.setLevel(level)
    root.addHandler(handler)


def cmd_status(args):
    """Check cursor-agent status."""
    available, msg = check_available()
    print(f"cursor-agent: {'✓' if available else '✗'} {msg}", file=sys.stderr)

    models = list_models()
    print(f"Available models from cursor-agent: {len(models)}", file=sys.stderr)
    for m in models[:5]:
        print(f"  - {m['id']}: {m['name']}", file=sys.stderr)
    if len(models) > 5:
        print(f"  ... and {len(models) - 5} more", file=sys.stderr)


def cmd_models(args):
    """List available models from both catalog and cursor-agent."""
    print("=== Model Catalog (routing targets) ===", file=sys.stderr)
    for mid, spec in sorted(MODEL_CATALOG.items(),
                              key=lambda x: (x[1].cost_tier, x[1].speed_tier)):
        print(f"  {mid:<45} {spec.name:<30} tier={spec.cost_tier}", file=sys.stderr)

    cursor_models = list_models()
    if cursor_models:
        print(f"\n=== cursor-agent reports {len(cursor_models)} models ===", file=sys.stderr)
        for m in cursor_models[:10]:
            print(f"  {m['id']:<45} {m['name']}", file=sys.stderr)
        if len(cursor_models) > 10:
            print(f"  ... and {len(cursor_models) - 10} more", file=sys.stderr)


def cmd_run(args):
    """Run a one-shot task with intelligent model routing."""
    prompt = args.prompt
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    if not prompt:
        print("Error: no prompt provided", file=sys.stderr)
        sys.exit(1)

    # Model selection
    if args.model:
        model = args.model
        spec = MODEL_CATALOG.get(model)
        if spec:
            print(f"Using explicit model: {model} ({spec.name})", file=sys.stderr)
        else:
            print(f"Using explicit model: {model}", file=sys.stderr)
    else:
        category, confidence = classify_task(prompt)
        model = select_model(prompt)
        spec = MODEL_CATALOG.get(model)
        print(f"Task classified as: {category} (confidence={confidence:.2f})",
              file=sys.stderr)
        if spec:
            print(f"Selected model: {model} ({spec.name}, tier={spec.cost_tier})",
                  file=sys.stderr)
        else:
            print(f"Selected model: {model}", file=sys.stderr)

    print(f"Running...", file=sys.stderr)

    result = call_agent(
        prompt=prompt,
        model=model,
        timeout=args.timeout,
    )

    if result["success"]:
        metrics = result.get("metrics")
        if metrics:
            print(f"\n--- Usage ---", file=sys.stderr)
            print(f"  Input tokens: {metrics.input_tokens:,}", file=sys.stderr)
            print(f"  Output tokens: {metrics.output_tokens:,}", file=sys.stderr)
            print(f"  Duration: {metrics.duration_ms / 1000:.1f}s", file=sys.stderr)
            if metrics.cost_estimate_usd > 0:
                print(f"  Est. cost: ${metrics.cost_estimate_usd:.6f}", file=sys.stderr)

        # Output the result
        print(result["result"])
    else:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)


def cmd_classify(args):
    """Classify a prompt and show which model would be selected."""
    prompt = args.prompt
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    if not prompt:
        print("Error: no prompt provided", file=sys.stderr)
        sys.exit(1)

    category, confidence = classify_task(prompt)
    model = select_model(prompt, preferred_model=args.model)
    spec = MODEL_CATALOG.get(model)

    print(json.dumps({
        "prompt": prompt[:100] + ("..." if len(prompt) > 100 else ""),
        "classification": {
            "category": category,
            "confidence": round(confidence, 3),
        },
        "selectedModel": {
            "id": model,
            "name": spec.name if spec else "unknown",
            "costTier": spec.cost_tier if spec else 0,
            "contextWindow": spec.context_window if spec else 0,
        },
    }, indent=2, ensure_ascii=False))


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="cursor-acp-hermes — Intelligent ACP adapter for Cursor Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              cursor-acp-hermes                        # Start ACP server (for Hermes)
              cursor-acp-hermes run "Write a function"  # One-shot task
              cursor-acp-hermes models                  # List models
              cursor-acp-hermes status                  # Check status
              cursor-acp-hermes classify "Fix bug in..." # See which model would be used
        """),
    )
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")
    parser.add_argument("--version", action="store_true",
                        help="Show version")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run a one-shot task")
    run_parser.add_argument("prompt", nargs="?", default="",
                            help="Task prompt")
    run_parser.add_argument("--model", "-m", default="",
                            help="Override model selection")
    run_parser.add_argument("--timeout", "-t", type=int, default=120,
                            help="Timeout in seconds")

    # Models command
    subparsers.add_parser("models", help="List available models")

    # Status command
    subparsers.add_parser("status", help="Check cursor-agent status")

    # Classify command
    classify_parser = subparsers.add_parser("classify",
                                             help="Classify a task and show model selection")
    classify_parser.add_argument("prompt", nargs="?", default="",
                                 help="Task prompt to classify")
    classify_parser.add_argument("--model", "-m", default="",
                                 help="Preferred model override")

    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    if args.version:
        print(f"cursor-acp-hermes v{__version__}")
        return

    if args.command == "status":
        cmd_status(args)
    elif args.command == "models":
        cmd_models(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "classify":
        cmd_classify(args)
    else:
        # Default: start ACP server (stdio mode)
        adapter = AcpAdapter()
        try:
            adapter.run()
        except KeyboardInterrupt:
            print("\nShutting down...", file=sys.stderr)
        except BrokenPipeError:
            # Parent process closed stdin
            pass


if __name__ == "__main__":
    main()
