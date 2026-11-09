"""Source-bound Wan 3.0 reference editing; no implicit 2.7 payload conversion."""
import math

from .common import require, require_number

MODEL = 'wan/3-0-video'
RATES = {'480P': 8, '720P': 16, '1080P': 32}
DOCUMENTATION = 'https://docs.kie.ai/market/wan/3-0-video'


def estimate(source_seconds, output_seconds, resolution='720P'):
    require(resolution in RATES, 'Unsupported Wan 3.0 resolution')
    return math.ceil((source_seconds + output_seconds) * RATES[resolution])


def inputs(prompt, seconds, portrait=True, reference=False):
    duration = round(seconds)
    require(2 <= duration <= 15 and abs(seconds - duration) <= .15,
            'Wan 3.0 source-preserving edits need a planned integer 2-15s clip; re-scope, never stretch')
    result = {'prompt': 'Edit Video1, preserving its full motion, timing and framing. ' + prompt,
              'reference_video_urls': ['ASSET:video'], 'resolution': '720P',
              'aspect_ratio': '9:16' if portrait else '16:9', 'duration': duration, 'audio': False}
    if reference:
        result['reference_image_urls'] = ['ASSET:image']
        result['prompt'] += '\nImage1 is same-shot restoration guidance only; preserve Video1 motion.'
    return result


def validate(data):
    value = data['payload']['input']
    require(set(value) <= {'prompt', 'reference_video_urls', 'reference_image_urls',
                           'resolution', 'aspect_ratio', 'duration', 'audio', 'seed'},
            'Unsupported Wan 3.0 editing field; 2.7 video_url/audio_setting/prompt_extend are not compatible')
    require(value.get('reference_video_urls') == ['ASSET:video'],
            'Wan 3.0 editing requires one hash-bound source reference video')
    require(value.get('audio') is False,
            'Wan 3.0 visual edits must be silent; preserve/mix original audio through the separate audio pipeline')
    require(value.get('resolution') in RATES and value.get('aspect_ratio') in
            ('adaptive', '16:9', '4:3', '1:1', '3:4', '9:16'), 'Invalid Wan 3.0 resolution/aspect ratio')
    duration = value.get('duration')
    require(isinstance(duration, int) and not isinstance(duration, bool) and 2 <= duration <= 30,
            'Wan 3.0 needs fixed integer output duration; automatic duration is not budget-bounded')
    start, end = data['source_interval']
    seconds = end - start
    require(1 <= seconds <= 15 and seconds + duration <= 30.001,
            'Wan 3.0 reference must be 1-15s, input plus output at most 30s')
    require(abs(seconds - duration) <= .15,
            'Wan 3.0 edit duration must match source timing; re-scope instead of stretching')
    require_number(data['estimated_credits'], 'Wan 3.0 reservation',
                   minimum=estimate(seconds, duration, value['resolution']))
    if 'reference_image_urls' in value:
        require(value['reference_image_urls'] == ['ASSET:image'] and 'image' in data['assets'],
                'Wan 3.0 image reference needs one bound image asset')
    if 'seed' in value:
        require(isinstance(value['seed'], int) and not isinstance(value['seed'], bool)
                and 0 <= value['seed'] <= 2147483647, 'Invalid Wan 3.0 seed')


def validate_media(path, meta):
    require(240 <= min(meta['width'], meta['height']) and max(meta['width'], meta['height']) <= 4096
            and max(meta['width'], meta['height']) / min(meta['width'], meta['height']) <= 8
            and path.suffix.lower() in ('.mp4', '.mov') and path.stat().st_size <= 100000000,
            'Wan 3.0 video must be MP4/MOV, 240-4096px, aspect <=8:1 and <=100MB')


def validate_image(path):
    from PIL import Image
    with Image.open(path) as im:
        require(240 <= min(im.size) and max(im.size) <= 8000
                and max(im.size) / min(im.size) <= 8 and path.stat().st_size <= 20000000,
                'Wan 3.0 reference image dimensions/size unsupported')
        require(not ('A' in im.getbands() and im.getchannel('A').getextrema()[0] < 255)
                and 'transparency' not in im.info, 'Wan 3.0 reference image cannot contain transparency')
