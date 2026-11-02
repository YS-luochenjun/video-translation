"""Link regressions use only synthetic trees; never real production or system tasks."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_localizer import project_storage
from video_localizer.common import CODE_ROOT, WorkflowError, read_json, write_json


class StorageLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.now = datetime.now(timezone.utc)
        for name in ('delivery-policy.json', 'storage-policy.json', 'maintenance.json'):
            target = self.root / 'config' / name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(CODE_ROOT / 'config' / name, target)
        write_json(self.root / 'config/storage-authorization.local.json', {
            'workspace': str(self.root), 'automatic_cleanup': True, 'reset_existing_data': True})
        write_json(self.root / 'knowledge/index.json', {'entries': []})
        write_json(self.root / 'knowledge/cases/index.json', {'entries': []})

    def link(self, path, target, junction=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        if junction:
            if os.name != 'nt':
                self.skipTest('Windows junction fixture')
            outcome = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(path), str(target)],
                                     capture_output=True)
            self.assertEqual(outcome.returncode, 0, outcome.stderr.decode(errors='replace'))
        else:
            try:
                path.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                if getattr(exc, 'winerror', None) == 1314:
                    self.skipTest('Windows symlink privilege unavailable; no elevation requested')
                raise
        # Remove only this synthetic directory entry before TemporaryDirectory.
        self.addCleanup(lambda: os.rmdir(path) if path.is_dir() and not path.is_symlink()
                        else path.unlink(missing_ok=True))

    def entry(self, package, days=20, requirement='expired'):
        return {'package': package, 'source_sha256': 'a' * 64,
                'video_sha256': 'b' * 64, 'target_language': 'ja',
                'requirement_name': requirement, 'task_name': 'source-1',
                'archived_at': (self.now - timedelta(days=days)).isoformat()}

    def reject_alias(self, target, junction=False):
        alias = self.root / 'outputs/.packages/expired'
        self.link(alias, target, junction)
        write_json(self.root / 'state/delivery-index.json', {
            'entries': [self.entry(alias.relative_to(self.root).as_posix())]})
        with self.assertRaises(WorkflowError):
            project_storage.preview(self.root, now=self.now)
        self.assertTrue((target / 'manifest.json').is_file())
        self.assertEqual((target / 'keep.mp4').read_bytes(), b'synthetic retained bytes')

    def target(self, relative):
        target = self.root / relative
        write_json(target / 'manifest.json', {'fixture': True})
        (target / 'keep.mp4').write_bytes(b'synthetic retained bytes')
        return target

    def test_symlink_package_cannot_resolve_to_live_run(self):
        target = self.target('runs/live')
        write_json(target / 'run.json', {'state': 'created'})
        self.reject_alias(target)

    def test_junction_package_cannot_resolve_to_live_run(self):
        target = self.target('runs/live')
        write_json(target / 'run.json', {'state': 'created'})
        self.reject_alias(target, junction=True)

    def test_symlink_package_cannot_resolve_to_retained_package(self):
        self.reject_alias(self.target('outputs/.packages/retained'))

    def test_junction_package_cannot_resolve_to_retained_package(self):
        self.reject_alias(self.target('outputs/.packages/retained'), junction=True)

    def reset_child_link(self, junction=False):
        # Outside all four production areas, but still inside this disposable fixture.
        target = self.root / 'independent'
        write_json(target / 'external-proof.json', {'sentinel': 'must not be copied'})
        (target / 'keep.mp4').write_bytes(b'external synthetic media')
        write_json(self.root / 'runs/closed/run.json', {'fixture': 'owned record'})
        child = self.root / 'runs/closed/linked-child'
        self.link(child, target, junction)
        plan = project_storage.preview(self.root, reset=True, now=self.now)
        tree = project_storage._tree(self.root / 'runs')
        self.assertFalse(any('external-proof.json' in row['path'] for row in tree))
        record = next(row for row in tree if row['path'].endswith('linked-child'))
        self.assertFalse(record['directory'], 'Link must not be classified as traversable directory')
        folder = self.root / 'state/synthetic-preserved'
        project_storage._preserve_records(self.root, plan, folder)
        preserved = read_json(folder / 'manifest.json')['files']
        self.assertFalse(any('external-proof.json' in row['path'] for row in preserved))
        self.assertTrue(any(row['path'] == 'runs/closed/run.json' for row in preserved))
        project_storage.execute(self.root, plan['fingerprint'], reset=True, now=self.now)
        self.assertEqual(read_json(target / 'external-proof.json'), {'sentinel': 'must not be copied'})
        self.assertEqual((target / 'keep.mp4').read_bytes(), b'external synthetic media')

    def test_reset_does_not_follow_child_symlink(self):
        self.reset_child_link()

    def test_reset_does_not_follow_child_junction(self):
        self.reset_child_link(junction=True)


if __name__ == '__main__':
    unittest.main()
