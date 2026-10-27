import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('inventory_agent', ROOT / 'agent/inventory.py')
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


class InventoryTests(unittest.TestCase):
    def test_card_borders_keep_gray_items_and_skip_empty_cells(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        expected = [(290, 249), (454, 249), (290, 448)]
        for x, y in expected:
            image[y, x+3:x+134] = 210
        with patch.object(inventory, '_number', return_value=42):
            cards = inventory._cards(None, image)
        self.assertEqual([(x, y, 42) for x, y in expected], cards)

    def test_page_change_ignores_small_touch_glow(self):
        before = np.zeros((720,1280,3),dtype=np.uint8)
        after = before.copy()
        after[500:510,1200:1210] = 255
        self.assertTrue(inventory._same_page(before, after))
        after[200:600,300:1100] = 100
        self.assertFalse(inventory._same_page(before, after))

    def test_swipe_waits_for_stable_frame_and_uses_shorter_motion(self):
        image_a = np.zeros((720, 1280, 3), dtype=np.uint8)
        image_b = np.full((720, 1280, 3), 100, dtype=np.uint8)
        controller = SimpleNamespace(post_swipe=Mock(return_value=SimpleNamespace(wait=Mock())))
        with patch.object(inventory, '_snapshot', side_effect=[image_a, image_b, image_b]), patch.object(inventory.time, 'sleep'):
            result = inventory._swipe(controller, True)
        controller.post_swipe.assert_called_once_with(1220, 605, 1220, 455, 1000)
        self.assertTrue(np.array_equal(result, image_b))

    def test_duplicate_card_crop_reuses_template_matches(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        entry = dict(id='blue', name='SearchTicket', category='items', template='SearchTicket.png', threshold=.88)
        match = SimpleNamespace(score=.94, box=[300, 260, 20, 20])
        context = SimpleNamespace(
            tasker=SimpleNamespace(stopping=False),
            run_recognition_direct=Mock(return_value=SimpleNamespace(filtered_results=[match], all_results=[])),
        )
        output = dict(items={}, unknown={})
        cache = {}
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, MBCC_DATA_DIR=temp), \
                patch.object(inventory, '_cards', return_value=[(290, 249, 17)]), \
                patch.object(inventory, '_color_matches', return_value=True):
            inventory.InventoryBegin().run(None, None)
            inventory._scan_page(context, image, 'items', [entry], output, 0, cache)
            inventory._scan_page(context, image, 'items', [entry], output, 1, cache)
        self.assertEqual(1, context.run_recognition_direct.call_count)
        self.assertEqual(17, output['items']['blue']['quantity'])

    def test_duplicate_visuals_in_different_categories_do_not_share_matches(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        context = SimpleNamespace(
            tasker=SimpleNamespace(stopping=False),
            run_recognition_direct=Mock(return_value=SimpleNamespace(filtered_results=[], all_results=[])),
        )
        output = dict(items={}, unknown={})
        cache = {}
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, MBCC_DATA_DIR=temp), \
                patch.object(inventory, '_cards', return_value=[(290, 249, 17)]), \
                patch.object(inventory, '_color_matches', return_value=True):
            inventory.InventoryBegin().run(None, None)
            for category in ('items', 'consumables'):
                entry = dict(id=category, name=category, category=category, template='same.png', threshold=.88)
                inventory._scan_page(context, image, category, [entry], output, 0, cache)
        self.assertEqual(2, context.run_recognition_direct.call_count)

    def test_quantity_is_strict(self):
        self.assertEqual(25860565, inventory.parse_quantity('25,860,565'))
        for value in ('27/300', 'N10-2', '1万', 'O17', '', '3 4'):
            self.assertIsNone(inventory.parse_quantity(value))

    def test_overlap_not_added_and_conflict_preserved(self):
        items = {}
        entry = dict(id='blue', name='搜索令', quantity=17)
        inventory.merge_item(items, entry.copy())
        inventory.merge_item(items, entry.copy())
        self.assertEqual(17, items['blue']['quantity'])
        inventory.merge_item(items, dict(entry, quantity=18))
        self.assertEqual([17,18], items['blue']['conflicting_quantities'])

    def test_partial_preserves_last_complete(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, MBCC_DATA_DIR=temp):
            inventory.InventoryBegin().run(None, None)
            session = inventory._session
            session['currencies'] = {'异方晶': 1, '狄斯币': 2}
            session['categories'] = {name: dict(status='complete', items={}, unknown={}, reason='底部') for name in ('道具','消耗品')}
            inventory.export_session(session)
            complete = (Path(temp)/'inventory/last-complete.json').read_text(encoding='utf-8')
            inventory.InventoryBegin().run(None, None)
            inventory.export_session(inventory._session)
            self.assertEqual(complete, (Path(temp)/'inventory/last-complete.json').read_text(encoding='utf-8'))
            self.assertEqual('partial', json.loads((Path(temp)/'inventory/latest.json').read_text(encoding='utf-8'))['status'])

    def test_wrong_screen_has_zero_input_and_partial(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, MBCC_DATA_DIR=temp):
            inventory.InventoryBegin().run(None, None)
            controller = SimpleNamespace()
            ctx = SimpleNamespace(tasker=SimpleNamespace(controller=controller))
            with patch.object(inventory, '_snapshot', return_value=np.zeros((720,1280,3),dtype=np.uint8)), patch.object(inventory, '_ocr', return_value=[]):
                self.assertFalse(inventory.InventoryScanCategory().run(ctx, SimpleNamespace(custom_action_param={'category':'道具'})))
            self.assertEqual('未确认仓库分类页面', inventory._session['categories']['道具']['reason'])

    def test_scan_only_swipes_and_does_not_click(self):
        calls = []
        image = np.zeros((720,1280,3),dtype=np.uint8)
        class Controller:
            def post_swipe(self, *args):
                calls.append(args)
                return SimpleNamespace(wait=lambda: None)
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, MBCC_DATA_DIR=temp):
            inventory.InventoryBegin().run(None, None)
            context = SimpleNamespace(tasker=SimpleNamespace(controller=Controller()))
            with patch.object(inventory, '_snapshot', return_value=image), patch.object(inventory, '_ocr', return_value=[SimpleNamespace(text='米诺斯管理系统-道具')]), patch.object(inventory, '_catalog', return_value=[]), patch.object(inventory, '_number', return_value=10), patch.object(inventory, '_scan_page', return_value=0), patch.object(inventory.time, 'sleep'):
                self.assertFalse(inventory.InventoryScanCategory().run(context, SimpleNamespace(custom_action_param={'category':'道具'})))
            self.assertEqual(4, len(calls))
            self.assertEqual('partial', inventory._session['categories']['道具']['status'])


if __name__ == '__main__':
    unittest.main()
