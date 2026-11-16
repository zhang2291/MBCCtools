"""Runtime inventory routes must never open an item, even on scan failure."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InventoryRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nodes = json.loads((ROOT / 'resource/base/pipeline/仓库识别.json').read_text(encoding='utf-8'))

    def test_clicks_are_limited_to_navigation_outside_item_grid(self):
        for name, node in self.nodes.items():
            action = node['action']
            kind = action.get('type') if isinstance(action, dict) else action
            if kind != 'Click':
                continue
            recognition = node['recognition']
            if isinstance(recognition, dict):
                self.assertIn(recognition['param']['template'], ['主菜单.png', '返回按钮.png'])
            else:
                self.assertIn(node['expected'], ['整备中心', '仓库', '^道具$', '^消耗品$'])
            self.assertGreater(node.get('max_hit', 0), 0, name)

    def test_all_routes_are_local_and_scans_are_gated_by_category_title(self):
        for node in self.nodes.values():
            for key in ('next', 'on_error'):
                for name in node.get(key, []):
                    self.assertIn(name, self.nodes)
        for category in ['道具', '消耗品']:
            gate = self.nodes['仓库识别_确认' + category]
            self.assertEqual(gate['recognition'], 'OCR')
            self.assertEqual(gate['action'], 'DoNothing')
            self.assertIn(category, gate['expected'])
            scan = self.nodes[gate['next'][0]]
            self.assertEqual(scan['action']['param']['custom_action'], 'InventoryScanCategory')
            self.assertEqual(scan['action']['param']['custom_action_param']['category'], category)
            self.assertEqual(scan['on_error'], ['仓库识别_保存汇总'])
        self.assertNotIn('next', self.nodes['仓库识别_确认主页'])

    def test_inventory_is_opt_in_after_stamina_task(self):
        interface = json.loads((ROOT / 'interface.json').read_text(encoding='utf-8'))
        names = [task['name'] for task in interface['task']]
        self.assertEqual(names.index('仓库识别'), names.index('每日体力用途') + 1)
        task = next(task for task in interface['task'] if task['name'] == '仓库识别')
        self.assertFalse(task['default_check'])
        self.assertEqual(['官服'], task['resource'])


if __name__ == '__main__':
    unittest.main()
