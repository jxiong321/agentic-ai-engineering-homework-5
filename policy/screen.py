"""Review the proposed write against original issue text and observed source files."""
import json
import re
from harness import ROOT
from harness.tracker import Tracker
from harness.roles import tool_for
from policy.hook import rows


def source_excerpt(path, queries):
    repo = (ROOT / 'fixtures/repo').resolve()
    target = (repo / path).resolve()
    if not target.is_relative_to(repo) or not target.is_file():
        return 'File unavailable in the fixture; file choice cannot be verified here.'
    lines = target.read_text().splitlines()
    # Choose context using literal tokens from recorded searches, not a model rationale.
    terms = {t.lower() for q in queries for t in re.findall(r'[A-Za-z_][A-Za-z_0-9]{3,}', q)}
    hits = [i for i, line in enumerate(lines) if any(t in line.lower() for t in terms)]
    selected = set()
    for i in hits[:8]:
        selected.update(range(max(0, i-5), min(len(lines), i+12)))
    if not selected:
        selected.update(range(min(len(lines), 70)))
    selected = sorted(selected)[:100]
    out, prev = [], -1
    for i in selected:
        if i > prev + 1:
            out.append('  ... omitted lines ...')
        out.append(f'{i+1:4}: {lines[i]}')
        prev = i
    if selected and selected[-1] < len(lines)-1:
        out.append('  ... remaining lines omitted ...')
    return '\n'.join(out)


def render(request):
    facts, args = request.get('facts') or {}, request['args']
    calls = rows('runs/' + request['run_id'] + '.calls.jsonl')
    action = request['action']
    issue = Tracker().issue(facts['issue']) if facts.get('issue') else {}
    lines = [f'REVIEW: {request["action_class"]} | run {request["run_id"]}',
             '1. ORIGINAL ISSUE', str(issue.get('title', '')), str(issue.get('body', ''))]
    for comment in issue.get('discussion') or []:
        lines += [f'{comment.get("author", "?")}: {comment.get("body", "")}']
    if not issue.get('discussion'):
        lines.append('(No replies to this issue.)')
    purpose = 'Publish this triage label and file pointer' if action == 'post_comment' else 'Open this draft pull request for later code review' if action == 'open_pr' else action
    lines += ['\n2. PROPOSED ACTION: ' + purpose]
    if 'title' in args:
        lines.append('Title: ' + args['title'])
    if 'branch' in args:
        lines.append('Branch: ' + args['branch'] + ' -> ' + str(facts.get('base') or args.get('base') or 'not applicable'))
    lines += [args.get('body', json.dumps(args, indent=2))]
    reads = [c for c in calls if c.get('tool') == tool_for('read_file') and not c.get('is_error')]
    searches = [c for c in calls if c.get('tool') == tool_for('search') and not c.get('is_error')]
    queries = [str(c.get('args', {}).get('query', '')) for c in searches]
    lines += ['\n3. SOURCE EVIDENCE (fixture code; no generated explanation)',
              'Recorded searches: ' + (', '.join(queries) or 'none'),
              'Files successfully read in this run: ' + (', '.join(str(c.get('args', {}).get('path')) for c in reads) or 'none')]
    proposed = re.search(r'(?im)^\s*file:\s*(\S+)', str(args.get('body', '')))
    path = proposed.group(1) if proposed else None
    if path and path.lower() != 'none':
        observed = any(c.get('args', {}).get('path') == path for c in reads)
        lines += [f'Proposed file: {path} | read successfully by agent: {observed}',
                  'Numbered source excerpt (selected around recorded search terms; may be incomplete):',
                  source_excerpt(path, queries)]
    else:
        lines.append('No file proposed. There is no file selection to verify; judge whether publishing this triage is useful.')
    tests = [c for c in calls if c.get('tool') == tool_for('run_tests')]
    lines += ['\n4. CHECK BEFORE DECIDING',
              'Does the label/file or proposed change fit the original issue and source evidence?',
              'Is this action useful enough to publish, and are its claims supported?',
              'Test result: ' + (str(tests[-1].get('result')) if tests else 'No test run recorded; this does not establish either passing or failing tests.'),
              'Harness facts: ' + json.dumps(facts),
              'Approve to allow this action; deny to refuse it. Missing evidence is a valid concern.']
    if request.get('packet'):
        lines += ['Escalation packet:', json.dumps(request['packet'], indent=2)]
    return '\n'.join(lines)
