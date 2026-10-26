"""Preserve source pixels outside timed text mattes; typeset tracked native glyphs."""
from pathlib import Path

from .common import require, write_json
from . import media


def spans(item, segment):
    start, end = max(item['start'], segment['start']), min(item['end'], segment['end'])
    if end <= start:
        return []
    points = sorted(item.get('trajectory') or [{'time': item['start'], 'bbox': item['bbox']}], key=lambda p: p['time'])
    active = [p for p in points if p['time'] <= start]
    first = active[-1] if active else points[0]
    sequence = [{**first, 'time': start}, *[p for p in points if start < p['time'] < end]]
    return [(p['time']-segment['start'], (sequence[i+1]['time'] if i+1 < len(sequence) else end)-segment['start'], p)
            for i,p in enumerate(sequence)]


def header(meta):
    return ['[Script Info]', 'ScriptType: v4.00+', f"PlayResX: {meta['width']}", f"PlayResY: {meta['height']}",
            'WrapStyle: 2', '[V4+ Styles]', 'Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding',
            'Style: Default,Microsoft YaHei,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1',
            '[Events]', 'Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text']


def event(start, end, text, layer=0):
    return f'Dialogue: {layer},{media.ass_time(start)},{media.ass_time(end)},Default,,0,0,0,,{text}'


def regions(source, edited, segment, items, meta, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    events = []
    for item in items:
        if item['action'] in ('preserve', 'solid_overlay'):
            continue
        for start,end,point in spans(item, segment):
            x,y,w,h = point['bbox']
            padding = item.get('erase_padding', 2)
            x1,y1 = max(0,x-padding), max(0,y-padding)
            x2,y2 = min(meta['width'],x+w+padding), min(meta['height'],y+h+padding)
            shape = f'm {x1} {y1} l {x2} {y1} {x2} {y2} {x1} {y2}'
            if point.get('polygon'):
                polygon=point['polygon']
                cx=sum(p[0] for p in polygon)/4
                cy=sum(p[1] for p in polygon)/4
                expanded=[(min(meta['width'],max(0,px+(padding if px>=cx else -padding))),min(meta['height'],max(0,py+(padding if py>=cy else -padding)))) for px,py in polygon]
                shape='m '+' l '.join(f'{px} {py}' for px,py in expanded)+' l '+f'{expanded[0][0]} {expanded[0][1]}'
            events.append(event(start,end,r'{\an7\pos(0,0)\p1\bord0\shad0\c&HFFFFFF&}'+shape))
    require(events, 'Regional model composition needs observed text regions')
    (directory/'mask.ass').write_text('\n'.join(header(meta)+events+['']),encoding='utf-8-sig')
    output = directory/'visual.mp4'
    duration = segment['end']-segment['start']
    media.ffmpeg(['-ss',segment['start'],'-i',source,'-i',edited,
                  '-f','lavfi','-i',f"color=c=black:s={meta['width']}x{meta['height']}:r=30:d={duration}",
                  '-filter_complex','[0:v]setpts=PTS-STARTPTS,format=gbrp[original];[1:v]setpts=PTS-STARTPTS,format=gbrp[edited];[2:v]format=rgb24,ass=mask.ass,format=gbrp,gblur=sigma=0.6[mask];[original][edited][mask]maskedmerge[out]',
                  '-map','[out]','-t',duration,'-an','-r','30','-c:v','libx264','-crf','16','-pix_fmt','yuv420p',output],cwd=directory)
    write_json(directory/'composition.json',{'method':'Model pixels enter only observed text regions at their source times. All other pixels come from original source before re-encoding.',
               'instance_ids':[item['id'] for item in items if item['action'] not in ('preserve','solid_overlay')],
               'limitations':'Model backgrounds inside mattes may drift; OCR timing and local borders require actual review.'})
    return output


def color(value):
    text=value.lstrip('#')
    require(len(text)==6 and all(c in '0123456789abcdefABCDEF' for c in text),'Invalid typography color')
    return text[4:]+text[2:4]+text[:2]


def text(source, segment, items, meta, directory):
    from . import layout
    from .captions import render_instances
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    events=[]
    for item in render_instances(items):
        if item['action'] in ('preserve','solid_overlay') or item.get('display',{}).get('typography_layer'):continue
        display=item.get('display',{})
        for start,end,point in spans(item,segment):
            x,y,w,h=point['bbox']
            size=point.get('font_size',display.get('font_size',40))
            angle=point.get('angle',display.get('angle',0))
            family=display.get('font_family','Microsoft YaHei')
            require(family in ('Microsoft YaHei','KaiTi','SimSun','Arial','Yu Gothic','Malgun Gothic'),'Unsupported typography font')
            target=point.get('target_text',item['target_text'])
            if family=='Arial' and any('\u4e00'<=char<='\u9fff' for char in target):family='Microsoft YaHei'
            size=layout.font_size({'bbox':point['bbox'],'target_text':target,'font_family':family,'font_size':size,'bold':display.get('bold',True),'fit_text':True,'padding':1})
            prefix=(f"{{\\an5\\pos({x+w/2},{y+h/2})\\fn{family}\\fs{size}\\b{1 if display.get('bold',True) else 0}"
                    f"\\i{1 if display.get('italic') else 0}\\frz{-angle}\\bord{display.get('outline',2)}\\shad{display.get('shadow',0)}"
                    f"\\c&H{color(display.get('color','#FFFFFF'))}&\\3c&H{color(display.get('outline_color','#111111'))}&}}")
            if point.get('occluded_by'):
                cx,cy,cw,ch=point['occluded_by']
                require(cw>0 and ch>0,'Text occluder must have positive dimensions')
                prefix=prefix[:-1]+f'\\iclip({cx},{cy},{cx+cw},{cy+ch})'+'}'
            if item['source_text']=='wait!':
                back=prefix.replace('\\bord'+str(display.get('outline',2)), '\\bord12').replace('\\3c&H'+color(display.get('outline_color','#111111')), '\\3c&H0000D6')
                events.append(event(start,end,back+media.ass_text(point.get('target_text',item['target_text'])),0))
            strokes=display.get('outline_layers',[])
            for layer,stroke in enumerate(strokes):
                require(0<=stroke['width']<=24,'Outline width outside supported range')
                back=prefix.replace('\\bord'+str(display.get('outline',2)),'\\bord'+str(stroke['width']))
                back=back.replace('\\3c&H'+color(display.get('outline_color','#111111')),'\\3c&H'+color(stroke['color']))
                events.append(event(start,end,back+media.ass_text(target),layer))
            events.append(event(start,end,prefix+media.ass_text(target),len(strokes)+1))
    (directory/'tracked.ass').write_text('\n'.join(header(meta)+events+['']),encoding='utf-8-sig')
    output=directory/'visual.mp4'
    media.ffmpeg(['-i',source,'-t',segment['end']-segment['start'],'-vf',media.ass_filter('tracked.ass'),'-an','-r','30','-c:v','libx264','-crf','16','-pix_fmt','yuv420p',output],cwd=directory)
    return output
