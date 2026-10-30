"""Read-only navigation of live knowledge, candidate families and history."""
from collections import Counter, defaultdict
from pathlib import Path

from .common import read_json, object_hash
from .knowledge_records import archives, placeholder_lesson
from .knowledge_review import queue


def build(root):
    root=Path(root).resolve()
    methods=[]
    references=[]
    for name,dest in [('knowledge/index.json',methods),('knowledge/cases/index.json',references)]:
        path=root/name
        for entry in read_json(path).get('entries',[]) if path.exists() else []:
            if entry.get('status')=='active' and not entry.get('superseded_by'):
                dest.append({k:entry[k] for k in ['id','path','scope','topic','validation_level','retrieval_role'] if k in entry})
    private = root / 'config/knowledge.local.json'
    for entry in read_json(private).get('entries',[]) if private.exists() else []:
        if entry.get('status')=='active' and not entry.get('superseded_by'):
            dest = references if entry.get('scope',{}).get('source_sha256') else methods
            dest.append({**{k:entry[k] for k in ['id','path','scope','topic','validation_level','retrieval_role'] if k in entry},
                         'visibility':'private'})
    rows=queue(root)
    parallel=defaultdict(list)
    families={}
    empty=0
    for row in rows:
        record=row['record'];scope=row['scope'];hypothesis=record.get('hypothesis')
        missing='hypothesis' in record and placeholder_lesson(hypothesis)
        empty+=int(missing)
        evidence=record.get('evidence') if isinstance(record.get('evidence'),dict) else {}
        video=record.get('video_sha256') or evidence.get('video_sha256') or (record.get('after') or {}).get('sha256')
        if video:
            parallel[object_hash({'scope':scope,'video':video,'hypothesis':hypothesis})].append(
                {'path':row['path'],'sha256':row['sha256'],'scope':scope,
                 'visibility':'private' if '/local/' in row['path'] else 'project'})
        # Grouping is a display operation. Every original scope, language,
        # outcome and review remains a separately addressable member.
        identity=({'workflow':scope.get('workflow'),'source_sha256':scope.get('source_sha256'),
                   'hypothesis':hypothesis} if isinstance(scope,dict) and hypothesis is not None else {'path':row['path']})
        key=object_hash(identity)
        method=record.get('method') if isinstance(record.get('method'),dict) else {}
        family=families.setdefault(key,{'id':key,'source_sha256':scope.get('source_sha256') if isinstance(scope,dict) else None,
                                       'summary':'Needs an attributed lesson' if missing else str(hypothesis or record.get('user_quote') or record.get('quote') or method.get('action') or row['next_action'])[:700],
                                       'members':[],'languages':[],'outcomes':[]})
        family['members'].append({k:row[k] for k in ['path','storage_path','sha256','scope','previous_review','next_action']})
        family['outcomes'].append(record.get('outcome','not_recorded'))
        if isinstance(scope,dict) and scope.get('target_language'):family['languages'].append(scope['target_language'])
    for family in families.values():
        family['languages']=sorted(set(family['languages']))
        family['outcomes']=dict(Counter(family['outcomes']))
        family['records']=len(family['members'])
    return {'schema_version':1,'scope':'Read-only navigation. Families do not merge evidence, broaden scope, activate rules or approve videos.',
            'counts':{'active_methods':len(methods),'active_source_references':len(references),'pending_records':len(rows),
                      'pending_families':len(families),'placeholder_reflections':empty,
                      'substantive_pending_records':len(rows)-empty,
                      'reviewed_pending_records':sum(bool(row['previous_review']) for row in rows),
                      'unreviewed_records':sum(not row['previous_review'] for row in rows),
                      'archived_project_candidates':len(archives(root))},
            'parallel_provenance':[{'members':members,'automatic_merge':False,
                'boundary':'Same scope/video/summary is a navigation clue. Preserve privacy, evidence, source hashes and separate review.'}
                for members in parallel.values() if len(members)>1],
            'methods':methods,'source_references':references,
            'families':sorted(families.values(),key=lambda f:(-f['records'],f['id']))}


def markdown(report):
    counts=report['counts']
    lines=['# 项目知识总览','',report['scope'],'','| 项目 | 数量 |','| --- | ---: |']
    lines += [f'| {name} | {value} |' for name,value in counts.items()]
    lines+=['','## 当前方法','','| 方法 | 入口 |','| --- | --- |']
    lines += [f"| {m['id']} | {m['path']} |" for m in report['methods']]
    lines+=['','## 候选家族（仅导航分组）','','所有成员的原scope、视频结果和审查状态保存在同名JSON报告中。没有按语言数量扩大证据强度。','']
    for family in report['families']:
        text=family['summary'].replace('\n',' ').replace('|','\\|')
        lines.append(f"- {family['records']}条；语种 {', '.join(family['languages']) or '未限定'}；source {family['source_sha256'] or '未限定'}：{text}")
    return '\n'.join(lines)+'\n'
