# RepoMind architecture

The planned executor validates a plan, gathers issue/code evidence, drafts a triage comment, applies its label, opens a draft PR when a file is identified and posts the checked comment. Synchronous checkpoints contain plan/status, completed calls and keys, findings and current step. Resume restores these records; stable write keys prevent duplication.

## Control & Policy layer

The registry installs its external policy hook at tools/__init__.py:145. Live calls and replay share circumstance classification at policy/hook.py:24. The callable at policy/hook.py:58 checks stop, prohibition, persisted boundaries, disclosure and approval; exceptions fail closed. Policy YAML and rules are not supplied to the model.

The inbox client drains before planner, executor, revision and compaction requests at policy/inbox.py:9; boundaries persist outside conversation. Required arguments absent from a valid plan are filled by the executor at ways/planned.py:459. The executor checks named escalation signals and checkpoints before holding at ways/planned.py:430. The escalation handler at policy/escalation.py:46 caps delivery by the Chicago reviewer day and holds unanswered or capped runs.

The screen at policy/screen.py:36 combines exact proposed writes with original issue text, harness facts and numbered fixture-source evidence; bounded excerpts are labeled incomplete. bin/review records actual student decisions through the unchanged harness. Pilot traces and remote rows remain in runs/discarded/; the fresh diagnostics reference active real-model runs only.

Notifications precede remote writes. bin/stop writes an external request; the hook refuses further calls, and the executor checkpoints and ends stopped. Resume records a lifted event and restores state. bin/rollback applies remove_label, close_pr or reopen_issue newest first and reports none for comments, pushes and merges. bin/resume_saved can execute complete saved actions with model calls guarded against execution; it never supplies substitute model responses.
