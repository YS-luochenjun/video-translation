"""Evidence-only knowledge projection for one console run; never retrieves anew."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re

from store import clean, digest

GROUPS = {'knowledge': '方法与规则', 'source_references': '同源参考',
          'related_source_references': '关联参考', 'knowledge_advisories': '补充提示'}
STAGES = {'recognize': 'analysis', 'image': 'base'}


def knowledge_path(value):
    """Only knowledge/contract documents can be opened through a knowledge row."""
    if not isinstance(value, str): return None
    parts = Path(value).parts
    if not parts or '..' in parts or '\\' in value or ':' in value: return None
    if value == 'AGENTS.md' or value in {'.agents/skills/video-localization/SKILL.md',
                                        '.agents/skills/knowledge-curation/SKILL.md'}:
        return value
    if parts[0] in {'knowledge', 'agent', 'docs'} and not any(p.startswith('.') for p in parts) and Path(value).suffix in {'.md', '.json'}:
        return value
    return None


def project_knowledge(data, run_id, versions):
    store = data.store
    rows = {}
    # Use the same live/retained-package selection as the existing task projection.
    base, _ = store._base(run_id, versions)

    def read(path):
        value = store.read(path)
        return value if isinstance(value, dict) else {}

    def safe_file(path):
        try:
            p = store.path(path)
            return p if p.is_file() and p.stat().st_size <= 2*1024*1024 else None
        except (OSError, ValueError): return None

    def add(entry, node, state, group, record, body_path=None, body_text=None, plan_id=None, note=None):
        if isinstance(entry, str): entry = {'path': entry}
        if not isinstance(entry, dict): return
        path = knowledge_path(entry.get('path'))
        if not path: return
        expected = entry.get('sha256') or entry.get('method_sha256')
        expected = expected if re.fullmatch('[a-f0-9]{64}', str(expected or '')) else None
        key = digest([node, state, group, path, expected, plan_id])[:24]
        source = safe_file(record)
        if not source: return
        at = datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat()
        if key not in rows:
            rows[key] = {'id': key, 'node': node, 'stage': node, 'state': state, 'group': group,
                         'path': path, 'title': clean(entry.get('title') or entry.get('id') or Path(path).stem),
                         'sha256': expected, 'plan_id': plan_id, 'scope': clean(entry.get('scope')),
                         'origin': clean(entry.get('origin')), 'recorded_at': at, 'evidence': [],
                         '_body_path': body_path, '_body_text': body_text}
        row = rows[key]
        evidence = {'path': record, 'at': at, 'note': clean(note) if note else None}
        if evidence not in row['evidence']: row['evidence'].append(evidence)
        if body_path or body_text is not None:
            row['_body_path'], row['_body_text'] = body_path, body_text
        row['recorded_at'] = max(row['recorded_at'], at)

    def groups(record, value, node='process', state='provided', plan_id=None):
        for group in GROUPS:
            entries = value.get(group, [])
            if not isinstance(entries, list): continue
            for i, entry in enumerate(entries):
                frozen = f'{base}/plans/{plan_id}/{group}/{i+1:02d}.md' if plan_id else None
                add(entry, node, state, group, record, body_path=frozen, plan_id=plan_id)

    plan = read(base+'/plan.json')
    plan_id = plan.get('id')
    if not isinstance(plan_id, str) or not re.fullmatch('[A-Za-z0-9_.-]+', plan_id): plan_id = None
    groups(base+'/plan.json', plan, state='frozen' if plan.get('knowledge_snapshot_version') == 1 else 'selected', plan_id=plan_id)

    # Saved context output is evidence of provision, never a claim of adoption.
    scratch = f'work/runs/{run_id}'
    for pattern in ('context*.json', '*work-packet*.json'):
        for record in store.glob(scratch, pattern): groups(record, read(record))

    packets = {}
    for record in store.glob(base+'/analysis/codex/packets', '*.json'):
        packet = read(record)
        node = STAGES.get(packet.get('stage'), 'process')
        groups(record, packet, node)
        contexts = packet.get('context', [])
        contexts = contexts if isinstance(contexts, list) else []
        packets[record] = {e.get('path'): e for e in contexts if isinstance(e, dict)}
        for entry in contexts:
            if isinstance(entry, dict):
                add(entry, node, 'provided', 'context', record, body_text=entry.get('text'))

    for record in store.glob(base+'/analysis/codex/results', '*.json'):
        result = read(record)
        report = result.get('report', {})
        if not isinstance(report, dict): continue
        packet_ref = result.get('packet', {})
        packet_ref = packet_ref if isinstance(packet_ref, dict) else {}
        packet_path = base+'/'+str(packet_ref.get('path', ''))
        # Read claims may use embedded content only when the result's packet hash matches.
        packet_file = safe_file(packet_path)
        matched = bool(packet_file and packet_ref.get('sha256') == store.sha(packet_path))
        declared = report.get('knowledge_read', [])
        if not isinstance(declared, list): continue
        for entry in declared:
            path = entry if isinstance(entry, str) else entry.get('path') if isinstance(entry, dict) else None
            context = packets.get(packet_path, {}).get(path, {}) if matched else {}
            ref = context or entry
            add(ref, STAGES.get(result.get('stage'), 'process'), 'declared_read', 'context', record,
                body_text=context.get('text'), note='结果报告声明已读；不等同于独立验证或采用')

    for pointer in store.glob(base+'/review/knowledge-use', '*.json'):
        ref = read(pointer)
        path = ref.get('path')
        # A pointer cannot turn this endpoint into an arbitrary workspace reader.
        if not isinstance(path, str) or not re.fullmatch(r'knowledge/local/feedback/knowledge-use/[A-Za-z0-9_.-]+/feedback.json', path): continue
        feedback = read(path)
        intact = bool(safe_file(path) and ref.get('sha256') == store.sha(path))
        uses = feedback.get('uses', [])
        if not isinstance(uses, list): continue
        for use in uses:
            if not isinstance(use, dict): continue
            snapshot = use.get('selected_snapshot')
            entry = {**(snapshot if isinstance(snapshot, dict) else {}), 'path': use.get('path'), 'sha256': use.get('sha256')}
            outcome = use.get('outcome', 'unrecorded')
            add(entry, 'review', 'usage' if intact else 'usage_unverified', 'usage', path,
                plan_id=feedback.get('plan_id'), note={'outcome': outcome, 'observation': use.get('observation'),
                                                     'review_type': feedback.get('review_type'), 'pointer': pointer})

    # Learning produced by this exact run remains a candidate, not a new rule.
    for folder in ('knowledge/candidates', 'knowledge/local/candidates'):
        for record in store.glob(folder, run_id+'-*.json'):
            candidate = read(record)
            evidence = candidate.get('evidence')
            if not isinstance(evidence, dict) or evidence.get('run') != run_id: continue
            if not safe_file(record): continue
            add({'path': record, 'sha256': store.sha(record), 'scope': candidate.get('scope'),
                 'title': str(candidate.get('hypothesis') or candidate.get('title') or candidate.get('id'))[:140]},
                'review', 'learned_candidate', 'lesson', record,
                note={'boundary': '本次复盘候选；不代表已验证、已发布或已改变规则',
                      'outcome': candidate.get('outcome'), 'limitations': candidate.get('limitations'),
                      'reflection_state': candidate.get('reflection_state')})

    return sorted(rows.values(), key=lambda r: (r['node'], r['path'], r['state'], r['recorded_at']))


def knowledge_document(data, row):
    """Prefer captured text; show integrity and distinguish today's source explicitly."""
    result = {k: v for k, v in row.items() if not k.startswith('_')}
    text = row.get('_body_text')
    path = row.get('_body_path')
    if isinstance(text, str):
        raw = text.encode('utf-8')
        result.update(content_source='工作包保存正文', content_path=row['path'])
    else:
        candidate = path
        try:
            frozen = data.store.path(candidate) if candidate else None
            if not frozen or not frozen.is_file(): candidate = row['path']
            p = (data.root/candidate).resolve() if candidate.startswith('.agents/skills/') else data.store.path(candidate)
            if not p.is_relative_to(data.root): raise ValueError('Path outside workspace')
            if p.stat().st_size > 2*1024*1024: raise ValueError('Knowledge exceeds read limit')
            raw = p.read_bytes(); text = raw.decode('utf-8-sig')
            result.update(content_source='计划冻结正文' if candidate == path else '当前来源正文（未保存当时正文）', content_path=candidate)
        except (OSError, ValueError, UnicodeError):
            return {**result, 'text': '正文缺失、已清理或不可读；保留来源与版本记录。', 'integrity': 'missing', 'actual_sha256': None}
    actual = hashlib.sha256(raw).hexdigest()
    expected = row.get('sha256')
    integrity = 'matched' if expected == actual else 'changed' if expected else 'unbound'
    if row['path'].endswith('.json'):
        try: text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except ValueError: pass
    heading = re.search(r'^#\s+(.+)', text, re.M)
    if heading: result['title'] = clean(heading.group(1))
    result.update(text=clean(text), actual_sha256=actual, integrity=integrity)
    return result
