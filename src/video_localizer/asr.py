"""Reusable actual-audio transcription; cached evidence never asserts acceptance."""
import importlib.metadata
import sys

from .common import CODE_ROOT, file_hash, guarded, inside, object_hash, read_json, require, write_json
from . import audio, media, model_cache, workflow


@guarded
def transcribe(run, audio_relative=None, size=None, download=False, vad=True, language=None):
    from .model_routing import selected, require_current
    size = size or selected('asr')
    require_current('asr', size)
    sys.path.insert(0, str(CODE_ROOT / '.runtime/deps/asr'))
    directory, assets = model_cache.ensure(size, download)
    candidate = read_json(run / 'outputs/candidate.json') if audio_relative is None else None
    if candidate:
        require(file_hash(inside(run, candidate['path'])) == candidate['sha256'], 'ASR candidate changed')
    path = inside(run, audio_relative) if audio_relative else run / 'review' / candidate['sha256'][:12] / 'audio.wav'
    require(path.is_file(), 'Capture candidate audio first, or provide an actual audio path')
    signature = {'version': 1, 'source_sha256': file_hash(workflow.source_path(run)),
                 'video_sha256': candidate['sha256'] if candidate else None,
                 'audio_path': path.relative_to(run).as_posix(), 'audio_sha256': file_hash(path),
                 'model_files': assets, 'engine_version': importlib.metadata.version('faster-whisper'),
                 'vad': vad, 'language_hint': language, 'word_timestamps': True,
                 'decoder_version': media.command(['ffmpeg', '-version']).stdout,
                 'implementation': file_hash(__file__)}
    output = run / 'analysis/asr' / (object_hash(signature) + '.json')
    reused = False
    if output.exists():
        record = read_json(output)
        require(record.get('signature') == signature and record.get('data_sha256') ==
                object_hash({k: v for k, v in record.items() if k != 'data_sha256'}), 'ASR evidence changed')
        reused = True
    else:
        from faster_whisper import WhisperModel
        import numpy as np
        from .timing import measure
        with measure(run, 'asr.load_model'):
            model = WhisperModel(str(directory), device='cpu', compute_type='int8', cpu_threads=4)
        waveform = np.asarray(audio.decode(path), dtype=np.float32) / 32768.0
        require(waveform.size > 0, 'Audio decoded to an empty waveform')
        with measure(run, 'asr.inference'):
            segments, info = model.transcribe(waveform, task='transcribe', language=language,
                beam_size=5, vad_filter=vad, condition_on_previous_text=False, word_timestamps=True)
            rows = [{'start': s.start, 'end': s.end, 'text': s.text,
                     'avg_logprob': s.avg_logprob, 'no_speech_prob': s.no_speech_prob,
                     'words': [{'text': w.word, 'start': w.start, 'end': w.end, 'probability': w.probability}
                               for w in s.words or []]} for s in segments]
        record = {'signature': signature, 'source_sha256': signature['source_sha256'],
                  'video_sha256': signature['video_sha256'], 'audio_path': signature['audio_path'],
                  'audio_sha256': signature['audio_sha256'], 'model_sha256': assets['model.bin'],
                  'engine': f'faster-whisper {size} multilingual CPU int8',
                  'language': info.language, 'language_probability': info.language_probability,
                  'language_hint': language, 'vad_filter': vad, 'segments': rows,
                  'proof_boundary': 'Actual audio transcription, no expected script supplied. '
                                    'Language hint is not detected-language proof. Not listening or acceptance.'}
        record['data_sha256'] = object_hash(record)
        write_json(output, record)
    # Preserve the source-snapshot interface; historical results remain under analysis/asr.
    alias = path.parent / ('offline-asr-' + path.stem + '.json')
    if not alias.exists() or read_json(alias) != record:
        write_json(alias, record)
    return {'path': output.relative_to(run).as_posix(), 'alias': alias.relative_to(run).as_posix(),
            'sha256': file_hash(output), 'reused': reused, 'language': record['language'],
            'state': 'needs_review'}
