import importlib.util
import json
import pathlib
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("survey_agent", ROOT / "agent/survey.py")
survey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(survey)


def _blank_survey_bgr(h=720, w=1280):
    """Create a white BGR survey canvas with white top header bar."""
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    return img


class SurveyTests(unittest.TestCase):
    def test_webview_header_detection(self):
        white_img = _blank_survey_bgr()
        self.assertTrue(survey.is_survey_webview(white_img))
        dark_img = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.assertFalse(survey.is_survey_webview(dark_img))

    def test_crimson_button_detection_ignores_paragraph_text(self):
        img = _blank_survey_bgr()
        # Draw a crimson button (RGB ~ 200, 10, 35 -> BGR ~ 35, 10, 200) at [590, 560, 100, 36]
        img[560:596, 590:690] = (35, 10, 200)
        items = [
            {"text": "多次填写、重复提交将不会获得额外奖励", "box": [100, 180, 320, 20], "score": 0.99},
            {"text": "提交", "box": [620, 568, 40, 20], "score": 0.99},
        ]
        btn = survey.find_crimson_button(items, img, survey.SUBMIT_KEYWORDS)
        self.assertIsNotNone(btn)
        self.assertEqual("提交", btn["text"])
        self.assertEqual([620, 568, 40, 20], btn["box"])

    def test_rating_rows_detect_unanswered_and_answered_and_quality_check(self):
        img = _blank_survey_bgr()
        # Row 1 (y=200): answered -> coral pink fill (RGB 250, 130, 130 -> BGR 130, 130, 250)
        img[188:212, 100:800] = (130, 130, 250)
        # Row 2 (y=320): unanswered (pure white)
        # Row 3 (y=440): quality check requesting "非常满意" (5)
        items = [
            {"text": "美术评价", "box": [80, 155, 120, 20], "score": 0.98},
            *[
                {"text": str(n), "box": [150 + (n - 1) * 200, 192, 16, 18], "score": 0.99}
                for n in range(1, 6)
            ],
            {"text": "剧情评价", "box": [80, 275, 120, 20], "score": 0.98},
            *[
                {"text": str(n), "box": [150 + (n - 1) * 200, 312, 16, 18], "score": 0.99}
                for n in range(1, 6)
            ],
            {"text": "质检题：本题请选择非常满意", "box": [80, 395, 280, 20], "score": 0.98},
            *[
                {"text": str(n), "box": [150 + (n - 1) * 200, 432, 16, 18], "score": 0.99}
                for n in range(1, 6)
            ],
        ]
        rows = survey.find_rating_rows(items, img, default_rating=4)
        self.assertEqual(3, len(rows))
        self.assertTrue(rows[0]["answered"])
        self.assertFalse(rows[1]["answered"])
        self.assertEqual(4, rows[1]["target_val"])
        self.assertFalse(rows[2]["answered"])
        self.assertEqual(5, rows[2]["target_val"])

    def test_option_blocks_group_skip_selected_and_avoid_other(self):
        img = _blank_survey_bgr()
        # Draw 3 radio controls at x=80..98 in Block 1 (y=200, 240, 280) with first being '其他'
        for y in (200, 240, 280):
            img[y:y + 18, 80:98] = (200, 200, 200)  # gray border
            img[y + 2:y + 16, 82:96] = (255, 255, 255)  # white interior
        # Draw Block 2 (y=420, 460) with option 1 ALREADY selected (crimson red)
        for y in (420, 460):
            img[y:y + 18, 80:98] = (200, 200, 200)
            img[y + 2:y + 16, 82:96] = (255, 255, 255)
        img[424:434, 84:94] = (30, 20, 210)  # crimson selected dot in BGR

        items = [
            {"text": "第一题：请选择来源", "box": [90, 160, 220, 20], "score": 0.98},
            {"text": "其他（请注明）", "box": [112, 200, 160, 18], "score": 0.98},
            {"text": "游戏内公告", "box": [112, 240, 140, 18], "score": 0.98},
            {"text": "社交媒体", "box": [112, 280, 140, 18], "score": 0.98},
            {"text": "第二题：已答题目", "box": [90, 380, 220, 20], "score": 0.98},
            {"text": "选项A", "box": [112, 420, 80, 18], "score": 0.98},
            {"text": "选项B", "box": [112, 460, 80, 18], "score": 0.98},
        ]
        blocks = survey.find_option_blocks(items, img)
        self.assertEqual(2, len(blocks))
        self.assertFalse(blocks[0]["selected"])
        self.assertEqual("游戏内公告", blocks[0]["pick"]["text"])
        self.assertTrue(blocks[1]["selected"])

    def test_matrix_radio_grid_detection(self):
        img = _blank_survey_bgr()
        # Draw 2 rows x 5 light-gray hollow radio circles on the right side
        for row_y in (250, 310):
            for col_x in (440, 520, 600, 680, 760):
                img[row_y:row_y + 18, col_x:col_x + 18] = (195, 195, 195)
                img[row_y + 2:row_y + 16, col_x + 2:col_x + 16] = (255, 255, 255)
        # Mark row 1 col 4 as already selected (crimson dot)
        img[254:264, 684:694] = (30, 20, 210)
        items = [
            {"text": "关卡画面契合度较高", "box": [80, 250, 200, 18], "score": 0.99},
            {"text": "战斗场景契合度较高", "box": [80, 310, 200, 18], "score": 0.99},
        ]
        mrows = survey.find_matrix_radio_rows(items, img, default_rating=4)
        self.assertEqual(2, len(mrows))
        self.assertTrue(mrows[0]["answered"])
        self.assertFalse(mrows[1]["answered"])
        self.assertEqual(4, mrows[1]["target_col"])
        self.assertAlmostEqual(689, mrows[1]["click"][0], delta=3)

    def test_stopping_flag_aborts_immediately(self):
        from unittest.mock import MagicMock
        ctx = MagicMock()
        ctx.tasker.stopping = True
        ctx.tasker.controller.cached_image = _blank_survey_bgr()
        argv = MagicMock()
        argv.custom_action_param = "{}"
        res = survey.SurveyAutoFill().run(ctx, argv)
        self.assertTrue(res)
        ctx.tasker.controller.post_click.assert_not_called()

    def test_interface_registers_manual_survey_task(self):
        interface = json.loads((ROOT / "interface.json").read_text(encoding="utf-8"))
        task = next(t for t in interface["task"] if t["name"] == "问卷调查")
        self.assertEqual("问卷调查", task["entry"])
        self.assertFalse(task["default_check"])
        pipeline = json.loads((ROOT / "resource/base/pipeline/问卷调查.json").read_text(encoding="utf-8"))
        self.assertIn("问卷_自动作答", pipeline)
        self.assertEqual("SurveyAutoFill", pipeline["问卷_自动作答"]["action"]["param"]["custom_action"])


if __name__ == "__main__":
    unittest.main()
