"""Exercise bounded material-map search using real MaaFramework and an offline controller."""
from pathlib import Path
import tempfile

import numpy as np
from maa.controller import CustomController
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

ROOT = Path(__file__).resolve().parents[1]


class OfflineController(CustomController):
    def __init__(self):
        super().__init__()
        self.swipes = []
        self.clicks = []

    def connect(self): return True
    def request_uuid(self): return 'offline-material-search'
    def get_features(self): return 0
    def screencap(self): return np.zeros((720, 1280, 3), dtype=np.uint8)
    def click(self, x, y):
        self.clicks.append((x, y))
        return True
    def swipe(self, *args):
        self.swipes.append(args)
        return True
    def start_app(self, intent): return False
    def stop_app(self, intent): return False
    def touch_down(self, *args): return False
    def touch_move(self, *args): return False
    def touch_up(self, *args): return False
    def click_key(self, *args): return False
    def input_text(self, *args): return False
    def key_down(self, *args): return False
    def key_up(self, *args): return False


with tempfile.TemporaryDirectory(prefix='mbcc-material-native-', ignore_cleanup_errors=True) as temp:
    Toolkit.init_option(temp)
    resource = Resource()
    assert resource.post_bundle(str(ROOT / 'resource/base')).wait().succeeded
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    tasker = Tasker()
    tasker.bind(resource, controller)
    assert tasker.inited
    # No target stage exists. Disable its recognizer so this test isolates Maa's
    # max_hit/next behavior; screenshot OCR is verified separately.
    overrides = {'目标材料关卡': {'enabled': False}}
    for name in ('滑动找关卡', '反向滑动找关卡'):
        overrides[name] = {'pre_delay': 0, 'post_delay': 0, 'post_wait_freezes': 0,
                           'duration': 1, 'timeout': 20, 'rate_limit': 1}
    result = tasker.post_task('滑动找关卡', overrides).wait()
    assert result.status.failed, f'Missing stage must fail, got {result.status}'
    assert len(controller.swipes) == 15, f'Unexpected swipe count: {len(controller.swipes)}'
    assert not controller.clicks, 'Missing target must never cause a click'
    directions = [args[2] > args[0] for args in controller.swipes]
    assert directions == [True] * 5 + [False] * 10, directions
    print('PASS: native Maa search ends FAILED after 5 right + 10 left swipes; zero clicks.')
