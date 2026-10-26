"""Existing narration mixer, promoted to a resumable project capability."""
import wave
import numpy as np
from . import captions, media, workflow
from .common import file_hash, guarded, inside, object_hash, read_json, require, require_number, write_json


def source_track(run):
    source=workflow.source_path(run)
    signature={'source_sha256':file_hash(source),'ffmpeg':media.command(['ffmpeg','-version']).stdout,
               'format':'stereo 44100 Hz pcm_s16le'}
    directory=run/'outputs/source-audio'/object_hash(signature)[:20]
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/'source-stereo.wav'; receipt=directory/'provenance.json'
    if receipt.exists():
        record=read_json(receipt)
        require(record['signature']==signature and path.is_file() and file_hash(path)==record['sha256'],'Source audio checkpoint changed')
    else:
        media.ffmpeg(['-i',source,'-vn','-ac','2','-ar','44100','-c:a','pcm_s16le',path])
        write_json(receipt,{'signature':signature,'sha256':file_hash(path)})
    return path


def pcm(path):
    with wave.open(str(path),'rb') as f:
        require(f.getsampwidth()==2,'Expected signed 16-bit WAV')
        rate,channels=f.getframerate(),f.getnchannels()
        values=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').reshape(-1,channels).astype(np.float32)/32768
    return values,rate


def save(path,values,rate):
    with wave.open(str(path),'wb') as f:
        f.setnchannels(values.shape[1]);f.setsampwidth(2);f.setframerate(rate)
        f.writeframes((np.clip(values,-1,1)*32767).astype('<i2').tobytes())


@guarded
def mix(run):
    plan=read_json(run/'inputs/narration-plan.json')
    require(plan['source_sha256']==file_hash(workflow.source_path(run)),'Narration plan source changed')
    inventory=read_json(run/'analysis/inventory.json')
    captions.validate_spoken_copy(inventory,plan['lines'])
    require({line['id'] for line in plan['lines']} == {line['id'] for line in inventory.get('speech_segments',[])},
            'Narration mix must cover every final speech segment')
    source_audio=source_track(run)
    source,rate=pcm(source_audio)
    stem=inside(run,plan['background']['path'])
    require(file_hash(stem)==plan['background']['sha256'],'Background stem changed')
    background,stem_rate=pcm(stem);require(rate==stem_rate,'Background sample rate changed')
    background=background[:len(source)];require(len(background)==len(source),'Background length changed')
    for line in plan['lines']:
        require(file_hash(inside(run,line['voice']['path']))==line['voice']['sha256'],'Voice take changed')
        require_number(line['start'],'Speech start',minimum=0)
        require_number(line['end'],'Speech end',minimum=line['start']+.001,maximum=len(source)/rate)
    windows=sorted((line['start'],line['end']) for line in plan['lines'])
    require(all(windows[i][1]<=windows[i+1][0] for i in range(len(windows)-1)),'Overlapping speech windows require explicit remixing')
    signature={'plan':plan,'source_audio_sha256':file_hash(source_audio),'implementation':file_hash(__file__),
               'ffmpeg':media.command(['ffmpeg','-version']).stdout}
    digest=object_hash(signature)
    directory=run/'outputs/audio-mix'/digest[:20];directory.mkdir(parents=True,exist_ok=True)
    provenance=directory/'provenance.json'
    if provenance.exists():
        saved=read_json(provenance)
        require(saved.get('signature')==signature,'Mix checkpoint inputs changed')
        require(all(file_hash(inside(run,a['path']))==a['sha256'] for a in [saved['output'],*[r['aligned'] for r in saved['lines']]]),'Mix checkpoint output changed')
        return {**saved['output'],'reused':True,'state':'needs_review'}
    result=source.copy();records=[];affected=np.zeros(len(source),dtype=bool)
    for i,line in enumerate(plan['lines'],1):
        voice=inside(run,line['voice']['path']);require(file_hash(voice)==line['voice']['sha256'],'Voice take changed')
        raw,vrate=pcm(voice);env=np.max(np.abs(raw),axis=1)
        active=np.flatnonzero(env>max(.002,float(np.max(env))*.012))
        require(len(active)>0,'Silent voice take')
        first=max(0,int(active[0])-round(.035*vrate));last=min(len(raw),int(active[-1])+round(.055*vrate))
        trimmed=directory/f'line-{i:02d}-trimmed.wav';save(trimmed,raw[first:last],vrate)
        voice_offset=require_number(line.get('voice_offset_seconds',0),'Narration voice offset',minimum=0,maximum=.35)
        duration=(last-first)/vrate;available=line['end']-line['start']-.08-voice_offset
        require(available>0,'Narration offset leaves no source window')
        speed=max(1,duration/available)
        require(speed<=1.65,'Voice exceeds source window; shorten or revise the voice take')
        ready=directory/f'line-{i:02d}-aligned.wav'
        media.ffmpeg(['-i',trimmed,'-af',f'atempo={speed},loudnorm=I=-16:LRA=7:TP=-2',
                      '-ar',rate,'-ac','2','-c:a','pcm_s16le',ready])
        data,_=pcm(ready)
        voice_gain_db=require_number(line.get('voice_gain_db',0),'Narration voice gain',minimum=-6,maximum=6)
        data*=10**(voice_gain_db/20)
        start=round(line['start']*rate);end=min(len(source),round(line['end']*rate))
        fade=min(round(.04*rate),(end-start)//2)
        blend=np.ones(end-start,dtype=np.float32)
        if start>0:blend[:fade]=np.linspace(0,1,fade)
        blend[-fade:]=np.linspace(1,0,fade)
        speech=np.zeros_like(source[start:end]);offset=round(voice_offset*rate)
        require(offset+len(data)<=len(speech),'Aligned voice would be truncated')
        speech[offset:offset+len(data)]=data
        mixed=source[start:end]*(1-blend[:,None])+background[start:end]*blend[:,None]+speech
        peak=float(np.max(np.abs(mixed)));gain=min(1,.985/max(.001,peak))
        result[start:end]=mixed*gain;affected[start:end]=True
        records.append({'id':line['id'],'start':line['start'],'end':line['end'],'target_text':line['target_text'],
                        'voice':line['voice'],'trim_seconds':[first/vrate,last/vrate],'atempo':speed,
                        'aligned':{'path':ready.relative_to(run).as_posix(),'sha256':file_hash(ready)},'voice_gain_db':voice_gain_db,'voice_offset_seconds':voice_offset,'window_peak_gain':gain})
    output=directory/'translated-mix.wav';save(output,result,rate)
    unchanged=np.max(np.abs(result[~affected]-source[~affected])) if np.any(~affected) else 0
    write_json(directory/'provenance.json',{'source_sha256':plan['source_sha256'],'source_audio_sha256':file_hash(source_audio),'signature':signature,
        'source_audio':{'path':source_audio.relative_to(run).as_posix(),'sha256':file_hash(source_audio)},
        'background':plan['background'],'lines':records,'original_mix_outside_windows_max_float_difference':float(unchanged),
        'outside_windows_seconds':float(np.count_nonzero(~affected)/rate),'music_time_scale':1,
        'method':'Original mix outside speech windows; local UVR background in speech windows plus native language TTS, 40ms boundary fades. Only isolated narration speed changed.',
        'output':{'path':output.relative_to(run).as_posix(),'sha256':file_hash(output)},
        'limitations':['UVR separation can attenuate musical vocal samples underneath narration.','No visual lip synchronization applied; source people are retained.']})
    return {'path':output.relative_to(run).as_posix(),'sha256':file_hash(output),'reused':False,'state':'needs_review'}
