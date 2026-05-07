"""
Debug test - show raw communication.
"""
import subprocess, json, time, threading

proc = subprocess.Popen(
    ["cursor-acp-hermes"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

stdout_lines = []
def read_stdout():
    for line in iter(proc.stdout.readline, ""):
        stdout_lines.append(line.strip())
t = threading.Thread(target=read_stdout, daemon=True)
t.start()

stderr_lines = []
def read_stderr():
    for line in iter(proc.stderr.readline, ""):
        stderr_lines.append(line.strip())
t2 = threading.Thread(target=read_stderr, daemon=True)
t2.start()

time.sleep(1)

# Send initialize
proc.stdin.write('{"jsonrpc":"2.0","method":"initialize","id":1}\n')
proc.stdin.flush()

time.sleep(2)

print("=== STDOUT ===")
for l in stdout_lines:
    print(f"  {l[:200]}")

print("\n=== STDERR ===")
for l in stderr_lines:
    print(f"  {l[:200]}")

proc.stdin.close()
proc.wait(timeout=5)
print(f"\nExit: {proc.returncode}")
