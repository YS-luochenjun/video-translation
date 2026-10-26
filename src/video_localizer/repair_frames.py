"""Reuse exact decoded repair frames from completed lossless masters, not reviews."""
import hashlib

from .common import file_hash, inside, read_json, require


def pixel_hash(frame):
    return hashlib.sha256(frame.tobytes()).hexdigest()


class PreviousFrames:
    def __init__(self, run, keys, cv2):
        self.run, self.keys, self.cv2 = run, keys, cv2
        self.record, self.cap, self.position = None, None, -1
        self.rows, self.hits = {}, 0
        best = 0
        for path in sorted((run/'outputs/local-repair').glob('*/preparation.json')):
            saved = read_json(path)
            index = saved.get('frame_index')
            output = saved.get('output')
            if saved.get('probe_only') or not index or not output:
                continue
            video = inside(run, output['path'])
            # Explicitly pruned/expired media is a miss, never a restored approval.
            if not video.is_file():
                continue
            index_path = inside(run, index['path'])
            require(file_hash(index_path) == index['sha256'], 'Repair frame index changed')
            rows = read_json(index_path)
            matches = {r['frame']: r for r in rows if r['frame'] in keys and keys[r['frame']] == r['key']}
            if len(matches) > best:
                self.record, self.rows, best = saved, matches, len(matches)

    def get(self, n):
        row = self.rows.get(n)
        if row is None:
            return None
        if self.cap is None:
            asset = self.record['output']
            path = inside(self.run, asset['path'])
            require(file_hash(path) == asset['sha256'], 'Previous repair master changed')
            self.cap = self.cv2.VideoCapture(str(path))
        require(n > self.position, 'Repair frames must be read in order')
        while self.position < n - 1:
            require(self.cap.grab(), 'Previous repair frame missing')
            self.position += 1
        ok, frame = self.cap.read()
        self.position += 1
        require(ok and pixel_hash(frame) == row['pixels_sha256'], 'Previous repair pixels changed')
        self.hits += 1
        return frame

    def close(self):
        if self.cap is not None:
            self.cap.release()
        if self.record and self.hits:
            asset = self.record['output']
            require(file_hash(inside(self.run, asset['path'])) == asset['sha256'],
                    'Previous repair master changed during reuse')
