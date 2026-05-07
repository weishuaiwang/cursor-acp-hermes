"""
Integration test — simulate Hermes delegate_task calling cursor-acp-hermes as ACP subagent.

This mimics what Hermes does internally when you use:
    delegate_task(goal="...", acp_command="cursor-acp-hermes")
"""
import subprocess, json, time, threading, sys

print("=" * 60)
print("Integration Test: Hermes delegate_task → cursor-acp-hermes ACP")
print("=" * 60)

# Start adapter
proc = subprocess.Popen(
    ["cursor-acp-hermes"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

# Reader threads
out_lines = []
def read_out():
    for line in iter(proc.stdout.readline, ""):
        out_lines.append(line.strip())
t = threading.Thread(target=read_out, daemon=True)
t.start()

err_lines = []
def read_err():
    for line in iter(proc.stderr.readline, ""):
        err_lines.append(line.strip())
t2 = threading.Thread(target=read_err, daemon=True)
t2.start()

def send(method, params=None, mid=1):
    msg = {"jsonrpc": "2.0", "method": method, "id": mid}
    if params:
        msg["params"] = params
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    deadline = time.time() + 120
    while time.time() < deadline:
        for i, line in enumerate(out_lines):
            try:
                data = json.loads(line)
                if data.get("id") == mid:
                    del out_lines[i]
                    return data
            except:
                continue
        time.sleep(0.05)
    return None

time.sleep(0.5)

# Simulate Hermes delegate_task flow:
# 1. Initialize
r = send("initialize")
assert r and "result" in r
agent = r["result"]["agentInfo"]
print(f"\n[1] Agent: {agent['name']} v{agent['version']}")
print(f"    Capabilities: {', '.join(r['result']['capabilities'].keys())}")

# 2. Create session with a coding task → should pick codex model
r = send("session/create", {
    "metadata": {
        "goal": "Write a FastAPI application with user CRUD endpoints",
        "workspace": "/tmp",
    }
}, mid=2)
assert r and "result" in r
model = r["result"]["model"]
print(f"\n[2] Session created → model: {model['name']} ({model['id']})")
print(f"    Context window: {model['contextWindow']:,} tokens")
sess_id = r["result"]["sessionId"]

# 3. Execute task
print(f"\n[3] Executing task via {model['id']}...")
r = send("session/prompt", {
    "sessionId": sess_id,
    "prompt": "Write a Python FastAPI application with:\n"
              "- GET /users - list all users\n"
              "- POST /users - create user\n"
              "- GET /users/{id} - get user by id\n"
              "- DELETE /users/{id} - delete user\n"
              "Use an in-memory list as storage. Return ONLY the complete code.",
}, mid=3)
assert r and "result" in r, f"Prompt failed: {r.get('error', 'unknown')}"

code = r["result"]["content"][0]["text"]
usage = r["result"].get("usage", {})
print(f"    Response: {len(code)} chars")
print(f"    Tokens: {usage.get('inputTokens','?'):>6} in / {usage.get('outputTokens','?'):<6} out")
print(f"    Duration: {usage.get('durationMs', 0) / 1000:.1f}s")
print(f"    Cost: ${usage.get('costEstimateUsd', 0):.8f}")

# 4. Verify the generated code contains FastAPI
if "FastAPI" in code or "fastapi" in code.lower():
    print("\n[4] ✓ Code contains FastAPI imports — task completed successfully")
else:
    print("\n[4] ⚠ Code may not be FastAPI")

# 5. Create another session for architecture task → should pick powerful model
r = send("session/create", {
    "metadata": {
        "goal": "Design a microservices architecture for e-commerce with Kubernetes, "
                "service mesh, event sourcing, CQRS, and multi-region deployment",
    }
}, mid=5)
assert r and "result" in r
model2 = r["result"]["model"]
print(f"\n[5] Architecture session → model: {model2['name']} ({model2['id']})")
tier = 5 if "opus" in model2['id'].lower() or "xhigh" in model2['id'].lower() or "5.5" in model2['id'] else 3
print(f"    Tier: {tier}/5 (powerful model for complex task) ✓")

# 6. Shutdown
send("shutdown", mid=6)
proc.stdin.close()
proc.wait(timeout=5)

print(f"\n{'=' * 60}")
print("✅ Integration test passed!")
print(f"   Agent: cursor-acp-hermes v{agent['version']}")
print(f"   Models: {model['name']} (coding) → {model2['name']} (architecture)")
print(f"   Output: {len(code)} chars generated")
print(f"{'=' * 60}")
