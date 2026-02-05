#!/usr/bin/env python3
import argparse
import csv
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
import requests

DEFAULT_BASE_URL = "https://chat.ai.e-infra.cz/api/v1"
DEFAULT_MODEL = "gpt-oss-120b"


def parse_args():
    p = argparse.ArgumentParser(
        description="Summarize the generic/typical attacker flow using LLM."
    )
    p.add_argument("--csv", required=True, help="Path to experiment_coder56_*.csv")
    p.add_argument("--outputs-root", required=True, help="Root outputs directory.")
    p.add_argument("--out-dir", default=None, help="Output directory for report.")
    p.add_argument("--model", default=None, help="LLM model (default gpt-oss-120b).")
    p.add_argument("--with-llm", action="store_true", help="Use LLM for summary.")
    p.add_argument("--max-runs", type=int, default=25, help="Max runs to sample.")
    return p.parse_args()


def load_commands(run_dir):
    cmds = []
    if not os.path.isdir(run_dir):
        return cmds
    stdout_files = [
        os.path.join(run_dir, f)
        for f in os.listdir(run_dir)
        if f == "opencode_stdout.jsonl" or (f.startswith("opencode_stdout_") and f.endswith(".jsonl"))
    ]
    for path in stdout_files:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "tool_use":
                    continue
                state = event.get("part", {}).get("state", {})
                cmd = state.get("input", {}).get("command")
                if cmd:
                    cmds.append(cmd)
    return cmds


def classify(cmd):
    c = cmd.lower()
    if "nmap" in c:
        return "nmap"
    if c.startswith("curl ") or c.startswith("wget "):
        return "curl"
    if "hydra" in c:
        return "hydra"
    return "other"


def extract_wordlists(cmd):
    lists = []
    for token in cmd.split():
        if token.startswith("/") and (token.endswith(".txt") or "wordlist" in token):
            lists.append(token)
    return lists


def call_llm(prompt, model):
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENCODE_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set.")
    url = base_url.rstrip("/") + "/chat/completions"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}]},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def main():
    args = parse_args()
    rows = list(csv.DictReader(open(args.csv, "r", encoding="utf-8")))
    if not rows:
        print("No rows in CSV.")
        return 1

    out_dir = args.out_dir
    if not out_dir:
        base = os.path.dirname(os.path.abspath(args.csv))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_dir = os.path.join(base, f"report_generic_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    sample_rows = rows[: args.max_runs]
    flow_counts = Counter()
    wordlists = Counter()
    sequences = Counter()

    for row in sample_rows:
        run_id = row.get("run_id")
        if not run_id:
            continue
        run_dir = os.path.join(args.outputs_root, run_id, "coder56")
        cmds = load_commands(run_dir)
        steps = [classify(c) for c in cmds if classify(c) != "other"]
        if steps:
            sequences[" > ".join(steps[:6])] += 1
        for c in cmds:
            for wl in extract_wordlists(c):
                wordlists[wl] += 1
        for s in steps:
            flow_counts[s] += 1

    report_path = os.path.join(out_dir, "generic_flow.md")
    with open(report_path, "w", encoding="utf-8") as rep:
        rep.write("# Generic Attacker Flow Summary\n\n")
        rep.write(f"Sampled runs: {len(sample_rows)}\n\n")
        rep.write("## Tool usage counts\n")
        for k, v in flow_counts.most_common():
            rep.write(f"- {k}: {v}\n")
        rep.write("\n## Common wordlists\n")
        for k, v in wordlists.most_common(10):
            rep.write(f"- {k}: {v}\n")
        rep.write("\n## Most common sequences (first 6 steps)\n")
        for seq, cnt in sequences.most_common(10):
            rep.write(f"- {seq} ({cnt})\n")

        if args.with_llm:
            model = args.model or DEFAULT_MODEL
            prompt = (
                "Summarize the typical attack flow based on these counts.\n"
                f"Tool counts: {flow_counts}\n"
                f"Top wordlists: {wordlists.most_common(10)}\n"
                f"Top sequences: {sequences.most_common(10)}\n"
                "Answer: Is it generally nmap > curl > hydra? Which wordlists are most used?"
            )
            try:
                analysis = call_llm(prompt, model)
            except Exception as exc:
                analysis = f"LLM call failed: {exc}"
            rep.write("\n## LLM Summary\n")
            rep.write(analysis + "\n")

    print(f"Wrote report to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
