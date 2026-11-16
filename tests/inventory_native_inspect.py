import sys
from pathlib import Path
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from unittest.mock import patch
from maa.agent.agent_server import AgentServer
with patch.object(AgentServer, 'custom_action', side_effect=lambda name: lambda cls: cls):
    import inventory
from maa.library import Library
import maa
Library.open(Path(maa.__file__).parent / 'bin', agent_server=False)
from maa.controller import CustomController
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
import numpy as np
from PIL import Image
class Offline(CustomController):
    def connect(self): return True
    def request_uuid(self): return 'inventory-offline'
    def get_features(self): return 0
    def screencap(self): return image
    def click(self,*a): raise AssertionError('read only')
    def swipe(self,*a): return True
    def start_app(self,*a): return False
    def stop_app(self,*a): return False
    def touch_down(self,*a): return False
    def touch_move(self,*a): return False
    def touch_up(self,*a): return False
    def click_key(self,*a): return False
    def input_text(self,*a): return False
    def key_down(self,*a): return False
    def key_up(self,*a): return False


def reference_match_card(context, image, category, catalog, roi):
    candidates = []
    for entry in catalog:
        if entry['category'] != category:
            continue
        detail = context.run_recognition_direct(inventory.JRecognitionType.TemplateMatch,
            inventory.JTemplateMatch(template=[entry['template']], roi=roi,
                                    threshold=[entry.get('threshold', .88)]), image)
        for match in inventory._results(detail):
            score = float(getattr(match, 'score', 0))
            if score >= entry.get('threshold', .88) and inventory._color_matches(image, match, entry['template']):
                candidates.append((score, entry))
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return candidates


class CountingContext:
    def __init__(self, context):
        self.context = context
        self.calls = 0

    def __getattr__(self, name):
        return getattr(self.context, name)

    def run_recognition_direct(self, *args):
        self.calls += 1
        return self.context.run_recognition_direct(*args)


comparison_failures = []


class Inspect(CustomAction):
    def run(self,ctx,argv):
        print('TITLE',[(r.text,r.score) for r in inventory._ocr(ctx,image,[260,75,420,80])])
        print('CARDS',inventory._cards(ctx,image))
        inventory.InventoryBegin().run(None, None)
        category = '消耗品' if 'consum' in str(path) else '道具'

        def scan(matcher):
            counted = CountingContext(ctx)
            output = dict(items={}, unknown={})
            started = time.perf_counter()
            with patch.object(inventory, '_match_card', matcher):
                inventory._scan_page(counted, image, category, inventory._catalog(), output, 0)
            return output, counted.calls, time.perf_counter()-started

        reference = scan(reference_match_card)
        optimized = scan(inventory._match_card)
        if reference[0] != optimized[0]:
            comparison_failures.append(f'识别结果不一致: {path}\nREFERENCE {reference[0]}\nOPTIMIZED {optimized[0]}')
        print('MATCHED',[(i['name'],i['quantity']) for i in optimized[0]['items'].values()], 'UNKNOWN',len(optimized[0]['unknown']))
        print(f'PERFORMANCE reference={reference[2]:.3f}s/{reference[1]} calls optimized={optimized[2]:.3f}s/{optimized[1]} calls')
        print('MONEY',inventory._number(ctx,image,[866,30,93,37]),inventory._number(ctx,image,[1012,30,114,37]))
        return True
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
    Toolkit.init_option(temp)
    import os
    os.environ['MBCC_DATA_DIR'] = temp
    resource=Resource()
    assert resource.post_bundle(str(inventory.ROOT/'resource/base')).wait().succeeded
    resource.register_custom_action('InventoryInspect',Inspect())
    controller=Offline()
    controller.post_connection().wait()
    tasker=Tasker()
    tasker.bind(resource,controller)
    for path in sys.argv[1:]:
        image=np.array(Image.open(path).convert('RGB').resize((1280,720)))[:,:,::-1].copy()
        print('IMAGE',path)
        assert tasker.post_task('InventoryInspect',{'InventoryInspect':{'action':'Custom','custom_action':'InventoryInspect'}}).wait().succeeded
    if comparison_failures:
        raise AssertionError('\n'.join(comparison_failures))


