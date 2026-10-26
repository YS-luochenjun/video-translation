"""Reuse identical lossless comparison pixels, never review decisions."""
import hashlib
import os
import shutil

from .common import file_hash, inside, lock, operation_hash, read_json, require, write_json


class PageStore:
    def __init__(self, root):
        self.root = root
        self.index_path = root / 'state/visual-pages/index.json'
        self.entries = read_json(self.index_path) if self.index_path.exists() else {}
        self.added = {}
        self.hits = 0
        self.hashes = {}
        self.pixel_checks = set()
        self.stats = {'linked': 0, 'copied': 0, 'written': 0, 'copy_reasons': {}}

    def _copy(self, source, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, destination)
            self.stats['linked'] += 1
        except OSError as exc:
            shutil.copyfile(source, destination)
            self.stats['copied'] += 1
            reason = str(exc.errno)
            self.stats['copy_reasons'][reason] = self.stats['copy_reasons'].get(reason, 0) + 1

    def reuse(self, source, destination, key, digest):
        # A complete layer/region/frame identity was already matched by the
        # decode cache. Verify bytes without decompressing and recomposing PNGs.
        require(operation_hash(source, self.hashes) == digest, 'Comparison pixel cache changed')
        self._copy(source, destination)
        require(operation_hash(destination, self.hashes) == digest, 'Comparison pixel copy changed')
        self.added[key] = {'path': destination.relative_to(self.root).as_posix(), 'sha256': digest}
        self.hits += 1

    def save(self, image, destination):
        # The decoded pixels, dimensions and in-image layer labels are the key.
        # PTS/frame/asset/review bindings remain in each new manifest.
        key = hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()
        entry = self.added.get(key, self.entries.get(key))
        source = inside(self.root, entry['path']) if entry else None
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source and source.is_file():
            from PIL import Image
            require(operation_hash(source, self.hashes) == entry['sha256'], 'Comparison pixel cache changed')
            checked = (key, entry['sha256'])
            if checked not in self.pixel_checks:
                with Image.open(source) as cached:
                    require(cached.size == image.size and cached.convert('RGB').tobytes() == image.tobytes(),
                            'Comparison pixel cache mismatch')
                self.pixel_checks.add(checked)
            self._copy(source, destination)
            self.hits += 1
        else:
            image.save(destination, compress_level=3)
            self.stats['written'] += 1
        self.added[key] = {'path': destination.relative_to(self.root).as_posix(),
                           'sha256': file_hash(destination)}
        return key

    def commit(self):
        with lock(self.root / 'state/visual-pages/index.lock'):
            current = read_json(self.index_path) if self.index_path.exists() else {}
            write_json(self.index_path, {**current, **self.added})
