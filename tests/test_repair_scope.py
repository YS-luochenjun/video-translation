import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from video_localizer import model_tasks, repair_scope
from video_localizer.common import WorkflowError, file_hash, write_json


class PackedRepairScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent = self.root/'runs/parent'
        self.run = self.root/'runs/packed'
        self.parent.mkdir(parents=True)
        self.run.mkdir()
        (self.parent/'source.mp4').write_bytes(b'synthetic source geometry fixture')
        digest = file_hash(self.parent/'source.mp4')
        write_json(self.parent/'run.json',{'source':'source.mp4','source_sha256':digest})
        write_json(self.parent/'analysis/media.json',{'fps':30})
        self.inventory = {'source_sha256':digest,'text_instances':[
            {'id':'title','start':0,'end':2.4,'bbox':[50,40,980,230],
             'source_effect_bbox':[0,12,1080,275]}]}
        write_json(self.parent/'analysis/inventory.json',self.inventory)
        self.mapping = {'parent_run':'parent','parent_source_sha256':digest,
            'packed_video':{'path':'source.mp4','sha256':'a'*64},
            'mapping':[{'parent_frame_interval':[0,71],'parent_crop':[0,75,1080,160],
                        'instance_ids':['title']}]}
        self.packet = {'assets':{'video':{'sha256':'a'*64}}}
        self.save()

    def save(self):
        path = self.run/'inputs/source-derivation.json'
        write_json(path,self.mapping)
        self.packet['source_derivation'] = {'path':'inputs/source-derivation.json','sha256':file_hash(path)}

    def test_actual_failure_geometry_160px_crop_cannot_cover_230px_title(self):
        with self.assertRaisesRegex(WorkflowError,'truncates.*title'):
            repair_scope.validate_packed(self.run,self.packet)
        self.mapping['mapping'][0]['parent_crop'] = [0,0,1080,310]
        self.mapping['mapping'][0]['parent_frame_interval'] = [0,72]
        self.save()
        repair_scope.validate_packed(self.run,self.packet)

    def test_last_title_frame_cannot_fall_outside_complete_repair_mapping(self):
        self.inventory['text_instances'][0]['end'] = 2.367  # actual native frame71 still present
        write_json(self.parent/'analysis/inventory.json',self.inventory)
        self.mapping['mapping'][0]['parent_crop'] = [0,0,1080,310]
        self.save()
        with self.assertRaisesRegex(WorkflowError,'omits native.*title'):
            repair_scope.validate_packed(self.run,self.packet)
        self.mapping['mapping'][0]['parent_frame_interval'] = [0,72]
        self.save()
        repair_scope.validate_packed(self.run,self.packet)

    def test_explicit_partial_probe_does_not_claim_full_instance_coverage(self):
        self.mapping['mapping'][0]['parent_crop'] = [0,0,1080,310]
        self.mapping['mapping'][0]['parent_frame_interval'] = [10,20]
        self.mapping['mapping_scope'] = 'partial_probe'
        self.save()
        repair_scope.validate_packed(self.run,self.packet)

    def test_baked_ghost_interval_requires_its_own_real_frame_coverage(self):
        item = self.inventory['text_instances'][0]
        item['source_interval'] = [0,1]
        item['source_ghost_interval'] = [2,2.4]
        write_json(self.parent/'analysis/inventory.json',self.inventory)
        row = self.mapping['mapping'][0]
        row['parent_crop'] = [0,0,1080,310]
        row['parent_frame_interval'] = [0,30]
        self.save()
        with self.assertRaisesRegex(WorkflowError,'omits native'):
            repair_scope.validate_packed(self.run,self.packet)
        ghost = copy.deepcopy(row);ghost['parent_frame_interval'] = [60,72]
        self.mapping['mapping'].append(ghost)
        self.save()
        repair_scope.validate_packed(self.run,self.packet)

    def test_outline_and_ghost_bounds_matter_even_when_primary_bbox_fits(self):
        self.mapping['mapping'][0]['parent_crop'] = [50,40,980,230]
        self.save()
        with self.assertRaisesRegex(WorkflowError,'outline/shadow'):
            repair_scope.validate_packed(self.run,self.packet)

    def test_missing_instance_binding_or_changed_derivation_cannot_dispatch(self):
        self.mapping['mapping'][0].pop('instance_ids')
        self.save()
        with self.assertRaisesRegex(WorkflowError,'instance_ids'):
            repair_scope.validate_packed(self.run,self.packet)
        self.packet['source_derivation']['sha256'] = '0'*64
        with self.assertRaisesRegex(WorkflowError,'freeze'):
            repair_scope.validate_packed(self.run,self.packet)

    def test_scope_validation_happens_before_any_provider_call(self):
        # Real packet path, synthetic bytes: invalid geometry is rejected before
        # media decoding, account reads, uploads, reservations or model creation.
        (self.run/'source.mp4').write_bytes(b'explicit synthetic packed fixture')
        sha = file_hash(self.run/'source.mp4')
        write_json(self.run/'run.json',{'source':'source.mp4','source_sha256':sha})
        data = {**copy.deepcopy(self.packet),'source_sha256':sha,'purpose':'repair geometry regression',
                'estimated_credits':80,'source_interval':[0,5],
                'payload':{'model':'wan/2-7-videoedit','input':{'prompt':'Erase source text'}}}
        write_json(self.run/'inputs/task.json',data)
        client = Mock()
        with self.assertRaisesRegex(WorkflowError,'truncates'):
            model_tasks.submit(self.run,'inputs/task.json',client=client)
        self.assertEqual(client.mock_calls,[])
        self.assertFalse((self.run/'jobs').exists())


if __name__ == '__main__':
    unittest.main()
