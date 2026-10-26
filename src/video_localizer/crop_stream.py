"""Bounded native RGBA crop decoding; no temporary per-frame image files."""
import subprocess

from .common import require


class CropStream:
    def __init__(self, path, numbers, region, selection):
        self.numbers = sorted(set(numbers))
        self.position = 0
        self.last = None
        self.index = None
        x,y,self.width,self.height = region
        self.process = subprocess.Popen(['ffmpeg','-v','error','-i',str(path),'-vf',
            f"select='{selection(self.numbers)}',crop={self.width}:{self.height}:{x}:{y}:exact=1",
            '-fps_mode','passthrough','-an','-pix_fmt','rgba','-f','rawvideo','-'],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE)

    def __enter__(self):
        return self

    def __getitem__(self, number):
        from PIL import Image
        if number == self.index:
            return self.last
        require(self.position < len(self.numbers) and self.numbers[self.position] == number,
                'Native crop stream requires increasing actual frame indices')
        size = self.width*self.height*4
        chunks,remaining = [],size
        while remaining:
            data = self.process.stdout.read(remaining)
            require(data, 'Native crop stream ended before required frames')
            chunks.append(data);remaining -= len(data)
        self.last = Image.frombytes('RGBA',(self.width,self.height),b''.join(chunks))
        self.index = number;self.position += 1
        return self.last

    def __exit__(self, kind, value, traceback):
        if self.process.poll() is not None and self.process.stdout.closed:
            return
        complete = self.position == len(self.numbers) and kind is None
        if not complete and self.process.poll() is None:
            self.process.kill()
        self.process.stdout.close()
        error = self.process.stderr.read().decode(errors='replace')
        self.process.stderr.close()
        status = self.process.wait()
        if complete:
            require(status == 0, 'Native crop decoding failed: '+error[-400:])
