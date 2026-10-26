from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_localizer import media, surface
from video_localizer.common import WorkflowError, file_hash, write_json


class SurfaceBindingTests(unittest.TestCase):
    def test_changed_copy_motion_or_locale_cannot_reuse_old_transparent_layer(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'work/test-tmp') as tmp:
            root = Path(tmp)
            (root/'layer.mov').write_bytes(b'fixture layer bytes')
            (root/'font.ttf').write_bytes(b'fixture font bytes')
            items = [{'id':'t001', 'target_text':'开始', 'start':0, 'end':1, 'bbox':[10,10,80,20],
                      'display':{'typography_layer':True}, 'trajectory':[]}]
            record = {'source_sha256':'source', 'target_language':'zh-CN', 'alpha_channel':True,
                      'texts':{'t001':'开始'}, 'instance_bindings':surface.instance_bindings(items),
                      'inputs':[{'path':'font.ttf','sha256':file_hash(root/'font.ttf')}],
                      'output':{'path':'layer.mov','sha256':file_hash(root/'layer.mov')}}
            write_json(root/'record.json',record)
            asset={**record['output'], 'record':'record.json', 'record_sha256':file_hash(root/'record.json')}
            self.assertEqual(surface.verify(root,asset,'source','zh-CN',items),root/'layer.mov')
            with self.assertRaises(WorkflowError):surface.verify(root,asset,'source','ko-KR',items)
            changed=json.loads(json.dumps(items));changed[0]['target_text']='スタート'
            with self.assertRaises(WorkflowError):surface.verify(root,asset,'source','zh-CN',changed)
            protected=json.loads(json.dumps(items))
            protected[0]['trajectory']=[{'time':0,'bbox':[10,10,80,20],'protected_regions':[[70,10,20,20]]}]
            # Even a freshly rebound layer cannot authorize glyphs over a protected icon.
            record['instance_bindings']=surface.instance_bindings(protected)
            write_json(root/'protected-record.json',record)
            protected_asset={**asset,'record':'protected-record.json','record_sha256':file_hash(root/'protected-record.json')}
            with self.assertRaises(WorkflowError):surface.verify(root,protected_asset,'source','zh-CN',protected)
            changed=json.loads(json.dumps(items));changed[0]['bbox'][0]=30
            with self.assertRaises(WorkflowError):surface.verify(root,asset,'source','zh-CN',changed)
            (root/'font.ttf').write_bytes(b'changed font bytes')
            with self.assertRaises(WorkflowError):surface.verify(root,asset,'source','zh-CN',items)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_transparent_layer_preserves_source_pixels_outside_glyph_region(self):
        from PIL import Image, ImageDraw
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'work/test-tmp') as tmp:
            root=Path(tmp);source=root/'source.mp4';layer=root/'layer.mov'
            media.ffmpeg(['-f','lavfi','-i','color=green:s=160x96:r=30:d=0.4','-c:v','libx264','-pix_fmt','yuv420p',source])
            im=Image.new('RGBA',(160,96),(0,0,0,0));ImageDraw.Draw(im).rectangle((20,20,60,50),fill=(230,20,20,255))
            im.save(root/'alpha.png')
            media.ffmpeg(['-loop','1','-i',root/'alpha.png','-t','0.4','-r','30','-c:v','qtrle','-pix_fmt','argb',layer])
            output=surface.composite(source,layer,.4,root/'render')
            def pixels(path):
                return subprocess.run(['ffmpeg','-v','error','-i',str(path),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],capture_output=True,check=True).stdout
            before,after=pixels(source),pixels(output)
            for x,y in [(5,5),(90,30),(140,80)]:
                n=(y*160+x)*3
                self.assertLess(max(abs(before[n+c]-after[n+c]) for c in range(3)),8)
            n=(30*160+30)*3
            self.assertGreater(after[n],180)
            self.assertLess(after[n+1],60)


if __name__=='__main__':unittest.main()
