"""Resolve the video explicitly attached to a public Pinterest Pin."""

import json
import re
from hashlib import sha256
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from .common import WorkflowError, require
from .kie import NoRedirect, download


PIN_HOSTS = {'pinterest.com', 'www.pinterest.com'}
PAGE_LIMIT = 4 * 1024 * 1024


def pin_id(url):
    parsed = urlsplit(url)
    match = re.fullmatch(r'/pin/(\d{1,30})/?', parsed.path)
    if parsed.scheme == 'https' and parsed.netloc.lower() in PIN_HOSTS and match:
        return match[1]
    return None


def _is_video_url(parsed):
    return (parsed.scheme == 'https' and parsed.netloc == 'v1.pinimg.com'
            and parsed.path.startswith('/videos/') and parsed.path.endswith('.mp4'))


def video_metadata(page, pin):
    candidates = {}
    for fragment in re.split(r'"__typename"\s*:\s*"PinResponse"\s*,\s*"data"\s*:\s*', page)[1:]:
        try:
            item, _ = json.JSONDecoder().raw_decode(fragment)
            if item['entityId'] != pin:
                continue
            video = item['videos']['videoList']['v720P']
            url = urlsplit(video['url'])
            if _is_video_url(url):
                metadata = tuple(video[key] for key in ('duration', 'width', 'height'))
                if all(type(value) is int and value > 0 for value in metadata):
                    candidates[(video['url'], *metadata)] = {
                        key: video[key] for key in ('url', 'duration', 'width', 'height')}
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    require(len(candidates) == 1, 'Pinterest Pin did not expose one verifiable MP4 for the exact Pin ID')
    return next(iter(candidates.values()))


def resolve(url):
    pin = pin_id(url)
    require(pin, 'Expected a public Pinterest Pin URL')
    # The fixed first-party hostname is authenticated by HTTPS. Redirects are
    # disabled so this route also works with a host using synthetic proxy DNS.
    page_url = f'https://www.pinterest.com/pin/{pin}/'
    try:
        opener = build_opener(NoRedirect)
        with opener.open(Request(page_url), timeout=20) as response:
            raw = response.read(PAGE_LIMIT + 1)
    except (OSError, URLError) as exc:
        raise WorkflowError(f'Pinterest Pin page unavailable: {exc}') from exc
    require(len(raw) <= PAGE_LIMIT, 'Pinterest Pin page exceeds the source metadata limit')
    video = video_metadata(raw.decode('utf-8', errors='replace'), pin)
    return {
        'pinterest_pin_id': pin, 'page_url': page_url, 'page_sha256': sha256(raw).hexdigest(),
        'video_url': video['url'], 'duration': video['duration'] / 1000,
        'width': video['width'], 'height': video['height'],
    }


def download_video(url, destination):
    require(_is_video_url(urlsplit(url)), 'Invalid Pinterest video CDN URL')
    download(url, destination, fixed_https_origin='v1.pinimg.com')
