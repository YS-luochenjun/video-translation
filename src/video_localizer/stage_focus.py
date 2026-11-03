"""Short production checks; analogous cases are prompts for observation only."""
from .common import read_json

# Each stage folds overlapping policies into one observable action.
FOCUS = {
    'source': ('source-led-visual-localization-v1', '记录每处原字的完整效果、位置、运动及前后景，区分需翻译与获准保留的内容。'),
    'translation': ('content-led-localization-v1', '逐实例对齐定稿；有人声时按角色和实际混音核对每句起止。'),
    'neutral': ('content-aware-text-restoration-v5', '扩语种前并排看全幅原片、底片和试译。沿原字框外检查描边、阴影及显隐边界，记录实际残影和背景变化。'),
    'render': ('source-led-visual-localization-v1', '先看代表语种与原片的字面、层级、位置和运动；复核共用底片再扩语种。'),
    'review': ('native-render-evidence-guards-v1', '正常播放并对照原片；检查字框外、切镜、主体及必需人声，区分共用缺陷与单语瑕疵。'),
    'delivery': ('fireplay-complete-delivery-v3', '核对所有原片×目标语种的正式版本与提交回执，记录有界返工后的遗留问题。'),
}


def focus(stage, inventory, root):
    method, action = FOCUS[stage]
    items = [i for i in inventory.get('text_instances', []) if i.get('action') != 'preserve' and i.get('text_role') != 'preserve']
    tags = set()
    inspections = []
    for item in items:
        display = item.get('display') or {}
        style = str(item.get('source_style_id', '')).lower()
        if display.get('outline_layers') or display.get('outline'):
            if stage in ('source', 'neutral', 'review', 'render'):
                tags.add('fade')  # The fade case illustrates partial glyph-edge erasure.
                inspections.append({key: item.get(key) for key in ('id', 'start', 'end', 'bbox')})
        if 'cta' in style and stage in ('source', 'neutral', 'render', 'review'):
            tags.add('cta')
    if inventory.get('speech_segments') and stage in ('translation', 'review'):
        tags.add('speech')
    if stage == 'delivery':
        tags.add('upload')
    index = root / 'knowledge/cases/index.json'
    cases = read_json(index)['entries'] if tags and index.exists() else []
    matches = sorted((entry for entry in cases if entry.get('status') == 'active'
                      and tags.intersection(entry.get('tags', []))),
                     key=lambda e: (-len(tags.intersection(e['tags'])), e['id']))
    return {'stage': stage, 'method': 'knowledge/rules/' + method + '.md', 'check': action,
            'inspect_intervals': inspections, 'similar_cases': [
                {k: entry.get(k) for k in ('id', 'path', 'scope')} for entry in matches[:2]],
            'case_use': '仅提示检查位置和失败方式；当前原片须独立验证，不沿用旧坐标或验收。'}
