"""Configure optional local Remotion; installation happens only with --install."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from video_localizer.common import require,write_json
from video_localizer.typography import environment_identity


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node');parser.add_argument('--pnpm');parser.add_argument('--browser')
    parser.add_argument('--chrome-mode',choices=['headless-shell','chrome-for-testing'],default='headless-shell')
    parser.add_argument('--install',action='store_true');parser.add_argument('--configure',action='store_true')
    args=parser.parse_args()
    if args.install:
        package_manager=args.pnpm or shutil.which('pnpm');require(package_manager,'Supply pnpm executable')
        dest=ROOT/'.runtime/deps/remotion';dest.mkdir(parents=True,exist_ok=True)
        for name in ['package.json','pnpm-lock.yaml']:shutil.copyfile(ROOT/'src/remotion_renderer'/name,dest/name)
        subprocess.run([package_manager,'install','--dir',str(dest),'--frozen-lockfile','--ignore-scripts',
                        '--store-dir',str(ROOT/'work/cache/pnpm-remotion')],check=True)
    if args.configure:
        node=args.node or shutil.which('node');require(node and Path(node).is_file(),'Supply Node executable')
        require(args.browser and Path(args.browser).is_file(),'Supply an installed browser or local launcher')
        write_json(ROOT/'config/remotion.local.json',{'node':str(Path(node).resolve()),
                   'browserExecutable':str(Path(args.browser).resolve()),'chromeMode':args.chrome_mode})
    print(json.dumps(environment_identity(ROOT),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
