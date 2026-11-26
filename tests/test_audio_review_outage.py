import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import audio_review_outage as outage
from video_localizer.common import WorkflowError, file_hash, read_json, write_json
from video_localizer.model_routing import policy


class AudioReviewOutageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.run = Path(temporary.name) / 'runs/example'
        self.source = self.asset('inputs/source.mp4', b'source')
        self.video = self.asset('outputs/final.mp4', b'encoded')
        self.mix = self.asset('outputs/mix/translated.wav', b'mix')
        self.voice = self.asset('outputs/voice.wav', b'voice')
        self.source_hash = file_hash(self.source)
        self.video_hash = file_hash(self.video)
        self.review = self.run / 'review' / self.video_hash[:12]
        write_json(self.run / 'run.json', {'source': 'inputs/source.mp4', 'source_sha256': self.source_hash})
        write_json(self.run / 'analysis/inventory.json', {
            'audio': {'strategy': 'replace', 'replacement_path': 'outputs/mix/translated.wav'},
            'speech_segments': [{'id': 'speech', 'target_text': 'Bonjour'}]})
        write_json(self.mix.parent / 'provenance.json', {
            'source_sha256': self.source_hash,
            'output': {'path': 'outputs/mix/translated.wav', 'sha256': file_hash(self.mix)},
            'lines': [{'id': 'speech', 'target_text': 'Bonjour',
                       'voice': {'path': 'outputs/voice.wav', 'sha256': file_hash(self.voice)}}]})
        self.models = policy()['audio_analysis_recovery']['outage_delivery']['required_models']
        for index, model in enumerate(self.models):
            write_json(self.run / 'jobs' / f'{index}.json', {
                'id': str(index), 'kind': 'audio_review', 'model': model,
                'source_sha256': self.source_hash, 'video_sha256': self.video_hash,
                'state': 'ambiguous', 'failure_stage': 'model_request', 'error': 'KIE code 502: Bad Gateway'})
        for target, result in [('media.probe', {'duration': 4}),
                               ('audio.evaluate', {'failures': [], 'video_sha256': self.video_hash}),
                               ('audio.inspect', ({}, [1, 2, 3])),
                               ('audio.waveform_match', {'correlation': .99, 'offset_seconds': 0})]:
            mocked = patch(f'video_localizer.audio_review_outage.{target}', return_value=result)
            mocked.start()
            self.addCleanup(mocked.stop)

    def asset(self, relative, value):
        path = self.run / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return path

    def test_both_provider_failures_retain_tts_without_claiming_review_pass(self):
        value = outage.receipt(self.run, self.video)
        self.assertFalse(value['semantic_review_passed'])
        self.assertEqual(value['remote_audio_review'], 'skipped_provider_outage')
        self.assertEqual(set(value['failed_models']), set(self.models))
        self.assertEqual(read_json(self.review / 'remote-audio-review-outage.json'), value)
        self.assertEqual(value['speech_ids'], ['speech'])
        self.assertEqual(read_json(self.run / 'jobs/0.json')['state'], 'ambiguous')

    def test_one_failure_or_old_video_failure_is_insufficient(self):
        job = self.run / 'jobs/1.json'
        value = read_json(job)
        for changes in ({'failure_stage': 'upload'}, {'video_sha256': 'a' * 64}):
            write_json(job, {**value, **changes})
            with self.assertRaisesRegex(WorkflowError, 'both comparative'):
                outage.receipt(self.run, self.video)

    def test_existing_review_cannot_be_waived(self):
        write_json(self.review / 'audio-model-review.json', {'analysis': {'foreign_speech_remaining': True}})
        with self.assertRaisesRegex(WorkflowError, 'actual comparative review exists'):
            outage.receipt(self.run, self.video)

    def unavailable_primary(self):
        path = self.run / 'jobs/0.json'
        job = read_json(path)
        report = {'source_sha256': self.source_hash, 'video_sha256': self.video_hash,
                  'model': job['model'], 'response_id': 'provider-response',
                  'analysis': {'has_speech': None, 'speech_segments': [], 'foreign_speech_remaining': [],
                               'uncertain_intervals': []}}
        for field, decision in (('dialogue_translation', 'complete'), ('background_music', 'same_track'),
                                ('sound_effects', 'preserved'), ('sync', 'acceptable')):
            report['analysis'][field] = {decision: None, 'reason': 'Audio A and Audio B could not be opened.'}
        result = self.run / 'jobs/0-response/audio-model-review.json'
        write_json(result, report)
        write_json(self.review / 'audio-model-review.json', report)
        write_json(path, {**job, 'state': 'success', 'response_id': report['response_id'],
                          'result': result.relative_to(self.run).as_posix(), 'result_sha256': file_hash(result)})
        return report

    def test_inaccessible_success_and_backup_failure_allow_outage(self):
        self.unavailable_primary()
        result = outage.receipt(self.run, self.video)
        self.assertEqual(result['failed_models'][self.models[0]]['provider_code'], 'media_unavailable')
        self.assertFalse(result['semantic_review_passed'])

    def test_default_route_switches_cached_inaccessible_review_once(self):
        self.unavailable_primary()
        write_json(self.run / 'outputs/candidate.json', {'sha256': self.video_hash})
        with patch('video_localizer.workflow.analyze_audio', side_effect=[
                {'job': '0', 'state': 'success', 'reused': True},
                {'job': '1', 'state': 'ambiguous', 'reused': True}]) as analyze:
            result = outage.review_with_fallback(self.run)
        self.assertEqual(result['state'], 'remote_review_unavailable')
        self.assertEqual([call.kwargs['model'] for call in analyze.call_args_list], self.models)

    def test_negative_review_stays_a_quality_finding(self):
        report = self.unavailable_primary()
        report['analysis']['dialogue_translation']['complete'] = False
        self.assertFalse(outage.inaccessible_audio(report))
        write_json(self.review / 'audio-model-review.json', report)
        with self.assertRaisesRegex(WorkflowError, 'actual comparative review exists'):
            outage.receipt(self.run, self.video)

    def test_inaccessible_audio_reason_can_name_media_after_failure(self):
        report = self.unavailable_primary()
        for field in ('dialogue_translation', 'background_music', 'sound_effects', 'sync'):
            report['analysis'][field]['reason'] = "Unable to open or access Audio A and Audio B."
        self.assertTrue(outage.inaccessible_audio(report))

    def test_model_timeout_keeps_unknown_request_without_retry(self):
        path = self.run / 'jobs/1.json'
        write_json(path, {**read_json(path), 'error': 'KIE transport/response failure (TimeoutError); inspect provider log before resubmitting'})
        result = outage.receipt(self.run, self.video)
        self.assertEqual(result['failed_models'][self.models[1]]['provider_code'], 'transport')
        self.assertEqual(read_json(path)['state'], 'ambiguous')

    def test_missing_dubbing_or_wrong_track_blocks(self):
        original = read_json(self.mix.parent / 'provenance.json')
        write_json(self.mix.parent / 'provenance.json', {**original, 'lines': []})
        with self.assertRaisesRegex(WorkflowError, 'every required target speech line'):
            outage.receipt(self.run, self.video)
        write_json(self.mix.parent / 'provenance.json', original)
        with patch.object(outage.audio, 'waveform_match', return_value={'correlation': .2, 'offset_seconds': 0}):
            with self.assertRaisesRegex(WorkflowError, 'does not match'):
                outage.receipt(self.run, self.video)
