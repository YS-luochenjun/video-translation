"""Generate a read-only knowledge map. No cleanup, paid inference or platform writes."""
import argparse
from pathlib import Path
import sys
import json

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from video_localizer.common import ROOT,write_json
from video_localizer.knowledge_overview import build,markdown


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default=str(ROOT));parser.add_argument('--output',default='work/project-health/knowledge.json')
    args=parser.parse_args();root=Path(args.root).resolve();dest=root/args.output
    report=build(root);write_json(dest,report);dest.with_suffix('.md').write_text(markdown(report),encoding='utf-8')
    print(json.dumps({'counts':report['counts'],'report':str(dest),'markdown':str(dest.with_suffix('.md'))},ensure_ascii=False,indent=2))
