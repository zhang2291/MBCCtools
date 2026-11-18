"""Material route contract: user-confirmed drops and bounded navigation, no game clicks."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MATERIAL_STAGES = {
    '裂生冰晶锥': 'S2-4', '沉雾泪晶': 'S2-6', '繁盛曲铜晶': 'S2-1',
    '结霜毒砂晶': 'S2-9&10', '燃念赤晶': 'S2-8', '衰变暮辉晶': 'S1-5',
    '异化暗凝胶': 'S2-11', '异化诡影鞘翅': 'S2-2', '异化棘状角': 'S2-5',
    '异化尖刺骨片': 'S2-3', '异化真红囊泡': 'S1-9', '异化拟怪腕足': 'S2-7',
}


class MaterialRouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.interface = json.loads((ROOT / 'interface.json').read_text(encoding='utf-8'))
        cls.pipeline = json.loads((ROOT / 'resource/base/pipeline/刷取材料.json').read_text(encoding='utf-8'))

    def test_each_material_selects_only_its_chapter_and_stage(self):
        cases = self.interface['option']['材料选择']['cases']
        self.assertEqual({c['name'] for c in cases}, set(MATERIAL_STAGES))
        for case in cases:
            with self.subTest(material=case['name']):
                stage = MATERIAL_STAGES[case['name']]
                chapter = stage.split('-')[0]
                overrides = case['pipeline_override']
                chapter_pattern = overrides['恩慈余光章节选择']['expected']
                stage_pattern = overrides['目标材料关卡']['expected']
                self.assertRegex(chapter, chapter_pattern)
                self.assertNotRegex('S1' if chapter == 'S2' else 'S2', chapter_pattern)
                self.assertRegex(stage, stage_pattern)
                self.assertRegex(stage.replace('-', ' - '), stage_pattern)
                self.assertNotRegex(stage + '0', stage_pattern)
                for other_stage in set(MATERIAL_STAGES.values()) - {stage}:
                    self.assertNotRegex(other_stage, stage_pattern)

    def test_new_city_two_is_distinct_from_new_city_one(self):
        pattern = self.pipeline['进入新城二']['expected']
        self.assertFalse(self.pipeline['进入新城二'].get('only_rec', False))
        for text in ['新城·II', '新城・Ⅱ', '新城·Ⅱ', '新城 2', '新城：2']:
            self.assertRegex(text, pattern)
        for text in ['新城·I', '新城·Ⅰ', '新城·1', '里湾', '远邦']:
            self.assertNotRegex(text, pattern)

    def test_map_entry_requires_a_second_chapter_click(self):
        self.assertEqual(self.pipeline['恩慈余光入口']['next'], ['恩慈余光章节选择'])
        chapter = self.pipeline['恩慈余光章节选择']
        self.assertEqual(chapter['next'], ['目标材料关卡'])
        self.assertEqual(chapter['on_error'], ['滑动找关卡'])
        self.assertEqual(chapter['timeout'], 800)
        # The map's S1/S2 labels are around y=210; the cover's labels start at y=452.
        self.assertGreater(chapter['roi'][1], 400)

    def test_missing_stage_search_terminates_after_two_bounded_sweeps(self):
        # Simulate Maa's documented max_hit rule: exhausted nodes are skipped in next.
        hits = {}
        current = '滑动找关卡'
        while current is not None:
            hits[current] = hits.get(current, 0) + 1
            self.assertLessEqual(sum(hits.values()), 15)
            current = next((name for name in self.pipeline[current]['next']
                            if name != '目标材料关卡'
                            and hits.get(name, 0) < self.pipeline[name]['max_hit']), None)
        self.assertEqual(hits, {'滑动找关卡': 5, '反向滑动找关卡': 10})

    def test_west_district_and_other_regions_handled_before_home_fallback(self):
        route = self.pipeline['刷取材料']['next']
        home_idx = route.index('[JumpBack]材料导航回主页')
        for node_name in ['远邦to新城二', '新城一to新城二', '里湾to新城二', '狄斯西区to新城二']:
            self.assertLess(route.index(f'[JumpBack]{node_name}'), home_idx)
            node = self.pipeline[node_name]
            self.assertLess(node['end'][1], node['begin'][1])
        self.assertEqual(self.pipeline['材料导航回主页']['max_hit'], 1)

    def test_completion_and_shortage_require_home_confirmation(self):
        route = ['材料确认主页', '材料返回主页', '材料返回上级']
        for name in ['材料扫荡完成', '材料扫荡失败', '材料返回主页', '材料返回上级']:
            self.assertEqual(self.pipeline[name]['next'], route)
        self.assertNotIn('next', self.pipeline['材料确认主页'])
        self.assertEqual(self.interface['option']['识别方式']['type'], 'select')


if __name__ == '__main__':
    unittest.main()
