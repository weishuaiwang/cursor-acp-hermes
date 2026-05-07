"""
Debug ACP communication issues - test with session/new and content blocks.
"""
import subprocess, json, time, threading, sys

proc = subprocess.Popen(
    ["cursor-acp-hermes", "--verbose"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

out_lines = []
def reader():
    for line in iter(proc.stdout.readline, ""):
        out_lines.append(line.strip())
threading.Thread(target=reader, daemon=True).start()

err_lines = []
def err_reader():
    for line in iter(proc.stderr.readline, ""):
        err_lines.append(line.strip())
threading.Thread(target=err_reader, daemon=True).start()

def send(method, params=None, mid=1):
    msg = {"jsonrpc": "2.0", "method": method, "id": mid}
    if params is not None:
        msg["params"] = params
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    deadline = time.time() + 30
    while time.time() < deadline:
        for i, line in enumerate(out_lines):
            try:
                data = json.loads(line)
                if data.get("id") == mid:
                    del out_lines[i]
                    return data
            except (json.JSONDecodeError, KeyError):
                continue
        time.sleep(0.05)
    return None

time.sleep(0.5)

# Test 1: Initialize
r = send("initialize", mid=1)
if r and "result" in r:
    print("✓ INITIALIZE")
else:
    print(f"✗ INITIALIZE: {r}")

# Test 2: session/new with goal in metadata
r = send("session/new", {"metadata": {"goal": "Write a Python function"}}, mid=2)
if r and "result" in r:
    print(f"✓ SESSION/NEW (metadata): model={r['result']['model']['id']}")
else:
    print(f"✗ SESSION/NEW (metadata): {r}")

# Test 3: session/prompt with content array (ACP standard format)
r = send("session/prompt", {
    "sessionId": r["result"]["sessionId"],
    "content": [{"type": "text", "text": "Write hello world in Python"}],
}, mid=3)
if r and "result" in r:
    content = r["result"].get("content", [])
    text = content[0].get("text", "") if content else ""
    print(f"✓ PROMPT (content blocks): {text[:60]}...")
else:
    print(f"✗ PROMPT (content blocks): {r.get('error', r)[:100] if r else 'no response'}")

# Test 4: session/create (alternative method name)
r = send("session/create", {"metadata": {"task": "debug"}}, mid=4)
if r and "result" in r:
    print(f"✓ SESSION/CREATE: model={r['result']['model']['id']}")
else:
    print(f"✗ SESSION/CREATE: {r}")

# Test 5: Shutdown
r = send("shutdown", mid=5)
if r and "result" in r:
    print("✓ SHUTDOWN")

proc.stdin.close()
proc.wait(timeout=5)

# Print any errors from stderr
err_output = [l for l in err_lines if "ERROR" in l or "error" in l.lower()]
if err_output:
    print(f"\nStderr errors ({len(err_output)}):")
    for e in err_output[:5]:
        print(f"  {e}")
