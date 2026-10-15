import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gacha_agent', ROOT / 'agent/gacha.py')
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class GachaTests(unittest.TestCase):
    def test_duplicate_pulls_and_repeated_collection(self):
        rows = [('2026-10-15 10:00:00', '卡池', '角色')] * 3
        keys = [agent._row_sig(r) for r in rows]
        session = agent._RecordSession(pathlib.Path('.'), 'test', {keys[0]: 2})
        collector = agent.GachaRecordPage()
        self.assertEqual(1, len(collector._scan_fresh(session, rows, keys, ['普'] * 3)))
        session = agent._RecordSession(pathlib.Path('.'), 'test', {keys[0]: 3})
        self.assertEqual([], collector._scan_fresh(session, rows, keys, ['普'] * 3))

    def test_ocr_groups_rows_and_excludes_badges(self):
        def item(text, x, y, score=1):
            return SimpleNamespace(text=text, box=[x, y, 30, 15], score=score)
        results = [item('角色', 930, 100), item('2026-10-15', 440, 100),
                   item('卡池', 700, 100), item('普', 870, 100), item('噪音', 500, 150, .1)]
        ctx = SimpleNamespace(run_recognition_direct=lambda *args: SimpleNamespace(all_results=results))
        rows, boxes = agent._ocr_rows(ctx, np.zeros((720, 1280, 3), dtype=np.uint8), [0, 0, 1280, 720], .5, 14, [856, 908])
        self.assertEqual([('2026-10-15', '卡池', '角色')], rows)
        self.assertEqual(1, len(boxes))

    def test_data_root_export_and_restart(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, MBCC_DATA_DIR=temp):
            agent._sessions.clear()
            session = agent._get_session(agent.DEFAULT_ARCHIVE)
            cells = ['2026-10-1510:00:00', '测试池', '测试角色']
            record = dict(index=1, key=agent._row_sig(cells), type='活动', rarity='狂', cells=cells)
            session.file_for('活动').write_text(json.dumps(record, ensure_ascii=False)+'\n', encoding='utf-8')
            self.assertTrue(agent.GachaRecordExport().run(None, SimpleNamespace(custom_action_param='{}')))
            self.assertTrue((pathlib.Path(temp) / 'record/抽卡记录.xlsx').is_file())
            self.assertTrue((pathlib.Path(temp) / 'record/抽卡记录.md').is_file())
            self.assertEqual(1, agent._get_session(agent.DEFAULT_ARCHIVE).store_counts[record['key']])
            agent.GachaRecordBeginRun().run(None, SimpleNamespace(custom_action_param='{}'))
            self.assertEqual({}, agent._sessions)
            self.assertTrue(session.file_for('活动').exists())

    def test_numpy_page_upscale(self):
        def recognize(kind, params, image):
            self.assertEqual((144, 260, 3), image.shape)
            return SimpleNamespace(all_results=[SimpleNamespace(text='12', score=.99)])
        ctx = SimpleNamespace(run_recognition_direct=recognize)
        with patch.object(agent, 'cv2', None):
            self.assertEqual(12, agent._read_page_number(ctx, np.zeros((720, 1280, 3), dtype=np.uint8), [735, 625, 65, 36], .5))

    def test_option_overrides_use_v2_and_keep_existing_tasks(self):
        interface = json.loads((ROOT / 'interface.json').read_text(encoding='utf-8'))
        cases = interface['option']['识别方式']['cases']
        modes = [c['pipeline_override']['抽卡记录_单页识别']['recognition']['param']['custom_recognition_param'].get('stop_on_known', False) for c in cases]
        self.assertEqual([False, True], modes)
        task = next(t for t in interface['task'] if t['name'] == '抽卡记录')
        self.assertFalse(task['default_check'])


if __name__ == '__main__':
    unittest.main()
