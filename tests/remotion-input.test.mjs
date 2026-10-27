import {test} from 'node:test';
import assert from 'node:assert/strict';
import {validateProps} from '../src/remotion_renderer/validate.mjs';
const sample = () => ({width:720,height:1280,fps:30,durationInFrames:150,fonts:[{family:'Arabic',file:'Arabic.ttf'}],blocks:[{
  id:'a',text:'اتخذ خطوتك التالية',family:'Arabic',fontSize:52,color:'#ffffff',direction:'rtl',
  box:[40,1000,640,140],startFrame:15,endFrame:135,track:[{frame:0,x:40,y:1000,rotation:0},{frame:149,x:40,y:1010,rotation:2}]}]});
test('supports RTL, exclusive frame intervals and explicit supplied tracks',()=>assert.doesNotThrow(()=>validateProps(sample())));
test('rejects invalid timing, stale emphasis, duplicate instances and unsorted tracks',()=>{
  for (const change of [p=>p.blocks[0].endFrame=151,p=>p.blocks[0].startFrame=135,p=>p.blocks[0].emphasize='missing',
    p=>p.blocks.push(p.blocks[0]),p=>p.blocks[0].track.reverse()]) {const p=sample();change(p);assert.throws(()=>validateProps(p));}
});
test('rejects remote/escaping fonts and missing font families',()=>{
  for (const file of ['https://example.com/a.ttf','../Arial.ttf','/tmp/a.ttf']) {const p=sample();p.fonts[0].file=file;assert.throws(()=>validateProps(p));}
  const p=sample();p.blocks[0].family='unknown';assert.throws(()=>validateProps(p));
});
test('checks visible box, animation phase and emphasis frame bounds',()=>{
  for(const change of [p=>p.blocks[0].box=[700,0,80,40],p=>p.blocks[0].animated='yes',
    p=>p.blocks[0].outline=-1,p=>p.blocks[0].emphasisFrame=135.5,
    p=>p.blocks[0].animationStartFrame=16,p=>p.blocks[0].animationEndFrame=134]) {
      const p=sample();change(p);assert.throws(()=>validateProps(p));
  }
  const p=sample();p.blocks[0].animationStartFrame=-30;p.blocks[0].animationEndFrame=300;
  p.blocks[0].emphasisFrame=240;
  assert.doesNotThrow(()=>validateProps(p));
});
