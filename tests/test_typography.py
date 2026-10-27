import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from video_localizer import typography, media, resources, render_cache
from video_localizer.common import CODE_ROOT, WorkflowError, file_hash, read_json, write_json


FONT = next((p for p in [CODE_ROOT/'assets/fonts/arial.ttf',Path('/System/Library/Fonts/Supplemental/Arial.ttf')]
             if p.is_file()),None)


@unittest.skipUnless(FONT and shutil.which('ffmpeg'),'Actual font and FFmpeg required')
class TypographyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=CODE_ROOT/'work/test-tmp');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.run=self.root/'runs/fixture';(self.run/'inputs').mkdir(parents=True)
        source=self.run/'inputs/source.mp4'
        media.ffmpeg(['-f','lavfi','-i','color=c=teal:s=320x180:r=30:d=0.8','-an','-c:v','libx264','-pix_fmt','yuv420p',source])
        shutil.copyfile(FONT,self.run/'inputs/font.ttf')
        write_json(self.run/'run.json',{'source':'inputs/source.mp4','source_sha256':file_hash(source)})
        write_json(self.run/'inputs/request.json',{'target_language':'en'})
        self.item={'id':'t001','source_text':'Go next','target_text':'Go next','action':'model_edit',
                   'start':1/30,'end':11/30,'bbox':[10,20,300,120],'text_role':'scene_text',
                   'display':{'font_size':26,'min_font_size':20,'color':'#FFFFFF','outline':1,
                              'font_asset':{'path':'inputs/font.ttf','sha256':file_hash(self.run/'inputs/font.ttf')},
                              'motion':{'kind':'emphasis','emphasize':'next','emphasis_at':.2}}}
        self.segment={'id':'s001','start':0,'end':.8,'instance_ids':['t001']}
        self.meta={'width':320,'height':180,'fps':30,'duration':.8}
        self.save()
    def save(self):write_json(self.run/'analysis/inventory.json',{'text_instances':[self.item]})
    def render(self):
        return typography.render(self.run,self.run/'inputs/source.mp4',self.segment,[self.item],self.meta,self.run/'outputs/type')

    def test_unavailable_browser_falls_back_with_frame_exact_alpha_and_bound_provenance(self):
        with patch.object(typography,'_remotion',side_effect=WorkflowError('browser unavailable')):
            output=self.render()
        self.assertTrue(output.is_file())
        path=self.run/'outputs/type/typography-result.json';asset={'path':str(path.relative_to(self.run)),'sha256':file_hash(path)}
        result=typography.verify_receipt(self.run,asset)
        typography.verify_assets(self.run,[asset],{'text_instances':[self.item]})
        with self.assertRaises(WorkflowError):typography.verify_assets(self.run,[],{'text_instances':[self.item]})
        from video_localizer.library import _asset_closure
        closure=_asset_closure(self.run,[(path,file_hash(path))])
        self.assertIn('inputs/font.ttf',closure)
        self.assertIn('outputs/type/motion/layer.mov',closure)
        self.assertEqual(result['renderer'],'ffmpeg_static');self.assertTrue(result['review_required'])
        alpha=read_json(self.run/result['alpha_check']['path'])
        self.assertEqual(len(alpha['nonzero_pixels']),24)
        self.assertEqual([i for i,v in enumerate(alpha['nonzero_pixels']) if v],list(range(1,11)))
        self.assertTrue(read_json(self.run/'outputs/type/motion/fallback.json')['text_and_timing_preserved'])
        self.assertTrue(typography.review_failures(self.run,[asset],{}))
        self.assertFalse(typography.review_failures(self.run,[asset],{'typography_fallbacks':[
            {'receipt_sha256':asset['sha256'],'accepted':True,'observation':'Fixture static text and timing inspected; animation intentionally absent'}]}))
        # Tampering with font, copy, source or output cannot be hidden by fallback.
        (self.run/'inputs/font.ttf').write_bytes(b'changed')
        with self.assertRaises(WorkflowError):typography.verify_receipt(self.run,asset)

    def test_missing_glyph_or_unreadable_fit_is_a_blocker_not_runtime_fallback(self):
        for text in ['Go \U0010ffff','this translation is far too long '*20]:
            self.item['target_text']=text;self.item['display']['motion']={'kind':'title'};self.save()
            with patch.object(typography,'_remotion') as remotion:
                with self.assertRaises(WorkflowError):self.render()
                remotion.assert_not_called()

    def test_rejects_stale_copy_bad_motion_and_specialist_geometry(self):
        with patch.object(typography,'_remotion') as remotion:
            stale=copy.deepcopy(self.item);stale['target_text']='changed'
            with self.assertRaises(WorkflowError):typography.render(self.run,self.run/'inputs/source.mp4',self.segment,[stale],self.meta,self.run/'outputs/stale')
            remotion.assert_not_called()
        for value in [{}, {'kind':'speech'}, {'kind':'emphasis','emphasize':'absent'}]:
            self.item['display']['motion']=value
            with self.assertRaises(WorkflowError):typography.contract(self.run,{'text_instances':[self.item]})
        self.item['display']['motion']={'kind':'title'};self.item['trajectory']=[{'time':0,'bbox':self.item['bbox']}]
        with self.assertRaises(WorkflowError):typography.contract(self.run,{'text_instances':[self.item]})

    def test_simple_text_uses_existing_ffmpeg_without_loading_remotion(self):
        del self.item['display']['motion'];self.save()
        with patch('video_localizer.compositor.text',return_value=self.run/'simple.mp4') as plain,patch.object(typography,'_remotion') as remotion:
            self.assertEqual(self.render(),self.run/'simple.mp4');plain.assert_called_once();remotion.assert_not_called()
        self.assertIsNone(typography.contract(self.run,{'text_instances':[self.item]}))

    def test_policy_font_and_locale_are_bound_and_runtime_failure_is_not_cached(self):
        inventory={'text_instances':[self.item]};contract=typography.contract(self.run,inventory)
        typography.verify_contract(self.run,{'typography_contract':contract},inventory)
        with self.assertRaises(WorkflowError):typography.verify_contract(self.run,{},inventory)
        self.assertIsNone(render_cache.signature(self.run,{'source_sha256':'a'*64},
                         {**self.segment,'route':'prepared_video'},inventory,self.meta))
        self.assertIn('typography.render',resources.HEAVY)

    def test_runtime_success_and_invalid_alpha_falls_back_once(self):
        def render_fixture(run,directory,props):typography._ffmpeg(directory,props)
        with patch.object(typography,'_remotion',side_effect=render_fixture) as remotion:
            self.render();self.assertEqual(remotion.call_count,1)
        self.assertEqual(read_json(self.run/'outputs/type/typography-result.json')['renderer'],'remotion')
        def invalid(run,directory,props):
            media.ffmpeg(['-f','lavfi','-i','color=c=white:s=320x180:r=30:d=0.8,format=rgba','-c:v','qtrle','-pix_fmt','argb',directory/'layer.mov'])
        with patch.object(typography,'_remotion',side_effect=invalid) as remotion:
            self.render();self.assertEqual(remotion.call_count,1)
        self.assertEqual(read_json(self.run/'outputs/type/typography-result.json')['renderer'],'ffmpeg_static')

    def test_rtl_fallback_keeps_one_logical_shaping_run(self):
        directory=self.run/'rtl';directory.mkdir()
        b={'box':[10,20,300,120],'text':'اتخذ خطوتك التالية','actualFamily':'Arial','fontSize':24,
           'align':'center','outline':1,'color':'#FFFFFF','outlineColor':'#111111','startFrame':1,'endFrame':11,
           'emphasize':'التالية','emphasisColor':'#FFFF00','bold':False,'italic':False}
        props={'width':320,'height':180,'fps':30,'durationInFrames':24,'blocks':[b]}
        with patch.object(media,'ffmpeg'):typography._ffmpeg(directory,props)
        ass=(directory/'fallback.ass').read_text(encoding='utf-8-sig')
        self.assertIn('اتخذ خطوتك التالية',ass)
        self.assertNotIn('FFFF00',ass)

    def test_cross_segment_animation_keeps_original_phase_and_resource_slot_is_respected(self):
        self.item['start']=0;self.item['end']=.8;self.save()
        segment={**self.segment,'start':.4,'end':.8}
        props,_=typography._prepare(self.run,segment,[self.item],self.meta,self.run/'prepare')
        self.assertEqual(props['blocks'][0]['animationStartFrame'],-12)
        self.assertEqual(props['blocks'][0]['animationEndFrame'],12)
        self.assertEqual(props['blocks'][0]['emphasisFrame'],-6)
        earlier,_=typography._prepare(self.run,{**self.segment,'end':.1},[self.item],self.meta,self.run/'earlier')
        self.assertEqual(earlier['blocks'][0]['emphasisFrame'],6)  # Do not highlight at the end of the earlier shot.
        with resources.heavy(self.run,'test'):
            self.assertTrue(list((self.root/'state/resources').glob('heavy-*.lock')))
        from video_localizer.processes import run_bounded
        with self.assertRaisesRegex(WorkflowError,'timed out'):
            run_bounded([sys.executable,'-c','import time;time.sleep(10)'],.05)

    def test_workflow_prepared_route_collects_receipts_and_keeps_neutral_gate(self):
        from video_localizer import workflow,prepared
        inventory={'text_instances':[self.item],'audio':{'strategy':'preserve'}}
        write_json(self.run/'analysis/inventory.json',inventory)
        write_json(self.run/'analysis/media.json',{**self.meta,'has_audio':False})
        plan={'id':'integration','source_sha256':file_hash(self.run/'inputs/source.mp4'),
              'inventory_sha256':file_hash(self.run/'analysis/inventory.json'),
              'segments':[{**self.segment,'route':'prepared_video','prepared_video':{'fixture':True}}]}
        with patch.object(workflow,'current_plan',return_value=plan),patch('video_localizer.batches.gate'), \
             patch.object(prepared,'verify_for_production',return_value=self.run/'inputs/source.mp4') as gate, \
             patch.object(typography,'_remotion',side_effect=WorkflowError('fixture unavailable')):
            workflow.render(self.run)
        self.assertGreaterEqual(gate.call_count,2)
        candidate=read_json(self.run/'outputs/candidate.json')
        self.assertEqual(len(candidate['typography_assets']),1)
        self.assertEqual(candidate['typography_fallbacks'][0]['segment'],'s001')
        typography.verify_assets(self.run,candidate['typography_assets'],inventory)
        with patch.object(prepared,'verify_for_production',side_effect=WorkflowError('neutral not approved')), \
             patch.object(typography,'render') as renderer:
            with self.assertRaises(WorkflowError):
                prepared.render(self.run,plan['segments'][0],[self.item],self.meta,self.run/'blocked',plan['source_sha256'])
            renderer.assert_not_called()


if __name__=='__main__':unittest.main()
