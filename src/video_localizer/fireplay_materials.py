"""Pure Fireplay material policy and read-back checks; no journal or external I/O.

The intake/outbox owns operation identity, locks and at-most-once recovery.
These helpers validate already-unwrapped connector data without mutating it.
"""
import re

from .common import object_hash, require


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
    value = spec.get('attribution') or record.get('decision', {}).get('attribution') or defaults.get('attribution', {})
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
