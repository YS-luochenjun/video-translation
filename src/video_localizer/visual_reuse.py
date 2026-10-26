"""Reuse verified comparison tiles before decoding, never review decisions.

Indexes reference existing lossless evidence pages; they do not duplicate media.
Missing pages are cache misses. Changed pages fail closed and remain inspectable.
"""
from collections import OrderedDict
import hashlib
from pathlib import Path

from . import media
from .common import (file_hash, inside, lock, object_hash, operation_hash, read_json,
                     require, write_json)


def tile(image, label):
    from PIL import Image, ImageDraw
    result = Image.new('RGB', (image.width, image.height + 25), '#777777')
    result.paste(image.convert('RGB'), (0, 25), image.getchannel('A') if 'A' in image.getbands() else None)
    ImageDraw.Draw(result).text((3, 4), label, fill='white')
    return result


class EvidenceCache:
    def __init__(self, root):
        import PIL
        self.root = Path(root)
        self.directory = self.root / 'state/visual-decode-cache'
        code = Path(__file__).parent
        self.engine = {
            'version': 1, 'pillow': PIL.__version__,
            'ffmpeg': media.command(['ffmpeg', '-version']).stdout,
            'ffprobe': media.command(['ffprobe', '-version']).stdout,
            'code': {name: file_hash(code / name) for name in
                     ('visual_reuse.py', 'visual_audit.py', 'crop_stream.py', 'media.py', 'common.py')},
        }
        self.hashes, self.groups, self.pending, self.assets = {}, {}, {}, {}
        self.paths, self.images = {}, OrderedDict()
        self.image_bytes, self.max_image_bytes = 0, 32 * 1024**2
        self.stats = {'layer_frames_reused': 0, 'layer_frames_decoded': 0,
                      'clocks_reused': 0, 'clocks_decoded': 0, 'pages_reused_before_composition': 0}

    def identity(self, path, **parameters):
        digest = operation_hash(path, self.hashes)
        previous = self.assets.setdefault(Path(path), digest)
        require(previous == digest, 'Visual decode input changed during generation')
        return object_hash({'asset': digest,
                            'engine': self.engine, **parameters})

    def verify_inputs(self):
        require(all(file_hash(path) == digest for path, digest in self.assets.items()),
                'Visual decode input changed during generation')

    def _path(self, relative):
        if relative not in self.paths:
            self.paths[relative] = inside(self.root, relative)
        return self.paths[relative]

    def _read(self, path, identity):
        record = read_json(path)
        require(record.get('identity') == identity and
                record.get('sha256') == object_hash(record.get('value')),
                'Visual decode cache changed; inspect the cache record')
        return record['value']

    def _write(self, path, identity, value):
        write_json(path, {'identity': identity, 'value': value, 'sha256': object_hash(value)})

    def clock(self, path, loader):
        key = self.identity(path, kind='clock')
        target = self.directory / 'clocks' / (key + '.json')
        if target.exists():
            value = self._read(target, key)
            self.stats['clocks_reused'] += 1
        else:
            times, meta = loader()
            require(file_hash(path) == self.assets[Path(path)], 'Visual decode input changed during probing')
            value = {'times': times, 'meta': meta}
            self._write(target, key, value)
            self.stats['clocks_decoded'] += 1
        return value['times'], value['meta']

    def tiles(self, path, numbers, region, label, selection):
        numbers = sorted(set(numbers))
        key = self.identity(path, kind='tile', region=list(region), label=label)
        if key not in self.groups:
            record = self.directory / 'tiles' / (key + '.json')
            self.groups[key] = self._read(record, key) if record.exists() else {}
        entries = {**self.groups[key], **self.pending.get(key, {})}
        available = {n: entries[str(n)] for n in set(numbers) if str(n) in entries
                     and self._path(entries[str(n)]['path']).is_file()}
        return TileStream(self, key, path, numbers, region, label, selection, available)

    def restore_page(self, references, destination, store):
        entries = [crops.available.get(number) for crops, number in references]
        candidates = [entry for entry in entries if entry and entry.get('tile_hashes')]
        if not candidates:
            return None
        size = [sum(crops.size[0] for crops, _ in references), max(crops.size[1] for crops, _ in references)]
        # New asset bytes still require actual decoding. If their displayed tile
        # pixels match the prior page, no unchanged PNG layer needs decompression.
        hashes = [crops.fingerprint(number) for crops, number in references]
        for entry in candidates:
            if entry.get('page_size') != size or entry['tile_hashes'] != hashes:
                continue
            store.reuse(self._path(entry['path']), destination, entry['pixels_sha256'], entry['sha256'])
            left = 0
            for crops, number in references:
                box = [left, 0, left + crops.size[0], crops.size[1]]
                crops.remember(number, destination, box, entry['pixels_sha256'], size, hashes)
                left += crops.size[0]
            self.stats['pages_reused_before_composition'] += 1
            return entry['pixels_sha256']
        return None

    def load(self, entry, size):
        from PIL import Image
        path = self._path(entry['path'])
        require(operation_hash(path, self.hashes) == entry['sha256'],
                'Visual tile cache changed; inspect the original evidence')
        box = entry['box']
        require(len(box) == 4 and all(isinstance(n, int) for n in box) and
                0 <= box[0] < box[2] and 0 <= box[1] < box[3] and
                (box[2] - box[0], box[3] - box[1]) == size, 'Visual tile cache geometry changed')
        key = (entry['sha256'], tuple(box))
        if key in self.images:
            self.images.move_to_end(key)
            return self.images[key].copy()
        with Image.open(path) as image:
            require(image.mode == 'RGB' and box[2] <= image.width and box[3] <= image.height,
                    'Visual tile cache geometry changed')
            result = image.crop(box)
        size_bytes = result.width * result.height * 3
        if size_bytes <= self.max_image_bytes:
            while self.image_bytes + size_bytes > self.max_image_bytes:
                _, old = self.images.popitem(last=False)
                self.image_bytes -= old.width * old.height * 3
            self.images[key] = result
            self.image_bytes += size_bytes
        return result.copy()

    def commit(self):
        for key, entries in self.pending.items():
            target = self.directory / 'tiles' / (key + '.json')
            with lock(target.with_suffix('.lock')):
                current = self._read(target, key) if target.exists() else {}
                self._write(target, key, {**current, **entries})


class TileStream:
    def __init__(self, cache, key, path, numbers, region, label, selection, available):
        from .crop_stream import CropStream
        self.cache, self.key, self.label = cache, key, label
        self.available = available
        self.size = (region[2], region[3] + 25)
        self.last_number, self.last_image, self.last_hash = None, None, None
        missing = sorted(set(numbers) - available.keys())
        self.decoder = CropStream(path, missing, region, selection) if missing else None
        cache.stats['layer_frames_reused'] += len(available)
        cache.stats['layer_frames_decoded'] += len(missing)

    def __enter__(self):
        return self

    def __getitem__(self, number):
        if number != self.last_number:
            self.last_image = (self.cache.load(self.available[number], self.size) if number in self.available
                               else tile(self.decoder[number], self.label))
            self.last_number = number
            self.last_hash = None
        return self.last_image

    def fingerprint(self, number):
        if number in self.available:
            return self.available[number]['tile_sha256']
        image = self[number]
        if self.last_hash is None:
            self.last_hash = hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()
        return self.last_hash

    def remember(self, number, page, box, pixels_sha256, page_size, tile_hashes):
        self.cache.pending.setdefault(self.key, {})[str(number)] = {
            'path': page.relative_to(self.cache.root).as_posix(),
            'sha256': operation_hash(page, self.cache.hashes), 'box': box,
            'pixels_sha256': pixels_sha256, 'page_size': list(page_size),
            'tile_sha256': self.fingerprint(number), 'tile_hashes': tile_hashes}

    def __exit__(self, kind, value, traceback):
        if self.decoder:
            self.decoder.__exit__(kind, value, traceback)
