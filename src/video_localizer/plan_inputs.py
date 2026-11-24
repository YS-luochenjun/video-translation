"""Keep complete plan inputs while sharing byte-identical frozen copies."""
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from .common import file_hash, operation_hash, require


def freeze(run, plan_id, name, source):
    plans = run / 'plans'
    destination = plans / plan_id / 'inputs' / name
    digest = file_hash(source)
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        resolved_plans = plans.resolve()
        verified = {}
        for frozen in sorted(plans.glob(f'*/inputs/{name}')):
            if (frozen.is_file() and not frozen.is_symlink()
                    and frozen.resolve().is_relative_to(resolved_plans)
                    and not os.path.samefile(frozen, source)
                    and operation_hash(frozen, verified) == digest):
                try:
                    os.link(frozen, destination)
                except OSError:
                    pass
                break
        if not destination.exists():
            with TemporaryDirectory(dir=destination.parent) as staging:
                temporary = Path(staging) / name
                shutil.copyfile(source, temporary)
                require(file_hash(temporary) == digest, 'Plan input changed during copy')
                temporary.replace(destination)
    require(file_hash(destination) == digest, 'Frozen plan input changed')
