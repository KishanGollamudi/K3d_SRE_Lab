import json
import os
import subprocess
import sys
import urllib.request

NAMESPACE = sys.argv[1] if len(sys.argv) > 1 else "agent-lab"
POD = sys.argv[2] if len(sys.argv) > 2 else "broken-worker"


def run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)
    return (res.stdout or "") + (res.stderr or "")


def get_logs(ns: str, pod: str) -> str:
    prev = run(["kubectl", "logs", pod, "-n", ns, "--previous"])
    if "unable to retrieve container logs" not in prev.lower() and prev.strip():
        return prev
    curr = run(["kubectl", "logs", pod, "-n", ns])
    return f"[--previous unavailable; current container logs:]\n{curr}"


evidence = {
    "pod_status": run(["kubectl", "get", "pod", POD, "-n", NAMESPACE, "-o", "yaml"]),
    "events": run([
        "kubectl", "get", "events", "-n", NAMESPACE,
        "--field-selector", f"involvedObject.name={POD}",
        "--sort-by=.lastTimestamp",
    ]),
    "logs": get_logs(NAMESPACE, POD),
}

base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
api_key = os.getenv("LLM_API_KEY", "")
model = os.getenv("LLM_MODEL", "gpt-4o-mini")

if not base_url:
    print("=== EVIDENCE COLLECTED (set LLM_BASE_URL to run AI diagnosis) ===")
    for k, v in evidence.items():
        print(f"\n--- {k.upper()} ---\n{v.strip()}")
    sys.exit(0)

prompt = f"""You are a read-only Kubernetes DevOps diagnostic agent.
Analyze ONLY the evidence below. Do not invent facts or logs not present.
Return valid JSON with keys:
- "root_cause": string
- "evidence_cited": list of strings
- "confidence": "high" | "medium" | "low"
- "recommended_fix": string

Evidence:
{json.dumps(evidence, indent=2)}
"""

req = urllib.request.Request(
    f"{base_url}/chat/completions",
    data=json.dumps({
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": "Respond strictly with valid JSON."},
            {"role": "user", "content": prompt},
        ],
    }).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
    },
    method="POST",
)

with urllib.request.urlopen(req, timeout=60) as resp:
    body = json.loads(resp.read().decode("utf-8"))
    print(body["choices"][0]["message"]["content"])
