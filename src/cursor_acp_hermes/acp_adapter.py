"""
ACP Protocol Adapter — JSON-RPC 2.0 over stdio.

Implements the Agent Client Protocol (ACP) that Hermes delegate_task
expects when using acp_command. Handles:
  - initialize / shutdown (lifecycle)
  - session/create, session/prompt, session/cancel (task execution)
  - Model routing via model_router
"""

import json
import logging
import os
import sys
import time
import uuid
from typing import Any, Dict, Optional

from .cursor_bridge import call_agent, check_available, list_models
from .model_router import select_model, get_model_spec, list_available_models
from .types import Session, UsageMetrics

logger = logging.getLogger(__name__)

# Version info
VERSION = "0.1.0"
PROTOCOL_VERSION = "0.1.0"

# ─── ACP Protocol Implementation ─────────────────────────────────────────────

class AcpAdapter:
    """
    ACP protocol adapter that reads JSON-RPC 2.0 from stdin and writes to stdout.

    Protocol methods:
      - initialize          → agent capabilities
      - shutdown            → clean exit
      - session/create      → create session with model selection
      - session/prompt      → execute a task with the selected model
      - session/cancel      → cancel ongoing task
    """

    def __init__(self):
        self.sessions: Dict[str, Session] = {}
        self.current_prompt: Optional[Dict] = None
        self.running = True
        self._check_cursor()

    def _check_cursor(self):
        """Verify cursor-agent is available on startup."""
        available, msg = check_available()
        if not available:
            logger.warning(f"cursor-agent check: {msg}")

    # ── Message Dispatch ──────────────────────────────────────────────────

    def handle_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Dispatch an incoming JSON-RPC message to the appropriate handler.
        Returns the response dict, or None for notifications (no id).
        """
        msg_id = message.get("id")
        method = message.get("method", "")
        params = message.get("params", {}) or {}

        logger.debug(f"Received method={method} id={msg_id}")

        # Method routing
        if method == "initialize":
            return self._handle_initialize(params, msg_id)
        elif method == "shutdown":
            return self._handle_shutdown(params, msg_id)
        elif method in ("session/create", "session/new"):
            return self._handle_session_create(params, msg_id)
        elif method in ("session/prompt", "session/complete"):
            return self._handle_session_prompt(params, msg_id)
        elif method in ("session/cancel", "session/cancel"):
            return self._handle_session_cancel(params, msg_id)
        elif method in ("sessions/list", "session/list"):
            return self._handle_sessions_list(params, msg_id)
        elif method in ("sessions/delete", "session/delete"):
            return self._handle_sessions_delete(params, msg_id)
        elif method in ("models/list", "model/list"):
            return self._handle_models_list(params, msg_id)
        else:
            return self._error(msg_id, -32601, f"Method not found: {method}")

    # ── Handlers ──────────────────────────────────────────────────────────

    def _handle_initialize(self, params: Dict, msg_id: Optional[int]) -> Dict:
        """ACP initialize — announce capabilities."""
        return self._result(msg_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "session": {
                    "create": True,
                    "prompt": True,
                    "cancel": True,
                    "list": True,
                    "delete": True,
                },
                "models": {
                    "list": True,
                    "select": True,
                },
                "streaming": True,
            },
            "agentInfo": {
                "name": "cursor-acp-hermes",
                "version": VERSION,
                "description": "Intelligent ACP adapter for Cursor Agent with model routing",
            },
            "serverInfo": {
                "cursorAgent": CURSOR_AGENT_VERSION,
            }
        })

    def _handle_shutdown(self, params: Dict, msg_id: Optional[int]) -> Dict:
        """ACP shutdown — prepare for clean exit."""
        self.running = False
        return self._result(msg_id, {"shutdown": "ok"})

    def _handle_session_create(self, params: Dict, msg_id: Optional[int]) -> Dict:
        """Create a new session with intelligent model selection."""
        session_id = str(uuid.uuid4())

        # Extract the task/prompt for model routing
        prompt_text = ""
        if "task" in params:
            prompt_text = params["task"]
        elif "goal" in params:
            prompt_text = params["goal"]
        elif "metadata" in params:
            meta = params["metadata"]
            prompt_text = meta.get("task", meta.get("goal", meta.get("prompt", "")))

        # Model selection
        preferred_model = params.get("model") or os.environ.get("CURSOR_ACP_MODEL")
        max_tier = int(os.environ.get("CURSOR_ACP_MAX_TIER", "5"))

        model_id = select_model(
            prompt=prompt_text,
            preferred_model=preferred_model,
            max_cost_tier=max_tier,
        )

        model_spec = get_model_spec(model_id)

        # Create session
        session = Session(
            session_id=session_id,
            model_id=model_id,
            created_at=time.time(),
            metadata={
                **params.get("metadata", {}),
                "selectedModel": model_id,
                "modelName": model_spec.name if model_spec else model_id,
            },
        )
        self.sessions[session_id] = session

        logger.info(f"Session created: {session_id[:8]} → model={model_id}")

        return self._result(msg_id, {
            "sessionId": session_id,
            "model": {
                "id": model_id,
                "name": model_spec.name if model_spec else model_id,
                "contextWindow": model_spec.context_window if model_spec else 64000,
            },
        })

    def _handle_session_prompt(self, params: Dict, msg_id: Optional[int]) -> Dict:
        """Execute a task prompt using the selected Cursor model."""
        session_id = params.get("sessionId", "")

        # Extract prompt text from content blocks (ACP standard)
        prompt_text = ""
        raw_prompt = params.get("prompt", params.get("content", ""))
        if isinstance(raw_prompt, list):
            for block in raw_prompt:
                if isinstance(block, dict):
                    prompt_text += block.get("text", "")
                elif isinstance(block, str):
                    prompt_text += block
        elif isinstance(raw_prompt, str):
            prompt_text = raw_prompt

        if not prompt_text:
            return self._error(msg_id, -32002, "No prompt text provided")

        # Get or create session
        if session_id and session_id in self.sessions:
            session = self.sessions[session_id]
        else:
            # Auto-create session
            create_resp = self._handle_session_create(
                {"task": prompt_text},
                None,
            )
            if create_resp and "result" in create_resp:
                session_id = create_resp["result"]["sessionId"]
                session = self.sessions.get(session_id)
                if not session:
                    return self._error(msg_id, -32000, "Failed to create session")
            else:
                return self._error(msg_id, -32000, "Failed to create session")

        model_id = session.model_id

        # Stream progress notification
        self._send_notification("session/update", {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "status",
                "content": {"text": f"🤖 Using {model_id}..."},
            },
        })

        # Call cursor-agent
        result = call_agent(
            prompt=prompt_text,
            model=model_id,
            timeout=120,
        )

        # Update conversation history
        session.conversation.append({
            "role": "user",
            "content": prompt_text,
            "timestamp": time.time(),
        })

        response_text = result.get("result", "")

        # Stream response back via session/update notifications (ACP streaming)
        if response_text:
            # Send in chunks
            chunk_size = 500
            for i in range(0, len(response_text), chunk_size):
                chunk = response_text[i:i + chunk_size]
                self._send_notification("session/update", {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"text": chunk},
                    },
                })

        # Final result notification
        self._send_notification("session/update", {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "agent_message_final",
                "content": {"text": response_text},
            },
        })

        # Update session
        session.conversation.append({
            "role": "assistant",
            "content": response_text,
            "timestamp": time.time(),
        })

        if not result["success"]:
            return self._error(msg_id, -32000, result.get("error", "Unknown error"))

        # Build response
        metrics = result.get("metrics")
        response = {
            "sessionId": session_id,
            "content": [
                {
                    "type": "text",
                    "text": response_text,
                }
            ],
        }
        if metrics:
            response["usage"] = {
                "model": metrics.model,
                "inputTokens": metrics.input_tokens,
                "outputTokens": metrics.output_tokens,
                "cacheReadTokens": metrics.cache_read_tokens,
                "cacheWriteTokens": metrics.cache_write_tokens,
                "durationMs": metrics.duration_ms,
                "costEstimateUsd": round(metrics.cost_estimate_usd, 6),
            }

        return self._result(msg_id, response)

    def _handle_session_cancel(self, params: Dict, msg_id: Optional[int]) -> Dict:
        """Cancel an ongoing session."""
        session_id = params.get("sessionId", "")
        if session_id and session_id in self.sessions:
            logger.info(f"Session cancelled: {session_id[:8]}")
        return self._result(msg_id, {"cancelled": True})

    def _handle_sessions_list(self, params: Dict, msg_id: Optional[int]) -> Dict:
        """List active sessions."""
        session_list = []
        for sid, session in self.sessions.items():
            session_list.append({
                "sessionId": sid,
                "model": session.model_id,
                "createdAt": session.created_at,
                "messageCount": len(session.conversation) // 2,
                "metadata": session.metadata,
            })
        return self._result(msg_id, {"sessions": session_list})

    def _handle_sessions_delete(self, params: Dict, msg_id: Optional[int]) -> Dict:
        """Delete a session."""
        session_id = params.get("sessionId", "")
        if session_id in self.sessions:
            del self.sessions[session_id]
            return self._result(msg_id, {"deleted": True})
        return self._error(msg_id, -32000, f"Session not found: {session_id}")

    def _handle_models_list(self, params: Dict, msg_id: Optional[int]) -> Dict:
        """List available models."""
        catalog = list_available_models()
        cursor_models = list_models()

        models = [
            {
                "id": mid,
                "name": name,
                "source": "catalog",
            }
            for mid, name in catalog.items()
        ]

        # Merge in cursor-agent's actual model list
        known_ids = set(catalog.keys())
        for m in cursor_models:
            if m["id"] not in known_ids:
                models.append({
                    "id": m["id"],
                    "name": m["name"],
                    "source": "cursor-agent",
                })

        return self._result(msg_id, {"models": models})

    # ── JSON-RPC Helpers ──────────────────────────────────────────────────

    def _result(self, msg_id: Optional[int], result: Any) -> Dict:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": result,
        }

    def _error(self, msg_id: Optional[int], code: int, message: str,
               data: Any = None) -> Dict:
        err: Dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": err,
        }

    def _send_notification(self, method: str, params: Dict):
        """Send a JSON-RPC notification (no id) to stdout."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        line = json.dumps(notification, ensure_ascii=False)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    # ── Main Loop ─────────────────────────────────────────────────────────

    def run(self):
        """Main ACP event loop — reads JSON-RPC from stdin, writes to stdout."""
        logger.info(f"cursor-acp-hermes v{VERSION} — ACP adapter starting")
        logger.info(f"cursor-agent: {CURSOR_AGENT_VERSION}")

        # Write startup log to stderr (stdout is reserved for ACP)
        print(f"[cursor-acp-hermes] v{VERSION} ready — ACP protocol {PROTOCOL_VERSION}",
              file=sys.stderr)

        # Signal readiness
        self._send_notification("initialized", {
            "version": VERSION,
            "protocol": PROTOCOL_VERSION,
        })

        while self.running:
            try:
                # Read one JSON-RPC message per line (ACP ndjson format)
                line = sys.stdin.readline()
                if not line:
                    # EOF
                    break
                line = line.strip()
                if not line:
                    continue

                try:
                    message = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON: {e}")
                    response = self._error(
                        None, -32700, f"Parse error: {e}"
                    )
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
                    continue

                response = self.handle_message(message)
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()

            except EOFError:
                break
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"ACP loop error: {e}")
                try:
                    response = self._error(None, -32603, f"Internal error: {e}")
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
                except Exception:
                    pass

        logger.info("ACP adapter shutdown complete")


# Module-level reference for version reporting
CURSOR_AGENT_VERSION = os.environ.get(
    "CURSOR_AGENT_VERSION",
    "bundled"
)
