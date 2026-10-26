"""Read-only reuse of historical local narration takes; new speech uses Gemini TTS."""
import re
import sys
from pathlib import Path

from .common import (CODE_ROOT, file_hash, guarded, inside, object_hash, read_json,
                     require, require_number, write_json)


def _voice(code_root, identity, locale):
    registry = read_json(code_root / 'config/local-voices.json')['voices']
    require(identity in registry, 'Unknown local voice; inspect config/local-voices.json')
    spec = registry[identity]
    require(locale in spec['locales'], 'Voice locale does not match the requested target locale')
    directory = inside(code_root, spec['directory'])
    require(directory.is_relative_to(code_root.resolve() / '.runtime/models/tts'), 'Voice must be an installed runtime asset')
    require(spec.get('files') and spec.get('license_note'), 'Voice asset manifest and license provenance required')
    for name, digest in spec['files'].items():
        path = inside(directory, name)
        require(path.is_file() and file_hash(path) == digest, 'Voice asset changed or missing: ' + name)
    for name in (spec['model'], spec['tokens']):
        require(name in spec['files'], 'Unbound voice model/tokens')
    data = inside(directory, spec['data'])
    require(data.is_dir() and any(k.startswith(spec['data']+'/') for k in spec['files']), 'Voice phoneme data missing')
    actual_data = {p.relative_to(directory).as_posix() for p in data.rglob('*') if p.is_file()}
    require(actual_data == {p for p in spec['files'] if p.startswith(spec['data']+'/')}, 'Unbound voice phoneme data')
    return {**spec, 'absolute_directory': directory}


def _engine_version(code_root):
    directory = code_root / '.runtime/deps/separation'
    sys.path.insert(0, str(directory))
    import sherpa_onnx
    return sherpa_onnx.__version__


def _take(run, signature, voice):
    directory = run / 'outputs/local-tts' / object_hash(signature)
    candidates = sorted(directory.parent.glob('*'))
    for candidate in reversed(candidates):
        receipt, output = candidate / 'provenance.json', candidate / 'voice.wav'
        if not receipt.is_file() or not output.is_file():
            continue
        saved = read_json(receipt)
        if {k:v for k,v in saved['signature'].items() if k != 'implementation'} != {k:v for k,v in signature.items() if k != 'implementation'}:
            continue
        require(file_hash(output) == saved['output']['sha256'],
                'Voice checkpoint changed')
        require(saved['output']['path'] == output.relative_to(run).as_posix(), 'Voice checkpoint path changed')
        return saved['output'], True
    from .common import WorkflowError
    raise WorkflowError('New narration uses Gemini TTS via tts-packet. Existing local voice takes remain reusable.')


@guarded
def generate(run, relative, code_root=CODE_ROOT):
    from .resources import heavy
    code_root = Path(code_root).resolve()
    spec = read_json(inside(run, relative))
    require(set(spec) <= {'voice', 'speed', 'speaker_id', 'speech_ids'}, 'Unknown local voice setting')
    speed = require_number(spec.get('speed', 1), 'Voice speed', minimum=.5, maximum=2)
    speaker = spec.get('speaker_id', 0)
    require(type(speaker) is int and 0 <= speaker <= 1000, 'Invalid speaker ID')
    source = read_json(run / 'run.json')
    require(file_hash(inside(run, source['source'])) == source['source_sha256'], 'Source changed before local TTS')
    locale = read_json(run / 'inputs/request.json')['target_language']
    inventory_path = run / 'analysis/inventory.json'
    inventory_hash = file_hash(inventory_path)
    speeches = read_json(inventory_path).get('speech_segments', [])
    ids = [s['id'] for s in speeches]
    require(ids and len(set(ids)) == len(ids), 'Unique finalized speech segments required')
    selected = spec.get('speech_ids', ids)
    require(isinstance(selected, list) and selected and len(set(selected)) == len(selected)
            and set(selected) <= set(ids), 'Invalid speech selection')
    require(all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', ident) for ident in ids), 'Invalid speech ID')
    with heavy(run, 'local_tts.generate'):
        voice = _voice(code_root, spec['voice'], locale)
        require(speaker < voice.get('speakers', 1), 'Speaker ID not supported by this voice')
        engine = _engine_version(code_root)
        lines = []
        for speech in speeches:
            if speech['id'] not in selected:
                continue
            text = speech.get('target_text')
            require(isinstance(text, str) and text.strip(), 'Final speech copy required')
            signature = {'source_sha256': source['source_sha256'], 'target_language': locale,
                         'voice': spec['voice'], 'assets': voice['files'], 'engine': engine,
                         'model': voice['model'], 'tokens': voice['tokens'], 'data': voice['data'],
                         'implementation': file_hash(__file__), 'text': text, 'speed': speed, 'speaker_id': speaker}
            asset, reused = _take(run, signature, voice)
            lines.append({'id': speech['id'], 'target_text': text, 'voice': asset, 'reused': reused})
        require(file_hash(inventory_path) == inventory_hash, 'Speech inventory changed during local TTS')
        require(file_hash(inside(run, source['source'])) == source['source_sha256'], 'Source changed during local TTS')
    return {'lines': lines, 'state': 'needs_review', 'approved_for_reuse': False,
            'scope': 'Use these hash-bound voice takes in narration-plan; no automatic timing, mixing or acceptance.'}
