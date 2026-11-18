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


def or_response(recognition_type, param, image, matches=None):
    assert recognition_type == inventory.JRecognitionType.Or
    matches = matches or {}
    sub_results = []
    for node in param.any_of:
        results = matches.get(node['sub_name'], [])
        sub_results.append(SimpleNamespace(
            name=node['sub_name'], hit=bool(results),
            filtered_results=[], all_results=[], best_result=results[0] if results else None,
        ))
        if results:
            break
    return SimpleNamespace(best_result=SimpleNamespace(sub_results=sub_results))


def catalog_entries(count=3):
    return [dict(id=f'item-{index}', name=f'物品{index}', category='items',
                 template=f'item-{index}.png', threshold=.88)
            for index in range(count)]


class InventoryTests(unittest.TestCase):
    def test_card_borders_keep_gray_items_and_skip_empty_cells(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        expected = [(290, 249), (454, 249), (290, 448)]
        for x, y in expected:
            image[y, x+3:x+134] = 210
            image[y+143:y+165, x+48:x+130] = 255
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

    def test_swipe_waits_for_motion_before_taking_new_frame(self):
        image = np.full((720, 1280, 3), 100, dtype=np.uint8)
        controller = SimpleNamespace(post_swipe=Mock(return_value=SimpleNamespace(wait=Mock())))
        with patch.object(inventory, '_snapshot', return_value=image) as snapshot, patch.object(inventory.time, 'sleep') as sleep:
            result = inventory._swipe(controller, True)
        controller.post_swipe.assert_called_once_with(1220, 605, 1220, 455, 1500)
        sleep.assert_called_once_with(.65)
        snapshot.assert_called_once_with(controller)
        self.assertTrue(np.array_equal(result, image))

    def test_duplicate_card_crop_reuses_template_matches(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        entry = dict(id='blue', name='SearchTicket', category='items', template='SearchTicket.png', threshold=.88)
        match = SimpleNamespace(score=.94, box=[300, 260, 20, 20])
        context = SimpleNamespace(
            tasker=SimpleNamespace(stopping=False),
            run_recognition_direct=Mock(side_effect=lambda kind, param, image: or_response(
                kind, param, image, {'blue': [match]})),
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
            run_recognition_direct=Mock(side_effect=or_response),
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

    def test_unmatched_card_checks_all_templates_in_one_call(self):
        entries = catalog_entries(67)
        context = SimpleNamespace(run_recognition_direct=Mock(side_effect=or_response))
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        candidates = inventory._match_card(context, image, 'items', entries, [290, 249, 136, 145])
        self.assertEqual([], candidates)
        context.run_recognition_direct.assert_called_once()
        param = context.run_recognition_direct.call_args.args[1]
        self.assertEqual(67, len(param.any_of))
        self.assertEqual([290, 249, 136, 145], param.any_of[0]['roi'])
        self.assertEqual([.88], param.any_of[0]['threshold'])
        self.assertEqual(inventory.JRecognitionType.TemplateMatch, param.any_of[0]['recognition'])
        self.assertEqual('item-0', param.any_of[0]['sub_name'])

    def test_template_hit_short_circuits_then_checks_remaining_suffix(self):
        entries = catalog_entries(67)
        match = SimpleNamespace(score=.94, box=[300, 260, 20, 20])
        context = SimpleNamespace(run_recognition_direct=Mock(
            side_effect=lambda kind, param, image: or_response(kind, param, image, {'item-0': [match]})))
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        with patch.object(inventory, '_color_matches', return_value=True):
            candidates = inventory._match_card(context, image, 'items', entries, [290, 249, 136, 145])
        self.assertEqual(2, context.run_recognition_direct.call_count)
        self.assertEqual('item-0', candidates[0][1]['id'])
        calls = context.run_recognition_direct.call_args_list
        self.assertEqual(67, len(calls[0].args[1].any_of))
        self.assertEqual(66, len(calls[1].args[1].any_of))
        self.assertEqual('item-1', calls[1].args[1].any_of[0]['sub_name'])

    def test_multiple_template_hits_are_all_preserved_for_margin_check(self):
        entries = catalog_entries()
        matches = {
            'item-0': [SimpleNamespace(score=.94, box=[300, 260, 20, 20])],
            'item-1': [SimpleNamespace(score=.93, box=[300, 260, 20, 20])],
        }
        context = SimpleNamespace(run_recognition_direct=Mock(
            side_effect=lambda kind, param, image: or_response(kind, param, image, matches)))
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        with patch.object(inventory, '_color_matches', return_value=True):
            candidates = inventory._match_card(context, image, 'items', entries, [290, 249, 136, 145])
        self.assertEqual(['item-0', 'item-1'], [entry['id'] for score, entry in candidates])
        self.assertEqual(3, context.run_recognition_direct.call_count)

    def test_misnamed_sub_result_is_rejected(self):
        entries = catalog_entries()
        detail = SimpleNamespace(best_result=SimpleNamespace(sub_results=[
            SimpleNamespace(name='wrong-item', hit=False, filtered_results=[], all_results=[]),
        ]))
        context = SimpleNamespace(run_recognition_direct=Mock(return_value=detail))
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        with self.assertRaisesRegex(ValueError, '顺序或名称'):
            inventory._match_card(context, image, 'items', entries, [290, 249, 136, 145])

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

    def test_scan_swipes_down_through_changed_pages_until_stable_bottom(self):
        calls = []
        image_a = np.zeros((720,1280,3),dtype=np.uint8)
        image_b = np.full((720,1280,3), 50, dtype=np.uint8)
        image_c = np.full((720,1280,3), 100, dtype=np.uint8)
        frames = iter([image_b, image_c, image_c, image_c])
        def swipe(controller, down):
            calls.append(down)
            return next(frames)
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, MBCC_DATA_DIR=temp):
            inventory.InventoryBegin().run(None, None)
            context = SimpleNamespace(tasker=SimpleNamespace(controller=SimpleNamespace()))
            with patch.object(inventory, '_snapshot', return_value=image_a), \
                    patch.object(inventory, '_swipe', side_effect=swipe), \
                    patch.object(inventory, '_ocr', return_value=[SimpleNamespace(text='米诺斯管理系统-道具')]), \
                    patch.object(inventory, '_catalog', return_value=[]), \
                    patch.object(inventory, '_number', return_value=10), \
                    patch.object(inventory, '_scan_page', return_value=1) as scan_page:
                self.assertTrue(inventory.InventoryScanCategory().run(context, SimpleNamespace(custom_action_param={'category':'道具'})))
            self.assertEqual([True, True, True, True], calls)
            self.assertEqual(4, scan_page.call_count)
            self.assertEqual('已到列表底部', inventory._session['categories']['道具']['reason'])

    def test_unknown_items_across_pages_deduplicated(self):
        # Two consecutive pages showing the same unknown item with small pixel shift/noise
        image1 = np.zeros((720, 1280, 3), dtype=np.uint8)
        image1[249+16:249+134, 290+8:290+126] = 120
        image2 = np.zeros((720, 1280, 3), dtype=np.uint8)
        # Small pixel variation (e.g. mean diff 3.0)
        image2[249+16:249+134, 290+8:290+126] = 123
        context = SimpleNamespace(
            tasker=SimpleNamespace(stopping=False),
            run_recognition_direct=Mock(side_effect=or_response),
        )
        output = dict(items={}, unknown={})
        cache, unknown_crops = {}, {}
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, MBCC_DATA_DIR=temp), \
                patch.object(inventory, '_cards', return_value=[(290, 249, 206)]):
            inventory.InventoryBegin().run(None, None)
            inventory._scan_page(context, image1, 'items', [], output, 0, cache, unknown_crops)
            inventory._scan_page(context, image2, 'items', [], output, 1, cache, unknown_crops)
        self.assertEqual(1, len(output['unknown']), 'Unknown items on consecutive pages should be deduplicated')


if __name__ == '__main__':
    unittest.main()
