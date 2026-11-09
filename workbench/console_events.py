"""Native macOS filesystem events. No model, desktop daemon, or media jobs."""
import ctypes as C
import sys
import threading
import time
from pathlib import Path


class MacEvents:
    def __init__(self, roots, changed):
        self.roots, self.changed = roots, changed
        self.ready = threading.Event()
        self.loop = None
        self.error = None
        self.thread = threading.Thread(target=self.run, daemon=True, name='console-filesystem-events')

    def start(self):
        self.thread.start()
        self.ready.wait(3)
        if self.error: raise RuntimeError(self.error)
        if not self.loop: raise RuntimeError('本机文件监听未就绪')

    def run(self):
        cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        fs = C.CDLL('/System/Library/Frameworks/CoreServices.framework/CoreServices')
        pointer, integer = C.c_void_p, C.c_long
        cf.CFStringCreateWithCString.argtypes = [pointer, C.c_char_p, C.c_uint32]
        cf.CFStringCreateWithCString.restype = pointer
        cf.CFArrayCreate.argtypes = [pointer, C.POINTER(pointer), integer, pointer]
        cf.CFArrayCreate.restype = pointer
        cf.CFRunLoopGetCurrent.restype = pointer
        cf.CFRunLoopStop.argtypes = [pointer]
        cf.CFRelease.argtypes = [pointer]
        callback_type = C.CFUNCTYPE(None, pointer, pointer, C.c_size_t, pointer,
                                   C.POINTER(C.c_uint32), C.POINTER(C.c_uint64))

        def receive(stream, context, count, paths, flags, ids):
            try:
                values = C.cast(paths, C.POINTER(C.c_char_p))
                self.changed([values[i].decode('utf-8', 'replace') for i in range(count)])
            except Exception:
                # Callback errors must never escape into CoreServices.
                pass

        callback = callback_type(receive)
        fs.FSEventStreamCreate.argtypes = [pointer, callback_type, pointer, pointer, C.c_uint64, C.c_double, C.c_uint32]
        fs.FSEventStreamCreate.restype = pointer
        fs.FSEventStreamScheduleWithRunLoop.argtypes = [pointer, pointer, pointer]
        fs.FSEventStreamStart.argtypes = [pointer]
        fs.FSEventStreamStart.restype = C.c_bool
        for method in ('Stop', 'Invalidate', 'Release'):
            getattr(fs, 'FSEventStream'+method).argtypes = [pointer]
        strings, array, stream = [], None, None
        try:
            strings = [cf.CFStringCreateWithCString(None, str(p).encode(), 0x08000100) for p in self.roots]
            array = cf.CFArrayCreate(None, (pointer*len(strings))(*strings), len(strings), None)
            stream = fs.FSEventStreamCreate(None, callback, None, array, 0xFFFFFFFFFFFFFFFF, .4, 0x12)
            if not stream: raise RuntimeError('无法建立 FSEvents 监听')
            self.loop = cf.CFRunLoopGetCurrent()
            self.cf = cf
            mode = pointer.in_dll(cf, 'kCFRunLoopDefaultMode')
            fs.FSEventStreamScheduleWithRunLoop(stream, self.loop, mode)
            if not fs.FSEventStreamStart(stream): raise RuntimeError('无法启动 FSEvents 监听')
            self.ready.set()
            cf.CFRunLoopRun()
        except Exception as exc:
            self.error = str(exc)
            self.ready.set()
        finally:
            if stream:
                fs.FSEventStreamStop(stream)
                fs.FSEventStreamInvalidate(stream)
                fs.FSEventStreamRelease(stream)
            if array: cf.CFRelease(array)
            for value in strings: cf.CFRelease(value)

    def close(self):
        if self.loop: self.cf.CFRunLoopStop(self.loop)
        self.thread.join(timeout=3)


class EventHub:
    def __init__(self, root, home, changed=None):
        self.root, self.home = Path(root).resolve(), Path(home).resolve()
        self.changed = changed
        self.condition = threading.Condition()
        self.lifecycle = threading.Lock()
        self.revision = 0
        self.clients = 0
        self.watcher = None
        self.backend = 'disconnected'
        self.release_timer = None

    def relevant(self, path):
        p = Path(path)
        return (any(p.is_relative_to(self.root/area) for area in ('runs', 'outputs', 'state', 'knowledge'))
                or p.parent == self.home and p.name.startswith('state_5.sqlite')
                or p.is_relative_to(self.home/'automations'))

    def notify(self, paths):
        if not any(self.relevant(p) for p in paths): return
        if self.changed: self.changed()
        with self.condition:
            self.revision += 1
            self.condition.notify_all()

    def subscribe(self):
        with self.lifecycle:
            if self.release_timer:
                self.release_timer.cancel()
                self.release_timer = None
            if self.watcher is None:
                if sys.platform != 'darwin': raise RuntimeError('此平台尚未接入原生文件监听，请手动刷新；不会回退为 Agent 轮询')
                roots = [self.root/a for a in ('state', 'runs', 'outputs', 'knowledge') if (self.root/a).exists()]
                if self.home.exists(): roots.append(self.home)
                watcher = MacEvents(roots, self.notify)
                try: watcher.start()
                except Exception:
                    watcher.close()
                    raise
                self.watcher, self.backend = watcher, 'macos_fsevents'
            self.clients += 1
            return self.revision

    def unsubscribe(self):
        with self.lifecycle:
            self.clients = max(0, self.clients-1)
            if self.clients == 0 and self.watcher:
                # Preserve events between consecutive UI long-waits. This is a
                # one-shot release timer, never a recurring scan or Agent call.
                self.release_timer = threading.Timer(2, self.close_if_unused)
                self.release_timer.daemon = True
                self.release_timer.start()

    def close_if_unused(self):
        with self.lifecycle:
            if self.clients == 0:
                self._close()

    def _close(self):
        if self.release_timer:
            self.release_timer.cancel()
            self.release_timer = None
        if self.watcher:
            self.watcher.close()
            self.watcher = None
        self.backend = 'disconnected'

    def close(self):
        with self.lifecycle:
            self._close()

    def wait(self, revision, timeout=20):
        with self.condition:
            self.condition.wait_for(lambda: self.revision != revision, timeout=timeout)
            return self.revision

    def status(self):
        return {'backend': self.backend, 'clients': self.clients, 'revision': self.revision,
                'agent_polling': False, 'observed_epoch': time.time()}
