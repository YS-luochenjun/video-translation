"""Install current model-policy assets and Python dependencies into this checkout."""
import argparse
import importlib.metadata
import json
import subprocess
import sys
import shutil
import re
from urllib.request import Request, urlopen
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from video_localizer import model_cache
from video_localizer.common import file_hash, inside, lock, read_json, require, write_json
from video_localizer.model_routing import policy, selected


def registered_models(root=ROOT):
    expected = selected('separation', root)
    require(expected == 'uvr-inst-hq3', 'No installer for the configured separation model')
    manifest = read_json(Path(root) / 'config/local-models.json')
    records = manifest.get('models')
    require(manifest.get('schema_version') == 1 and isinstance(records, list)
            and len(records) == 1 and isinstance(records[0], dict)
            and records[0].get('id') == expected,
            'Local model manifest must contain only the configured separation model')
    for record in records:
        require(isinstance(record.get('url'), str) and record['url'].startswith('https://'),
                'Model downloads require HTTPS')
        require(re.fullmatch(r'[a-f0-9]{64}', str(record.get('sha256', ''))), 'Model SHA256 required')
        destination = inside(root, record['path'])
        require(destination.is_relative_to(Path(root).resolve() / '.runtime/models/separation'),
                'Separation models must be installed under .runtime/models/separation/')
    return records


def installation_plan(root=ROOT):
    """Validate the whole model selection before installing packages or creating model files."""
    root = Path(root).resolve()
    models = registered_models(root)
    asr = selected('asr', root)
    require(asr in model_cache.SIZES, 'No installer for the configured ASR model')
    groups = [('core', '.venv/Lib/site-packages'), ('vision', '.runtime/deps/vision'),
              ('asr', '.runtime/deps/asr'), ('separation', '.runtime/deps/separation')]
    dependencies = []
    for group, directory in groups:
        requirements = f'bin/requirements/{group}.txt'
        pins = [line.strip().split('==') for line in (root / requirements).read_text().splitlines()
                if line.strip() and not line.lstrip().startswith('#')]
        require(all(len(pin) == 2 and all(pin) for pin in pins), 'Pinned dependency versions required')
        dependencies.append({'group': group, 'directory': directory, 'requirements': requirements, 'pins': pins})
    current = policy(root)
    return {'asr': asr, 'models': models, 'dependencies': dependencies,
            'remote_only': {key: current[key] for key in ('audio_analysis', 'tts', 'video')},
            'scope': 'Only current ASR and separation weights are installed. Codex visual work and remote APIs need no local model weights.'}


def install_model(record, root=ROOT, opener=urlopen):
    require(record in registered_models(root), 'Model is not an exact current registered asset; retired/arbitrary downloads are disabled')
    destination = inside(root, record['path'])
    require(destination.is_relative_to(Path(root).resolve() / '.runtime/models'), 'Models must be installed under project .runtime/models/')
    expected = record['sha256']
    destination.parent.mkdir(parents=True, exist_ok=True)
    with lock(destination.with_suffix('.install.lock')):
        if destination.exists():
            require(file_hash(destination) == expected, f'Installed model hash differs: {record["id"]}; preserve and inspect it')
            return
        partial = destination.with_suffix('.download')
        require(record['url'].startswith('https://'), 'Model downloads require HTTPS')
        with opener(Request(record['url'], headers={'User-Agent': 'ad-localizer-setup'}), timeout=120) as response, partial.open('wb') as output:
            shutil.copyfileobj(response, output)
        require(file_hash(partial) == expected, f'Model download hash mismatch: {record["id"]}; partial retained for diagnosis')
        partial.replace(destination)


def installed(requirements, directory):
    normalize = lambda name: name.lower().replace('_', '-').replace('.', '-')
    available = {normalize(d.metadata['Name']): d.version
                 for d in importlib.metadata.distributions(path=[str(directory)])}
    return all(available.get(normalize(name)) == version for name, version in requirements)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--uv', help='Project uv executable; required for installation')
    parser.add_argument('--plan', action='store_true', help='Print the current installation plan without downloading or installing')
    args = parser.parse_args()
    plan = installation_plan()
    if args.plan:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return
    if not args.uv:
        parser.error('--uv is required unless --plan is used')
    records = []
    for dependency in plan['dependencies']:
        group, directory = dependency['group'], ROOT / dependency['directory']
        requirements, pins = ROOT / dependency['requirements'], dependency['pins']
        if directory.exists() and not directory.resolve().is_relative_to(ROOT):
            raise RuntimeError(f'External dependency link: {directory}; materialize it before installing')
        if not installed(pins, directory):
            command = [args.uv, 'pip', 'install', '--python', sys.executable, '--link-mode', 'copy', '-r', str(requirements)]
            if group != 'core':
                command += ['--target', str(directory), '--upgrade']
            subprocess.run(command, check=True)
        require(installed(pins, directory), f'Installed dependency versions differ: {group}')
        records.append({'group': group, 'requirements': str(requirements.relative_to(ROOT)), 'verified_direct_versions': True})
    sys.path.insert(0, str(ROOT / '.runtime/deps/asr'))
    path, assets = model_cache.ensure(plan['asr'], download=True, root=ROOT)
    records.append({'asr_model': plan['asr'], 'path': str(path.relative_to(ROOT)), 'files': assets})
    for model in plan['models']:
        install_model(model)
        records.append({'model': model['id'], 'path': model['path'], 'sha256': model['sha256']})
    write_json(ROOT / '.runtime/install.json', {'python': sys.version, 'plan': plan, 'records': records})
    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
