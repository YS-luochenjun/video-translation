from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .common import CODE_ROOT, WorkflowError, inside, require, require_number, write_json
from .timing import timed


def command(args, cwd=None, timeout=240):
    try:
        result = subprocess.run([str(arg) for arg in args], cwd=cwd, capture_output=True,
                                encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkflowError(f"Media command failed: {type(exc).__name__}") from exc
    if result.returncode:
        raise WorkflowError(f"{Path(str(args[0])).name}: {result.stderr[-2500:]}")
    return result


@timed('media.probe')
def probe(path):
    result = command(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path])
    raw = json.loads(result.stdout)
    videos = [stream for stream in raw["streams"] if stream["codec_type"] == "video"]
    require(bool(videos), "Input contains no video stream")
    video = videos[0]
    duration = float(raw["format"].get("duration", video.get("duration", 0)))
    require(duration > 0, "Input duration must be positive")
    rate = video.get("avg_frame_rate", "0/1").split("/")
    fps = float(rate[0]) / (float(rate[1]) or 1)
    return {"duration": duration, "width": video["width"], "height": video["height"],
            "fps": fps, "video_codec": video["codec_name"],
            "has_audio": any(stream["codec_type"] == "audio" for stream in raw["streams"]),
            "raw": raw}


@timed('media.ffmpeg')
def ffmpeg(args, cwd=None):
    return command(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], cwd)


def ass_filter(filename, fonts_directory=None):
    fonts = Path(fonts_directory or CODE_ROOT / 'assets/fonts').as_posix().replace(':', r'\:').replace("'", r"'\''")
    return f"ass={filename}:fontsdir='{fonts}'"


def cut(source, start, end, output):
    ffmpeg(["-ss", start, "-i", source, "-t", end - start, "-map", "0:v:0", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-movflags", "+faststart", output])


def scene_points(source, duration):
    """Candidate visual cuts, never a reviewed text/pose timeline."""
    scene = command(['ffmpeg', '-hide_banner', '-i', source, '-vf',
                     "select='gt(scene,0.32)',showinfo", '-an', '-f', 'null', '-'])
    points = [0.0]
    for match in re.finditer(r'pts_time:([0-9.]+)', scene.stderr):
        timestamp = float(match[1])
        if timestamp-points[-1] >= .5 and timestamp < duration-.15:
            points.append(timestamp)
    return points+[duration]


def extract(source, directory, interval=1.0, max_clip=8.0):
    require_number(interval, "sampling interval", minimum=0.05, maximum=10)
    require_number(max_clip, "maximum clip duration", minimum=0.1, maximum=30)
    meta = probe(source)
    require_number(meta["duration"], "source duration", minimum=.001)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    frames = directory / "frames"
    frames.mkdir(exist_ok=True)
    ffmpeg(["-i", source, "-vf", f"fps=1/{interval}", "-pix_fmt", "yuvj420p", "-q:v", "3", frames / "frame-%05d.jpg"])
    if meta["has_audio"]:
        ffmpeg(["-i", source, "-vn", "-ac", "1", "-ar", "16000", directory / "audio.wav"])
    points = scene_points(source, meta['duration'])
    boundaries = [0.0]
    for start, end in zip(points, points[1:]):
        while end - start > max_clip + 0.001:
            start += max_clip
            boundaries.append(start)
        boundaries.append(end)
    shots = []
    for i, (start, end) in enumerate(zip(boundaries, boundaries[1:]), 1):
        image = directory / f"shot-{i:03d}.jpg"
        timestamp = min((start + end) / 2, meta["duration"] - 0.05)
        ffmpeg(["-ss", timestamp, "-i", source, "-frames:v", "1", "-pix_fmt", "yuvj420p", "-q:v", "2", image])
        shots.append({"id": f"s{i:03d}", "start": round(start, 3), "end": round(end, 3),
                      "description": "", "keyframe": f"analysis/{image.name}"})
    sampled = sorted(frames.glob("frame-*.jpg"))
    # One second sampling is navigation evidence, not complete OCR or temporal coverage.
    if sampled:
        contact_sheets(frames, directory, columns=6, per_page=48, width=200)
    write_json(directory / "media.json", meta)
    write_json(directory / "frame-index.json", [
        {"path": f"analysis/frames/{frame.name}", "approx_time": round((i + 0.5) * interval, 3)}
        for i, frame in enumerate(sampled)])
    return meta, shots


def contact_sheets(frames, directory, columns=4, per_page=32, width=240):
    count = len(list(Path(frames).glob("frame-*.jpg")))
    pages = []
    for offset in range(0, count, per_page):
        page = offset // per_page + 1
        name = "contact-sheet.jpg" if page == 1 else f"contact-sheet-{page:02d}.jpg"
        size = min(per_page, count-offset)
        rows = (size + columns - 1) // columns
        ffmpeg(["-framerate", "1", "-start_number", offset+1, "-i", Path(frames) / "frame-%05d.jpg",
                "-vf", f"scale={width}:-1,tile={columns}x{rows}:nb_frames={size}", "-frames:v", "1",
                "-pix_fmt", "yuvj420p", Path(directory) / name])
        pages.append({"file": name, "first_frame": offset+1, "last_frame": offset+size})
    write_json(Path(directory) / "contact-pages.json", pages)
    return pages


def tools_available():
    return {name: shutil.which(name) for name in ("ffmpeg", "ffprobe")}


def ass_time(seconds):
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{fraction:02d}"


def ass_text(value):
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", r"\N")


def render_local(source, segment, instances, meta, directory):
    from . import layout
    from .captions import render_instances
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    width, height = meta["width"], meta["height"]
    filters, events = [], []
    for item in instances:
        if item["action"] != "solid_overlay":
            continue
        erase_start, erase_end = item.get("source_interval", [item["start"], item["end"]])
        start = max(erase_start, segment["start"]) - segment["start"]
        end = min(erase_end, segment["end"]) - segment["start"]
        if end <= start:
            continue
        x, y, w, h = item["bbox"]
        color = item.get("background", "#FFFFFF").replace("#", "0x")
        require(bool(re.fullmatch(r"0x[0-9A-Fa-f]{6}", color)), "Invalid background color")
        filters.append(f"drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t=fill:enable='gte(t,{start})*lt(t,{end})'")
    for item in render_instances([item for item in instances if item["action"] == "solid_overlay"]):
        start = max(item["start"], segment["start"]) - segment["start"]
        end = min(item["end"], segment["end"]) - segment["start"]
        if end <= start:
            continue
        layout.validate(item, meta)
        x, y, w, h = item["bbox"]
        text_color = item.get("text_color", "#111111").lstrip("#")
        require(bool(re.fullmatch(r"[0-9A-Fa-f]{6}", text_color)), "Invalid text color")
        ass_color = text_color[4:6] + text_color[2:4] + text_color[0:2]
        family = item.get("font_family", layout.default_family(item['target_text'], item.get('target_language') or meta.get('target_language')))
        size = layout.font_size({**item, 'font_family': family})
        from .fonts import ass_name
        family = ass_name(CODE_ROOT, family, item.get('bold', False), directory)
        alignment = item.get("align", "center")
        padding = item.get("padding", 2)
        anchor = 4 if alignment == "left" else 6 if alignment == "right" else 5
        position = x + padding if alignment == "left" else x+w-padding if alignment == "right" else x+w/2
        bold = 1 if item.get("bold") else 0
        prefix = f"{{\\an{anchor}\\pos({position},{y+h/2})\\fn{family}\\b{bold}\\fs{size}\\clip({x},{y},{x+w},{y+h})\\c&H{ass_color}&}}"
        events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{prefix}{ass_text(item['target_text'])}")
    ass = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "[V4+ Styles]", "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        "Style: Default,Arial,36,&H00111111,&H00111111,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1",
        "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text", *events, ""])
    (directory / "overlay.ass").write_text(ass, encoding="utf-8-sig")
    filters.append(ass_filter('overlay.ass', directory / 'fonts'))
    ffmpeg(["-ss", segment["start"], "-i", source, "-t", segment["end"]-segment["start"],
            "-vf", ",".join(filters), "-an", "-r", "30", "-c:v", "libx264", "-crf", "18",
            "-pix_fmt", "yuv420p", "visual.mp4"], cwd=directory)
    return directory / "visual.mp4"


def normalize(source, duration, meta, output):
    actual = probe(source)
    require(abs(actual["duration"] - duration) <= 0.3,
            f"Candidate duration {actual['duration']:.2f}s differs from segment {duration:.2f}s; review or replan")
    # Cropping/timing errors are gated rather than hidden with stretching or frame duplication.
    target_ratio = meta["width"] / meta["height"]
    require(abs(actual["width"] / actual["height"] - target_ratio) < 0.02,
            "Candidate aspect ratio differs from the source")
    ffmpeg(["-i", source, "-t", duration, "-vf", f"scale={meta['width']}:{meta['height']},setsar=1",
            "-r", "30", "-an", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", output])


def restore_regions(source, edited, segment, regions, directory):
    """Copy explicitly preserved source regions over a model edit before local typesetting."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    graph, previous = [], "1:v"
    if len(regions) > 1:
        graph.append(f"[0:v]split={len(regions)}" + "".join(f"[source{i}]" for i in range(len(regions))))
    for index, (x, y, width, height) in enumerate(regions):
        original = "0:v" if len(regions) == 1 else f"source{index}"
        graph.append(f"[{original}]crop={width}:{height}:{x}:{y},setpts=PTS-STARTPTS[region{index}]")
        graph.append(f"[{previous}][region{index}]overlay={x}:{y}:eof_action=repeat:repeatlast=1[out{index}]")
        previous = f"out{index}"
    output = directory / "visual.mp4"
    ffmpeg(["-ss", segment["start"], "-i", source, "-i", edited, "-filter_complex", ";".join(graph),
            "-map", f"[{previous}]", "-t", segment["end"] - segment["start"], "-an",
            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", output])
    return output


def retime(source, duration, output, reason):
    """Explicit experiment mapping; unplanned normalization still rejects duration changes."""
    require(bool(reason), "Video retiming requires an explicit experiment reason")
    actual = probe(source)
    ratio = duration / actual['duration']
    require(.5 <= ratio <= 2, "Experimental video timeline conversion must stay within 2x")
    ffmpeg(['-i',source,'-vf',f'setpts={ratio}*PTS,fps=30,tpad=stop_mode=clone:stop_duration=0.15',
            '-t',duration,'-an','-c:v','libx264','-crf','16','-pix_fmt','yuv420p',output])
    write_json(Path(output).with_suffix('.timeline.json'), {'source_duration': actual['duration'], 'output_duration': duration,
               'time_scale': ratio, 'reason': reason, 'audio': 'Excluded; original audio timeline is handled independently',
               'limitation': 'Temporal interpolation/duplication inside model text repair regions requires visual review.'})
    return Path(output)


def render_foreground(source, segment, instances, meta, directory):
    """Typeset reviewed target copy on an already text-free video, without erasing pixels."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    events = []
    from .captions import render_instances
    for item in render_instances(instances):
        start = max(item["start"], segment["start"])-segment["start"]
        end = min(item["end"], segment["end"])-segment["start"]
        if end <= start:
            continue
        x, y, width, height = item["bbox"]
        display = item.get("display", {})
        from . import layout
        family = display.get('font_family', layout.default_family(item['target_text'], item.get('target_language') or meta.get('target_language')))
        require(layout.supported_family(family), 'Unsupported font family')
        from .fonts import missing_glyphs
        face = layout.measurement_face(CODE_ROOT, family, display.get('bold', True))
        require(face['path'].is_file(), f'Requested font is unavailable: {family}')
        require(not missing_glyphs(face, item['target_text']), f'Font has missing glyphs: {family}')
        from .fonts import ass_name
        family = ass_name(CODE_ROOT, family, display.get('bold', True), directory)
        size, outline = display.get("font_size", 64), display.get("outline", 5)
        if display.get("pill"):
            # Native ASS vector drawing: no generated lettering or raster repair.
            radius = height/2
            offset = radius * 0.55228475
            shape = (f"m {radius} 0 l {width-radius} 0 "
                     f"b {width-radius+offset} 0 {width} {radius-offset} {width} {radius} "
                     f"b {width} {radius+offset} {width-radius+offset} {height} {width-radius} {height} "
                     f"l {radius} {height} b {radius-offset} {height} 0 {radius+offset} 0 {radius} "
                     f"b 0 {radius-offset} {radius-offset} 0 {radius} 0")
            slide_ms = min(230, max(1, round((end-start)*1000)))
            motion = f"\\move({x-width-180},{y},{x},{y},0,{slide_ms})"
            drawing = f"{{\\an7{motion}\\p1\\c&HCECEBE&\\3c&H5A5A50&\\bord3\\shad2}}{shape}"
            events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{drawing}")
            text_motion = f"\\move({x-width-180+width/2},{y+height/2},{x+width/2},{y+height/2},0,{slide_ms})"
            label = f"{{\\an5{text_motion}\\fn{family}\\b{int(display.get('bold',True))}\\fs{size}\\c&H080808&\\3c&HF7F7ED&\\bord2\\shad0}}{ass_text(item['target_text'])}"
            events.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{label}")
            continue
        lines = item["target_text"].split("\n")
        line_height = display.get("line_height", 88)
        total = sum(len(line) for line in lines)
        step = display.get("reveal_seconds", 0)/max(1, total)
        cursor = start
        for index, line in enumerate(lines):
            prefix = f"{{\\an8\\pos({x+width/2},{y+index*line_height})\\fn{family}\\b{int(display.get('bold',True))}\\fs{size}\\bord{outline}\\shad2}}"
            if not step:
                events.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{prefix}{ass_text(line)}")
            else:
                for count in range(1, len(line)+1):
                    until = end if count == len(line) else min(end, cursor+step)
                    if cursor < until:
                        events.append(f"Dialogue: 1,{ass_time(cursor)},{ass_time(until)},Default,,0,0,0,,{prefix}{ass_text(line[:count])}")
                    cursor += step
    header = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {meta['width']}", f"PlayResY: {meta['height']}",
              "[V4+ Styles]", "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
              "Style: Default,Arial,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,8,0,0,0,1",
              "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]
    (directory / "foreground.ass").write_text("\n".join(header+events+[""]), encoding="utf-8-sig")
    ffmpeg(["-i", source, "-t", segment["end"]-segment["start"], "-vf", ass_filter('foreground.ass', directory / 'fonts'),
            "-an", "-r", "30", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "visual.mp4"], cwd=directory)
    return directory / "visual.mp4"


def render_reference(source, segment, instances, meta, directory, run):
    """Approximate occluded animation with reviewed plates; retain source outside explicit mattes."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    config = segment["reference_composite"]
    knots = config["blend_knots"]
    weight = str(knots[-1][1])
    for (t0, v0), (t1, v1) in reversed(list(zip(knots, knots[1:]))):
        ramp = f"({v0}+({v1-v0})*max(0,T+{segment['start']}-{t0})/{t1-t0})"
        weight = f"if(lt(T+{segment['start']},{t1}),{ramp},{weight})"
    w, h, duration = meta["width"], meta["height"], segment["end"]-segment["start"]
    matte = [f"color=black:s={w}x{h}:r=30:d={duration}", "format=gbrp"]
    for x, y, rw, rh in config["erase_regions"]:
        matte.append(f"drawbox=x={x}:y={y}:w={rw}:h={rh}:color=white:t=fill")
    # Feathering is deliberately only eight pixels, with regions expanded beyond all lettering/shadow.
    matte.append("gblur=sigma=8")
    graph = [f"[0:v]format=gbrp,setpts=PTS-STARTPTS[src]",
             f"[1:v]scale={w}:{h},format=gbrp,setpts=PTS-STARTPTS[day]",
             f"[2:v]scale={w}:{h},format=gbrp,setpts=PTS-STARTPTS[night]",
             # Evaluate the time curve on four pixels rather than every full-resolution pixel.
             f"color=black:s=2x2:r=30:d={duration},format=gbrp,"
             f"geq=r='255*({weight})':g='255*({weight})':b='255*({weight})',"
             f"scale={w}:{h}:flags=neighbor[weight]",
             "[day][night][weight]maskedmerge=planes=7[plate]",
             ",".join(matte)+"[matte]", "[src][plate][matte]maskedmerge=planes=7[clean]"]
    (directory / "reference-filter.txt").write_text(";\n".join(graph), encoding="utf-8")
    clean = directory / "clean.mp4"
    ffmpeg(["-ss", segment["start"], "-i", source,
            "-loop", "1", "-framerate", "30", "-i", inside(run, config["day"]["path"]),
            "-loop", "1", "-framerate", "30", "-i", inside(run, config["night"]["path"]),
            "-filter_complex", ";\n".join(graph), "-map", "[clean]", "-t", duration,
            "-an", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", clean])
    from . import typography
    return typography.render(run, clean, segment, instances, meta, directory / "target-overlay", legacy='foreground')


def assemble(visuals, audio_source, output, duration):
    output = Path(output)
    listing = output.parent / "concat.txt"
    # Only generated local files are placed in this concat list.
    for visual in visuals:
        require("'" not in str(visual) and "\n" not in str(visual), "Unsupported concat path")
    listing.write_text("\n".join(f"file '{Path(p).resolve().as_posix()}'" for p in visuals), encoding="utf-8")
    args = ["-f", "concat", "-safe", "0", "-i", listing]
    if audio_source:
        args.extend(["-i", audio_source, "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac"])
    else:
        args.extend(["-map", "0:v:0", "-an"])
    ffmpeg([*args, "-c:v", "copy", "-t", duration, "-movflags", "+faststart", output])

