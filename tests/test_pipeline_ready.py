import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PipelineReadyTest(unittest.TestCase):
    def test_task_interval_waits_for_home_instead_of_fixed_delay(self):
        pipeline = json.loads((ROOT / 'resource/base/pipeline/项目名.json').read_text(encoding='utf-8'))
        interval = pipeline['任务间隔']
        self.assertNotIn('post_delay', interval)
        self.assertEqual('OCR', interval['recognition']['type'])
        self.assertEqual('公告', interval['recognition']['param']['expected'])
        self.assertEqual(5000, interval['timeout'])

    def test_management_entries_rely_on_next_page_recognition(self):
        pipeline = json.loads((ROOT / 'resource/base/pipeline/监管.json').read_text(encoding='utf-8'))
        for name in ('监管入口', '收菜', '监管终端'):
            with self.subTest(node=name):
                self.assertNotIn('post_delay', pipeline[name])
                self.assertTrue(pipeline[name]['next'])

    def test_stamina_entries_use_clearing_operation_ocr(self):
        for filename, node_name in (('狄斯币.json', '狄斯币入口'), ('狂厄精粹.json', '恶兆之种')):
            with self.subTest(node=node_name):
                pipeline = json.loads((ROOT / 'resource/base/pipeline' / filename).read_text(encoding='utf-8'))
                node = pipeline[node_name]
                self.assertEqual('OCR', node['recognition'])
                self.assertEqual('清剿行动', node['expected'])
                self.assertEqual([768, 185, 129, 62], node['roi'])

    def test_only_official_resource_is_available(self):
        interface = json.loads((ROOT / 'interface.json').read_text(encoding='utf-8'))
        self.assertEqual(['官服'], [item['name'] for item in interface['resource']])
        for task in interface['task']:
            self.assertLessEqual(set(task.get('resource', [])), {'官服'})
        self.assertFalse((ROOT / 'resource/bilibili').exists())
        self.assertFalse((ROOT / 'resource/global').exists())


if __name__ == '__main__':
    unittest.main()
