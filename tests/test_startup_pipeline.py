"""Tests for game startup, pre-login announcement, and post-login popup closures."""
import json
import os
import pathlib
import unittest
import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRATCH_DIR = pathlib.Path(os.environ.get('USERPROFILE', '')) / '.gemini/antigravity/brain/52a9da4b-27e0-4c6d-9b69-993bf2637072/scratch'

# Set MAAFW_BINARY_PATH to VSCode extension native install if available
vscode_maa = (
    pathlib.Path.home()
    / 'AppData/Roaming/Code/User/globalStorage/nekosu.maa-support'
    / 'native/install/5.13.0/node_modules/@maaxyz/maa-node-win32-x64'
)
if vscode_maa.exists():
    os.environ.setdefault('MAAFW_BINARY_PATH', str(vscode_maa))


class StartupPipelineTest(unittest.TestCase):
    def setUp(self):
        self.pipeline_file = ROOT / 'resource/base/pipeline/启动.json'
        self.pipeline = json.loads(self.pipeline_file.read_text(encoding='utf-8'))

    def test_announcement_closure_schema(self):
        node = self.pipeline.get('关闭公告')
        self.assertIsNotNone(node)
        self.assertEqual(node['recognition']['type'], 'OCR')
        expected = node['recognition']['param']['expected']
        self.assertTrue(any('系统公告' in e for e in expected))
        self.assertTrue(any('狄斯资讯' in e for e in expected))
        self.assertEqual(node['action']['type'], 'Click')
        # Left margin click to dismiss announcement
        self.assertLessEqual(node['action']['param']['target'][0], 100)

    def test_skin_popup_closure_schema(self):
        node = self.pipeline.get('关闭四星皮肤弹窗')
        self.assertIsNotNone(node)
        self.assertEqual(node['recognition']['type'], 'OCR')
        expected = node['recognition']['param']['expected']
        self.assertTrue(any('单独购买' in e for e in expected))
        self.assertTrue(any('2580' in e for e in expected))
        self.assertEqual(node['action']['type'], 'Click')
        # Top-right X button
        self.assertGreaterEqual(node['action']['param']['target'][0], 1000)
        self.assertLessEqual(node['action']['param']['target'][1], 150)

    def test_general_popup_closure_schema(self):
        node = self.pipeline.get('一般弹窗')
        self.assertIsNotNone(node)
        self.assertEqual(node['recognition']['type'], 'TemplateMatch')
        self.assertIn('弹窗关闭按钮.png', node['recognition']['param']['template'])
        roi = node['recognition']['param']['roi']
        # ROI should cover top-right corner
        self.assertGreaterEqual(roi[0], 900)
        self.assertLessEqual(roi[1], 50)

    def test_pre_and_post_login_nodes(self):
        pre = self.pipeline.get('登录前处理')
        self.assertIsNotNone(pre)
        self.assertIn('timeout', pre)
        self.assertGreater(pre['timeout'], 0)
        self.assertIn('[JumpBack]关闭公告', pre['next'])
        self.assertIn('登录', pre['next'])

        post = self.pipeline.get('登录后处理')
        self.assertIsNotNone(post)
        self.assertIn('timeout', post)
        self.assertGreater(post['timeout'], 0)
        self.assertIn('[JumpBack]关闭四星皮肤弹窗', post['next'])
        self.assertIn('[JumpBack]一般弹窗', post['next'])
        self.assertIn('首页', post['next'])


@unittest.skipUnless(SCRATCH_DIR.exists(), 'Offline scratch screenshots not present')
class StartupNativeRecognitionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from maa.resource import Resource
            from maa.tasker import Tasker
            from maa.controller import CustomController
            from maa.toolkit import Toolkit
        except ImportError:
            raise unittest.SkipTest('MaaFramework binding not installed')

        try:
            cls.res = Resource()
            post_job = cls.res.post_bundle(str(ROOT / 'resource/base')).wait()
            if not post_job.succeeded:
                raise unittest.SkipTest('Could not load base resource bundle')
        except Exception as e:
            raise unittest.SkipTest(f'Full MaaFramework Resource not available in this process: {e}')

    def _run_node_on_image(self, node_name, image_path):
        from maa.tasker import Tasker
        from maa.controller import CustomController

        frame = np.array(Image.open(image_path))[:, :, ::-1]
        clicks = []

        class DummyCtrl(CustomController):
            def connect(self): return True
            def request_uuid(self): return 'uuid'
            def screencap(self): return frame
            def touch_down(self, c, x, y, p):
                clicks.append((x, y))
                return True
            def touch_up(self, c): return True

        ctrl = DummyCtrl()
        ctrl.post_connection().wait()
        tasker = Tasker()
        tasker.bind(self.res, ctrl)
        job = tasker.post_task(node_name).wait()
        return job.succeeded, clicks

    def test_announcement_recognized_and_dismissed(self):
        img = SCRATCH_DIR / 'announcement_1280.png'
        if not img.exists():
            self.skipTest(f'{img} does not exist')
        succeeded, clicks = self._run_node_on_image('关闭公告', img)
        self.assertTrue(succeeded)
        self.assertTrue(len(clicks) > 0)
        # Should click left area
        self.assertLess(clicks[0][0], 150)

    def test_skin_popup_recognized_and_dismissed(self):
        img = SCRATCH_DIR / 'skin_popup_1280.png'
        if not img.exists():
            self.skipTest(f'{img} does not exist')
        succeeded, clicks = self._run_node_on_image('关闭四星皮肤弹窗', img)
        self.assertTrue(succeeded)
        self.assertTrue(len(clicks) > 0)
        # Should click top-right X button
        self.assertGreater(clicks[0][0], 1000)
        self.assertLess(clicks[0][1], 150)

    def test_mainline_popup_recognized_and_dismissed(self):
        img = SCRATCH_DIR / 'mainline_popup_1280.png'
        if not img.exists():
            self.skipTest(f'{img} does not exist')
        succeeded, clicks = self._run_node_on_image('一般弹窗', img)
        self.assertTrue(succeeded)
        self.assertTrue(len(clicks) > 0)
        # Should click top-right X button
        self.assertGreater(clicks[0][0], 1050)
        self.assertLess(clicks[0][1], 150)


if __name__ == '__main__':
    unittest.main()
