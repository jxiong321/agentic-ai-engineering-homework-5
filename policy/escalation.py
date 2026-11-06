"""Named environmental signals; no model-confidence trigger."""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from harness import ROOT
from harness.clock import now
from harness.roles import arg
from harness.reviewer import Reviewer
from policy.hook import append, rows, stopped, classify

REVIEWER_ZONE = ZoneInfo("America/Chicago")

def reviewer_day(timestamp):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(REVIEWER_ZONE).date()

DAILY_CAP = 5  # At most half the ten-minute reviewer budget, at 60 seconds per escalation.

def signal_for(executor, action, args):
    if action not in ("push_commit", "post_comment", "merge_pr"):
        return None
    for completed in reversed(executor.completed):
        if completed.get("tool") == __import__("harness.roles", fromlist=["tool_for"]).tool_for("run_tests"):
            try:
                result = json.loads(completed["result"])
            except (ValueError, KeyError):
                return "uninterpretable_result", "Test result could not be interpreted"
            if result.get("passed") is False and (action != "push_commit" or result.get("ref") == args.get(arg("push_commit", "branch"))):
                return "failed_verification", "This run's own test suite failed on the target branch"
    if any("declared shape" in c.get("result", "") for c in executor.completed):
        return "uninterpretable_result", "A tool returned a result outside its declared schema"
    blocked = [c for c in rows("logs/hook.jsonl") if c["run_id"] == executor.ctx.run_id]
    if len([c for c in blocked if c.get("args") == args and c.get("action") == action]) >= 3:
        return "blocked_three_times", "The same action and arguments were refused three times"
    if action == "post_comment":
        from harness.formats import parse_triage_comment
        label, file = parse_triage_comment(args.get(arg("comment", "body"), ""))
        for memory in executor.memory:
            # Stored triage facts have this exact structured sentence; prose uncertainty is not a signal.
            import re
            found = re.search(r"label ([^,]+), file (.+)\.", memory.get("text", ""))
            if found and memory.get("issue") == executor.ctx.issue_number and (label, file or "none") != found.groups():
                return "memory_contradiction", "The proposed triage disagrees with this issue's stored label/file fact"
    return None

def ask_escalation(executor, action, args, signal):
    ctx = executor.ctx
    packet = dict(attempted=f"{action}: {json.dumps(args)}", why_stopped=signal[1], needs_from_human="Approve the attempted action despite this signal, or deny and revise before resuming.", signal=signal[0], at=now())
    path = ROOT / "escalations" / (ctx.run_id + ".json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(packet, indent=2) + "\n")
    ctx.trace.event("escalation", signal=signal[0], packet=str(path.relative_to(ROOT)))
    prior = [x for x in rows("logs/escalations.jsonl") if reviewer_day(x["at"]) == reviewer_day(now()) and x["event"] == "asked"]
    if len(prior) >= DAILY_CAP:
        append("logs/escalations.jsonl", dict(run_id=ctx.run_id, event="cap_hit", signal=signal[0]))
        return None
    append("logs/escalations.jsonl", dict(run_id=ctx.run_id, event="asked", signal=signal[0]))
    facts = ctx.tracker.facts(ctx.run_id, action, args, ctx.issue_number)
    klass, _ = classify(action, facts)
    answer = Reviewer.from_env().ask(dict(run_id=ctx.run_id, action=action, action_class=klass, args=args, facts=facts, kind="escalation", packet=packet), timeout_s=60, until=lambda: stopped(ctx.run_id))
    mode = os.environ.get("REVIEWER", "scripted:none")
    append("logs/approvals.jsonl", dict(run_id=ctx.run_id, action=action, action_class=klass, facts=facts, kind="escalation", decision=answer["decision"] if answer else "none", seconds=answer["seconds"] if answer else None, reviewer=answer["reviewer"] if answer else "human" if mode == "human" else "scripted", mode=mode))
    return answer["decision"] if answer else None
