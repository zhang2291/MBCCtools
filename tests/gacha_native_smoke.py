"""Real MaaFramework/AgentClient handshake with a blank offline controller, never a game device."""
import os
import pathlib
import subprocess
import sys
import tempfile
import json

import numpy as np
from maa.agent_client import AgentClient
from maa.controller import CustomController
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

ROOT = pathlib.Path(__file__).resolve().parents[1]


class OfflineController(CustomController):
    def __init__(self):
        super().__init__()
        self.clicks = []
        self.frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    def connect(self): return True
    def request_uuid(self): return 'offline-gacha-test'
    def start_app(self, intent): return False
    def stop_app(self, intent): return False
    def get_features(self): return 0
    def screencap(self): return self.frame
    def click(self, x, y):
        self.clicks.append((x, y))
        return True
    def swipe(self, *args): return False
    def touch_down(self, *args): return False
    def touch_move(self, *args): return False
    def touch_up(self, *args): return False
    def click_key(self, *args): return False
    def input_text(self, *args): return False
    def key_down(self, *args): return False
    def key_up(self, *args): return False


with tempfile.TemporaryDirectory(prefix='mbcc-gacha-native-', ignore_cleanup_errors=True) as temp:
    Toolkit.init_option(temp)
    resource = Resource()
    assert resource.post_bundle(str(ROOT / 'resource/base')).wait().succeeded
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    client = AgentClient.create_tcp(0)
    assert client.bind(resource)
    env = dict(os.environ, MBCC_DATA_DIR=str(pathlib.Path(temp) / 'data'), PYTHONUTF8='1')
    with open(pathlib.Path(temp) / 'agent.log', 'w+', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, str(ROOT / 'agent/main.py'), client.identifier], cwd=temp, env=env, stdout=log, stderr=log)
        try:
            assert client.connect(), 'Agent handshake failed'
            tasker = Tasker()
            tasker.bind(resource, controller)
            assert tasker.inited
            assert tasker.post_task('抽卡记录_开始采集', {'抽卡记录_开始采集': {'next': ['抽卡记录汇总']}}).wait().succeeded
            # No game record header on a black frame: must exit without ANY click.
            job = tasker.post_task('抽卡记录', {'抽卡记录_开始采集': {'next': ['抽卡记录_识别追踪类型'], 'timeout': 300}}).wait()
            assert not job.succeeded, 'Off-page collection should fail without pretending it collected data'
            assert controller.clicks == [], 'Unexpected click outside record page'
            assert not list((pathlib.Path(temp) / 'data').rglob('*.jsonl'))
            print('PASS: actual Maa 5.13.1 resource load, TCP Agent handshake, Custom action/OCR guard, zero clicks outside record page')
            if '--synthetic' in sys.argv:
                from PIL import Image, ImageDraw, ImageFont
                image = Image.new('RGB', (1280, 720), 'white')
                draw = ImageDraw.Draw(image)
                font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 20)
                draw.text((416, 222), '活动追踪 近期抽卡记录(UTC+8)', font=font, fill='black')
                for y in (300, 345):
                    draw.text((445, y), '2026-10-15 10:00:00', font=font, fill='black')
                    draw.text((700, y), '测试卡池', font=font, fill='black')
                    draw.text((940, y), '测试角色', font=font, fill='black')
                draw.text((748, 629), '1', font=font, fill='black')
                controller.frame = np.array(image)[:, :, ::-1].copy()
                # Restore task overrides after the off-page test. This is an artificial single page.
                override = {'抽卡记录_开始采集': {'timeout': 3000, 'next': ['抽卡记录_识别追踪类型']}}
                assert tasker.post_task('抽卡记录', override).wait().succeeded
                files = list((pathlib.Path(temp) / 'data/record/抽卡记录').glob('*.jsonl'))
                collected = [json.loads(line) for file in files for line in file.read_text(encoding='utf-8').splitlines()]
                assert len(collected) == 2, collected
                assert collected[0]['key'] == collected[1]['key'], collected
                assert tasker.post_task('抽卡记录', override).wait().succeeded
                assert sum(len(file.read_text(encoding='utf-8').splitlines()) for file in files) == 2
                assert (pathlib.Path(temp) / 'data/record/抽卡记录.xlsx').exists()
                print('PASS: synthetic-frame native OCR -> two identical pulls -> page stall -> export -> repeat run without duplicates (NOT a game/device test)')
        finally:
            client.disconnect()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
            log.seek(0)
            print(log.read()[-3000:])
