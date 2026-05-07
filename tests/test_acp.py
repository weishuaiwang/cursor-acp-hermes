"""
Test ACP adapter — full lifecycle including prompt execution.
"""
import subprocess, json, sys, time, threading

proc = subprocess.Popen(
    ["cursor-acp-hermes"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True,
)

# Non-blocking stdout reader
stdout_lines = []
def read_stdout():
    for line in iter(proc.stdout.readline, ""):
        stdout_lines.append(line.strip())
t = threading.Thread(target=read_stdout, daemon=True)
t.start()

def send(method, params=None, mid=1):
    msg = {"jsonrpc": "2.0", "method": method, "id": mid}
    if params:
        msg["params"] = params
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    deadline = time.time() + 60
    while time.time() < deadline:
        for i, line in enumerate(stdout_lines):
            try:
                data = json.loads(line)
                if data.get("id") == mid:
                    del stdout_lines[i]
                    return data
            except (json.JSONDecodeError, KeyError):
                continue
        time.sleep(0.05)
    return None

passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  ✓ {name}")
        passed += 1
    except Exception as e:
        print(f"  ✗ {name}: {e}")
        failed += 1

time.sleep(0.5)

print("🚀 cursor-acp-hermes ACP Adapter Tests\n")

# 1. Initialize
r = send("initialize")
test("Initialize", lambda: (
    r is not None and "result" in r or (_ for _ in []).throw(AssertionError(f"Got: {r}")),
    r["result"]["agentInfo"]["name"] == "cursor-acp-hermes" or (_ for _ in []).throw(AssertionError("Wrong name")),
))

# 2. Create session (simple → cheap model)
r = send("session/create", {"metadata": {"task": "What is 2+2?"}}, mid=2)
test("Session create (simple task → cheap model)", lambda: (
    r is not None and "result" in r or (_ for _ in []).throw(AssertionError(f"Got: {r}")),
    r["result"]["model"]["id"] in ("composer-2-fast", "gpt-5.4-mini", "gpt-5.4-nano") or
        (_ for _ in []).throw(AssertionError(f"Expected cheap model, got {r['result']['model']['id']}")),
))
sess_id = r["result"]["sessionId"]

# 3. Prompt on cheap model
r = send("session/prompt", {
    "sessionId": sess_id,
    "prompt": "Return just the word: hello_python",
}, mid=3)
test("Session prompt (execute task)", lambda: (
    r is not None and "result" in r or (_ for _ in []).throw(AssertionError(f"Got: {r}")),
    "content" in r["result"] or (_ for _ in []).throw(AssertionError("No content")),
))
if r and "result" in r:
    usage = r["result"].get("usage", {})
    print(f"    Tokens: {usage.get('inputTokens','?')}i / {usage.get('outputTokens','?')}o | "
          f"${usage.get('costEstimateUsd', 0):.6f} | {usage.get('durationMs', 0)}ms")

# 4. Auto-create session (by omitting sessionId)
r = send("session/prompt", {
    "sessionId": "",
    "prompt": "Debug why this Python code crashes: x = 1/0",
}, mid=4)
test("Auto-create session + debug routing", lambda: (
    r is not None and "result" in r or (_ for _ in []).throw(AssertionError(f"Got: {r}")),
    r["result"].get("sessionId", "") != "" or (_ for _ in []).throw(AssertionError("No sessionId")),
))

# 5. Models list
r = send("models/list", mid=5)
test("List models", lambda: (
    r is not None and "result" in r or (_ for _ in []).throw(AssertionError(f"Got: {r}")),
    len(r["result"]["models"]) > 0 or (_ for _ in []).throw(AssertionError("No models")),
    any(m["source"] == "catalog" for m in r["result"]["models"]) or
        (_ for _ in []).throw(AssertionError("No catalog models")),
))

# 6. Sessions list
r = send("sessions/list", mid=6)
test("List sessions", lambda: (
    r is not None and "result" in r or (_ for _ in []).throw(AssertionError(f"Got: {r}")),
    len(r["result"]["sessions"]) >= 1 or (_ for _ in []).throw(AssertionError("No sessions")),
))

# 7. Shutdown
r = send("shutdown", mid=7)
test("Shutdown", lambda: (
    r is not None and "result" in r or (_ for _ in []).throw(AssertionError(f"Got: {r}")),
))

proc.stdin.close()
proc.wait(timeout=5)

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed, {passed+failed} total")
if failed == 0:
    print("✨ All tests passed!")
else:
    print(f"⚠  {failed} test(s) failed")
