"""Submission-time cost guard, independent of an old plan's model choice."""
import re
from .common import ROOT, read_json, require


def check_new_video_task(model, estimated_credits, root=None):
    from .model_routing import require_current
    path=(root or ROOT)/'config/model-policy.json'
    if not path.exists():
        require_current('video', model, root)
        return
    policy=read_json(path)
    match=re.search(r'(?:^|/)seedance-(\d+)',model)
    minimum=policy.get('block_seedance_major_at_least')
    require(not (match and minimum is not None and int(match.group(1))>=minimum),
            'New Seedance 2.0+ submissions blocked; new video work uses configured Wan editing')
    require_current('video', model, root)
    cap=policy.get('max_new_video_task_estimated_credits')
    require(cap is None or estimated_credits<=cap,
            f'Video estimate exceeds the current {cap}-credit short-trial guard; reduce the scoped duration or leave pending')
