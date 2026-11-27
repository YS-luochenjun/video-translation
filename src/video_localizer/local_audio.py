"""Existing narration mixer, promoted to a resumable project capability."""
import wave
import numpy as np
from . import captions, media, workflow
from .common import WorkflowError, file_hash, guarded, inside, object_hash, read_json, require, require_number, write_json


def _source_scope(run):
    binding = run / 'inputs/fireplay.json'
    if not binding.exists():
        return {'kind': 'local'} if not binding.is_symlink() else None
    try:
        requirement = read_json(binding)['requirement_id']
        if isinstance(requirement, str) and requirement:
            return {'kind': 'fireplay', 'requirement_id': requirement}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _reuse_source_track(run, index, signature, path):
    root = run.parent.parent
    try:
        cached = read_json(index)
        origin = inside(root / 'runs', cached['run'])
        if origin.parent != root / 'runs' or _source_scope(origin) != _source_scope(run):
            return False
        source = origin / path.relative_to(run)
        record = read_json(source.with_name('provenance.json'))
        if record['signature'] != signature or record['sha256'] != cached['sha256']:
            return False
        media.copy_verified_video(source, path, record['sha256'])
        return True
    except (OSError, ValueError, WorkflowError, KeyError, TypeError):
        return False


def source_track(run):
    source=workflow.source_path(run)
    signature={'source_sha256':file_hash(source),'ffmpeg':media.command(['ffmpeg','-version']).stdout,
               'format':'stereo 44100 Hz pcm_s16le'}
    directory=run/'outputs/source-audio'/object_hash(signature)[:20]
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/'source-stereo.wav'; receipt=directory/'provenance.json'
    scope = _source_scope(run)
    index = (run.parent.parent / 'state/source-audio-cache' /
             (object_hash({'scope': scope, 'signature': signature}) + '.json')) if scope else None
    if receipt.exists():
        record=read_json(receipt)
        require(record['signature']==signature and path.is_file() and file_hash(path)==record['sha256'],'Source audio checkpoint changed')
    else:
        if index is None or not _reuse_source_track(run, index, signature, path):
            media.ffmpeg(['-i',source,'-vn','-ac','2','-ar','44100','-c:a','pcm_s16le',path])
        write_json(receipt,{'signature':signature,'sha256':file_hash(path)})
    if index is not None:
        write_json(index, {'run': run.name, 'sha256': read_json(receipt)['sha256']})
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


def background_mix(source, background, rate, windows):
    """Remove source speech throughout each window; fade only in the gaps."""
    blend = np.zeros(len(source), dtype=np.float32)
    for start, end in windows:
        blend[start:end] = 1
    transitions = []
    for (_, previous_end), (next_start, _) in zip(
            [(0, 0), *windows], [*windows, (len(source), len(source))]):
        gap = next_start - previous_end
        if gap <= 0:
            continue
        if previous_end and next_start < len(source) and gap < round(.02 * rate):
            blend[previous_end:next_start] = 1
            transitions.append({'start_sample': previous_end, 'end_sample': next_start, 'direction': 'keep_stem_short_gap'})
            continue
        available = gap // 2 if previous_end and next_start < len(source) else gap
        if previous_end:
            fade = min(round(.12 * rate), available)
            if fade:
                blend[previous_end:previous_end + fade] = .5 + .5 * np.cos(np.linspace(0, np.pi, fade))
                transitions.append({'start_sample': previous_end, 'end_sample': previous_end + fade, 'direction': 'to_source'})
        if next_start < len(source):
            fade = min(round(.12 * rate), available)
            if fade:
                blend[next_start - fade:next_start] = .5 - .5 * np.cos(np.linspace(0, np.pi, fade))
                transitions.append({'start_sample': next_start - fade, 'end_sample': next_start, 'direction': 'to_stem'})
    bed = source * (1 - blend[:, None]) + background * blend[:, None]
    return bed, blend, transitions


def voice_only_limit(bed, voice, rate):
    """Limit the voice contribution against existing background headroom."""
    ceiling = np.maximum(.985, np.abs(bed))
    headroom = ceiling - np.sign(voice) * bed
    allowed = np.ones_like(voice)
    np.divide(headroom, np.abs(voice), out=allowed, where=np.abs(voice) > 1e-8)
    allowed = np.clip(np.min(allowed, axis=1), 0, 1)
    block = max(1, round(.02 * rate))
    positions = np.arange(0, len(voice), block)
    minima = np.minimum.reduceat(allowed, positions)
    boundaries = np.minimum(np.r_[1, minima], np.r_[minima, 1])
    envelope = np.interp(np.arange(len(voice)), np.r_[positions, len(voice)], boundaries).astype(np.float32)
    envelope = np.minimum(envelope, allowed)
    return bed + voice * envelope[:, None], envelope


def signal_levels(samples):
    if not len(samples):
        return {'rms_dbfs': None, 'peak_dbfs': None}
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    peak = float(np.max(np.abs(samples)))
    return {'rms_dbfs': round(20 * np.log10(rms), 2) if rms > 0 else None,
            'peak_dbfs': round(20 * np.log10(peak), 2) if peak > 0 else None}


def background_continuity(source, bed, rate, removal_windows):
    block = max(1, round(.25 * rate))
    intervals = []
    windows = []
    for window_start, window_end in removal_windows:
        if window_end <= window_start:
            continue
        current = None
        flagged_samples = 0
        for start in range(window_start, window_end, block):
            end = min(window_end, start + block)
            source_block, bed_block = source[start:end], bed[start:end]
            levels = {
                'source_rms_dbfs': signal_levels(source_block)['rms_dbfs'],
                'bed_rms_dbfs': signal_levels(bed_block)['rms_dbfs'],
                'source_side_rms_dbfs': signal_levels(source_block[:, 0] - source_block[:, 1])['rms_dbfs'],
                'bed_side_rms_dbfs': signal_levels(bed_block[:, 0] - bed_block[:, 1])['rms_dbfs'],
            }
            source_rms, bed_rms, source_side, bed_side = levels.values()
            flags = []
            if source_rms is not None and source_rms >= -36 and (bed_rms is None or bed_rms <= -48):
                flags.append('active_source_near_silent_bed')
            if source_side is not None and source_side >= -48 and (bed_side is None or source_side - bed_side >= 12):
                flags.append('stereo_component_attenuated')
            if bed_rms is not None and (source_rms is None or bed_rms - source_rms >= 6):
                flags.append('bed_exceeds_source_mix')
            if not flags:
                current = None
                continue
            flagged_samples += end - start
            if current is None or current['flags'] != flags:
                current = {'start_seconds': round(start / rate, 3), 'flags': flags, 'blocks': []}
                intervals.append(current)
            current['end_seconds'] = round(end / rate, 3)
            current['blocks'].append({'start_seconds': round(start / rate, 3), **levels})
        windows.append({
            'start_seconds': round(window_start / rate, 3),
            'end_seconds': round(window_end / rate, 3),
            'source_rms_dbfs': signal_levels(source[window_start:window_end])['rms_dbfs'],
            'bed_rms_dbfs': signal_levels(bed[window_start:window_end])['rms_dbfs'],
            'flagged_seconds': round(flagged_samples / rate, 3),
        })
    return {
        'review_required': bool(intervals),
        'source_speech_windows': windows,
        'review_intervals': intervals,
        'limitation': 'Pre-dub RMS screening. Source activity may be entirely speech, and stereo differences can contain speech or effects. No interval proves music loss or retention.',
    }


def speech_activity(voice, rate):
    block = max(1, round(.05 * rate))
    starts = np.arange(0, len(voice), block)
    energy = np.mean(np.square(voice), axis=1)
    lengths = np.diff(np.r_[starts, len(voice)])
    rms = np.sqrt(np.add.reduceat(energy, starts) / lengths)
    threshold = max(float(np.max(rms)) * .1, .001)
    return np.repeat(rms >= threshold, lengths)


def voice_margin(bed, voice, active):
    bed_levels = signal_levels(bed[active])
    voice_levels = signal_levels(voice[active])
    background_db = bed_levels['rms_dbfs']
    voice_db = voice_levels['rms_dbfs']
    margin = None if background_db is None or voice_db is None else round(voice_db - background_db, 2)
    return {'background': bed_levels, 'voice': voice_levels, 'voice_over_background_db': margin}


def validate_level_profile(profile):
    require(isinstance(profile, dict) and isinstance(profile.get('evidence'), str)
            and profile['evidence'].strip(), 'Source-relative level profile requires actual evidence')
    for key, minimum, maximum in (
            ('voice_rms_range_dbfs', -90, 0), ('background_rms_range_dbfs', -90, 0),
            ('voice_over_background_range_db', -90, 90)):
        limits = profile.get(key)
        if limits is None:
            continue
        require(isinstance(limits, list) and len(limits) == 2, f'{key}: expected lower and upper bounds')
        lower = require_number(limits[0], key, minimum=minimum, maximum=maximum)
        require_number(limits[1], key, minimum=lower, maximum=maximum)
    require(any(profile.get(key) is not None for key in (
        'voice_rms_range_dbfs', 'background_rms_range_dbfs', 'voice_over_background_range_db')),
        'Level profile requires at least one measured range')
    return profile


def level_range_issues(levels, profile):
    issues = []
    for key, value in (
            ('voice_rms_range_dbfs', levels['voice']['rms_dbfs']),
            ('background_rms_range_dbfs', levels['background']['rms_dbfs']),
            ('voice_over_background_range_db', levels['voice_over_background_db'])):
        limits = profile.get(key)
        if limits is not None and (value is None or not limits[0] <= value <= limits[1]):
            issues.append({'range': key, 'expected': limits, 'measured': value})
    return issues


def balance_voice(bed, voice, rate, profile=None):
    profile = validate_level_profile(profile) if profile is not None else None
    margin_range = profile.get('voice_over_background_range_db') if profile is not None else None
    target_margin = margin_range[0] if margin_range else (6. if profile is None else None)
    active = speech_activity(voice, rate)
    require(np.any(active), 'Aligned voice has no measurable active speech signal')
    before = voice_margin(bed, voice, active)
    margin = before['voice_over_background_db']
    voice_range = profile.get('voice_rms_range_dbfs') if profile is not None else None
    bed_range = profile.get('background_rms_range_dbfs') if profile is not None else None
    voice_db = before['voice']['rms_dbfs']
    bed_db = before['background']['rms_dbfs']
    gain_db = target_margin - margin if target_margin is not None and margin is not None else 0.
    if profile is None:
        gain_db = max(0., gain_db)
    else:
        gain_db = max(0., gain_db)
        if margin_range and margin is not None and margin > margin_range[1]:
            gain_db = margin_range[1] - margin
        if voice_range and voice_db is not None:
            gain_db = min(voice_range[1] - voice_db, max(voice_range[0] - voice_db, gain_db))
        if bed_range and (bed_db is None or bed_db < bed_range[0]) and gain_db < 0:
            gain_db = min(0., voice_range[1] - voice_db) if voice_range and voice_db is not None else 0.
    boost_db = min(9., max(-9., gain_db))
    boosted = voice * 10**(boost_db / 20)
    mixed, limiter = voice_only_limit(bed, boosted, rate)
    after = voice_margin(bed, boosted * limiter[:, None], active)
    duck_db = 0.
    adjusted_bed = bed
    if target_margin is not None and after['voice_over_background_db'] is not None:
        duck_db = min(4., max(0., target_margin - after['voice_over_background_db']))
    if bed_range and bed_db is not None:
        duck_db = min(4., max(duck_db, bed_db - bed_range[1]), max(0., bed_db - bed_range[0]))
    if duck_db > .1:
        positions = np.arange(len(bed))
        active_positions = np.flatnonzero(active)
        fade = max(1, round(.12 * rate))
        distance = np.maximum(np.maximum(active_positions[0] - positions, positions - active_positions[-1]), 0)
        weight = np.maximum(0., 1 - distance / fade)
        weight = np.minimum(weight, np.minimum(positions, len(bed) - 1 - positions) / fade)
        adjusted_bed = bed * (10**(-duck_db * weight / 20))[:, None]
        mixed, limiter = voice_only_limit(adjusted_bed, boosted, rate)
        after = voice_margin(adjusted_bed, boosted * limiter[:, None], active)
    else:
        duck_db = 0.
    achieved = after['voice_over_background_db']
    review = target_margin is not None and achieved is not None and achieved < target_margin - .5
    profile_issues = level_range_issues(after, profile) if profile is not None else []
    local_risks = []
    quiet_background = []
    block = max(1, round(.25 * rate))
    effective_voice = boosted * limiter[:, None]
    for start in range(0, len(voice), block):
        end = min(len(voice), start + block)
        active_block = active[start:end]
        if np.count_nonzero(active_block) < max(1, round(.05 * rate)):
            continue
        local = voice_margin(adjusted_bed[start:end], effective_voice[start:end], active_block)
        local_margin = local['voice_over_background_db']
        if local_margin is not None and local_margin < 0:
            local_risks.append({'start_seconds': round(start/rate, 3), 'end_seconds': round(end/rate, 3),
                                'voice_over_background_db': local_margin})
        bed_db = local['background']['rms_dbfs']
        if bed_db is None or (bed_db <= -36 and local_margin is not None and local_margin >= 18):
            quiet_background.append({'start_seconds': round(start/rate, 3), 'end_seconds': round(end/rate, 3),
                                     'background_rms_dbfs': bed_db, 'voice_over_background_db': local_margin})
    return mixed, limiter, {'target_voice_over_background_db': target_margin,
                            'level_profile': profile,
                            'level_profile_issues_before': level_range_issues(before, profile) if profile is not None else [],
                            'level_profile_issues_after': profile_issues,
                            'active_speech_seconds': round(float(np.count_nonzero(active)/rate), 3),
                            'before': before, 'after': after,
                            'automatic_voice_gain_db': round(boost_db, 2),
                            'maximum_background_duck_db': round(duck_db, 2),
                            'background_dominant_intervals': local_risks,
                            'quiet_background_intervals': quiet_background,
                            'review_required': bool(review or local_risks or profile_issues),
                            'measurement': 'Active 50ms voice blocks; stem-component RMS dBFS; quiet background can be intentional and does not establish music loss.'}


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
        if 'level_profile' in line:
            validate_level_profile(line['level_profile'])
        require_number(line['start'],'Speech start',minimum=0)
        require_number(line['end'],'Speech end',minimum=line['start']+.001,maximum=len(source)/rate)
    windows=sorted((line['start'],line['end']) for line in plan['lines'])
    require(all(windows[i][1]<=windows[i+1][0] for i in range(len(windows)-1)),'Overlapping speech windows require explicit remixing')
    require(background.shape == source.shape, 'Background channel layout changed')
    removal_windows = []
    speech_by_id = {speech['id']: speech for speech in inventory.get('speech_segments', [])}
    for line in plan['lines']:
        removal = line.get('source_removal', {'start': line['start'], 'end': line['end']})
        require_number(removal['start'], 'Source voice removal start', minimum=0, maximum=line['end'])
        require_number(removal['end'], 'Source voice removal end', minimum=removal['start']+.001, maximum=len(source)/rate)
        if 'source_removal' in line:
            require(isinstance(removal.get('evidence'), str) and removal['evidence'].strip(),
                    'Independent source removal requires actual boundary evidence')
            speech = speech_by_id[line['id']]
            require(removal['start'] <= speech['start'] and removal['end'] >= speech['end'],
                    'Source removal must cover inventoried source speech')
        removal_windows.append((round(removal['start']*rate), min(len(source), round(removal['end']*rate))))
    removal_windows.sort()
    require(all(first[1] <= second[0] for first, second in zip(removal_windows, removal_windows[1:])),
            'Overlapping source removal windows require explicit remixing')
    signature={'plan':plan,'source_audio_sha256':file_hash(source_audio),'implementation':file_hash(__file__),
               'ffmpeg':media.command(['ffmpeg','-version']).stdout}
    digest=object_hash(signature)
    directory=run/'outputs/audio-mix'/digest[:20];directory.mkdir(parents=True,exist_ok=True)
    provenance=directory/'provenance.json'
    if provenance.exists():
        saved=read_json(provenance)
        require(saved.get('signature')==signature,'Mix checkpoint inputs changed')
        require(all(file_hash(inside(run,a['path']))==a['sha256'] for a in [saved['output'],saved['source_level_baseline'],*[r['aligned'] for r in saved['lines']]]),'Mix checkpoint output changed')
        return {**saved['output'],'reused':True,'state':'needs_review',
                'background_continuity_review_required':saved['background_continuity_review_required'],
                'source_level_baseline':saved['source_level_baseline']}
    source_levels = {}
    for line in plan['lines']:
        speech = speech_by_id[line['id']]
        measured_source_window = 'start' in speech and 'end' in speech
        window = speech if measured_source_window else line.get('source_removal', line)
        source_start = round(window['start'] * rate)
        source_end = min(len(source), round(window['end'] * rate))
        original_window = source[source_start:source_end]
        original_stem = background[source_start:source_end]
        source_levels[line['id']] = {
            'start': source_start/rate, 'end': source_end/rate,
            'window_origin': 'source_inventory' if measured_source_window else 'legacy_plan_window_estimate',
            'original_mix': signal_levels(original_window),
            'background_stem': signal_levels(original_stem),
            'source_vocal_residual_estimate': signal_levels(original_window-original_stem)}
    bed, blend, transitions = background_mix(source, background, rate, removal_windows)
    continuity = background_continuity(source, bed, rate, removal_windows)
    baseline = {'source_sha256': plan['source_sha256'], 'source_audio_sha256': file_hash(source_audio),
                'background': plan['background'], 'original_mix': signal_levels(source),
                'separated_background': signal_levels(background), 'speech_windows': source_levels,
                'background_continuity': continuity,
                'limitation': 'Mix minus selected stem is a residual estimate, unreliable if the stem is incomplete or reconstructed.'}
    baseline_path = directory/'level-baseline.json'
    write_json(baseline_path, baseline)
    result=bed.copy();records=[];affected=blend > 0
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
        profile = line.get('level_profile')
        audio_filter = f'atempo={speed}' if profile is not None else f'atempo={speed},loudnorm=I=-16:LRA=7:TP=-2'
        media.ffmpeg(['-i',trimmed,'-af',audio_filter,
                      '-ar',rate,'-ac','2','-c:a','pcm_s16le',ready])
        data,_=pcm(ready)
        voice_gain_db=require_number(line.get('voice_gain_db',0),'Narration voice gain',minimum=-6,maximum=6)
        data*=10**(voice_gain_db/20)
        start=round(line['start']*rate);end=min(len(source),round(line['end']*rate))
        speech=np.zeros_like(source[start:end]);offset=round(voice_offset*rate)
        require(offset+len(data)<=len(speech),'Aligned voice would be truncated')
        speech[offset:offset+len(data)]=data
        mixed, envelope, balance = balance_voice(bed[start:end], speech, rate, profile)
        result[start:end]=mixed;affected[start:end]=True
        active_voice = np.max(np.abs(speech), axis=1) > .002
        minimum_gain = float(np.min(envelope[active_voice])) if np.any(active_voice) else 1.
        records.append({'id':line['id'],'start':line['start'],'end':line['end'],'target_text':line['target_text'],
                        'voice':line['voice'],'trim_seconds':[first/vrate,last/vrate],'atempo':speed,
                        'aligned':{'path':ready.relative_to(run).as_posix(),'sha256':file_hash(ready)},'voice_gain_db':voice_gain_db,'voice_offset_seconds':voice_offset,
                        'window_peak_gain':1.,'voice_minimum_limiter_gain':minimum_gain,
                        'voice_limited_seconds':float(np.count_nonzero(active_voice & (envelope < .999))/rate),
                        'source_level_baseline':source_levels[line['id']],'speech_balance':balance})
    output=directory/'translated-mix.wav';save(output,result,rate)
    unchanged=np.max(np.abs(result[~affected]-source[~affected])) if np.any(~affected) else 0
    write_json(directory/'provenance.json',{'source_sha256':plan['source_sha256'],'source_audio_sha256':file_hash(source_audio),'signature':signature,
        'source_audio':{'path':source_audio.relative_to(run).as_posix(),'sha256':file_hash(source_audio)},
        'background':plan['background'],'lines':records,'original_mix_outside_windows_max_float_difference':float(unchanged),
        'source_level_baseline':{'path':baseline_path.relative_to(run).as_posix(),'sha256':file_hash(baseline_path)},
        'background_continuity_review_required':continuity['review_required'],
        'speech_balance_review_required':any(record['speech_balance']['review_required'] for record in records),
        'outside_windows_seconds':float(np.count_nonzero(~affected)/rate),'music_time_scale':1,
        'source_removal_windows_samples':removal_windows,'background_transitions':transitions,
        'background_gain_from_voice_limiter':1.,
        'method':'Source mix outside source removal windows and gap transitions; UVR background inside. Gap-bounded cosine transitions never restore source speech inside removal windows. Voice-only headroom limiting preserves background gain and timing.',
        'output':{'path':output.relative_to(run).as_posix(),'sha256':file_hash(output)},
        'limitations':['UVR separation can attenuate musical vocal samples underneath narration.','No visual lip synchronization applied; source people are retained.']})
    return {'path':output.relative_to(run).as_posix(),'sha256':file_hash(output),'reused':False,'state':'needs_review',
            'background_continuity_review_required':continuity['review_required'],
            'source_level_baseline':{'path':baseline_path.relative_to(run).as_posix(),'sha256':file_hash(baseline_path)}}
