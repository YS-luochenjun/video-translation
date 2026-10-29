"""Pure Fireplay material policy and read-back checks; no journal or external I/O.

The intake/outbox owns operation identity, locks and at-most-once recovery.
These helpers validate already-unwrapped connector data without mutating it.
"""
import re
from datetime import datetime, timezone

from .common import object_hash, require


def resolve_assignees(record, receipt, defaults):
    """Resolve current assignees from actual Fireplay members, without asking for IDs."""
    policy = defaults.get('designer_selection', {})
    require(policy.get('automatic_verified_user_ids') is True and policy.get('authority') == 'user'
            and policy.get('authorization_ref') and policy.get('source_quote'), 'Missing automatic designer resolution authority')
    directory = receipt.get('member_directory', {})
    try:
        observed = datetime.fromisoformat(directory['query_meta']['observed_at'].replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - observed).total_seconds()
    except (KeyError, TypeError, ValueError):
        require(False, 'Read the current Fireplay member directory before resolving designers')
    require(-60 <= age <= 600, 'Refresh the current Fireplay member directory')
    assignees = record['snapshot']['row'].get('assigneeIds', [])
    members = directory.get('members', [])
    resolved = []
    for identifier in assignees:
        matches = [m for m in members if m.get('feishuUserId') == identifier]
        require(len(matches) == 1 and matches[0].get('username'),
                'Query Fireplay for each unresolved assignee; a partial/empty directory does not mean no designer. Do not ask the user for an ID')
        resolved.append(matches[0])
    designers = [m for m in resolved if m['username'].strip() not in policy.get('excluded_names', [])]
    value = {'authorization_ref': policy['authorization_ref'], 'source_quote': policy['source_quote'],
             'identity_evidence': {'member_receipt_sha256': object_hash(receipt),
                                   'observed_at': directory['query_meta']['observed_at'],
                                   'assignees': [{'id': m['feishuUserId'], 'name': m['username']} for m in resolved]}}
    if designers:
        value.update(designer_ids=[m['feishuUserId'] for m in designers],
                     designer_names=[m['username'] for m in designers], identity_route='verified_user_id',
                     identity_authorization_ref=policy['authorization_ref'], creation_type='derivative')
    else:
        value.update(unassigned=True, creation_type='unspecified')
    return value


def attribution_instruction():
    return ('设计师由Agent读取当前需求执行人及Fireplay真实成员目录自行确定，排除罗晨钧、邹彬，其余全部填为设计师并标二创。'
            '用requirement_field_options_query(include_members=true,member_ids=真实assigneeIds)查询并完整翻页；'
            '空目录或部分目录不表示没有设计师，继续按真实组/当前执行人查询或查看Fireplay原生页面，不要求用户提供DID/用户ID。'
            '回传spec可附designer_receipt实际成员响应，项目按feishuUserId/username核对后采用用户已授权的真实ID归属路径；'
            '若已有真实DID映射也可使用命名归属。归属写入必须遵守实际接口的预览/执行及权限合同，读回designerIds和二创状态，不能把预览算成功。')


def publication(record, spec, defaults, sharing):
    policy = defaults.get('publication', {})
    require(policy.get('authority') == 'user' and policy.get('authorization_ref') and
            policy.get('youtube_auto_upload') is True and policy.get('share_to_requirement_group') is True,
            'Missing the user-approved Fireplay publication policy')
    options = sharing.get('departments', [])
    row = record['snapshot']['row']
    # Only use an ID actually returned by the sharing tool, never construct one.
    source_id = row['deptId']
    candidates = [d for d in options if d.get('deptName') == row.get('deptName') and
                  d.get('deptId') in (source_id, source_id[3:] if source_id.startswith('od-') else source_id)]
    require(len(candidates) == 1, 'Read current material_sharing_departments and resolve the exact requirement group')
    product = spec.get('product_tag')
    if not product:
        for field in ('title', 'description'):
            text = record['snapshot']['brief'].get(field) or ''
            if '翻译' in text:
                candidate = text.split('翻译', 1)[0].strip()
                if candidate and not re.search(r'https?://|[【\[\n]', candidate):
                    product = candidate
                    break
    require(isinstance(product, str) and 1 <= len(product.strip().split()) <= 2 and
            len(product.strip()) <= 80 and not re.search(r'https?://|[\n\r]', product),
            'Agent must derive a one- or two-word product tag from the brief or actual video')
    return {'policy': policy, 'shared_dept_id': candidates[0]['deptId'], 'dept_name': candidates[0]['deptName'],
            'product_tag': product.strip(), 'sharing_receipt_sha256': object_hash(sharing),
            'youtube_status': 'requested_not_verified', 'instruction': defaults.get('submission_instruction', '')}


def attribution(record, spec, defaults):
    """Validate an explicit attribution route and return its import-name suffix."""
    value = (resolve_assignees(record, spec['designer_receipt'], defaults) if 'designer_receipt' in spec else
             spec.get('attribution') or record.get('decision', {}).get('attribution'))
    if not value:
        require(not defaults.get('designer_selection', {}).get('automatic_verified_user_ids'),
                'Read Fireplay members and supply designer_receipt; do not ask the user for an ID or silently use legacy unassigned attribution')
        value = defaults.get('attribution', {})
    require(value.get('authorization_ref') and value.get('source_quote'),
            'Specify the human-confirmed designer DID(s), or explicitly choose unassigned attribution')
    dids = value.get('designer_dids')
    designer_ids = value.get('designer_ids')
    if designer_ids:
        require(not dids and isinstance(designer_ids, list) and
                all(isinstance(v, str) and v.strip() for v in designer_ids) and
                len(set(designer_ids)) == len(designer_ids), 'Invalid verified designer user IDs')
        require(value.get('identity_route') == 'verified_user_id' and
                value.get('identity_authorization_ref'),
                'Direct designer user IDs need explicit user authorization')
        require(set(designer_ids).issubset(set(record['snapshot']['row'].get('assigneeIds', []))),
                'Verified designer user IDs must be current requirement assignees')
    if dids:
        require(isinstance(dids, str) and re.fullmatch(r'D\d+(?:\+D\d+)*', dids), 'Invalid designer DID naming suffix')
        suffix = '_' + dids
    else:
        require(designer_ids or value.get('unassigned') is True,
                'Missing verified designer DID; resolve requirement assignees under the user attribution policy or record no designer')
        suffix = ''
    creation = value.get('creation_type', 'unspecified')
    require(creation in ('unspecified', 'original', 'derivative'), 'Invalid creation attribution')
    require(creation == 'unspecified' or dids or designer_ids, 'Creation attribution needs confirmed designer DID(s) or verified user IDs')
    if dids:
        suffix += {'unspecified': '', 'original': '_$', 'derivative': '_#'}[creation]
    return value, suffix


def verify_attribution(material, attribution, designer_message, creation_message):
    """Check the same direct-ID contract at attribution and final verification."""
    ids = attribution.get('designer_ids')
    if ids:
        require(set(ids).issubset(set(material.get('designerIds', []))), designer_message)
        creation = attribution.get('creation_type', 'unspecified')
        require(creation == 'unspecified' or material.get('creationType') == creation, creation_message)


def identity(attribution):
    """Compare the frozen business identity, leaving original authority untouched."""
    return (attribution.get('designer_dids') or '',
            tuple(sorted(attribution.get('designer_ids') or [])),
            attribution.get('creation_type', 'unspecified'),
            bool(attribution.get('unassigned')))
