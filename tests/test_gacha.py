import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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

    def test_known_page_skips_rarity_recognition(self):
        cells = ('2026-10-15 10:00:00', '测试池', '已知角色')
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, MBCC_DATA_DIR=temp):
            agent._sessions.clear()
            session = agent._get_session(agent.DEFAULT_ARCHIVE)
            session.file_for(None).write_text(json.dumps(
                dict(index=1, key=agent._row_sig(cells), rarity='普', cells=cells),
                ensure_ascii=False) + '\n', encoding='utf-8')
            context = SimpleNamespace(
                override_next=lambda *args: True,
                tasker=SimpleNamespace(controller=SimpleNamespace()),
            )
            argv = SimpleNamespace(
                roi=SimpleNamespace(x=440, y=275, w=640, h=350),
                image=np.zeros((720, 1280, 3), dtype=np.uint8),
                node_name='抽卡记录_单页识别', custom_recognition_param={},
            )
            with patch.object(agent, '_ocr_find', return_value=True), \
                    patch.object(agent, '_read_page_number', return_value=1), \
                    patch.object(agent, '_ocr_rows', return_value=([cells], [[440, 300, 640, 30]])), \
                    patch.object(agent, '_rarity_by_row') as rarity:
                self.assertIsNotNone(agent.GachaRecordPage().analyze(context, argv))
            rarity.assert_not_called()
            self.assertEqual(0, session.new_count)

    def test_mixed_page_only_reads_rarity_for_new_rows(self):
        known = ('2026-10-15 10:00:00', '测试池', '已知角色')
        new = ('2026-10-15 10:01:00', '测试池', '新增角色')
        rows = [known, new]
        boxes = [[440, 300, 640, 30], [440, 340, 640, 30]]
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, MBCC_DATA_DIR=temp):
            agent._sessions.clear()
            session = agent._get_session(agent.DEFAULT_ARCHIVE)
            session.file_for(None).write_text(json.dumps(
                dict(index=1, key=agent._row_sig(known), rarity='普', cells=known),
                ensure_ascii=False) + '\n', encoding='utf-8')
            context = SimpleNamespace(
                override_next=lambda *args: True,
                tasker=SimpleNamespace(controller=SimpleNamespace()),
            )
            argv = SimpleNamespace(
                roi=SimpleNamespace(x=440, y=275, w=640, h=350),
                image=np.zeros((720, 1280, 3), dtype=np.uint8),
                node_name='抽卡记录_单页识别', custom_recognition_param={},
            )
            with patch.object(agent, '_ocr_find', return_value=True), \
                    patch.object(agent, '_read_page_number', return_value=1), \
                    patch.object(agent, '_ocr_rows', return_value=(rows, boxes)), \
                    patch.object(agent, '_rarity_by_row', return_value=['狂']) as rarity:
                self.assertIsNotNone(agent.GachaRecordPage().analyze(context, argv))
            self.assertEqual([boxes[1]], rarity.call_args.args[2])
            self.assertEqual(1, session.new_count)
            records = [json.loads(line) for line in session.file_for(None).read_text(encoding='utf-8').splitlines()]
            self.assertEqual(2, len(records))
            self.assertEqual(agent._row_sig(new), records[-1]['key'])
            self.assertEqual('狂', records[-1]['rarity'])

    def test_numpy_page_upscale(self):
        def recognize(kind, params, image):
            self.assertEqual((144, 260, 3), image.shape)
            return SimpleNamespace(all_results=[SimpleNamespace(text='12', score=.99)])
        ctx = SimpleNamespace(run_recognition_direct=recognize)
        with patch.object(agent, 'cv2', None):
            self.assertEqual(12, agent._read_page_number(ctx, np.zeros((720, 1280, 3), dtype=np.uint8), [735, 625, 65, 36], .5))

    def test_page_number_none_infers_page_when_rows_change(self):
        new = ('2026-10-15 10:02:00', '测试池', '新页角色')
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, MBCC_DATA_DIR=temp):
            agent._sessions.clear()
            session = agent._get_session(agent.DEFAULT_ARCHIVE)
            session.last_page = 16
            session.last_keys = ['old_key_16']
            context = SimpleNamespace(
                override_next=lambda node, next_list: next_list[0] == '抽卡记录翻页',
                tasker=SimpleNamespace(controller=SimpleNamespace()),
            )
            argv = SimpleNamespace(
                roi=SimpleNamespace(x=440, y=275, w=640, h=350),
                image=np.zeros((720, 1280, 3), dtype=np.uint8),
                node_name='抽卡记录_单页识别', custom_recognition_param={},
            )
            with patch.object(agent, '_ocr_find', return_value=True), \
                    patch.object(agent, '_read_page_number', return_value=None), \
                    patch.object(agent, '_ocr_rows', return_value=([new], [[440, 300, 640, 30]])), \
                    patch.object(agent, '_rarity_by_row', return_value=['普']):
                result = agent.GachaRecordPage().analyze(context, argv)
            self.assertIsNotNone(result)
            self.assertEqual(17, session.last_page)
            self.assertEqual(1, session.new_count)

    def test_pool_type_matching_and_recognition(self):
        self.assertEqual('返场限定', agent._match_type('返场限定追踪·近期抽卡记录(UTC+8)', agent.DEFAULT_POOL_TYPES))
        self.assertEqual('限定', agent._match_type('限定追踪·近期抽卡记录(UTC+8)', agent.DEFAULT_POOL_TYPES))
        self.assertEqual('活动', agent._match_type('活动追踪·近期抽卡记录(UTC+8)', agent.DEFAULT_POOL_TYPES))
        self.assertEqual('常规', agent._match_type('常规追踪·近期抽卡记录(UTC+8)', agent.DEFAULT_POOL_TYPES))
        self.assertEqual('统合', agent._match_type('统合追踪·近期抽卡记录(UTC+8)', agent.DEFAULT_POOL_TYPES))
        self.assertEqual('特殊联动', agent._match_type('特殊联动追踪·近期抽卡记录(UTC+8)', agent.DEFAULT_POOL_TYPES))

        with tempfile.TemporaryDirectory() as td:
            archive_path = pathlib.Path(td)
            session = agent._get_session(archive_path)
            context = MagicMock()
            argv = MagicMock()
            argv.roi = MagicMock(x=0, y=0, w=0, h=0)
            argv.image = np.zeros((720, 1280, 3), dtype=np.uint8)
            argv.custom_recognition_param = json.dumps({"archive": str(archive_path)})

            class DummyOCRResult:
                def __init__(self, text, box, score):
                    self.text = text
                    self.box = box
                    self.score = score

            # 1. 命中返场限定
            detail1 = MagicMock()
            detail1.all_results = [DummyOCRResult('返场限定追踪·近期抽卡记录(UTC+8)', [440, 225, 397, 28], 0.98)]
            context.run_recognition_direct.return_value = detail1
            res1 = agent.GachaRecordPoolType().analyze(context, argv)
            self.assertIsNotNone(res1)
            self.assertEqual('返场限定', session.pool_type)

            # 2. 未能精确识别类型，但存在门卫词（抽卡记录页），降级为未判而不阻断任务
            detail2 = MagicMock()
            detail2.all_results = [DummyOCRResult('近期抽卡记录(UTC+8)', [440, 225, 300, 28], 0.98)]
            context.run_recognition_direct.return_value = detail2
            res2 = agent.GachaRecordPoolType().analyze(context, argv)
            self.assertIsNotNone(res2)
            self.assertIsNone(session.pool_type)

            # 3. 不在记录页（非门卫词），返回 None
            detail3 = MagicMock()
            detail3.all_results = [DummyOCRResult('主界面其他内容', [100, 100, 200, 30], 0.95)]
            context.run_recognition_direct.return_value = detail3
            res3 = agent.GachaRecordPoolType().analyze(context, argv)
            self.assertIsNone(res3)

    def test_merged_timestamp_and_pool_split(self):
        def item(text, x, y, score=1):
            return SimpleNamespace(text=text, box=[x, y, 30, 15], score=score)
        results = [
            item('2024-02-08 22:19:29光影留痕', 440, 100),
            item('玛奇朵', 930, 100)
        ]
        ctx = SimpleNamespace(run_recognition_direct=lambda *args: SimpleNamespace(all_results=results))
        rows, boxes = agent._ocr_rows(ctx, np.zeros((720, 1280, 3), dtype=np.uint8), [0, 0, 1280, 720], .5, 14, [856, 908])
        self.assertEqual([('2024-02-08 22:19:29', '光影留痕', '玛奇朵')], rows)

    def test_first_page_check_bypasses_when_page_is_one(self):
        context = SimpleNamespace(
            override_next=lambda *args: True,
            tasker=SimpleNamespace(controller=SimpleNamespace()),
        )
        argv = SimpleNamespace(
            roi=SimpleNamespace(x=440, y=275, w=640, h=350),
            image=np.zeros((720, 1280, 3), dtype=np.uint8),
            node_name='抽卡记录_回首页', custom_recognition_param={},
        )
        with patch.object(agent, '_ocr_find', return_value=True), \
                patch.object(agent, '_read_page_number', return_value=1):
            res = agent.GachaRecordFirstPage().analyze(context, argv)
            self.assertIsNone(res)

    def test_option_overrides_use_v2_and_keep_existing_tasks(self):
        interface = json.loads((ROOT / 'interface.json').read_text(encoding='utf-8'))
        cases = interface['option']['识别方式']['cases']
        modes = [c['pipeline_override']['抽卡记录_单页识别']['recognition']['param']['custom_recognition_param'].get('stop_on_known', False) for c in cases]
        self.assertEqual([False, True], modes)
        task = next(t for t in interface['task'] if t['name'] == '抽卡记录')
        self.assertFalse(task['default_check'])

    def test_constrained_fuzzy_deduplication_and_same_second_preservation(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = pathlib.Path(temp)
            h1 = {'cells': ['2026-11-18 14:00:10', '慈·爱·念', '卡兹安'], 'rarity': '危'}
            h2 = {'cells': ['2026-11-18 14:00:10', '慈·爱·念', '澈'], 'rarity': '普'}
            h3 = {'cells': ['2026-11-18 14:00:10', '慈·爱·念', '澈'], 'rarity': '普'}
            h4 = {'cells': ['2026-11-18 14:00:10', '慈·爱·念', '海拉'], 'rarity': '普'}
            (archive / '活动.jsonl').write_text(
                '\n'.join(json.dumps(r, ensure_ascii=False) for r in [h1, h2, h3, h4]) + '\n',
                encoding='utf-8'
            )
            counts, total, by_ts = agent._load_store(archive)
            self.assertEqual(4, total)
            self.assertEqual(1, len(by_ts))
            session = agent._RecordSession(archive, 'test', counts, by_ts)
            collector = agent.GachaRecordPage()

            # 3字及以上角色允许唯一编辑距离<=1归并：卡茲安 -> 卡兹安
            rows1 = [('2026-11-18 14:00:10', '慈·爱·念', '卡茲安')]
            keys1 = [agent._row_sig(r) for r in rows1]
            fresh1, known1 = collector._fresh_row_indices(session, rows1, keys1)
            self.assertEqual(0, len(fresh1))
            self.assertEqual(1, known1)

            # 同秒重复出货配额扣减：2 个澈均正常命中历史配额
            rows2 = [('2026-11-18 14:00:10', '慈·爱·念', '澈')] * 2
            keys2 = [agent._row_sig(r) for r in rows2]
            fresh2, known2 = collector._fresh_row_indices(session, rows2, keys2)
            self.assertEqual(0, len(fresh2))
            self.assertEqual(2, known2)

            # 超出配额的第 3 个澈判定为 fresh
            rows3 = [('2026-11-18 14:00:10', '慈·爱·念', '澈')]
            keys3 = [agent._row_sig(r) for r in rows3]
            fresh3, known3 = collector._fresh_row_indices(session, rows3, keys3)
            self.assertEqual(1, len(fresh3))

            # 1 字角色禁止模糊归并：琼 不归并至 澈
            rows4 = [('2026-11-18 14:00:10', '慈·爱·念', '琼')]
            keys4 = [agent._row_sig(r) for r in rows4]
            fresh4, known4 = collector._fresh_row_indices(session, rows4, keys4)
            self.assertEqual(1, len(fresh4))

            # 2 字角色稀有度不同禁止归并：海莉(危) 不归并至 海拉(普)
            rows5 = [('2026-11-18 14:00:10', '慈·爱·念', '海莉')]
            keys5 = [agent._row_sig(r) for r in rows5]
            fresh5, known5 = collector._fresh_row_indices(session, rows5, keys5)
            self.assertEqual(1, len(fresh5))

    def test_stop_on_known_saves_fresh_rows_on_mixed_page(self):
        new_row = ('2026-11-25 16:46:50', '明轨将追', '新增角色')
        k1 = ('2026-09-16 21:07:05', '明轨将追', '艾米潘')
        k2 = ('2026-09-16 21:07:05', '明轨将追', '雷比尼斯')
        rows = [new_row, k1, k2]
        boxes = [[440, 290, 640, 28], [440, 320, 640, 28], [440, 350, 640, 28]]
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, MBCC_DATA_DIR=temp):
            agent._sessions.clear()
            session = agent._get_session(agent.DEFAULT_ARCHIVE)
            session.file_for(None).write_text(
                '\n'.join([
                    json.dumps(dict(index=1, key=agent._row_sig(k1), rarity='普', cells=k1), ensure_ascii=False),
                    json.dumps(dict(index=2, key=agent._row_sig(k2), rarity='普', cells=k2), ensure_ascii=False),
                ]) + '\n',
                encoding='utf-8',
            )
            routed = []
            context = SimpleNamespace(
                override_next=lambda node, next_list: routed.append((node, list(next_list))) or True,
                tasker=SimpleNamespace(controller=SimpleNamespace()),
            )
            argv = SimpleNamespace(
                roi=SimpleNamespace(x=440, y=275, w=640, h=350),
                image=np.zeros((720, 1280, 3), dtype=np.uint8),
                node_name='抽卡记录_单页识别',
                custom_recognition_param=json.dumps({'stop_on_known': True}),
            )
            with patch.object(agent, '_ocr_find', return_value=True), \
                    patch.object(agent, '_read_page_number', return_value=None), \
                    patch.object(agent, '_ocr_rows', return_value=(rows, boxes)), \
                    patch.object(agent, '_rarity_by_row', return_value=['普']) as rarity:
                res = agent.GachaRecordPage().analyze(context, argv)
            self.assertIsNotNone(res)
            rarity.assert_called_once()
            self.assertEqual(1, session.new_count)
            self.assertEqual(1, session.pages)
            self.assertEqual(2, session.known_count)
            self.assertEqual('completed', session.status)
            self.assertEqual(('抽卡记录_单页识别', ['抽卡记录汇总']), routed[-1])
            saved = [json.loads(line) for line in session.file_for(None).read_text(encoding='utf-8').splitlines()]
            self.assertEqual(3, len(saved))
            self.assertEqual(agent._row_sig(new_row), saved[-1]['key'])

    def test_off_page_gate_failure_never_writes_or_flips_page(self):
        fake_row = ('2026-11-25 17:10:00', '明轨将追', '假行')
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, MBCC_DATA_DIR=temp):
            agent._sessions.clear()
            session = agent._get_session(agent.DEFAULT_ARCHIVE)
            routed = []
            context = SimpleNamespace(
                override_next=lambda node, next_list: routed.append((node, list(next_list))) or True,
                tasker=SimpleNamespace(controller=SimpleNamespace()),
            )
            argv = SimpleNamespace(
                roi=SimpleNamespace(x=440, y=275, w=640, h=350),
                image=np.zeros((720, 1280, 3), dtype=np.uint8),
                node_name='抽卡记录_单页识别',
                custom_recognition_param=json.dumps({'stop_on_known': True}),
            )
            with patch.object(agent, '_ocr_find', return_value=None), \
                    patch.object(agent, '_ocr_rows', return_value=([fake_row], [[440, 290, 640, 28]])) as ocr_rows:
                res = agent.GachaRecordPage().analyze(context, argv)
            self.assertIsNotNone(res)
            ocr_rows.assert_not_called()
            self.assertEqual('partial', session.status)
            self.assertEqual(('抽卡记录_单页识别', ['抽卡记录汇总']), routed[-1])
            self.assertEqual([], list(session.path.glob('*.jsonl')))

    def test_stop_on_known_does_not_complete_on_corrupted_ocr_rows(self):
        corrupted_row = ('2026-11-25 17:00:00', '明轨将追')
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, MBCC_DATA_DIR=temp):
            agent._sessions.clear()
            session = agent._get_session(agent.DEFAULT_ARCHIVE)
            routed = []
            context = SimpleNamespace(
                override_next=lambda node, next_list: routed.append((node, list(next_list))) or True,
                tasker=SimpleNamespace(controller=SimpleNamespace()),
            )
            argv = SimpleNamespace(
                roi=SimpleNamespace(x=440, y=275, w=640, h=350),
                image=np.zeros((720, 1280, 3), dtype=np.uint8),
                node_name='抽卡记录_单页识别',
                custom_recognition_param=json.dumps({'stop_on_known': True}),
            )
            with patch.object(agent, '_ocr_find', return_value=True), \
                    patch.object(agent, '_read_page_number', return_value=1), \
                    patch.object(agent, '_ocr_rows', return_value=([corrupted_row], [[440, 290, 640, 28]])):
                res = agent.GachaRecordPage().analyze(context, argv)
            self.assertIsNotNone(res)
            self.assertEqual('partial', session.status)
            self.assertNotIn('命中已知历史记录', session.finish_reason)
            self.assertEqual(('抽卡记录_单页识别', ['抽卡记录汇总']), routed[-1])

    def test_cross_page_fuzzy_dedup_does_not_reuse_consumed_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = pathlib.Path(temp)
            h1 = {'cells': ['2026-11-18 14:00:10', '慈·爱·愈', '艾米潘'], 'rarity': '普'}
            (archive / '活动.jsonl').write_text(json.dumps(h1, ensure_ascii=False) + '\n', encoding='utf-8')
            counts, total, by_ts = agent._load_store(archive)
            self.assertEqual(1, total)
            session = agent._RecordSession(archive, 'test', counts, by_ts)
            collector = agent.GachaRecordPage()

            # 第 1 页精确命中唯一的「艾米潘」
            rows1 = [('2026-11-18 14:00:10', '慈·爱·愈', '艾米潘')]
            keys1 = [agent._row_sig(r) for r in rows1]
            fresh1, known1 = collector._fresh_row_indices(session, rows1, keys1)
            self.assertEqual([], fresh1)
            self.assertEqual(1, known1)

            # 第 2 页跨页遇到同秒同池但 OCR 错成「艾米帕」的另一抽，不能重复消耗已用完的历史记录
            rows2 = [('2026-11-18 14:00:10', '慈·爱·愈', '艾米帕')]
            keys2 = [agent._row_sig(r) for r in rows2]
            fresh2, known2 = collector._fresh_row_indices(session, rows2, keys2)
            self.assertEqual([0], fresh2)
            self.assertEqual(0, known2)

    def test_page_jump_recovers_when_back_succeeds_and_marks_partial_when_not(self):
        row_p2 = ('2026-11-25 17:15:00', '明轨将追', '第2页角色')
        row_p3 = ('2026-11-25 17:14:00', '明轨将追', '第3页角色')
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, MBCC_DATA_DIR=temp):
            # 1. 跳到第 3 页，点 ◀ 后成功回退到第 2 页恢复
            agent._sessions.clear()
            session = agent._get_session(agent.DEFAULT_ARCHIVE)
            session.last_page = 1
            session.attempts = 1
            wait_ok = SimpleNamespace(wait=lambda: None)
            ctrl = SimpleNamespace(
                cached_image=np.zeros((720, 1280, 3), dtype=np.uint8),
                post_click=lambda x, y: wait_ok,
                post_screencap=lambda: wait_ok,
            )
            context = SimpleNamespace(override_next=lambda *args: True, tasker=SimpleNamespace(controller=ctrl))
            argv = SimpleNamespace(
                roi=SimpleNamespace(x=440, y=275, w=640, h=350),
                image=np.zeros((720, 1280, 3), dtype=np.uint8),
                node_name='抽卡记录_单页识别',
                custom_recognition_param={},
            )
            # _read_page_number 依次返回: 3 (首次) -> 3 (0.25s复检) -> 2 (◀回退后)
            with patch.object(agent, '_ocr_find', return_value=True), \
                    patch.object(agent, '_read_page_number', side_effect=[3, 3, 2]), \
                    patch.object(agent, '_ocr_rows', return_value=([row_p2], [[440, 290, 640, 28]])), \
                    patch.object(agent, '_rarity_by_row', return_value=['普']), \
                    patch('time.sleep'):
                agent.GachaRecordPage().analyze(context, argv)
            self.assertEqual(2, session.last_page)
            self.assertEqual('running', session.status)

            # 2. 回退未能恢复第 2 页时，必须标为 partial
            agent._sessions.clear()
            session2 = agent._get_session(agent.DEFAULT_ARCHIVE)
            session2.last_page = 1
            session2.attempts = 1
            with patch.object(agent, '_ocr_find', return_value=True), \
                    patch.object(agent, '_read_page_number', side_effect=[3, 3, 3]), \
                    patch.object(agent, '_ocr_rows', return_value=([row_p3], [[440, 290, 640, 28]])), \
                    patch.object(agent, '_rarity_by_row', return_value=['普']), \
                    patch('time.sleep'):
                agent.GachaRecordPage().analyze(context, argv)
            self.assertEqual('partial', session2.status)
            self.assertIn('页码跳变', session2.finish_reason)

    def test_full_rescan_repairs_unknown_rarity_atomically(self):
        row = ('2026-11-25 17:20:00', '明轨将追', '未知新角色')
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, MBCC_DATA_DIR=temp):
            agent._sessions.clear()
            session = agent._get_session(agent.DEFAULT_ARCHIVE)
            archive_file = session.file_for('定向')
            archive_file.write_text(
                json.dumps(
                    dict(index=1, key=agent._row_sig(row), rarity='未知:狂:0.41', type='定向', cells=list(row)),
                    ensure_ascii=False,
                ) + '\n',
                encoding='utf-8',
            )
            context = SimpleNamespace(
                override_next=lambda *args: True,
                tasker=SimpleNamespace(controller=SimpleNamespace()),
            )
            argv = SimpleNamespace(
                roi=SimpleNamespace(x=440, y=275, w=640, h=350),
                image=np.zeros((720, 1280, 3), dtype=np.uint8),
                node_name='抽卡记录_单页识别',
                custom_recognition_param=json.dumps({'stop_on_known': False, 'rarity_tiers': ['狂', '危', '普']}),
            )
            with patch.object(agent, '_ocr_find', return_value=True), \
                    patch.object(agent, '_read_page_number', return_value=1), \
                    patch.object(agent, '_ocr_rows', return_value=([row], [[440, 290, 640, 28]])), \
                    patch.object(agent, '_rarity_by_row', return_value=['狂']) as rarity:
                res = agent.GachaRecordPage().analyze(context, argv)
            self.assertIsNotNone(res)
            rarity.assert_called_once()
            self.assertEqual(0, session.new_count)
            saved = [json.loads(line) for line in archive_file.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(1, len(saved))
            self.assertEqual('狂', saved[0]['rarity'])


if __name__ == '__main__':
    unittest.main()
