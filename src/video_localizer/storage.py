"""Read-only inventory: logical copies are not equivalent to reclaimable disk space."""
from collections import defaultdict
import os
from pathlib import Path
import stat

from .common import ROOT, file_hash


AREAS = {
    "runs": "Mutable task workspace, source copy, jobs, reviews and task outputs",
    "outputs": "Independent delivery/reuse bundles; survives run deletion",
    "media": "Exact-source, language-neutral analysis snapshots; survives run deletion",
    "state": "Preservation receipts, recovery inputs and deletion records",
    "knowledge": "Permanent methods, independent evidence and private candidate learning",
    "work": "Disposable scratch, draft inputs and rebuildable caches; no installed runtime assets",
    ".runtime": "Installed project tools, dependencies and model weights; not scratch",
    ".archive": "Local cold history; not consulted by ordinary task retrieval",
}


def report(root=None, duplicates=False):
    root = Path(root or ROOT).resolve()
    areas, by_size, skipped, unavailable = {}, defaultdict(list), [], []
    for name, purpose in AREAS.items():
        sizes = []
        children = defaultdict(lambda: {'files': 0, 'logical_bytes': 0})
        directory = root / name
        if directory.resolve() != directory:
            skipped.append(name)
        elif directory.exists():
            def scan_error(error):
                unavailable.append(str(error.filename))

            for parent, folders, names in os.walk(directory, followlinks=False, onerror=scan_error):
                # Do not traverse junctions, including those pointing inside the root.
                for folder in list(folders):
                    child = Path(parent) / folder
                    try:
                        linked = child.is_symlink() or getattr(child, "is_junction", lambda: False)()
                        if linked or child.resolve() != child:
                            folders.remove(folder)
                            skipped.append(child.relative_to(root).as_posix())
                    except OSError:
                        folders.remove(folder)
                        unavailable.append(child.relative_to(root).as_posix())
                for filename in names:
                    path = Path(parent) / filename
                    relative = path.relative_to(root).as_posix()
                    try:
                        if path.is_symlink() or path.resolve() != path:
                            skipped.append(relative)
                            continue
                        info = path.stat()
                        if not stat.S_ISREG(info.st_mode):
                            continue
                        sizes.append(info.st_size)
                        parts = path.relative_to(directory).parts
                        child = parts[0] if len(parts) > 1 else '(root files)'
                        children[child]['files'] += 1
                        children[child]['logical_bytes'] += info.st_size
                        if duplicates:
                            by_size[info.st_size].append(path)
                    except OSError:
                        # Work/test/runtime files may disappear during a read-only scan.
                        unavailable.append(relative)
        areas[name] = {"purpose": purpose, "files": len(sizes), "logical_bytes": sum(sizes),
                       "largest_children": [dict(path=f'{name}/{child}', **totals)
                           for child, totals in sorted(children.items(), key=lambda item: (-item[1]['logical_bytes'], item[0]))[:15]]}
        if name == 'work':
            runtime, other = [], []
            for child, totals in sorted(children.items()):
                protected = child.endswith(('-deps', '-models')) or child in ('tools', 'fonts', 'ffmpeg', 'python', 'uv')
                (runtime if protected else other).append(dict(path=f'work/{child}', **totals))
            areas[name]['retention_groups'] = {
                'runtime_dependencies': {'items': runtime, 'logical_bytes': sum(x['logical_bytes'] for x in runtime),
                                         'action': 'Keep installed tools/models; separate from disposable job intermediates.'},
                'scratch_and_unclassified': {'items': other, 'logical_bytes': sum(x['logical_bytes'] for x in other),
                                             'action': 'Inspect references and purpose before considering cleanup; not a deletion list.'},
                'basis': 'Directory-name hints only; no age-based deletion or dependency-completeness claim.'}
    groups = []
    if duplicates:
        for size, paths in by_size.items():
            if len(paths) < 2 or not size:
                continue
            by_hash = defaultdict(list)
            for path in paths:
                try:
                    by_hash[file_hash(path)].append(path.relative_to(root).as_posix())
                except OSError:
                    unavailable.append(path.relative_to(root).as_posix())
            for digest, matches in by_hash.items():
                if len(matches) > 1:
                    groups.append({"sha256": digest, "bytes_per_copy": size, "paths": sorted(matches),
                                   "extra_logical_bytes": size * (len(matches)-1)})
        groups.sort(key=lambda group: (-group["extra_logical_bytes"], group["sha256"]))
    return {"areas": areas, "skipped_links": skipped, "skipped_unavailable": unavailable,
            "duplicates_scanned": duplicates,
            "duplicate_groups": len(groups),
            "extra_logical_bytes": sum(group["extra_logical_bytes"] for group in groups),
            "largest_duplicates": groups[:20],
            "scope": "Read-only, logical file sizes; hardlinks and independently required evidence mean duplicates are not a safe deletion list"}
