import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import visual_audit as audit, prepared, media, reuse, batches, workflow
from video_localizer.common import WorkflowError, file_hash, read_json, write_json
from workspace_fixture import observe_visual_fixture

PROJECT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg needed')
class VisualAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=PROJECT/'work/test-tmp')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.seed = cls.root/'seed'; cls.seed.mkdir()
        for name, color in [('source', 'blue'), ('master', 'black'), ('candidate', 'green')]:
            media.ffmpeg(['-f','lavfi','-i',f'color=c={color}:s=160x120:r=10:d=0.6',
                          '-c:v','libx264','-pix_fmt','yuv420p',cls.seed/(name+'.mp4')])

    def setUp(self):
        self.run = self.root/'runs'/self._testMethodName
        shutil.copytree(self.seed, self.run)
        sha = file_hash(self.run/'source.mp4')
        write_json(self.run/'run.json', {'source':'source.mp4','source_sha256':sha})
        write_json(self.run/'inputs/request.json', {'target_language':'es'})
        write_json(self.run/'analysis/media.json', media.probe(self.run/'source.mp4'))
        master = {'path':'master.mp4','sha256':file_hash(self.run/'master.mp4')}
        write_json(self.run/'preparation.json', {'source_sha256':sha,'target_language':None,'contains_target_typography':False,
                   'output':master,'inputs':[{'path':'source.mp4','sha256':sha}]})
        self.asset = {**master,'record':'preparation.json','record_sha256':file_hash(self.run/'preparation.json')}
        self.inventory = {'content_features':['animated_text'],'shots':[{'id':'s1','start':0,'end':.6,'prepared_video':self.asset}],
            'text_instances':[{'id':'t1','source_text':'Test','target_text':'Prueba','action':'solid_overlay',
                               'start':.1,'end':.5,'bbox':[20,30,80,30],'background_is_static':True}]}
        write_json(self.run/'analysis/inventory.json', self.inventory)
        write_json(self.run/'plan.json', {'id':'fixture-plan'})
        write_json(self.run/'outputs/candidate.json', {'path':'candidate.mp4','sha256':file_hash(self.run/'candidate.mp4'),'plan_id':'fixture-plan'})

    def test_pending_native_evidence_and_boundary_coverage_do_not_change_video(self):
        before = file_hash(self.run/'candidate.mp4')
        with patch.object(audit, '_timestamps', wraps=audit._timestamps) as clocks:
            result = audit.generate(self.run)
        decoded = [str(call.args[0]) for call in clocks.call_args_list]
        self.assertEqual(decoded.count(str(self.run/'candidate.mp4')), 1)
        manifest = read_json(self.run/result['manifest'])
        row = manifest['instances'][0]
        self.assertEqual(row['required_frames'], list(range(6)))
        template = read_json(next((self.run/result['manifest']).parent.glob('templates/*.json')))
        self.assertEqual({c['status'] for c in template['checks'].values()}, {'pending'})
        self.assertEqual(template['reviewed_pages'], [])
        from PIL import Image
        with Image.open((self.run/result['manifest']).parent/row['pages'][0]['id']) as image:
            self.assertEqual(image.width, row['region'][2]*3)  # source/master/final, no thumbnail
        with self.assertRaisesRegex(WorkflowError, 'pending or incomplete'):
            audit.verify_final(self.run)
        self.assertEqual(file_hash(self.run/'candidate.mp4'), before)
        self.assertTrue(audit.generate(self.run)['reused'])

    def test_per_instance_observation_pass_staleness_and_tampered_evidence(self):
        result = observe_visual_fixture(self.run)
        self.assertIn('reviews_sha256', audit.verify_final(self.run))
        path = self.run/result['manifest']; manifest = read_json(path)
        page = path.parent/manifest['instances'][0]['pages'][0]['id']
        page.write_bytes(b'tampered')
        with self.assertRaisesRegex(WorkflowError, 'evidence missing or changed'):
            audit.verify_final(self.run)

    def test_changed_copy_invalidates_review_even_when_video_is_unchanged(self):
        observe_visual_fixture(self.run)
        self.inventory['text_instances'][0]['target_text'] = 'Different copy'
        write_json(self.run/'analysis/inventory.json', self.inventory)
        with self.assertRaisesRegex(WorkflowError, 'audit missing'):
            audit.verify_final(self.run)

    def test_missing_frames_and_fake_na_are_rejected(self):
        result = observe_visual_fixture(self.run)
        folder = (self.run/result['manifest']).parent
        manifest = read_json(folder/audit.MANIFEST)
        manifest['instances'][0]['pages'].pop()
        write_json(folder/audit.MANIFEST, manifest)
        with self.assertRaisesRegex(WorkflowError, 'pages are missing'):
            audit.verify_final(self.run)
        row = manifest['instances'][0]
        record = read_json(folder/read_json(folder/'reviews.json')['t1']['path'])
        record['checks']['erasure']['status'] = 'not_applicable'
        with self.assertRaises(WorkflowError):
            audit._review_valid(record, row, manifest['binding'])

    def test_neutral_release_requires_individual_review_and_is_portable(self):
        record = read_json(self.run/'run.json')
        write_json(self.run/'run.json', {**record, 'visual_storage': 'comparisons-v2'})
        old = file_hash(self.run/'preparation.json')
        audit.generate(self.run, 'neutral', 's1')
        with self.assertRaisesRegex(WorkflowError, 'pending or incomplete'):
            audit.release_neutral(self.run, 's1')
        observe_visual_fixture(self.run, 'neutral', 's1')
        asset = read_json(self.run/'analysis/inventory.json')['shots'][0]['prepared_video']
        prepared.verify_for_production(self.run, asset, file_hash(self.run/'source.mp4'), self.root)
        self.assertEqual(file_hash(self.run/'preparation.json'), old)
        target = self.root/'runs/reuse-target'; shutil.copytree(self.seed, target)
        write_json(target/'run.json', read_json(self.run/'run.json'))
        inv = copy.deepcopy(self.inventory); inv['shots'][0].pop('prepared_video'); inv['text_instances'][0]['target_text']='Bonjour'
        write_json(target/'analysis/inventory.json',inv)
        result = reuse.neutral(target,self.run,'s1','s1')
        (self.run/'master.mp4').write_bytes(b'origin removed')
        prepared.verify_for_production(target,result['prepared_video'],file_hash(target/'source.mp4'),self.root)

    def test_pilot_cannot_use_old_quality_pass_without_visual_observations(self):
        plan = {'id':'fixture-plan','source_sha256':file_hash(self.run/'source.mp4'),'segments':[]}
        record = {'pilot':self.run.name,'source_sha256':plan['source_sha256']}
        with patch.object(workflow,'current_plan',return_value=plan), patch.object(workflow,'quality',return_value={'decision':'pass'}) as quality:
            with self.assertRaisesRegex(WorkflowError, 'Representative language'):
                batches._pilot_snapshot(record,self.root)
            quality.assert_called_once()

    def test_identical_neutral_bytes_in_two_shots_keep_separate_interval_reviews(self):
        # Two pure-color cards may have identical prepared bytes but belong to
        # different times and text instances in the same source.
        source = self.run/'long-source.mp4'
        media.ffmpeg(['-f','lavfi','-i','color=c=blue:s=160x120:r=10:d=1.2',
                      '-c:v','libx264','-pix_fmt','yuv420p',source])
        sha = file_hash(source)
        write_json(self.run/'run.json', {'source':'long-source.mp4','source_sha256':sha})
        record = read_json(self.run/'preparation.json')
        record.update(source_sha256=sha, inputs=[{'path':'long-source.mp4','sha256':sha}])
        write_json(self.run/'preparation.json',record)
        asset = {**self.asset,'record_sha256':file_hash(self.run/'preparation.json')}
        self.inventory['shots'] = [{'id':'s1','start':0,'end':.6,'prepared_video':asset},
                                  {'id':'s2','start':.6,'end':1.2,'prepared_video':asset}]
        self.inventory['text_instances'].append({**self.inventory['text_instances'][0], 'id':'t2','start':.7,'end':1.1})
        write_json(self.run/'analysis/inventory.json',self.inventory)
        observe_visual_fixture(self.run,'neutral','s1')
        observe_visual_fixture(self.run,'neutral','s2')
        for shot in read_json(self.run/'analysis/inventory.json')['shots']:
            prepared.verify_for_production(self.run,shot['prepared_video'],sha,self.root)
            binding, *_ = audit.context(self.run,'neutral',asset=shot['prepared_video'])
            self.assertEqual(binding['interval'],[shot['start'],shot['end']])

    def test_bulk_pass_submission_is_rejected(self):
        result = audit.generate(self.run)
        write_json(self.run/'bulk.json',[{'decision':'pass'}])
        with self.assertRaisesRegex(WorkflowError,'one instance'):
            audit.review(self.run,result['manifest'],'bulk.json')

    def test_identical_boilerplate_cannot_approve_two_instances(self):
        self.inventory['text_instances'].append({**self.inventory['text_instances'][0], 'id':'t2', 'bbox':[30,70,60,20]})
        write_json(self.run/'analysis/inventory.json', self.inventory)
        result = observe_visual_fixture(self.run)
        folder = (self.run/result['manifest']).parent
        index = read_json(folder/'reviews.json')
        first = read_json(folder/index['t1']['path']); second = read_json(folder/index['t2']['path'])
        for key in second['checks']:
            second['checks'][key]['observation'] = first['checks'][key]['observation']
        write_json(self.run/'second.json',second)
        audit.review(self.run,result['manifest'],'second.json')
        with self.assertRaisesRegex(WorkflowError,'Duplicated'):
            audit.verify_final(self.run)

    def test_new_failed_neutral_observation_revokes_release_without_touching_old_record(self):
        result = observe_visual_fixture(self.run,'neutral','s1')
        folder = (self.run/result['manifest']).parent
        asset = read_json(self.run/'analysis/inventory.json')['shots'][0]['prepared_video']
        frozen = file_hash(self.run/asset['record'])
        entry = read_json(folder/'reviews.json')['t1']; observation = read_json(folder/entry['path'])
        observation['checks']['erasure']['status']='fail'
        write_json(self.run/'failure.json',observation)
        audit.review(self.run,result['manifest'],'failure.json')
        with self.assertRaisesRegex(WorkflowError,'pending or failed'):
            prepared.verify_for_production(self.run,asset,file_hash(self.run/'source.mp4'),self.root)
        self.assertEqual(file_hash(self.run/asset['record']),frozen)

    def test_layer_change_invalidates_final_even_without_reencoding(self):
        observe_visual_fixture(self.run)
        (self.run/'master.mp4').write_bytes(b'changed neutral asset')
        with self.assertRaisesRegex(WorkflowError,'asset missing or changed'):
            audit.verify_final(self.run)

    def test_quality_objection_blocks_neutral_release_even_with_complete_observations(self):
        observe_visual_fixture(self.run,'neutral','s1')
        before = file_hash(self.run/'analysis/inventory.json')
        with patch('video_localizer.quality_holds.active',return_value=[{'id':'fixture-objection','reason':'Residual letters'}]):
            with self.assertRaisesRegex(WorkflowError,'Quality hold'):
                audit.release_neutral(self.run,'s1')
        self.assertEqual(file_hash(self.run/'analysis/inventory.json'),before)

    def test_frame_policy_static_is_bounded_and_motion_is_continuous(self):
        item = {'start':1,'end':9,'background_is_static':True}
        times = [n/10 for n in range(100)]
        static,_ = audit.required_frames(item,times,0,[])
        moving,_ = audit.required_frames(item,times,0,['foreground_occlusion'])
        self.assertLess(len(static),20)
        self.assertTrue(set(range(10,90)) <= set(moving))

    def test_compact_storage_keeps_identical_native_pages_and_legacy_bundle(self):
        from PIL import Image
        legacy = audit.generate(self.run)
        folder = (self.run/legacy['manifest']).parent
        manifest = read_json(folder/audit.MANIFEST)
        pixels = {}
        for page in manifest['instances'][0]['pages']:
            with Image.open(folder/page['id']) as im:
                pixels[page['id']] = (im.size, im.tobytes())
        old = read_json(self.run/'run.json')
        write_json(self.run/'run.json', {**old, 'visual_storage': 'comparisons-v2'})
        self.assertTrue(audit.generate(self.run)['reused'])
        archived = folder.with_name(folder.name+'-legacy')
        folder.rename(archived)
        compact = audit.generate(self.run)
        new = read_json(self.run/compact['manifest'])
        self.assertEqual(new['instances'], manifest['instances'])
        self.assertFalse(any('/source/' in p or '/final/' in p or '/neutral-0/' in p for p in new['files']))
        for name, expected in pixels.items():
            with Image.open(folder/name) as im:
                self.assertEqual((im.size, im.tobytes()), expected)
        self.assertLess(sum((folder/p).stat().st_size for p in new['files']),
                        sum((archived/p).stat().st_size for p in manifest['files']))

    def test_concise_notes_preserve_explicit_coverage_and_verify_once(self):
        from video_localizer import visual_notes
        self.inventory['text_instances'].append({**self.inventory['text_instances'][0], 'id': 't2', 'bbox': [30,70,60,20]})
        write_json(self.run/'analysis/inventory.json', self.inventory)
        result = observe_visual_fixture(self.run)
        folder = (self.run/result['manifest']).parent
        index = read_json(folder/'reviews.json')
        record = read_json(folder/index['t1']['path'])
        note = {k: v for k, v in record.items() if k not in ('binding_id', 'reviewer', 'review_type', 'reviewed_at', 'reviewed_pages')}
        note['reviewed_frames'] = [[0, 5]]
        for check in note['checks'].values():
            check.pop('evidence_pages'); check['frames'] = [0, 5]
        packet = {'manifest_sha256': file_hash(folder/audit.MANIFEST), 'reviewer': 'test author',
                  'review_type': 'same_agent', 'instances': [note]}
        second = copy.deepcopy(note); second['instance_id'] = 't2'
        for check in second['checks'].values():
            check['observation'] += ' Second instance separately observed.'
        packet['instances'].append(second)
        write_json(self.run/'notes.json', packet)
        with patch.object(audit, '_verify_files', wraps=audit._verify_files) as verified:
            outcome = visual_notes.submit(self.run, result['manifest'], 'notes.json')
            self.assertEqual(verified.call_count, 1)
        self.assertEqual(outcome['results'][0]['state'], 'reviewed')
        audit.verify_final(self.run)
        before = file_hash(folder/'reviews.json')
        original_write = visual_notes.write_json
        def interrupted(path, value):
            if Path(path).name == 'reviews.json':
                raise OSError('Simulated interruption before atomic index publication')
            return original_write(path, value)
        with patch.object(visual_notes, 'write_json', side_effect=interrupted):
            with self.assertRaises(OSError):
                visual_notes.submit(self.run, result['manifest'], 'notes.json')
        self.assertEqual(file_hash(folder/'reviews.json'), before)
        audit.verify_final(self.run)
        note['reviewed_frames'] = [0]
        write_json(self.run/'notes.json', packet)
        self.assertEqual(visual_notes.submit(self.run, result['manifest'], 'notes.json')['results'][0]['state'], 'pending_or_failed')
        with self.assertRaises(WorkflowError):
            audit.verify_final(self.run)
        packet['manifest_sha256'] = 'stale'
        write_json(self.run/'notes.json', packet)
        with self.assertRaisesRegex(WorkflowError, 'Stale'):
            visual_notes.submit(self.run, result['manifest'], 'notes.json')

    def test_minimal_failure_revokes_pass_without_fabricated_observations(self):
        from video_localizer import visual_notes
        result = observe_visual_fixture(self.run)
        folder = (self.run/result['manifest']).parent
        packet = {'manifest_sha256': file_hash(folder/audit.MANIFEST), 'reviewer': 'test author',
                  'review_type': 'same_agent', 'instances': [{'instance_id': 't1',
                  'issue': {'check': 'erasure', 'frames': [2], 'observation': 'Residual source letters at frame two'}}]}
        write_json(self.run/'issue.json', packet)
        visual_notes.submit(self.run, result['manifest'], 'issue.json')
        reference = read_json(folder/'reviews.json')['t1']
        saved = read_json(folder/reference['path'])
        self.assertEqual(saved['source_appearance'], {})
        self.assertEqual(saved['checks']['erasure']['status'], 'fail')
        with self.assertRaises(WorkflowError):
            audit.verify_final(self.run)

    def test_native_gallery_preserves_pixels_and_does_not_approve(self):
        from video_localizer import visual_notes
        from PIL import Image
        result = audit.generate(self.run)
        folder = (self.run/result['manifest']).parent
        before = file_hash(folder/'reviews.json')
        gallery = visual_notes.pages(self.run, result['manifest'], 't1', max_height=220)
        self.assertFalse(gallery['automatic_pass'])
        for group in gallery['pages']:
            with Image.open(self.run/group['path']) as im:
                for tile in group['tiles']:
                    with Image.open(folder/tile['id']) as source:
                        cropped = im.crop((0, tile['top'], source.width, tile['top']+source.height))
                        self.assertEqual(cropped.tobytes(), source.convert('RGB').tobytes())
        self.assertEqual(file_hash(folder/'reviews.json'), before)
        self.assertTrue(visual_notes.pages(self.run, result['manifest'], 't1', max_height=220)['reused'])
        Path(gallery['pages'][0]['path']).write_bytes(b'broken cache')
        self.assertNotIn('reused', visual_notes.pages(self.run, result['manifest'], 't1', max_height=220))
        manifest = read_json(folder/audit.MANIFEST)
        (folder/manifest['instances'][0]['pages'][0]['id']).write_bytes(b'tampered evidence')
        with self.assertRaisesRegex(WorkflowError, 'evidence missing or changed'):
            visual_notes.pages(self.run, result['manifest'], 't1', max_height=220)

    def test_layer_selection_uses_actual_strip_order_and_returns_cursor(self):
        from video_localizer import visual_notes
        from PIL import Image
        result=audit.generate(self.run)
        folder=(self.run/result['manifest']).parent
        manifest=read_json(folder/audit.MANIFEST)
        before=file_hash(folder/'reviews.json')
        gallery=visual_notes.pages(self.run,result['manifest'],'t1',220,'final',None,1)
        first=manifest['instances'][0]['pages'][0]
        with Image.open(folder/first['id']) as strip, Image.open(gallery['pages'][0]['path']) as shown:
            width=strip.width//len(first['layers']);index=list(first['layers']).index('final')
            expected=strip.crop((index*width,0,(index+1)*width,strip.height)).convert('RGB')
            actual=shown.crop((0,24,width,24+strip.height))
            self.assertEqual(expected.tobytes(),actual.tobytes())
        self.assertIsNotNone(gallery['next_frame'])
        self.assertEqual(before,file_hash(folder/'reviews.json'))
        self.assertEqual(gallery['layer'],'final')

    def test_multicolumn_gallery_keeps_all_native_pixels_and_frame_ids(self):
        from video_localizer import visual_notes
        from PIL import Image
        result = audit.generate(self.run)
        folder = (self.run/result['manifest']).parent
        manifest = read_json(folder/audit.MANIFEST)
        before = file_hash(folder/'reviews.json')
        gallery = visual_notes.pages(self.run, result['manifest'], 't1', 220, columns=2)
        frames = []
        for page in gallery['pages']:
            with Image.open(page['path']) as shown:
                for tile in page['tiles']:
                    frames.append(tile['frame'])
                    with Image.open(folder/tile['id']) as source:
                        x,y = tile['left'],tile['top']
                        self.assertEqual(shown.crop((x,y,x+source.width,y+source.height)).tobytes(),
                                         source.convert('RGB').tobytes())
        self.assertEqual(frames,manifest['instances'][0]['required_frames'])
        self.assertEqual(before,file_hash(folder/'reviews.json'))

    def test_v3_reuses_identical_pixels_but_new_video_has_no_inherited_review(self):
        from PIL import Image
        write_json(self.run/'run.json',{**read_json(self.run/'run.json'),'visual_storage':'comparisons-v3'})
        first=audit.generate(self.run)
        self.assertGreater(first['identical_pixel_pages_reused'],0)
        folder=(self.run/first['manifest']).parent
        manifest=read_json(folder/audit.MANIFEST)
        page=manifest['instances'][0]['pages'][0]
        with Image.open(folder/page['id']) as shown:
            self.assertEqual(shown.width,manifest['instances'][0]['region'][2]*3)
        media.ffmpeg(['-i',self.run/'candidate.mp4','-c','copy','-metadata','comment=container-change',self.run/'other.mp4'])
        write_json(self.run/'outputs/candidate.json',{'path':'other.mp4','sha256':file_hash(self.run/'other.mp4'),'plan_id':'fixture-plan'})
        second=audit.generate(self.run)
        self.assertNotEqual(first['manifest'],second['manifest'])
        self.assertEqual(second['identical_pixel_pages_reused'],6)
        second_folder=(self.run/second['manifest']).parent
        self.assertEqual(read_json(second_folder/'reviews.json'),{})
        shutil.rmtree(folder)
        audit._verify_files(second_folder,read_json(second_folder/audit.MANIFEST))
        with self.assertRaisesRegex(WorkflowError,'pending or incomplete'):
            audit.verify_final(self.run)
