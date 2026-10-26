"""Validate the Agent's content judgment and reasons without choosing its method."""
from .common import inside, require, require_number

TYPES = ('audio_led', 'onscreen_text_led', 'mixed', 'preserve_only')
SPEECH_ROLES = ('dialogue', 'narration', 'monologue', 'spoken_cta', 'unknown')


def translation_domains(inventory):
    speech = [s for s in inventory.get('speech_segments', []) if s.get('action') != 'preserve']
    text = [t for t in inventory.get('text_instances', []) if t.get('action') != 'preserve']
    independent = [t for t in text if t.get('text_role') != 'speech_caption']
    return speech, text, independent


def validate(inventory, request, run, entries=None, duration=None):
    """Versioned intake gate; historical requests gain no fabricated assessment."""
    assessment = inventory.get('routing_assessment')
    required = request.get('routing_contract_version', 0) >= 1
    if not assessment and not required:
        return None
    require(isinstance(assessment, dict), 'Agent routing assessment is required before planning/registering')
    require(assessment.get('version') == 1 and assessment.get('primary_type') in TYPES,
            'Choose audio_led, onscreen_text_led, mixed or preserve_only with actual evidence')
    require(isinstance(assessment.get('reason'), str) and bool(assessment['reason'].strip())
            and isinstance(assessment.get('evidence'), list) and bool(assessment['evidence']),
            'Routing type needs the Agent reason and actual source evidence')
    for path in assessment['evidence']:
        require(inside(run, path).is_file(), 'Routing source evidence missing')
    speech, text, independent = translation_domains(inventory)
    kind = assessment['primary_type']
    require(not speech or inventory.get('audio', {}).get('has_speech') is True,
            'Speech inventory contradicts speech presence; include dialogue AND narration')
    require(kind != 'audio_led' or bool(speech), 'Audio-led translation needs actual speech, not music alone')
    require(kind != 'onscreen_text_led' or bool(independent), 'Text-led translation needs independent onscreen copy')
    require(kind != 'mixed' or bool(speech) and bool(independent),
            'Mixed translation needs speech and independent onscreen copy; captions alone repeat speech')
    require(kind != 'preserve_only' or not speech and not text, 'Preserve-only cannot omit language content')
    require(kind != 'preserve_only' or isinstance(inventory.get('audio', {}).get('has_speech'), bool),
            'Unknown speech cannot be classified as preserve-only')
    for line in speech:
        require(isinstance(line.get('character_id'), str) and bool(line['character_id'].strip())
                and line['character_id'] == line['character_id'].strip() and line.get('speech_role') in SPEECH_ROLES,
                'Describe each spoken role, including narration; keep unresolved identity as unknown')
    for segment in assessment.get('segments', []):
        require(segment.get('type') in TYPES and bool(segment.get('reason')), 'Explain segment routing exceptions')
        start = require_number(segment['start'], 'routing segment start', minimum=0)
        end = require_number(segment['end'], 'routing segment end', minimum=0)
        require(end > start and (duration is None or end <= duration + .01), 'Routing segment exceeds source timeline')
    choices = assessment.get('method_choices', [])
    require(isinstance(choices, list) and len(choices) <= 32, 'Routing method choices must be a bounded list')
    needed = ({'speech'} if speech else set()) | ({'visual'} if text else set())
    domains, seen = set(), set()
    selected = {entry['id'] for entry in entries} if entries is not None else None
    for choice in choices:
        require(isinstance(choice, dict) and choice.get('domain') in ('speech', 'visual'), 'Choose a speech/visual method domain')
        for key in ('method_id', 'reason', 'alternative', 'switch_when', 'stop_when'):
            require(isinstance(choice.get(key), str) and bool(choice[key].strip()), 'Routing choice needs ' + key)
        identity = (choice['domain'], choice['method_id'])
        require(identity not in seen, 'Duplicate routing method choice')
        seen.add(identity)
        domains.add(choice['domain'])
        require(selected is None or choice['method_id'] in selected, 'Chosen method is outside eligible knowledge; retrieve/review before selecting')
    require(needed.issubset(domains), 'Explain a method for every translation domain, including narration')
    return assessment
