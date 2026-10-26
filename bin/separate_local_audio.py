"""Run a cached UVR separation model locally; writes source-bound stem evidence."""
import argparse
from pathlib import Path
import sys
import time
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.runtime/deps/separation'))
sys.path.insert(0,str(ROOT/'src'))
import numpy as np
from video_localizer.common import file_hash,get_run,require,run_operation,write_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('--output',default='outputs/local-separation')
    args=parser.parse_args()
    import sherpa_onnx
    run=get_run(args.run)
    from video_localizer.timing import measure
    from video_localizer.resources import heavy
    with run_operation(run), heavy(run, 'audio.separation'), measure(run, 'audio.separation'):
        return execute(args, run, sherpa_onnx)


def execute(args, run, sherpa_onnx):
    from video_localizer.local_audio import source_track
    from video_localizer.common import read_json, object_hash
    from video_localizer.workflow import source_path
    from video_localizer.model_routing import require_current
    require_current('separation', 'uvr-inst-hq3')
    source=source_track(run)
    model=ROOT/'.runtime/models/separation/UVR-MDX-NET-Inst_HQ_3.onnx'
    require(model.is_file(),'Download the documented Sherpa UVR model first')
    from video_localizer.common import inside
    out=inside(run,args.output)
    signature={'source_sha256':file_hash(source_path(run)),'source_audio_sha256':file_hash(source),
               'model_sha256':file_hash(model),'engine':sherpa_onnx.__version__,'implementation':file_hash(__file__)}
    out=out/object_hash(signature)[:20]
    out.mkdir(parents=True,exist_ok=True)
    if (out/'provenance.json').exists():
        saved=read_json(out/'provenance.json')
        require(saved.get('signature')==signature and all(file_hash(inside(run,s['path']))==s['sha256'] for s in saved['stems']),
                'Separation checkpoint changed; preserve and inspect it')
        print({'stems':saved['stems'],'reused':True,'new_kie_credits':0},flush=True)
        return
    with wave.open(str(source),'rb') as f:
        rate=f.getframerate();channels=f.getnchannels()
        require(f.getsampwidth()==2 and channels==2,'Use 16-bit stereo source PCM')
        samples=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').reshape(-1,channels).T.astype(np.float32)/32768
    config=sherpa_onnx.OfflineSourceSeparationConfig(model=sherpa_onnx.OfflineSourceSeparationModelConfig(
        uvr=sherpa_onnx.OfflineSourceSeparationUvrModelConfig(model=str(model)),num_threads=4,debug=False,provider='cpu'))
    require(config.validate(),'UVR model configuration invalid')
    separator=sherpa_onnx.OfflineSourceSeparation(config)
    start=time.monotonic()
    result=separator.process(sample_rate=rate,samples=np.ascontiguousarray(samples))
    records=[]
    for i,stem in enumerate(result.stems):
        # This Inst_HQ_3 model predicts instrumental as its primary output.
        # The generic UVR example uses a vocal model and has opposite ordering.
        name='accompaniment' if i==0 else 'vocals'
        data=np.asarray(stem.data,dtype=np.float32).T
        path=out/(name+'.wav')
        peak=float(np.max(np.abs(data)))
        pcm=(np.clip(data,-1,1)*32767).astype('<i2')
        with wave.open(str(path),'wb') as f:
            f.setnchannels(data.shape[1]);f.setsampwidth(2);f.setframerate(result.sample_rate);f.writeframes(pcm.tobytes())
        records.append({'stem':name,'path':path.relative_to(run).as_posix(),'sha256':file_hash(path),'sample_rate':result.sample_rate,'samples':len(data),'float_peak':peak})
    write_json(out/'provenance.json',{'source_sha256':file_hash(source_path(run)),'source_audio_sha256':file_hash(source),'signature':signature,
        'engine':'sherpa-onnx '+sherpa_onnx.__version__,'model_path':model.relative_to(ROOT).as_posix(),'model_sha256':file_hash(model),
        'model_source':'https://github.com/k2-fsa/sherpa-onnx/releases/tag/source-separation-models',
        'elapsed_seconds':round(time.monotonic()-start,3),'stems':records,'kie_credits':0,'primary_stem':'accompaniment',
        'proof_boundary':'Actual local AI inference, not Codex imagining audio. Separation is approximate; check retained music and narration residue.'})
    print({'stems':records,'seconds':round(time.monotonic()-start,3),'new_kie_credits':0},flush=True)


if __name__=='__main__':main()
