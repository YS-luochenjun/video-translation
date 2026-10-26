"""Single-writer ASR model installation with complete-file receipts."""
from pathlib import Path

from .common import CODE_ROOT, file_hash, lock, read_json, require, write_json
from .resources import preflight
from .model_routing import require_current, selected

SIZES = {'small': 600 * 1024**2}


def files(directory):
    directory = Path(directory)
    paths = [directory / name for name in ('model.bin', 'config.json', 'tokenizer.json')]
    vocabulary = sorted(directory.glob('vocabulary.*'))
    require(vocabulary and all(p.is_file() and p.stat().st_size > 0 for p in paths),
            'ASR model incomplete; resume the model download before inference')
    return paths + vocabulary + sorted(directory.glob('preprocessor_config.json'))


def verify(directory):
    assets = {p.name: file_hash(p) for p in files(directory)}
    receipt = Path(directory) / 'localizer-complete.json'
    if receipt.exists():
        require(read_json(receipt)['files'] == assets, 'ASR model changed since installation; inspect model cache')
    return assets


def ensure(size=None, download=False, root=CODE_ROOT, downloader=None):
    size = size or selected('asr', root)
    require_current('asr', size, root)
    require(size in SIZES, 'No installer for the configured ASR model')
    directory = Path(root) / '.runtime/models/asr' / size
    # Inference must work with a read-only, already installed model. Download
    # serialization is needed only for incomplete installs, not every ASR call.
    complete = all((directory / name).is_file() for name in ('model.bin', 'config.json', 'tokenizer.json')) and bool(list(directory.glob('vocabulary.*')))
    if complete:
        return directory, verify(directory)
    require(download, 'ASR model missing; use asr --download once')
    # The lock is on the actual shared model directory, even for separate workspaces.
    directory.mkdir(parents=True, exist_ok=True)
    with lock(directory / '.localizer-download.lock'):
        complete = all((directory / name).is_file() for name in ('model.bin', 'config.json', 'tokenizer.json')) and bool(list(directory.glob('vocabulary.*')))
        if not complete:
            require(download, 'ASR model missing; use asr --download once')
            preflight(root, directory, SIZES[size])
            if downloader is None:
                from huggingface_hub import snapshot_download
                downloader = snapshot_download
            downloader('Systran/faster-whisper-' + size, local_dir=str(directory), token=False,
                       allow_patterns=['model.bin', 'config.json', 'tokenizer.json', 'vocabulary.*', 'preprocessor_config.json'])
        assets = verify(directory)
        receipt = directory / 'localizer-complete.json'
        if not receipt.exists():
            write_json(receipt, {'model': size, 'files': assets,
                                'scope': 'Local complete-file integrity, not provider authenticity or ASR accuracy'})
    return directory, assets
