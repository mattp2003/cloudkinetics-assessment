"""Quick CLI to inspect conversation history for a given verified user."""
import sys
import os

# Load .env before importing anything that reads env vars
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from ck_agent.session_store import get_user_history  # noqa: E402

if len(sys.argv) < 2:
    print("usage: python scripts/inspect_history.py <user_email> [limit]")
    sys.exit(1)

user_email = sys.argv[1]
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 50

history = get_user_history(user_email, limit=limit)
print(f"Found {len(history)} messages for {user_email}\n")

for msg in history:
    role = msg.get("role", "?")
    content = msg.get("content", [])
    # Extract first text block; summarise tool use/results
    text = None
    for block in content:
        if "text" in block:
            text = block["text"][:120]
            break
        if "toolUse" in block:
            tu = block["toolUse"]
            text = f"[tool_use: {tu['name']}({list(tu.get('input', {}).keys())})]"
            break
        if "toolResult" in block:
            inner = block["toolResult"].get("content", [])
            inner_text = next((b.get("text", "") for b in inner if "text" in b), "")
            text = f"[tool_result: {inner_text[:80]}]"
            break
    safe = (text or "[no text]").encode("ascii", errors="replace").decode("ascii")
    print(f"  [{role:9s}] {safe}")
