import json
import os
import re
import subprocess
import sys
import urllib.request

DEFAULT_NS = sys.argv[1] if len(sys.argv) > 1 else "agent-lab"
TARGET_POD = sys.argv[2] if len(sys.argv) > 2 else ""


def kubectl_run(args: list[str]) -> str:
    res = subprocess.run(["kubectl", *args], capture_output=True, text=True, timeout=20)
    out = (res.stdout or "").strip()
    err = (res.stderr or "").strip()
    if res.returncode != 0 and not out:
        return f"[kubectl error rc={res.returncode}] {err}"
    return out if not err else f"{out}\n[stderr] {err}"


def tool_list_unhealthy_pods(namespace: str = DEFAULT_NS) -> str:
    raw = kubectl_run(["get", "pods", "-n", namespace, "-o", "json"])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    findings = []
    for item in data.get("items", []):
        name = item.get("metadata", {}).get("name")
        phase = item.get("status", {}).get("phase")
        statuses = item.get("status", {}).get("containerStatuses", [])
        unhealthy = []
        for cs in statuses:
            waiting = cs.get("state", {}).get("waiting", {})
            last_term = cs.get("lastState", {}).get("terminated", {})
            if not cs.get("ready") or cs.get("restartCount", 0) > 0 or waiting:
                unhealthy.append({
                    "container": cs.get("name"),
                    "ready": cs.get("ready"),
                    "restarts": cs.get("restartCount", 0),
                    "waiting_reason": waiting.get("reason"),
                    "waiting_msg": waiting.get("message"),
                    "last_exit_code": last_term.get("exitCode"),
                    "last_reason": last_term.get("reason"),
                })
        if unhealthy or phase not in ("Running", "Succeeded"):
            findings.append({"pod": name, "phase": phase, "containers": unhealthy})
    return json.dumps({"namespace": namespace, "unhealthy_pods": findings}, indent=2)


def tool_get_pod_summary(namespace: str, pod: str) -> str:
    raw = kubectl_run(["get", "pod", pod, "-n", namespace, "-o", "json"])
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    spec = d.get("spec", {})
    status = d.get("status", {})
    compact_statuses = [
        {
            "name": cs.get("name"),
            "ready": cs.get("ready"),
            "restartCount": cs.get("restartCount", 0),
            "state": cs.get("state"),
            "lastState": cs.get("lastState"),
        }
        for cs in status.get("containerStatuses", [])
    ]
    summary = {
        "name": d.get("metadata", {}).get("name"),
        "namespace": namespace,
        "nodeName": spec.get("nodeName"),
        "restartPolicy": spec.get("restartPolicy"),
        "containers": [
            {
                "name": c.get("name"),
                "image": c.get("image"),
                "command": c.get("command"),
                "args": c.get("args"),
            }
            for c in spec.get("containers", [])
        ],
        "containerStatuses": compact_statuses,
    }
    return json.dumps(summary, indent=2)


def tool_get_pod_events(namespace: str, pod: str) -> str:
    return kubectl_run([
        "get", "events", "-n", namespace,
        "--field-selector", f"involvedObject.name={pod}",
        "--sort-by=.lastTimestamp",
    ])


def tool_get_pod_logs(namespace: str, pod: str, container: str = "") -> str:
    base_args = ["logs", pod, "-n", namespace, "--tail=40"]
    if container:
        base_args.extend(["-c", container])
    prev = kubectl_run([*base_args, "--previous"])
    if not prev.startswith("[kubectl error"):
        return f"[previous logs]\n{prev}"
    curr = kubectl_run(base_args)
    return f"[--previous unavailable; current logs]\n{curr}"


TOOLS = {
    "list_unhealthy_pods": {
        "fn": tool_list_unhealthy_pods,
        "schema": {
            "type": "function",
            "function": {
                "name": "list_unhealthy_pods",
                "description": "List pods in a namespace that are not ready, have restarts, or have waiting states.",
                "parameters": {
                    "type": "object",
                    "properties": {"namespace": {"type": "string"}},
                    "required": ["namespace"],
                },
            },
        },
    },
    "get_pod_summary": {
        "fn": tool_get_pod_summary,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_pod_summary",
                "description": "Get container command/image spec and containerStatuses for a pod.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string"},
                        "pod": {"type": "string"},
                    },
                    "required": ["namespace", "pod"],
                },
            },
        },
    },
    "get_pod_events": {
        "fn": tool_get_pod_events,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_pod_events",
                "description": "Get Kubernetes events for a specific pod.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string"},
                        "pod": {"type": "string"},
                    },
                    "required": ["namespace", "pod"],
                },
            },
        },
    },
    "get_pod_logs": {
        "fn": tool_get_pod_logs,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_pod_logs",
                "description": "Fetch previous container logs with fallback to current logs.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string"},
                        "pod": {"type": "string"},
                        "container": {"type": "string"},
                    },
                    "required": ["namespace", "pod"],
                },
            },
        },
    },
}


def call_llm(messages: list[dict], base_url: str, api_key: str, model: str) -> dict:
    payload = {
        "model": model,
        "temperature": 0.0,
        "max_tokens": 256,
        "messages": messages,
        "tools": [t["schema"] for t in TOOLS.values()],
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def clean_final_output(raw: str) -> str:
    # Strip any trailing hallucinated turn markers like "<tool_call>\nuser..."
    trimmed = re.split(r"\n*(?:<tool_call>\s*)?user\b", raw, maxsplit=1)[0].strip()
    # Extract JSON block if wrapped in markdown fences
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", trimmed, flags=re.DOTALL)
    if fence:
        trimmed = fence.group(1).strip()
    try:
        parsed = json.loads(trimmed)
        return json.dumps(parsed, indent=2)
    except json.JSONDecodeError:
        return trimmed


def main() -> None:
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-3B-Instruct").strip()

    if not base_url:
        print("[*] LLM_BASE_URL not set; running read-only tool check on namespace:", DEFAULT_NS)
        print(tool_list_unhealthy_pods(DEFAULT_NS))
        if TARGET_POD:
            print(tool_get_pod_summary(DEFAULT_NS, TARGET_POD))
            print(tool_get_pod_events(DEFAULT_NS, TARGET_POD))
            print(tool_get_pod_logs(DEFAULT_NS, TARGET_POD))
        return

    user_goal = (
        f"Investigate pod '{TARGET_POD}' in namespace '{DEFAULT_NS}'."
        if TARGET_POD
        else f"Find and diagnose unhealthy pods in namespace '{DEFAULT_NS}'."
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a read-only Kubernetes DevOps diagnostic agent. "
                "First call tools to inspect the pod spec, status, events, and logs. "
                "Quote exact facts from tool outputs (such as container command, exitCode, waiting reason, and log lines). "
                "Never claim logs are missing if tool output returned lines. "
                "Output ONLY a single valid JSON object with no extra text, using this exact schema:\n"
                '{"root_cause": "...", "evidence_cited": ["..."], "confidence": "high|medium|low", "recommended_fix": "..."}'
            ),
        },
        {"role": "user", "content": user_goal},
    ]

    max_steps = 5
    for step in range(1, max_steps + 1):
        resp = call_llm(messages, base_url, api_key, model)
        msg = resp["choices"][0]["message"]
        messages.append(msg)

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            final_text = clean_final_output(msg.get("content") or "")
            print(f"\n=== FINAL DIAGNOSIS (step {step}) ===\n{final_text}")
            return

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            raw_args = tc["function"].get("arguments") or "{}"
            args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
            print(f"[step {step}] tool={fn_name} args={args}")
            entry = TOOLS.get(fn_name)
            result = entry["fn"](**args) if entry else f"Unknown tool: {fn_name}"
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

    print("[!] Reached max_steps without a final answer.")


if __name__ == "__main__":
    main()
