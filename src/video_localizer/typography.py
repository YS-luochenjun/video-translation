"""Content-selected typography with measured fonts, bound alpha and visible fallback.

Only explicitly specified title/CTA/emphasis motion enters Remotion. Background
repair, manual surface layers, speech alignment and acceptance stay upstream.
"""
import copy
import importlib
import math
from pathlib import Path
import shutil
import subprocess
import sys
import unicodedata

from .common import (CODE_ROOT, WorkflowError, file_hash, guarded, inside, object_hash,
                     read_json, require, require_number, utc_now, write_json)
from . import media


def selected(item):
    return 'motion' in item.get('display', {})


def code_identity():
    files = ['config/typography.json', 'src/video_localizer/typography.py',
             'src/remotion_renderer/index.tsx', 'src/remotion_renderer/validate.mjs',
             'src/remotion_renderer/render.mjs', 'src/remotion_renderer/package.json', 'src/remotion_renderer/pnpm-lock.yaml']
    return {p: file_hash(CODE_ROOT / p) for p in files}


def settings(root):
    path = Path(root) / 'config/remotion.local.json'
    local = read_json(path) if path.exists() else {}
    require(set(local) <= {'node', 'browserExecutable', 'chromeMode'}, 'Unknown local Remotion setting')
    return {**local, 'runtime': str(CODE_ROOT / '.runtime/deps/remotion')}


def environment_identity(root):
    config = settings(root)
    def identity(value):
        path = Path(value) if value else None
        return {'path': value, 'sha256': file_hash(path) if path and path.is_file() else None}
    node = config.get('node') or shutil.which('node')
    return {'code': code_identity(), 'node': identity(node),
            'browser': identity(config.get('browserExecutable')),
            'runtime_package': identity(str(Path(config['runtime']) / 'node_modules/remotion/package.json')),
            'chromeMode': config.get('chromeMode', 'headless-shell')}


def _font_modules():
    try:
        return importlib.import_module('fontTools.ttLib')
    except ImportError:
        local = CODE_ROOT / '.runtime/deps/remotion-font-tools'
        if local.is_dir() and str(local) not in sys.path:
            sys.path.insert(0, str(local))
        try:
            return importlib.import_module('fontTools.ttLib')
        except ImportError as exc:
            raise WorkflowError('Typography preflight requires fonttools; install optional typography dependencies') from exc


def contract(run, inventory):
    items = [i for i in inventory.get('text_instances', []) if selected(i)]
    if not items:
        return None
    fonts = []
    policy = read_json(CODE_ROOT / 'config/typography.json')
    for item in items:
        display = item.get('display', {})
        motion = display['motion']
        require(isinstance(motion, dict) and motion.get('kind') in policy['remotion_kinds'], 'Motion kind must be title, cta or emphasis')
        require(set(motion) <= {'kind', 'effect', 'emphasize', 'emphasis_at'}, 'Unknown motion option')
        require(motion.get('effect', 'fade_scale') in ('fade_scale', 'none'), 'Unsupported motion effect')
        require(item.get('text_role') != 'speech_caption', 'Speech captions keep their existing aligned renderer')
        require(item.get('action') not in ('preserve', 'solid_overlay') and not display.get('typography_layer'), 'Motion needs clean-master text, separate from fixed UI/manual surface assets')
        require(not item.get('trajectory') and not item.get('protected_regions') and not display.get('pill')
                and not display.get('timed_fragments') and not display.get('outline_layers')
                and not display.get('angle') and not display.get('reveal_seconds'),
                'Initial Remotion route supports rigid screen-space text only; use specialist route for tracks, masks or layered art')
        require(display.get('direction', 'ltr') in ('ltr', 'rtl'), 'Invalid text direction')
        require(display.get('align', 'center') in ('left', 'center', 'right'), 'Invalid alignment')
        for key in ('color', 'outline_color', 'emphasis_color'):
            value = display.get(key, '#FFFFFF')
            require(isinstance(value, str) and len(value) == 7 and value[0] == '#' and all(c in '0123456789abcdefABCDEF' for c in value[1:]), 'Invalid typography RGB color')
        emphasis = motion.get('emphasize')
        require(motion['kind'] != 'emphasis' or bool(emphasis), 'Keyword emphasis needs exact target copy')
        if emphasis is not None:
            require(isinstance(emphasis, str) and emphasis and item['target_text'].count(emphasis) == 1, 'Emphasis must uniquely match final target copy')
        if 'emphasis_at' in motion:
            require_number(motion['emphasis_at'], 'emphasis_at', minimum=item['start'], maximum=item['end'])
            require(motion['emphasis_at'] < item['end'], 'Emphasis must start before the instance ends')
        asset = display.get('font_asset', {})
        require(set(asset) == {'path', 'sha256'}, 'Motion text needs a hash-bound run-local font_asset')
        font = inside(run, asset['path'])
        require(font.is_file() and file_hash(font) == asset['sha256'], 'Typography font missing or changed')
        require(font.suffix.lower() in ('.ttf', '.otf'), 'Supply an explicit single-face TTF/OTF font; extract TTC before planning')
        fonts.append(asset)
    return {'version': 1, 'policy_sha256': file_hash(CODE_ROOT / 'config/typography.json'),
            'fonts': sorted({f['path']: f for f in fonts}.values(), key=lambda f: f['path'])}


def verify_contract(run, plan, inventory):
    expected = contract(run, inventory)
    require(plan.get('typography_contract') == expected, 'Typography inputs or policy changed; rebuild/register the plan')


def _prepare(run, segment, items, meta, directory):
    """Hard content checks happen outside the runtime-failure fallback boundary."""
    from PIL import ImageFont, features
    fonts = _font_modules()
    policy = read_json(CODE_ROOT / 'config/typography.json')
    contract(run, {'text_instances': items})
    fps = policy['fps']
    duration = segment['end'] - segment['start']
    frames = math.ceil(duration * fps - 1e-7)
    require(frames > 0, 'Empty typography segment')
    props = {'width': meta['width'], 'height': meta['height'], 'fps': fps,
             'durationInFrames': frames, 'fonts': [], 'blocks': []}
    family_map = {}
    family_hashes = {}
    inputs = []
    for item in items:
        display, motion = item['display'], item['display']['motion']
        asset = display['font_asset']; font_path = inside(run, asset['path'])
        inputs.append(asset)
        key = asset['sha256']
        with fonts.TTFont(font_path) as face:
            cmap = face.getBestCmap() or {}
            missing = {c for c in item['target_text'] if not c.isspace() and ord(c) not in cmap}
            require(not missing, f"Missing glyphs in {item['id']}: " + ','.join(f'U+{ord(c):04X}' for c in sorted(missing)))
            actual_family = face['name'].getDebugName(1)
            actual_postscript = face['name'].getDebugName(6)
            require(actual_family and not any(c in actual_family for c in ',\n\r{}\\'), 'Invalid font family metadata')
            style = face['head'].macStyle
            bold, italic = bool(style & 1) or face['OS/2'].usWeightClass >= 600, bool(style & 2)
            require(not display.get('bold') or bold, 'Supply an actual bold font asset for bold typography')
            require(not display.get('italic') or italic, 'Supply an actual italic font asset for italic typography')
            require(actual_family not in family_hashes or family_hashes[actual_family] == key,
                    'Use one exact face per font family in the initial typography route')
            family_hashes[actual_family] = key
        if key not in family_map:
            filename = key[:16] + font_path.suffix.lower()
            dest = directory / 'fonts' / filename; dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(font_path, dest)
            family_map[key] = 'BoundFont' + str(len(family_map))
            props['fonts'].append({'family': family_map[key], 'file': filename})
        box = item['bbox']
        require(len(box) == 4, 'Text box needs four values')
        x,y,w,h = [require_number(v, 'text box') for v in box]
        require(w > 0 and h > 0 and x+w <= meta['width'] and y+h <= meta['height'], 'Typography box exceeds frame')
        outline = require_number(display.get('outline', 2), 'outline', maximum=12)
        minimum = require_number(display.get('min_font_size', policy['minimum_font_size']), 'minimum font size', minimum=policy['minimum_font_size'])
        requested = require_number(display.get('font_size', 48), 'font size', minimum=minimum, maximum=meta['height'])
        direction = display.get('direction', 'ltr')
        complex_script = direction == 'rtl' or any(0x590 <= ord(c) <= 0xDFF or 0xE00 <= ord(c) <= 0xEFF for c in item['target_text'])
        # Browser/libass perform final shaping. Basic Pillow metrics are only a
        # conservative proposal when RAQM is absent; actual alpha must fit too.
        shaped_metrics = complex_script and features.check('raqm')
        chosen = None
        for size in range(int(requested), math.ceil(minimum)-1, -1):
            font = ImageFont.truetype(str(font_path), size)
            lines = item['target_text'].split('\n')
            widths = [font.getlength(line, direction=direction) if shaped_metrics else font.getlength(line) for line in lines]
            ascent, descent = font.getmetrics()
            if max(widths) + 2*outline + 4 <= w and (ascent+descent) * len(lines) * 1.2 + 2*outline + 4 <= h:
                chosen = size; break
        require(chosen is not None, f"Text {item['id']} does not fit at readable size; revise box or line breaks")
        first = max(0, math.ceil((max(item['start'],segment['start'])-segment['start'])*fps-1e-7))
        last = min(frames, math.ceil((min(item['end'],segment['end'])-segment['start'])*fps-1e-7))
        require(last > first, 'Typography interval has no output frames')
        block = {'id':item['id'], 'text':item['target_text'], 'family':family_map[key], 'fontSize':chosen,
                 'box':box, 'startFrame':first, 'endFrame':last, 'direction':direction,
                 'animationStartFrame':math.ceil((item['start']-segment['start'])*fps-1e-7),
                 'animationEndFrame':math.ceil((item['end']-segment['start'])*fps-1e-7),
                 'animated':motion.get('effect','fade_scale') == 'fade_scale', 'color':display.get('color','#FFFFFF'),
                 'outline':outline, 'outlineColor':display.get('outline_color','#111111'),
                 'align':display.get('align','center'), 'actualFamily':actual_family,
                 'actualPostScript':actual_postscript, 'bold':bold, 'italic':italic}
        if motion.get('emphasize'):
            at=motion.get('emphasis_at',min(item['start']+.4,max(item['start'],item['end']-1/fps)))
            block.update(emphasize=motion['emphasize'], emphasisColor=display.get('emphasis_color','#FFE56A'),
                         emphasisFrame=math.ceil((at-segment['start'])*fps-1e-7))
        props['blocks'].append(block)
    write_json(directory/'props.json',props)
    return props, inputs


def _remotion(run, directory, props):
    config = settings(run.parent.parent)
    node = config.get('node') or shutil.which('node')
    require(node and Path(node).is_file(), 'Remotion Node runtime unavailable')
    require(config.get('browserExecutable') and Path(config['browserExecutable']).is_file(), 'Remotion browser unavailable')
    require((Path(config['runtime'])/'node_modules/remotion/package.json').is_file(), 'Remotion dependencies unavailable')
    for name,version in read_json(CODE_ROOT/'src/remotion_renderer/package.json')['dependencies'].items():
        path=Path(config['runtime'])/'node_modules'/name/'package.json'
        require(path.is_file() and read_json(path).get('version')==version,'Remotion dependency version mismatch: '+name)
    scratch = run.parent.parent/'work/runs'/run.name/('remotion-'+object_hash(str(directory))[:12])
    job = {**config, 'bundleDirectory':str(scratch/'bundle'), 'publicDirectory':str(directory/'fonts'),
           'result':str(directory/'renderer-metrics.json'), 'isProduction':True,
           'renders':[{'props':str(directory/'props.json'), 'output':str(directory/'native.mov')}]}
    write_json(directory/'job.json',job)
    # Bound entire process tree: render.mjs exits on error, browser.close runs in finally.
    from .processes import run_bounded
    result = run_bounded([node,str(CODE_ROOT/'src/remotion_renderer/render.mjs'),str(directory/'job.json')],
                         read_json(CODE_ROOT/'config/typography.json')['timeout_seconds'])
    (directory/'renderer.log').write_text(result,encoding='utf-8')
    media.ffmpeg(['-i',directory/'native.mov','-an','-c:v','qtrle','-pix_fmt','argb',directory/'layer.mov'])


def _ffmpeg(directory, props):
    from .compositor import header, event, color
    events=[]
    for b in props['blocks']:
        x,y,w,h=b['box'];align={'left':4,'center':5,'right':6}[b['align']]
        xpos=x+3 if align==4 else x+w-3 if align==6 else x+w/2
        text=media.ass_text(b['text'])
        # ASS inline overrides split bidi shaping runs in some libass versions.
        # Keep RTL paragraphs intact; log lost word coloring rather than reorder copy.
        if b.get('emphasize') and not any(unicodedata.bidirectional(c) in ('R','AL') for c in b['text']):
            before,after=b['text'].split(b['emphasize'])
            text=media.ass_text(before)+r'{\c&H'+color(b['emphasisColor'])+'&}'+media.ass_text(b['emphasize'])+r'{\c&H'+color(b['color'])+'&}'+media.ass_text(after)
        prefix=(f"{{\\an{align}\\pos({xpos},{y+h/2})\\fn{b['actualFamily']}\\fs{b['fontSize']}\\b{int(b['bold'])}\\i{int(b['italic'])}\\bord{b['outline']}\\shad0"
                f"\\c&H{color(b['color'])}&\\3c&H{color(b['outlineColor'])}&}}")
        # ASS stores centiseconds. Floor boundaries so 30fps exclusive end
        # never rounds forward and leaks one frame beyond the bound interval.
        first=math.floor(b['startFrame']/props['fps']*100+1e-7)/100
        last=math.floor(b['endFrame']/props['fps']*100+1e-7)/100
        events.append(event(first,last,prefix+text))
    (directory/'fallback.ass').write_text('\n'.join(header(props)+events+['']),encoding='utf-8-sig')
    media.ffmpeg(['-f','lavfi','-i',f"color=c=black@0:s={props['width']}x{props['height']}:r={props['fps']}:d={props['durationInFrames']/props['fps']},format=rgba",
                  '-vf','ass=fallback.ass:fontsdir=fonts:alpha=1','-an','-c:v','qtrle','-pix_fmt','argb','layer.mov'],cwd=directory)


def _check_layer(directory, props):
    """Decode every actual alpha frame; reject missing, clipped or extra lettering."""
    import numpy as np
    layer = directory/'layer.mov'; meta = media.probe(layer)
    require((meta['width'],meta['height']) == (props['width'],props['height']) and abs(meta['fps']-props['fps'])<.001, 'Typography frame geometry/rate mismatch')
    streams = meta['raw']['streams']
    require(not meta['has_audio'] and streams[0].get('pix_fmt') == 'argb', 'Typography needs silent argb alpha')
    n,w,h=props['durationInFrames'],props['width'],props['height']
    # Alpha is one byte per pixel; bounded run operation owns workspace compute.
    process=subprocess.Popen(['ffmpeg','-v','error','-i',str(layer),'-vf','alphaextract','-pix_fmt','gray','-f','rawvideo','-'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    counts=[]
    try:
        for frame in range(n):
            raw=process.stdout.read(w*h)
            require(len(raw)==w*h,'Typography frame count/decode failed')
            alpha=np.frombuffer(raw,dtype=np.uint8).reshape(h,w)
            allowed=np.zeros((h,w),dtype=bool)
            active=[]
            for block in props['blocks']:
                if block['startFrame']<=frame<block['endFrame']:
                    x,y,bw,bh=block['box'];x,y,right,bottom=math.floor(x),math.floor(y),math.ceil(x+bw),math.ceil(y+bh)
                    allowed[y:bottom,x:right]=True;active.append((x,y,right,bottom))
            require(not np.any(alpha[~allowed]), 'Typography alpha escaped its reviewed box or timeline')
            for x,y,right,bottom in active:
                require(np.count_nonzero(alpha[y:bottom,x:right])>0, 'Active typography is missing')
                require(not np.any(alpha[y,x:right]) and not np.any(alpha[bottom-1,x:right])
                        and not np.any(alpha[y:bottom,x]) and not np.any(alpha[y:bottom,right-1]), 'Typography touches box edge; fit is unsafe')
            counts.append(int(np.count_nonzero(alpha)))
        require(not process.stdout.read(1),'Typography has extra frames')
        require(process.wait(timeout=15)==0,'Typography full decode failed')
    finally:
        if process.poll() is None:process.kill();process.wait()
        process.stdout.close();process.stderr.close()
    result={'frames':n,'alpha_checked_all_frames':True,'nonzero_pixels':counts,'box_and_timing_check':'pass','scope':'Technical check, not content/visual acceptance'}
    write_json(directory/'alpha-check.json',result)
    return result


@guarded
def render(run, source, segment, items, meta, directory, legacy='tracked'):
    directory=Path(directory).resolve();inside(run,directory.relative_to(run).as_posix())
    request = run / 'inputs/request.json'
    if request.is_file():
        meta = {**meta, 'target_language': read_json(request).get('target_language')}
    active=[i for i in items if i['start']<segment['end'] and i['end']>segment['start']]
    chosen=[i for i in active if selected(i)]
    if chosen:
        original=read_json(run/'run.json')
        require(file_hash(inside(run,original['source']))==original['source_sha256'],'Typography original source changed')
        current={i['id']:i for i in read_json(run/'analysis/inventory.json')['text_instances']}
        require(all(current.get(i['id'])==i for i in chosen),'Typography copy or instance geometry is stale')
        require(Path(source).resolve().is_relative_to(run.resolve()),'Typography visual input must belong to this run')
    from . import compositor, surface
    plain=[i for i in items if not selected(i)]
    base=compositor.text(source,segment,plain,meta,directory/'plain',run=run) if legacy=='tracked' else media.render_foreground(source,segment,plain,meta,directory/'plain',run=run)
    if not chosen:return base
    layerdir=directory/'motion';layerdir.mkdir(parents=True,exist_ok=True)
    props,font_inputs=_prepare(run,segment,chosen,meta,layerdir)
    policy=read_json(CODE_ROOT/'config/typography.json')
    # Rigid independently timed boxes must not overlap while simultaneously active.
    from .layout import overlaps
    for i,a in enumerate(chosen):
        for b in active:
            if b['id']!=a['id'] and max(a['start'],b['start'])<min(a['end'],b['end']):
                require(not overlaps(a['bbox'],b['bbox']), 'Motion text overlaps another active text instance')
    engine='remotion';fallback=None
    if policy['enabled']:
        try:
            _remotion(run,layerdir,props);_check_layer(layerdir,props)
        except (WorkflowError,OSError,ValueError,subprocess.SubprocessError) as exc:
            engine='ffmpeg_static';fallback=str(exc)[-2000:]
    else:engine='ffmpeg_static';fallback='Remotion disabled by typography policy'
    if engine=='ffmpeg_static':
        lost=['fade/scale','timed keyword color change']
        if any(b.get('emphasize') and any(unicodedata.bidirectional(c) in ('R','AL') for c in b['text']) for b in props['blocks']):
            lost.append('RTL word coloring; intact paragraph uses original text color')
        write_json(layerdir/'fallback.json',{'requested':'remotion','actual':engine,'reason':fallback,'lost_effects':lost,'text_and_timing_preserved':True,'review_required':True})
        _ffmpeg(layerdir,props);_check_layer(layerdir,props)
    request=read_json(run/'inputs/request.json');original=read_json(run/'run.json')
    bound=copy.deepcopy(chosen)
    for item in bound:item['display']['typography_layer']=True
    def asset(path):return {'path':Path(path).relative_to(run).as_posix(),'sha256':file_hash(path)}
    inputs=[asset(run/'inputs/request.json'),asset(run/'analysis/inventory.json'),asset(inside(run,original['source'])),
            asset(source),asset(base),asset(layerdir/'props.json'),*font_inputs]
    for font in props['fonts']:inputs.append(asset(layerdir/'fonts'/font['file']))
    write_json(layerdir/'policy.json',policy);inputs.append(asset(layerdir/'policy.json'))
    record={'source_sha256':original['source_sha256'],'target_language':request['target_language'],
            'texts':{i['id']:i['target_text'] for i in bound},'instance_bindings':surface.instance_bindings(bound),
            'alpha_channel':True,'inputs':inputs,'output':asset(layerdir/'layer.mov'),'renderer':engine,'code':code_identity()}
    write_json(layerdir/'provenance.json',record)
    layer_asset={**record['output'],'record':str((layerdir/'provenance.json').relative_to(run)),'record_sha256':file_hash(layerdir/'provenance.json')}
    surface.verify(run,layer_asset,original['source_sha256'],request['target_language'],bound)
    output=surface.composite(base,layerdir/'layer.mov',segment['end']-segment['start'],directory/'composite')
    receipt={'source_sha256':original['source_sha256'],'target_language':request['target_language'],'segment':segment['id'],
             'interval':[segment['start'],segment['end']],
             'created_at':utc_now(),'renderer':engine,'fallback_reason':fallback,'review_required':True,
             'inputs':inputs,'layer':record['output'],'provenance':asset(layerdir/'provenance.json'),
             'alpha_check':asset(layerdir/'alpha-check.json'),'output':asset(output),'code':record['code']}
    if engine=='ffmpeg_static':receipt['degradation']=asset(layerdir/'fallback.json')
    write_json(directory/'typography-result.json',receipt)
    return output


def verify_receipt(run, asset):
    path=inside(run,asset['path']);require(path.is_file() and file_hash(path)==asset['sha256'],'Typography receipt changed')
    record=read_json(path)
    require(record['source_sha256']==read_json(run/'run.json')['source_sha256'] and
            record['target_language']==read_json(run/'inputs/request.json')['target_language'],'Typography source/locale changed')
    extra=[record['degradation']] if record.get('degradation') else []
    require(record['renderer']!='ffmpeg_static' or bool(extra),'Fallback needs bound degradation evidence')
    for item in [*record['inputs'],record['layer'],record['provenance'],record['alpha_check'],record['output'],*extra]:
        p=inside(run,item['path']);require(p.is_file() and file_hash(p)==item['sha256'],'Typography prepared input or output changed')
    return record


def review_failures(run, assets, review):
    """A static fallback is reviewable output, never an automatic motion pass."""
    failures=[]
    for asset in assets:
        record=verify_receipt(run,asset)
        if record['renderer']!='ffmpeg_static':continue
        accepted=any(row.get('receipt_sha256')==asset['sha256'] and row.get('accepted') is True
                     and isinstance(row.get('observation'),str) and row['observation'].strip()
                     for row in review.get('typography_fallbacks',[]))
        if not accepted:failures.append('typography_fallback_unreviewed:'+record['segment'])
    return failures


def verify_assets(run, assets, inventory):
    """Receipts must cover every motion instance over its complete interval."""
    wanted={i['id']:i for i in inventory.get('text_instances',[]) if selected(i)}
    spans={key:[] for key in wanted}
    for asset in assets:
        record=verify_receipt(run,asset)
        provenance=read_json(inside(run,record['provenance']['path']))
        for key,text in provenance['texts'].items():
            require(key in wanted and text==wanted[key]['target_text'],'Typography receipt copy does not match current inventory')
            spans[key].append(record['interval'])
    for key,item in wanted.items():
        cursor=item['start']
        for start,end in sorted(spans[key]):
            require(start<=cursor+1e-6,'Typography receipts omit an instance interval')
            cursor=max(cursor,end)
        require(cursor>=item['end']-1e-6,'Missing typography receipt for '+key)
