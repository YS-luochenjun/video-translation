"""Source-style provenance and actual typesetting, never synthetic acceptance of ads."""
import copy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_localizer import compositor, fast_delivery, fonts, media, source_styles
from video_localizer.common import CODE_ROOT, WorkflowError, file_hash, read_json, write_json

REGULAR = next((p for p in [CODE_ROOT/'assets/fonts/arial.ttf',
    Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
    Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')] if p.exists()), None)
ITALIC = next((p for p in [Path('/System/Library/Fonts/Supplemental/Times New Roman Bold Italic.ttf'),
    Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif-BoldItalic.ttf')] if p.exists()), None)


@unittest.skipUnless(REGULAR, 'An actual installed font is needed')
class SourceStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (CODE_ROOT/'work/test-tmp').mkdir(parents=True, exist_ok=True)
        cls.shared = tempfile.TemporaryDirectory(dir=CODE_ROOT/'work/test-tmp')
        cls.video = Path(cls.shared.name)/'fixture.mp4'
        media.ffmpeg(['-f','lavfi','-i','color=c=teal:s=320x180:r=30:d=1',
                      '-an','-c:v','libx264','-pix_fmt','yuv420p',cls.video])

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=CODE_ROOT/'work/test-tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root/'runs/style-fixture'
        (self.run/'inputs').mkdir(parents=True)
        shutil.copyfile(self.video, self.run/'inputs/source.mp4')
        self.sha = file_hash(self.run/'inputs/source.mp4')
        write_json(self.run/'run.json', {'source':'inputs/source.mp4','source_sha256':self.sha})
        write_json(self.run/'inputs/request.json', {'target_language':'es','delivery_mode':'fast',
                                                   'source_style_contract_version':1})
        write_json(self.run/'analysis/media.json', {'width':320,'height':180,'duration':1,'fps':30,'has_audio':False})
        self.font = fonts.bind_file(self.run, REGULAR, 'Texto')
        self.item = {'id':'t001','source_text':'Text','target_text':'Texto','action':'model_edit',
            'start':0,'end':1,'bbox':[10,20,300,120],
            'display':{'font_asset':self.font,'font_size':34,'min_font_size':20,'bold':False,'italic':False,
                       'color':'#FFFFFF','outline':0},
            'style_treatment':{'route':'typeset','reason':'Synthetic known static label',
                'font_choice_reason':'Actual available sans-serif face with all Spanish glyphs','adaptations':{}}}
        self.inventory = {'source_sha256':self.sha,'text_instances':[self.item], 'speech_segments':[], 'shots':[]}
        self.style = {'id':'headline','instance_ids':['t001'],'reference_times':[.5],
            'observation':'Synthetic contract fixture only; not an observation of a customer video',
            'appearance':{'kind':'plain','font_class':'sans','weight':'regular','italic':False,
                          'color':'#FFFFFF','outline_layers':[],'effects':'none'},
            'layout':{'bbox':[10,20,300,120],'line_count':1,'align':'center'},
            'motion':{'kind':'static','observation':'Known generated stationary test fixture'},
            'protected_content':'Known uniform background; no scene object in this fixture'}
        self.spec = {'source_sha256':self.sha,'observed_by':'Synthetic fixture reviewer','styles':[self.style]}
        self.save()

    def save(self):
        write_json(self.run/'analysis/inventory.json', self.inventory)
        write_json(self.run/'inputs/styles.json', self.spec)

    def capture(self):
        self.save()
        result = source_styles.capture(self.run, 'inputs/styles.json', apply=True)
        self.inventory = read_json(self.run/'analysis/inventory.json')
        self.item = self.inventory['text_instances'][0]
        return result

    def contract(self):
        return source_styles.contract(self.run, self.inventory)

    def test_new_request_requires_capture_but_legacy_is_not_rewritten(self):
        with self.assertRaisesRegex(WorkflowError, 'Capture source typography'):
            self.contract()
        write_json(self.run/'inputs/request.json', {'target_language':'es'})
        self.assertIsNone(self.contract())

    def test_snapshot_comes_from_original_video_and_is_idempotent(self):
        result = self.capture()
        path = self.run/result['snapshot']['path']; original = path.read_bytes()
        snapshot = read_json(path)
        self.assertEqual(len(snapshot['frames']),1)
        from PIL import Image
        with Image.open(self.run/next(iter(snapshot['frames'].values()))['path']) as image:
            self.assertEqual(image.size,(320,180))
        with patch.object(media,'ffmpeg',side_effect=AssertionError('Existing immutable frames must be reused')):
            again = source_styles.capture(self.run,'inputs/styles.json',apply=True)
        self.assertEqual(result['snapshot'],again['snapshot'])
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(self.contract()['snapshot'],result['snapshot'])

    def test_style_change_creates_a_new_snapshot_without_overwriting_old(self):
        first = self.capture(); path = self.run/first['snapshot']['path']; data=path.read_bytes()
        self.spec['styles'][0]['observation'] += '; additional observed fact'
        second = self.capture()
        self.assertNotEqual(first['snapshot']['path'],second['snapshot']['path'])
        self.assertEqual(path.read_bytes(),data)

    def test_invalid_reference_time_and_incomplete_coverage_stop_capture(self):
        self.style['reference_times']=[1]
        with self.assertRaisesRegex(WorkflowError,'outside its source text'):self.capture()
        self.style['reference_times']=[.5]
        other=copy.deepcopy(self.item);other['id']='t002';self.inventory['text_instances'].append(other)
        with self.assertRaisesRegex(WorkflowError,'every translated text'):self.capture()

    def test_tampered_source_frame_or_source_geometry_invalidates_snapshot(self):
        first=self.capture();saved=read_json(self.run/first['snapshot']['path'])
        image=self.run/next(iter(saved['frames'].values()))['path'];raw=image.read_bytes()
        image.write_bytes(b'changed')
        with self.assertRaisesRegex(WorkflowError,'reference frame missing or changed'):self.contract()
        image.write_bytes(raw);self.item['bbox'][0]+=1
        with self.assertRaisesRegex(WorkflowError,'Source text/geometry changed'):self.contract()

    def test_target_copy_and_style_change_require_a_new_plan_not_a_new_source_snapshot(self):
        self.capture();old=self.contract();self.item['target_text']='Otro texto'
        self.assertEqual(self.contract()['snapshot'],old['snapshot'])
        with self.assertRaisesRegex(WorkflowError,'rebuild/register'):source_styles.verify_contract(self.run,{'source_style_contract':old},self.inventory)

    def test_colour_outline_line_count_and_motion_changes_need_explicit_adaptations(self):
        self.capture()
        for key,value,aspect in [('color','#000000','color'),('outline',4,'outlines')]:
            original=copy.deepcopy(self.item['display']);self.item['display'][key]=value
            with self.assertRaisesRegex(WorkflowError,'without an explained adaptation'):self.contract()
            self.item['style_treatment']['adaptations'][aspect]='Synthetic deliberately chosen target-language variation'
            self.contract();self.item['display']=original;self.item['style_treatment']['adaptations']={}
        self.item['target_text']='Dos\nlíneas'
        with self.assertRaisesRegex(WorkflowError,'without an explained adaptation'):self.contract()

    def test_no_default_font_or_fake_italic_and_no_silent_tiny_text(self):
        self.capture();self.item['display'].pop('font_asset')
        with self.assertRaisesRegex(WorkflowError,'real hash-bound'):self.contract()
        self.item['display']['font_asset']=self.font;self.item['display']['italic']=True
        with self.assertRaisesRegex(WorkflowError,'actual requested upright/italic'):self.contract()
        self.item['display']['italic']=False;self.item['target_text']='unreadably long '*80
        with self.assertRaisesRegex(WorkflowError,'readable size'):
            compositor.text(self.video,{'start':0,'end':1},[self.item],{'width':320,'height':180},self.run/'outputs/unreadable',run=self.run)

    def test_route_labels_cannot_fake_imagegen_or_tracking_execution(self):
        self.capture();self.item['style_treatment']['route']='imagegen_asset'
        with self.assertRaisesRegex(WorkflowError,'bound surface'):self.contract()
        self.item['display']['typography_layer']=True
        with self.assertRaisesRegex(WorkflowError,'every covered shot'):self.contract()

    def test_motion_loss_requires_explanation_and_is_never_an_automatic_pass(self):
        self.style['motion']['kind']='rigid';self.capture()
        with self.assertRaisesRegex(WorkflowError,'tracked route or an explicit motion downgrade'):self.contract()
        self.item['style_treatment']['adaptations']['motion']='Synthetic bounded static fallback; motion remains lost'
        self.contract()
        self.assertTrue(source_styles.review_failures(self.run,self.inventory,{}, {'sha256':'c'*64}))

    def test_wan_reference_needs_actual_bytes_and_rejects_erase_only_use(self):
        self.capture();self.item['style_treatment']['route']='wan_reference'
        self.inventory['shots']=[{'id':'s001','start':0,'end':1,'reference_image':{'path':'missing.jpg','sha256':'x'}}]
        with self.assertRaisesRegex(WorkflowError,'reference missing or changed'):self.contract()
        snapshot=read_json(self.run/self.inventory['source_style_snapshot']['path'])
        frame=next(iter(snapshot['frames'].values()))
        self.inventory['shots'][0]['reference_image']={k:frame[k] for k in ('path','sha256')}
        self.contract()
        with self.assertRaisesRegex(WorkflowError,'erase-only'):
            source_styles.validate_routes(self.run,self.inventory,[{'route':'wan_edit','instance_ids':['t001'],'model_text_mode':'erase_then_overlay'}])

    def test_explicit_two_line_spacing_is_rendered_and_not_silently_ignored(self):
        self.capture();self.item['target_text']='Dos\nlíneas';self.item['display']['line_height']=40
        events=compositor.text_events({'start':0,'end':1},[self.item],{'width':320,'height':180},self.run/'outputs/lines',self.run)
        self.assertEqual(len(events),2)
        self.assertIn('\\pos(160.0,60.0)',events[0]);self.assertIn('\\pos(160.0,100.0)',events[1])

    def test_target_layout_can_move_without_rewriting_source_erase_geometry(self):
        self.capture();old=self.item['bbox'][:];snapshot=self.inventory['source_style_snapshot']
        self.item['display']['bbox']=[10,60,300,80]
        with self.assertRaisesRegex(WorkflowError,'without an explained adaptation'):self.contract()
        self.item['style_treatment']['adaptations']['layout']='Synthetic deliberate target layout shift; original erase bbox remains unchanged'
        self.assertEqual(self.contract()['snapshot'],snapshot)
        events=compositor.text_events({'start':0,'end':1},[self.item],{'width':320,'height':180},self.run/'outputs/moved',self.run)
        self.assertIn('\\pos(160.0,100.0)',events[0]);self.assertEqual(self.item['bbox'],old)

    def test_exact_source_reuse_copies_references_but_not_target_choices(self):
        result=self.capture();target=self.root/'runs/other-locale'
        shutil.copytree(self.run,target)
        write_json(target/'inputs/request.json',{'target_language':'pt','source_style_contract_version':1})
        inv=read_json(target/'analysis/inventory.json');inv['text_instances'][0]['target_text']='Texto português'
        write_json(target/'analysis/inventory.json',inv)
        receipt=source_styles.reuse(target,self.run)
        inv=read_json(target/'analysis/inventory.json')
        self.assertEqual(receipt['snapshot'],result['snapshot']);self.assertNotIn('style_treatment',inv['text_instances'][0])
        with self.assertRaisesRegex(WorkflowError,'Choose a typography route'):source_styles.contract(target,inv)
        inv['source_sha256']='0'*64;write_json(target/'analysis/inventory.json',inv)
        with self.assertRaisesRegex(WorkflowError,'exact source'):source_styles.reuse(target,self.run)

    def test_reuse_checks_actual_video_bytes_before_copying_any_style_files(self):
        self.capture();target=self.root/'runs/tampered-source';shutil.copytree(self.run,target)
        (target/'inputs/source.mp4').write_bytes(b'changed source with stale metadata')
        with patch.object(source_styles.shutil,'copyfile') as copier:
            with self.assertRaisesRegex(WorkflowError,'Source changed'):source_styles.reuse(target,self.run)
            copier.assert_not_called()

    def test_fast_plan_binds_source_snapshot_font_and_review_template(self):
        self.capture();self.save()
        (self.root/'config').mkdir();shutil.copyfile(CODE_ROOT/'config/fast-delivery.json',self.root/'config/fast-delivery.json')
        (self.run/'outputs').mkdir();shutil.copyfile(self.video,self.run/'outputs/fixture.mp4')
        write_json(self.run/'inputs/recipe.json',{'source_sha256':self.sha,'native_frame_mapping':True,
            'output':{'path':'outputs/fixture.mp4','sha256':file_hash(self.run/'outputs/fixture.mp4')},'assets':[]})
        fast_delivery.register(self.run,'inputs/recipe.json')
        plan=read_json(self.run/'plan.json');self.assertIn('source_style_contract',plan)
        self.assertEqual(read_json(self.run/'review/fast-template.json')['source_style_review'][0]['checks']['lettering']['status'],'pending')
        (self.run/self.font['path']).write_bytes(b'font changed')
        with self.assertRaisesRegex(WorkflowError,'font missing or changed'):fast_delivery.validate_plan(self.run,plan)

    def test_style_review_needs_current_result_images_and_preserves_negative_judgment(self):
        self.capture();candidate={'sha256':'c'*64,'plan_id':'fixture'}
        self.assertIn('source_style_review_coverage_missing',source_styles.review_failures(self.run,self.inventory,{},candidate))
        frame=self.run/'review/result.jpg';frame.parent.mkdir();frame.write_bytes(b'synthetic captured image fixture')
        asset={'path':'review/result.jpg','sha256':file_hash(frame)}
        write_json(self.run/'review/capture.json',{'video_sha256':candidate['sha256'],'files':{asset['path']:asset['sha256']}})
        rows=source_styles.review_template(self.inventory)
        for row in rows:
            row['evidence']=[asset]
            for check in row['checks'].values():check.update(status='pass',observation='Synthetic contract fixture only')
        review={'source_style_review':rows}
        self.assertEqual(source_styles.review_failures(self.run,self.inventory,review,candidate),[])
        rows[0]['checks']['motion']['status']='fail'
        self.assertIn('source_style_motion_unreviewed_or_failed:t001',source_styles.review_failures(self.run,self.inventory,review,candidate))
        rows[0]['checks']['motion']['status']='minor'
        self.assertEqual(source_styles.review_failures(self.run,self.inventory,review,candidate),[])
        candidate['sha256']='d'*64
        self.assertIn('source_style_current_video_capture_missing',source_styles.review_failures(self.run,self.inventory,review,candidate))

    @unittest.skipUnless(ITALIC,'A real serif bold italic font is required')
    def test_actual_serif_bold_italic_two_line_render_and_archive_closure(self):
        self.capture();asset=fonts.bind_file(self.run,ITALIC,'¡No adivinarás\neste giro!')
        item=copy.deepcopy(self.item);item['target_text']='¡No adivinarás\neste giro!'
        item['display'].update(font_asset=asset,bold=True,italic=True,color='#000000',outline=3,outline_color='#FFFFFF')
        output=compositor.text(self.video,{'start':0,'end':1},[item],{'width':320,'height':180},self.run/'outputs/styled',run=self.run)
        self.assertEqual(media.probe(output)['width'],320)
        ass=(output.parent/'tracked.ass').read_text(encoding='utf-8-sig')
        self.assertIn('\\i1',ass);self.assertIn('\\b1',ass);self.assertIn('\\bord3',ass)
        family=fonts.inspect_asset(self.run,asset)['family'];self.assertIn('\\fn'+family,ass)
        result=media.command(['ffmpeg','-hide_banner','-loglevel','verbose','-i',self.video,
            '-vf',media.ass_filter('tracked.ass',output.parent/'fonts'),'-t','0.1','-f','null','-'],cwd=output.parent)
        self.assertNotIn('failed to find any fallback',result.stderr.lower())
        from video_localizer.library import _asset_closure
        closure=_asset_closure(self.run,[(self.run/self.inventory['source_style_snapshot']['path'],self.inventory['source_style_snapshot']['sha256'])])
        self.assertTrue(any('/frames/' in k for k in closure))


if __name__=='__main__':
    unittest.main()
