import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import curation
from video_localizer.common import WorkflowError, file_hash, write_json


class CurationPriorityTests(unittest.TestCase):
    def test_real_private_repair_precedes_placeholder_without_changing_visibility_or_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = {'workflow': 'video-localization', 'source_sha256': 'a'*64, 'target_language': 'ja'}
            a = root/'knowledge/candidates/a.json'
            b = root/'knowledge/local/feedback/improvements/b/feedback.json'
            write_json(a, {'scope': scope, 'hypothesis': 'Needs an evidence-backed lesson'})
            write_json(b, {'scope': scope, 'hypothesis': 'Actual before/after defect observation', 'outcome': 'improved'})
            write_json(root/'knowledge/index.json', {'entries': []})
            records = [{'path': str(p.relative_to(root)), 'sha256': file_hash(p)} for p in (a, b)]
            with patch.object(curation, 'inventory', return_value=records), patch.object(curation, 'catalogs', return_value={}):
                result = curation.packet(root, {'pending': []}, {'max_records': 1, 'max_packet_bytes': 100000})
            self.assertEqual(len(result['events']), 1)
            self.assertEqual(result['events'][0]['path'], records[1]['path'])
            self.assertEqual(result['events'][0]['visibility'], 'private')
            self.assertEqual(result['events'][0]['scope'], scope)

    def test_byte_limit_defers_complete_tail_records_without_advancing_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); records=[]
            write_json(root/'knowledge/index.json',{'entries':[]})
            for number in range(3):
                path=root/f'knowledge/candidates/{number}.json'
                write_json(path,{'scope':{'workflow':'video-localization'},'hypothesis':'Actual observation '+str(number),'details':'x'*1600})
                records.append({'path':str(path.relative_to(root)),'sha256':file_hash(path)})
            state={'pending':[],'seen_record_versions':[]}
            with patch.object(curation,'inventory',return_value=records),patch.object(curation,'catalogs',return_value={}):
                packet=curation.packet(root,state,{'max_records':24,'max_packet_bytes':3000})
                self.assertEqual(len(packet['events']),1)
                self.assertEqual(packet['events'][0]['sha256'],records[0]['sha256'])
                self.assertEqual(packet['events'][0]['record']['details'],'x'*1600)
                self.assertLessEqual(len(json.dumps(packet,ensure_ascii=False).encode()),3000)
                self.assertEqual(state,{'pending':[],'seen_record_versions':[]})
                with self.assertRaisesRegex(WorkflowError,'One curation record'):
                    curation.packet(root,state,{'max_records':24,'max_packet_bytes':500})
