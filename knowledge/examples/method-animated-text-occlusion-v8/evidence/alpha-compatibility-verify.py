"""Actual asset/consumer validation; derived copies only, no production writes."""
import sys
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'.runtime/deps/vision'))
import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from video_localizer.alpha_assets import sanitize
from video_localizer.common import read_json,write_json,file_hash

WORK=Path(__file__).resolve().parent
FFMPEG=ROOT/'.runtime/ffmpeg/bin/ffmpeg'
ASSETS=[
 ('emoji',ROOT/'runs/SHE-20261026-053-01/inputs/foreground/emoji-020.png','SHE-20261026-053-01',20),
 ('empty_emoji',ROOT/'runs/SHE-20261026-053-01/inputs/foreground/emoji-000.png','SHE-20261026-053-01',0),
 ('en',WORK/'remotion-en-frame40.png','remotion-evaluation-20261026',40),
 ('ar',WORK/'remotion-ar-frame60.png','remotion-evaluation-20261026',60)]

def ffmpeg(args):
    subprocess.run([str(FFMPEG),'-hide_banner','-loglevel','error','-y',*map(str,args)],check=True)

def diff(a,b):
    a=np.asarray(a);b=np.asarray(b)
    d=np.abs(a.astype(np.float64)-b.astype(np.float64))
    return {'changed_pixels':int(np.count_nonzero(np.any(d!=0,axis=-1))), 'maximum_channel_difference':float(d.max())}

def background(size,kind):
    w,h=size
    if kind=='checker':
        yy,xx=np.indices((h,w));t=((xx//19+yy//19)%2)*130+60
        z=np.stack([t,t,t],axis=-1).astype(np.uint8)
        return Image.fromarray(z).convert('RGBA')
    return Image.new('RGBA',size,{'black':(0,0,0,255),'white':(255,255,255,255),'blue':(30,65,160,255)}[kind])

def composed(im,kind='checker'):
    return Image.alpha_composite(background(im.size,kind),im).convert('RGB')

def transform(im,operation,*,premultiplied):
    z=np.array(im).astype(np.float32)/255
    if premultiplied:z[:,:,:3]*=z[:,:,3:4]
    h,w=z.shape[:2]
    if operation=='resize':z=cv2.resize(z,(int(w*.73),int(h*.73)),interpolation=cv2.INTER_LINEAR)
    else:z=cv2.warpAffine(z,cv2.getRotationMatrix2D((w/2,h/2),13.7,1),(w,h),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
    if premultiplied:
        a=z[:,:,3:4];z[:,:,:3]=np.divide(z[:,:,:3],a,out=np.zeros_like(z[:,:,:3]),where=a>0)
    return Image.fromarray(np.round(np.clip(z,0,1)*255).astype(np.uint8))

records=[]
for name,path,run_id,frame in ASSETS:
    directory=WORK/name;directory.mkdir(exist_ok=True)
    run=ROOT/'runs'/run_id;run_record=read_json(run/'run.json')
    source=run/run_record['source'];assert file_hash(source)==run_record['source_sha256']
    origin={'source_sha256':run_record['source_sha256'],'origin_asset':path.relative_to(ROOT).as_posix(),'original_asset_sha256':file_hash(path),'frame':frame}
    # Verify foreground/typography frame actually comes from its stored layer.
    if name in ('emoji','empty_emoji'):
        layer=run/'inputs/emoji-foreground.mkv'
    else:
        layer=ROOT/f'outputs/reports/remotion-evaluation-20261026/layers/{name}-argb.mov'
        p=read_json(layer.parent/f'{name}-provenance.json')
        assert p['output']['sha256']==file_hash(layer) and p['source_sha256']==run_record['source_sha256']
        origin['layer_provenance_sha256']=file_hash(layer.parent/f'{name}-provenance.json')
    origin['original_layer_sha256']=file_hash(layer)
    decoded=directory/'decoded.png'
    ffmpeg(['-i',layer,'-vf',f'select=eq(n\\,{frame})','-frames:v',1,'-pix_fmt','rgba',decoded])
    original=Image.open(path).convert('RGBA');assert np.array_equal(np.array(original),np.array(Image.open(decoded).convert('RGBA')))
    shutil.copyfile(path,directory/'original.png')
    clean,meta=sanitize(original);clean.save(directory/'clean.png')
    tight,tight_meta=sanitize(original,crop=True,padding=2);tight.save(directory/'tight.png');write_json(directory/'placement.json',tight_meta)
    a=np.array(original);b=np.array(clean);alpha=a[:,:,3];visible=alpha>0;soft=(alpha>0)&(alpha<255)
    assert np.array_equal(a[:,:,3],b[:,:,3]) and np.array_equal(a[visible],b[visible])
    assert not np.any(b[alpha==0,:3])
    native={}
    for bg in ['black','white','blue','checker']:
        native[bg]=diff(composed(original,bg),composed(clean,bg));assert native[bg]['changed_pixels']==0
    original.convert('RGB').save(directory/'ignored-before.png');clean.convert('RGB').save(directory/'ignored-after.png')
    original_cv=cv2.imread(str(directory/'original.png'),cv2.IMREAD_COLOR)
    clean_cv=cv2.imread(str(directory/'clean.png'),cv2.IMREAD_COLOR)
    ignored=diff(original_cv,clean_cv)
    assert ignored['changed_pixels']==meta['cleared_hidden_rgb_pixels']
    assert np.array_equal(original_cv[:,:,::-1],np.array(original.convert('RGB')))
    # Alpha is essential: the cleaned RGB-only result is not a transparent composite.
    rgb_only_vs_composite=diff(clean.convert('RGB'),composed(clean))
    restored=Image.new('RGBA',original.size);restored.paste(tight,tuple(tight_meta['origin']))
    assert np.array_equal(np.array(restored),b)
    crop_checks={'with_origin':diff(composed(restored),composed(clean))}
    wrong=Image.new('RGBA',original.size);wrong.paste(tight,(0,0));crop_checks['without_origin']=diff(composed(wrong),composed(clean))
    transforms={}
    for operation in ['resize','rotate']:
        raw=transform(original,operation,premultiplied=False);san=transform(clean,operation,premultiplied=False)
        before=composed(raw);after=composed(san)
        transforms[operation+'_straight_channels']=diff(before,after)
        if name in ('emoji','en') and operation=='resize':
            before.save(directory/'naive-resize-before.png');after.save(directory/'naive-resize-after.png')
        raw=transform(original,operation,premultiplied=True);san=transform(clean,operation,premultiplied=True)
        transforms[operation+'_premultiplied']=diff(composed(raw),composed(san));assert transforms[operation+'_premultiplied']['changed_pixels']==0
    for operation in ['resize','rotate']:
        if operation=='resize':
            size=(int(original.width*.73),int(original.height*.73))
            first=original.resize(size,Image.Resampling.LANCZOS);second=clean.resize(size,Image.Resampling.LANCZOS)
        else:first=original.rotate(13.7,Image.Resampling.BICUBIC);second=clean.rotate(13.7,Image.Resampling.BICUBIC)
        transforms['pillow_'+operation]=diff(composed(first),composed(second));assert transforms['pillow_'+operation]['changed_pixels']==0
    # A threshold of even 8 is a destructive operation on real soft edges.
    destructive=a.copy();destructive[destructive[:,:,3]<=8]=0
    threshold=diff(composed(original,'white'),composed(Image.fromarray(destructive),'white'))
    codecs={}
    for codec,pixel,suffix in [('qtrle','argb','mov'),('ffv1','bgra','mkv')]:
        clip=directory/f'clean-{codec}.{suffix}';back=directory/f'roundtrip-{codec}.png'
        ffmpeg(['-i',directory/'clean.png','-frames:v',1,'-an','-c:v',codec,'-pix_fmt',pixel,clip])
        ffmpeg(['-i',clip,'-frames:v',1,'-pix_fmt','rgba',back])
        codecs[codec]=diff(clean,Image.open(back).convert('RGBA'));assert codecs[codec]['changed_pixels']==0
    # Real FFmpeg RGB overlay, lossless frame output: hidden RGB cannot alter this path.
    background(original.size,'blue').save(directory/'background.png')
    ff_checks=[]
    for asset in ['original','clean']:
        out=directory/f'ffmpeg-{asset}-composite.png'
        ffmpeg(['-i',directory/'background.png','-i',directory/f'{asset}.png','-filter_complex','[0:v]format=rgba[bg];[1:v]format=rgba[fg];[bg][fg]overlay=0:0:format=rgb:alpha=straight[out]','-map','[out]','-frames:v',1,'-pix_fmt','rgb24',out])
        ff_checks.append(Image.open(out).convert('RGB'))
    ff_result=diff(*ff_checks);assert ff_result['changed_pixels']==0
    composed(original).save(directory/'proper-composite.png')
    records.append({'name':name,'origin':origin,'size':list(original.size),'soft_edge_pixels':int(np.count_nonzero(soft)),
        'hidden_rgb_pixels':meta['cleared_hidden_rgb_pixels'],'alpha_changed_pixels':int(np.count_nonzero(a[:,:,3]!=b[:,:,3])),
        'visible_rgba_changed_pixels':diff(a[visible].reshape(-1,1,4),b[visible].reshape(-1,1,4)) if np.any(visible) else {'changed_pixels':0},
        'native_composites':native,'opencv_and_pillow_ignored_alpha':ignored,'rgb_drop_is_not_a_composite':rgb_only_vs_composite,
        'crop':{**tight_meta,'checks':crop_checks},'transforms':transforms,'destructive_threshold8':threshold,'lossless_codec_roundtrips':codecs,'ffmpeg_native_rgb_overlay':ff_result,
        'input_asset_sha256':file_hash(directory/'original.png'),'clean_asset_sha256':file_hash(directory/'clean.png'),'tight_asset_sha256':file_hash(directory/'tight.png')})

assert len({r['origin']['source_sha256'] for r in records})==2
assert all(r['origin']['source_sha256']!='f90102a24069fcfc91ca97d3f6b5106486f8343bc7756e6f360987a752e3d2fe' for r in records)
assert any(r['soft_edge_pixels']>0 and r['destructive_threshold8']['changed_pixels']>0 for r in records)
assert any(r['transforms']['resize_straight_channels']['changed_pixels']>0 for r in records)
result={'decision':'pass','independent_new_sources':2,'actual_assets':4,'reviewed_by':'Codex same-agent technical/visual review',
    'versions':{'pillow':Image.__version__,'opencv':cv2.__version__,'numpy':np.__version__},'records':records,
    'conclusion':'Conditionally supported. Clear RGB only where alpha==0 on derived straight-alpha copies. Native alpha/visible pixels and correctly premultiplied transforms stay identical. Real alpha-ignoring readers expose hidden source pixels; cleanup does not make those readers alpha-aware. Straight-channel filtering and nonzero-alpha thresholding are counterexamples to unconditional cleanup. Crop retains all nonzero alpha and requires the original origin.',
    'boundary':'Two new actual source families; English/Arabic are one source. No claim of compatibility with all consumers/color formats, artistic foreground-matte correctness, generic tracking or whole-ad quality. No original production assets changed.'}
write_json(WORK/'verification.json',result)
print({'decision':'pass','assets':len(records),'soft_pixels':{r['name']:r['soft_edge_pixels'] for r in records},'hidden_rgb_pixels':{r['name']:r['hidden_rgb_pixels'] for r in records},'naive_resize_changed':{r['name']:r['transforms']['resize_straight_channels']['changed_pixels'] for r in records}})
