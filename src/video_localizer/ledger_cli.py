"""Explicit ledger operations, shared by the CLI and loopback workbench."""
from pathlib import Path
import json
import sys
import uuid

from .ledger import Ledger, now


def configure(commands):
    command = commands.add_parser('ledger', help='Demand ledger: sync, preview, agent events, ETA and consistent backups')
    command.add_argument('action', choices=['sync', 'preview', 'status', 'detail', 'register', 'claim', 'heartbeat', 'release', 'stage', 'ready', 'block', 'resume', 'eta', 'link', 'backup'])
    command.add_argument('--spec', help='Workspace-relative JSON input; use a stable operation_id for retries')
    command.add_argument('--id', help='Exact ledger requirement ID')


def execute(args, root):
    from .common import CODE_ROOT, inside, read_json
    if args.action in {'sync', 'preview'}:
        sys.path.insert(0, str(CODE_ROOT / 'workbench'))
        from collector import Collector
        result = Collector(root).sync(preview=args.action=='preview')
        return {'health': result['health'], 'events': result['events'], 'preview': result['preview'],
                'requirements': [{k:r.get(k) for k in ('id','code','video_count','task_count','output_count','state','countable','association','evidence')} for r in result['requirements']]}
    ledger = Ledger(root)
    if args.action == 'status':
        view = ledger.view()
        view['metrics'] = ledger.metrics(view['requirements'])
        return view
    if args.action == 'detail':
        return ledger.detail(args.id)
    if args.action == 'backup':
        return ledger.backup(Path(root)/'state/ledger/backups'/('ledger-'+now().replace(':','-')+'-'+uuid.uuid4().hex[:8]+'.sqlite3'))
    if not args.spec:
        raise ValueError('This action requires --spec')
    spec = read_json(inside(root, args.spec))
    return ledger.action(args.action, spec['data'], spec['operation_id'], spec.get('expected_revision'))
