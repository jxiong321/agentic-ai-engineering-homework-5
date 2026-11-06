"""Consequence-based policy enforced outside model context."""
import json
import os
import re
from pathlib import Path
import yaml
from harness import ROOT
from harness.clock import now
from harness.roles import action_of, arg
from harness.reviewer import Reviewer

DISCLOSURE = "Written by RepoMind, an automated AI agent. To reach a person, reply requesting a human maintainer."

def append(path, row):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({"at": now(), **row}) + "\n")

def rows(path):
    path = ROOT / path
    return [json.loads(s) for s in path.read_text().splitlines() if s.strip()] if path.exists() else []

def classify(action, facts):
    if action == "post_comment":
        minutes = facts.get("minutes_since_human_comment")
        circumstance = "human_active" if minutes is not None and minutes < 60 else "agent_opened" if facts.get("issue_opened_by_agent") else "human_quiet"
    elif action == "close_issue":
        circumstance = "agent_opened" if facts.get("issue_opened_by_agent") else "human_opened"
    elif action == "push_commit":
        circumstance = "protected" if facts.get("branch_protected") else "unprotected"
    elif action == "open_pr":
        circumstance = "develop" if facts.get("base") == "develop" else "other_base"
    else:
        circumstance = None
    klass = action + ("/" + circumstance if circumstance else "")
    policy = yaml.safe_load((ROOT / "policy/autonomy.yaml").read_text())
    columns = [c for c in ("independent", "requires_approval", "prohibited") if klass in policy[c]]
    if len(columns) != 1:
        raise ValueError("Unplaced or ambiguous action class: " + klass)
    return klass, columns[0]

def matches(pattern, path):
    # Match whole paths; single stars never cross a directory separator.
    parts = re.split(r"(\*\*/|\*\*|\*|\?)", pattern)
    expression = "".join("(?:.*/)?" if s == "**/" else ".*" if s == "**" else "[^/]*" if s == "*" else "[^/]" if s == "?" else re.escape(s) for s in parts)
    return re.fullmatch(expression, path) is not None

def stopped(run_id):
    events = [r for r in rows("logs/stops.jsonl") if r["run_id"] == run_id]
    return bool(events and events[-1]["event"] != "lifted")

class PolicyHook:
    def __init__(self, ctx):
        self.ctx = ctx
        self.pending = None

    def __call__(self, name, args):
        action = action_of(name)
        klass, column = action or "unknown", None
        def refuse(reason):
            append("logs/hook.jsonl", dict(run_id=self.ctx.run_id, action=action, action_class=klass, column=column, reason=reason, args=args))
            return reason
        try:
            if stopped(self.ctx.run_id):
                if not any(r["run_id"] == self.ctx.run_id and r["event"] == "effective" for r in rows("logs/stops.jsonl")):
                    append("logs/stops.jsonl", dict(run_id=self.ctx.run_id, event="effective", action=action))
                self.pending = "stopped"
                return refuse("stopped")
            facts = self.ctx.tracker.facts(self.ctx.run_id, action, args, self.ctx.issue)
            klass, column = classify(action, facts)
            if column == "prohibited":
                return refuse("prohibited")
            for rule in rows("policy/rules.jsonl"):
                if rule["run_id"] == self.ctx.run_id and any(matches(rule["path"], path) for path in facts.get("paths") or []):
                    return refuse("boundary")
            if action == "post_comment" and DISCLOSURE not in str(args.get(arg("comment", "body"), "")).splitlines():
                return refuse("disclosure")
            if column == "requires_approval":
                answer = Reviewer.from_env().ask(dict(run_id=self.ctx.run_id, action=action, action_class=klass, args=args, facts=facts), timeout_s=600, until=lambda: stopped(self.ctx.run_id))
                mode = os.environ.get("REVIEWER", "scripted:none")
                append("logs/approvals.jsonl", dict(run_id=self.ctx.run_id, action=action, action_class=klass, facts=facts, kind="approval", decision=answer["decision"] if answer else "none", seconds=answer["seconds"] if answer else None, reviewer=answer["reviewer"] if answer else "human" if mode == "human" else "scripted", mode=mode))
                if not answer:
                    self.pending = "stopped" if stopped(self.ctx.run_id) else "held"
                    return refuse("stopped" if self.pending == "stopped" else "no_answer")
                if answer["decision"] != "approve":
                    return refuse("declined")
            if stopped(self.ctx.run_id):
                self.pending = "stopped"
                return refuse("stopped")
            return None
        except Exception:
            refuse("error")
            raise
