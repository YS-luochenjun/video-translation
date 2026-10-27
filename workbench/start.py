"""Portable launcher. --background survives terminal closure; never kills ports."""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8768)
    parser.add_argument('--background',action='store_true')
    parser.add_argument('--open',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    command=[sys.executable,'-B',str(root/'workbench/server.py'),'--port',str(args.port),'--workspace',str(root)]
    if not args.background:
        return subprocess.call(command,cwd=root)
    folder=root/'work/workbench'
    folder.mkdir(parents=True,exist_ok=True)
    url=f'http://127.0.0.1:{args.port}'
    with (folder/f'server-{args.port}.out.log').open('ab') as out, (folder/f'server-{args.port}.err.log').open('ab') as err:
        options={'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.DETACHED_PROCESS} if sys.platform=='win32' else {'start_new_session':True}
        process=subprocess.Popen(command,cwd=root,stdin=subprocess.DEVNULL,stdout=out,stderr=err,**options)
    for _ in range(100):
        if process.poll() is not None:
            raise SystemExit(f'Workbench did not start; see {folder}. Existing services were not stopped.')
        try:
            with urllib.request.urlopen(url+'/api/ledger',timeout=2) as response:
                result=json.load(response)
            if result.get('collector',{}).get('pid')!=process.pid:
                time.sleep(.1)
                continue
            break
        except (OSError,ValueError):
            time.sleep(.1)
    else:
        raise SystemExit('Process started but readiness was not confirmed; inspect the log before relaunching.')
    record={'pid':process.pid,'url':url,'python':sys.executable}
    (folder/f'server-{args.port}.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False))
    if args.open:webbrowser.open(url)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
