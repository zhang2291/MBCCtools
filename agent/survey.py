"""Universal auto-fill custom action for Path to Nowhere in-game H5 surveys.

Pure Python + NumPy (no OpenCV dependency) so it runs identically on Desktop
Windows and Android MaaFwApp. Works across versions without hardcoding specific
question text: handles consent/resume screens, single/multi-choice options,
1..N satisfaction/matrix rating scales (defaulting to 4 = 比较满意), basic
attention-check prompts, and '未回答' validation recovery (including required
text boxes and multi-select minimums).
"""
import json
import re
import sys
import time

import numpy as np

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.pipeline import JOCR, JRecognitionType

COMPLETION_KEYWORDS = (
    "感谢局长填写",
    "邮件奖励将在",
    "感谢您的参与",
    "感谢参与",
    "提交成功",
    "已完成本次",
    "问卷已提交",
    "您已填写",
    "您已完成",
    "已完成作答",
    "已提交问卷",
    "问卷已结束",
    "奖励已发放",
    "奖励将通过邮件",
)

RESUME_PROMPT_KEYWORDS = ("继续上次作答", "继续作答", "已经回答了部分题目")
CONFIRM_DIALOG_BUTTONS = ("确认", "确定")
CANCEL_DIALOG_BUTTONS = ("取消",)
START_KEYWORDS = ("开始作答", "开始填写")
CONSENT_KEYWORDS = ("我已详细阅读并同意", "同意上述内容", "已阅读并同意")
SUBMIT_KEYWORDS = ("确认提交", "提交问卷", "提交")
NEXT_KEYWORDS = ("下一页", "下一题")
ERROR_KEYWORDS = ("未回答", "请填写", "至少选择", "最少选择", "请至少", "此题为必答")
AVOID_OPTION_KEYWORDS = ("其他", "其它", "请注明", "请填写", "请说明", "手机号", "微信", "QQ", "邮箱")

RATING_WORD_MAP = {
    "非常不满意": 1,
    "很不满意": 1,
    "极不满意": 1,
    "非常不认同": 1,
    "完全不同意": 1,
    "比较不满意": 2,
    "不太满意": 2,
    "不满意": 2,
    "不太认同": 2,
    "比较不认同": 2,
    "一般": 3,
    "比较满意": 4,
    "满意": 4,
    "比较认同": 4,
    "认同": 4,
    "非常满意": 5,
    "很满意": 5,
    "极其满意": 5,
    "非常认同": 5,
    "完全同意": 5,
}


def _log(msg):
    print(f"[MBCCtools-survey] {msg}", file=sys.stderr, flush=True)


def _parse_param(argv):
    raw = getattr(argv, "custom_action_param", None)
    if isinstance(raw, str):
        try:
            return json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _rect_of(box):
    if box is None:
        return None
    if isinstance(box, (list, tuple)) and len(box) == 4:
        return [int(box[0]), int(box[1]), int(box[2]), int(box[3])]
    if all(hasattr(box, k) for k in ("x", "y", "w", "h")):
        return [int(box.x), int(box.y), int(box.w), int(box.h)]
    return None


def _to_rgb(image):
    """Convert MaaFramework BGR image to RGB uint8 view."""
    if image is None or image.ndim != 3 or image.shape[2] < 3:
        return None
    return image[:, :, 2::-1]


def is_survey_webview(image):
    """Detect the white top 'Survey' WebView header bar."""
    rgb = _to_rgb(image)
    if rgb is None:
        return False
    h, w = rgb.shape[:2]
    y0, y1 = max(0, int(h * 0.007)), min(h, int(h * 0.052))
    x0, x1 = int(w * 0.08), int(w * 0.92)
    bar = rgb[y0:y1, x0:x1]
    if bar.size == 0:
        return False
    white = (bar[:, :, 0] > 235) & (bar[:, :, 1] > 235) & (bar[:, :, 2] > 235)
    return float(white.mean()) >= 0.78


def is_crimson_button(image, box):
    """Verify OCR text sits inside a solid crimson-red survey button."""
    rgb = _to_rgb(image)
    if rgb is None or box is None:
        return False
    h, w = rgb.shape[:2]
    x, y, bw, bh = box
    pad_x = max(8, int(w * 0.012))
    pad_y = max(4, int(h * 0.008))
    x0, x1 = max(0, x - pad_x), min(w, x + bw + pad_x)
    y0, y1 = max(0, y - pad_y), min(h, y + bh + pad_y)
    patch = rgb[y0:y1, x0:x1]
    if patch.size == 0:
        return False
    r = patch[:, :, 0].astype(np.int16)
    g = patch[:, :, 1].astype(np.int16)
    b = patch[:, :, 2].astype(np.int16)
    crimson = (r > 140) & ((r - g) > 70) & ((r - b) > 50)
    return float(crimson.mean()) >= 0.28


def _ocr_items(context, image, roi=None, min_score=0.45):
    h, w = image.shape[:2]
    use_roi = roi or [0, int(h * 0.06), w, h - int(h * 0.06)]
    detail = context.run_recognition_direct(
        JRecognitionType.OCR,
        JOCR(roi=use_roi),
        image,
    )
    results = (
        getattr(detail, "all_results", None)
        or getattr(detail, "filtered_results", None)
        or []
    )
    items = []
    for res in results:
        text = (getattr(res, "text", "") or "").strip()
        box = _rect_of(getattr(res, "box", None))
        score = float(getattr(res, "score", 0.0))
        if not text or box is None or score < min_score:
            continue
        items.append({"text": text, "box": box, "score": score})
    items.sort(key=lambda it: (it["box"][1], it["box"][0]))
    return items


def find_crimson_button(items, image, keywords):
    """Find a crimson-red button matching any keyword (exact or tight match)."""
    for kw in keywords:
        for it in items:
            clean = re.sub(r"\s+", "", it["text"])
            if (clean == kw or (len(kw) >= 3 and kw in clean)) and is_crimson_button(image, it["box"]):
                return it
    return None


def find_text_item(items, keywords):
    for kw in keywords:
        for it in items:
            if kw in re.sub(r"\s+", "", it["text"]):
                return it
    return None


def parse_quality_check_rating(header_text, max_val=5):
    """Extract required rating if prompt is an attention/quality check."""
    if not header_text:
        return None
    if not any(k in header_text for k in ("请选择", "请选", "请打", "请勾")):
        return None
    m = re.search(r"请(?:选择|选|打|勾)[^\d]{0,6}(\d+)", header_text)
    if m:
        val = int(m.group(1))
        if 1 <= val <= max_val:
            return val
    # Check longest word first so '非常不满意' beats '满意'
    for word in sorted(RATING_WORD_MAP, key=len, reverse=True):
        if word in header_text:
            val = RATING_WORD_MAP[word]
            if 1 <= val <= max_val:
                return val
    return None


def parse_quality_check_option(header_text, option_texts):
    """Extract matching option index if prompt explicitly requests an option."""
    if not header_text or not any(k in header_text for k in ("请选择", "请选", "请勾")):
        return None
    m = re.search(r"请(?:选择|选|勾)[「【\"“]?([^」】\"”。，,\s]{1,16})", header_text)
    if not m:
        return None
    target = m.group(1)
    for idx, text in enumerate(option_texts):
        if target in text:
            return idx
    return None


def find_rating_rows(items, image, default_rating=4):
    """Detect horizontal rating bars (e.g. 1 | 2 | 3 | 4 | 5) and their state."""
    rgb = _to_rgb(image)
    if rgb is None:
        return []
    h, w = rgb.shape[:2]
    tol_y = max(10, int(h * 0.02))

    # Collect pure small integer tokens in the main white content region
    num_items = []
    for it in items:
        t = it["text"].strip()
        if re.fullmatch(r"\d{1,2}", t):
            val = int(t)
            if 0 <= val <= 10:
                num_items.append((val, it))

    # Group by horizontal band
    rows = []
    for val, it in sorted(num_items, key=lambda x: (x[1]["box"][1], x[1]["box"][0])):
        cy = it["box"][1] + it["box"][3] // 2
        placed = False
        for grp in rows:
            if abs(cy - grp["cy"]) <= tol_y:
                grp["cells"].append((val, it))
                grp["cy"] = int(np.mean([c[1]["box"][1] + c[1]["box"][3] // 2 for c in grp["cells"]]))
                placed = True
                break
        if not placed:
            rows.append({"cy": cy, "cells": [(val, it)]})

    rating_rows = []
    for grp in rows:
        cells = sorted(grp["cells"], key=lambda c: c[1]["box"][0])
        vals = [c[0] for c in cells]
        # Require at least 3 strictly ascending values (e.g. 1,2,3,4,5 or 1..5 with 1 missing)
        if len(vals) < 3 or any(vals[i] >= vals[i + 1] for i in range(len(vals) - 1)):
            continue
        if max(vals) - min(vals) > 10:
            continue
        x0 = max(0, cells[0][1]["box"][0] - int(w * 0.03))
        x1 = min(w, cells[-1][1]["box"][0] + cells[-1][1]["box"][2] + int(w * 0.03))
        y0 = max(0, grp["cy"] - int(h * 0.018))
        y1 = min(h, grp["cy"] + int(h * 0.018))
        band = rgb[y0:y1, x0:x1]
        r = band[:, :, 0].astype(np.int16)
        g = band[:, :, 1].astype(np.int16)
        b = band[:, :, 2].astype(np.int16)
        coral = (r > 190) & ((r - g) > 30) & ((r - b) > 30)
        answered = int(coral.sum()) >= max(80, int(band.shape[0] * band.shape[1] * 0.05))

        # Look for header text directly above this rating row (within 65px on 720p)
        header_parts = [
            it["text"]
            for it in items
            if grp["cy"] - int(h * 0.11) <= (it["box"][1] + it["box"][3] // 2) < grp["cy"] - int(h * 0.025)
            and not re.fullmatch(r"\d{1,2}", it["text"].strip())
        ]
        header_text = " ".join(header_parts)
        desired = parse_quality_check_rating(header_text, max_val=max(vals))
        if desired is None:
            desired = default_rating if default_rating in vals else vals[-2]

        # Find closest cell to desired rating
        target_cell = min(cells, key=lambda c: abs(c[0] - desired))
        tb = target_cell[1]["box"]
        rating_rows.append({
            "cy": grp["cy"],
            "vals": vals,
            "answered": answered,
            "target_val": target_cell[0],
            "click": (tb[0] + tb[2] // 2, tb[1] + tb[3] // 2),
        })

    rating_rows.sort(key=lambda r: r["cy"])
    return rating_rows


def is_control_widget(patch):
    """Return (is_widget, is_selected) for an RGB patch of a ○/□ or ◉/☑ control.

    Distinguishes hollow light-gray / crimson survey controls from dark Chinese text.
    """
    if patch is None or patch.size == 0:
        return False, False
    ph, pw = patch.shape[:2]
    if ph < 11 or pw < 11 or ph > 28 or pw > 28 or abs(ph - pw) > 6:
        return False, False
    r = patch[:, :, 0].astype(np.int16)
    g = patch[:, :, 1].astype(np.int16)
    b = patch[:, :, 2].astype(np.int16)
    red_px = int(((r > 150) & ((r - g) > 55) & ((r - b) > 50)).sum())
    if red_px >= max(12, int(pw * ph * 0.04)):
        return True, True
    # Unselected ○ / □: light-gray outline with virtually no dark text ink (<130)
    dark_px = int(((r < 130) & (g < 130) & (b < 130)).sum())
    if dark_px > max(2, int(pw * ph * 0.015)):
        return False, False
    # Center interior must be mostly light/white (hollow circle/square; supports #F0F0F0..#FFFFFF backgrounds)
    cy0, cy1 = int(ph * 0.30), max(int(ph * 0.30) + 1, int(ph * 0.70))
    cx0, cx1 = int(pw * 0.30), max(int(pw * 0.30) + 1, int(pw * 0.70))
    center = patch[cy0:cy1, cx0:cx1]
    if center.size == 0 or float((center.mean(axis=2) > 225).mean()) < 0.75:
        return False, False
    non_white = (r < 228) | (g < 228) | (b < 228)
    if int(non_white.sum()) < max(14, int((pw + ph) * 0.65)):
        return False, False
    return True, False


def find_matrix_radio_rows(items, image, default_rating=4):
    """Detect horizontal matrix radio grids regardless of left-side text or banner artwork.

    Uses a 2D light-halo integral filter + coarse 4x4 connected components so colorful
    banners (e.g. gacha/event artwork) on the left never suppress or spoof circles on the right.
    """
    rgb = _to_rgb(image)
    if rgb is None:
        return []
    h, w = rgb.shape[:2]
    y0, y1 = int(h * 0.10), int(h * 0.96)
    x0, x1 = int(w * 0.11), int(w * 0.96)
    reg = rgb[y0:y1, x0:x1]
    if reg.size == 0:
        return []

    r = reg[:, :, 0].astype(np.int16)
    g = reg[:, :, 1].astype(np.int16)
    b = reg[:, :, 2].astype(np.int16)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)

    # Neutral light-gray circle outline OR crimson selected circle
    gray_outline = (mn >= 130) & (mx <= 228) & ((mx - mn) <= 22)
    red_fill = (r > 150) & ((r - g) > 55) & ((r - b) > 50)
    cand = gray_outline | red_fill

    # Erase only long horizontal table divider segments (>= 30px continuous runs), never whole rows
    rh, rw = cand.shape
    if rw > 36:
        csum = np.cumsum(np.pad(gray_outline.astype(np.int32), ((0, 0), (1, 0))), axis=1)
        win = csum[:, 35:] - csum[:, :-35]
        for ry in np.where(win.max(axis=1) >= 30)[0]:
            padded = np.concatenate(([False], cand[ry], [False]))
            starts = np.where(padded[1:] & ~padded[:-1])[0]
            ends = np.where(~padded[1:] & padded[:-1])[0]
            for s, e in zip(starts, ends):
                if e - s >= 30:
                    cand[ry, s:e] = False

    # Require local 29x29 neighborhood to be >=50% light paper (eliminates all artwork/banners)
    light = (r > 225) & (g > 225) & (b > 225)
    pad = max(10, int(h * 0.019))
    ii = np.pad(light.astype(np.int32), ((pad + 1, pad), (pad + 1, pad)), mode="constant").cumsum(axis=0).cumsum(axis=1)
    span = 2 * pad + 1
    light_cnt = ii[span:, span:] - ii[:-span, span:] - ii[span:, :-span] + ii[:-span, :-span]
    cand &= light_cnt >= int(span * span * 0.50)

    # Fast 4x4 grid BFS to isolate individual circle boxes
    bh, bw = rh // 4, rw // 4
    if bh == 0 or bw == 0:
        return []
    grid = cand[:bh * 4, :bw * 4].reshape(bh, 4, bw, 4).any(axis=(1, 3))
    visited = np.zeros_like(grid)
    ys_g, xs_g = np.where(grid)
    max_comp = max(32, int(h * 0.048))
    circles = []
    for gy, gx in zip(ys_g, xs_g):
        if visited[gy, gx]:
            continue
        stack = [(int(gy), int(gx))]
        visited[gy, gx] = True
        min_y = max_y = int(gy)
        min_x = max_x = int(gx)
        while stack:
            cy_g, cx_g = stack.pop()
            if cy_g < min_y:
                min_y = cy_g
            if cy_g > max_y:
                max_y = cy_g
            if cx_g < min_x:
                min_x = cx_g
            if cx_g > max_x:
                max_x = cx_g
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = cy_g + dy, cx_g + dx
                    if 0 <= ny < bh and 0 <= nx < bw and grid[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
        py0, py1 = max(0, min_y * 4 - 2), min(rh, (max_y + 1) * 4 + 2)
        px0, px1 = max(0, min_x * 4 - 2), min(rw, (max_x + 1) * 4 + 2)
        if not (10 <= py1 - py0 <= max_comp and 10 <= px1 - px0 <= max_comp):
            continue
        sub = cand[py0:py1, px0:px1]
        sy, sx = np.where(sub)
        if sy.size == 0:
            continue
        ty0, ty1 = y0 + py0 + int(sy.min()), y0 + py0 + int(sy.max()) + 1
        tx0, tx1 = x0 + px0 + int(sx.min()), x0 + px0 + int(sx.max()) + 1
        ok, sel = is_control_widget(rgb[ty0:ty1, tx0:tx1])
        if not ok:
            continue
        # Verify narrow light halo on left and right outside the control
        hl = rgb[ty0:ty1, max(0, tx0 - 4):max(1, tx0 - 1)]
        hr = rgb[ty0:ty1, min(w - 1, tx1 + 1):min(w, tx1 + 4)]
        if hl.size and float((hl.mean(axis=2) > 225).mean()) < 0.70:
            continue
        if hr.size and float((hr.mean(axis=2) > 225).mean()) < 0.70:
            continue
        circles.append({
            "x": tx0,
            "y": ty0,
            "w": tx1 - tx0,
            "h": ty1 - ty0,
            "cx": (tx0 + tx1) // 2,
            "cy": (ty0 + ty1) // 2,
            "selected": sel,
        })

    # Group circles into horizontal matrix rows
    tol_y = max(12, int(h * 0.018))
    grouped = []
    for c in sorted(circles, key=lambda d: (d["cy"], d["cx"])):
        placed = False
        for grp in grouped:
            if abs(c["cy"] - grp["cy"]) <= tol_y:
                grp["circles"].append(c)
                placed = True
                break
        if not placed:
            grouped.append({"cy": c["cy"], "circles": [c]})

    matrix_rows = []
    for grp in grouped:
        row_circles = sorted(grp["circles"], key=lambda c: c["cx"])
        if len(row_circles) < 2:
            continue
        cy = int(np.mean([c["cy"] for c in row_circles]))
        answered = any(c["selected"] for c in row_circles)
        row_label = " ".join(
            it["text"]
            for it in items
            if it["box"][0] < row_circles[0]["x"]
            and abs((it["box"][1] + it["box"][3] // 2) - cy) <= max(16, int(h * 0.025))
        )
        desired = parse_quality_check_rating(row_label, max_val=len(row_circles))
        if desired is None:
            col_idx = min(max(0, default_rating - 1), len(row_circles) - 1)
        else:
            col_idx = min(max(0, desired - 1), len(row_circles) - 1)
        pick = row_circles[col_idx]
        matrix_rows.append({
            "cy": cy,
            "label": row_label,
            "answered": answered,
            "target_col": col_idx + 1,
            "click": (pick["cx"], pick["cy"]),
        })
    matrix_rows.sort(key=lambda r: r["cy"])
    return matrix_rows


def find_option_blocks(items, image):
    """Detect vertical radio/checkbox controls on the left margin and group into question blocks."""
    rgb = _to_rgb(image)
    if rgb is None:
        return []
    h, w = rgb.shape[:2]

    # Left control strip: x in [5.7%, 7.9%] of width (73..101 on 1280px), strictly isolating 18x18 ○/□ from text
    sx0, sx1 = int(w * 0.057), int(w * 0.079)
    sy0, sy1 = int(h * 0.065), int(h * 0.96)
    strip = rgb[sy0:sy1, sx0:sx1]
    if strip.size == 0:
        return []

    non_white = (strip[:, :, 0] < 236) | (strip[:, :, 1] < 236) | (strip[:, :, 2] < 236)
    row_counts = non_white.sum(axis=1)

    min_sz = max(12, int(h * 0.017))
    max_sz = max(24, int(h * 0.036))

    controls = []
    in_band = False
    start = 0
    for idx, cnt in enumerate(row_counts):
        if cnt >= 2 and not in_band:
            in_band = True
            start = idx + sy0
        elif cnt < 2 and in_band:
            in_band = False
            end = idx + sy0
            bh = end - start
            if min_sz <= bh <= max_sz:
                patch = rgb[start:end, sx0:sx1]
                mask = (patch[:, :, 0] < 236) | (patch[:, :, 1] < 236) | (patch[:, :, 2] < 236)
                xs = np.where(mask)[1]
                if xs.size == 0:
                    continue
                x_rel0, x_rel1 = int(xs.min()), int(xs.max()) + 1
                bw = x_rel1 - x_rel0
                if min_sz <= bw <= max_sz:
                    cx0 = sx0 + x_rel0
                    cy = (start + end) // 2
                    ok, selected = is_control_widget(rgb[start:end, cx0:cx0 + bw])
                    if not ok:
                        continue
                    # Pair with OCR text on the same row extending to the right of the control
                    row_texts = [
                        it["text"]
                        for it in items
                        if (it["box"][0] + it["box"][2]) > (cx0 + bw + 8)
                        and abs((it["box"][1] + it["box"][3] // 2) - cy) <= max(14, int(h * 0.022))
                    ]
                    if not row_texts:
                        continue
                    controls.append({
                        "x": cx0,
                        "y": start,
                        "w": bw,
                        "h": bh,
                        "cy": cy,
                        "selected": selected,
                        "text": " ".join(row_texts),
                        "click": (cx0 + bw // 2, cy),
                    })

    if not controls:
        return []

    # Group controls into question blocks.
    # Split whenever there is a non-option question header between two controls or gap > 68px (on 720p).
    max_gap = max(62, int(h * 0.095))
    blocks = []
    cur = [controls[0]]
    for prev, nxt in zip(controls, controls[1:]):
        gap = nxt["cy"] - prev["cy"]
        # Check if an OCR header line sits strictly between prev and nxt
        mid_headers = [
            it for it in items
            if prev["y"] + prev["h"] + 4 < (it["box"][1] + it["box"][3] // 2) < nxt["y"] - 4
            and it["box"][0] <= int(w * 0.25)
        ]
        if gap > max_gap or mid_headers:
            blocks.append(cur)
            cur = [nxt]
        else:
            cur.append(nxt)
    blocks.append(cur)

    # Enrich each block with header text and chosen click target
    result = []
    for blk in blocks:
        top_y = blk[0]["y"]
        headers = [
            it["text"]
            for it in items
            if top_y - int(h * 0.14) <= (it["box"][1] + it["box"][3] // 2) < top_y - 4
            and not any(abs((it["box"][1] + it["box"][3] // 2) - c["cy"]) <= 12 for c in controls)
        ]
        header_text = " ".join(headers)
        selected = any(c["selected"] for c in blk)
        opt_texts = [c["text"] for c in blk]

        # Decide best option index if unanswered
        pick_idx = parse_quality_check_option(header_text, opt_texts)
        if pick_idx is None:
            # Prefer '比较满意' if this radio block is a satisfaction scale
            for i, t in enumerate(opt_texts):
                if "比较满意" in t:
                    pick_idx = i
                    break
        if pick_idx is None:
            # Prefer first option that does NOT trigger '其他/请填写' text input
            for i, t in enumerate(opt_texts):
                if not any(kw in t for kw in AVOID_OPTION_KEYWORDS):
                    pick_idx = i
                    break
        if pick_idx is None:
            pick_idx = 0

        result.append({
            "top_y": top_y,
            "bottom_y": blk[-1]["y"] + blk[-1]["h"],
            "header": header_text,
            "selected": selected,
            "options": blk,
            "pick": blk[pick_idx],
        })
    return result


def find_consent_click(image, consent_box):
    """Locate the consent checkbox (either inside left edge or just left of OCR text).

    Returns (x, y) to click, or None if already ticked (crimson red pixels present).
    """
    rgb = _to_rgb(image)
    bx, by, bw, bh = consent_box
    cy = by + bh // 2
    if rgb is None:
        return (bx + 10, cy)
    h, w = rgb.shape[:2]
    x0 = max(0, bx - int(w * 0.025))
    x1 = min(w, bx + int(w * 0.028))
    y0 = max(0, cy - max(12, bh))
    y1 = min(h, cy + max(12, bh))
    patch = rgb[y0:y1, x0:x1]
    if patch.size == 0:
        return (bx + 10, cy)
    r = patch[:, :, 0].astype(np.int16)
    g = patch[:, :, 1].astype(np.int16)
    b = patch[:, :, 2].astype(np.int16)
    # Already ticked checkbox shows crimson/red checkmark
    if int(((r > 150) & ((r - g) > 55) & ((r - b) > 50)).sum()) >= 12:
        return None
    non_white = (patch[:, :, 0] < 235) | (patch[:, :, 1] < 235) | (patch[:, :, 2] < 235)
    cols = np.where(non_white.sum(axis=0) >= 3)[0]
    if cols.size > 0:
        left_x = x0 + int(cols[0])
        return (left_x + max(7, int(w * 0.007)), cy)
    return (bx + 10, cy)


def _frame_diff(img1, img2):
    if img1 is None or img2 is None or img1.shape != img2.shape:
        return 999.0
    return float(np.abs(img1.astype(np.float32) - img2.astype(np.float32)).mean())


@AgentServer.custom_action("SurveyAutoFill")
class SurveyAutoFill(CustomAction):
    """Automatically fill and submit the open Path to Nowhere H5 survey."""

    def run(self, context, argv):
        param = _parse_param(argv)
        max_steps = int(param.get("max_steps", 120))
        default_rating = int(param.get("default_rating", 4))
        fill_text = str(param.get("fill_text", "无"))
        ctrl = context.tasker.controller

        def is_stopping():
            try:
                return bool(getattr(context.tasker, "stopping", False))
            except Exception:
                return False

        def screencap():
            ctrl.post_screencap().wait()
            return ctrl.cached_image

        def tap(x, y, delay=0.35):
            if is_stopping():
                return False
            ctrl.post_click(int(x), int(y)).wait()
            if delay > 0 and not is_stopping():
                time.sleep(delay)
            return True

        def swipe_down_page(h, w):
            if is_stopping():
                return False
            ctrl.post_swipe(w // 2, int(h * 0.80), w // 2, int(h * 0.30), 450).wait()
            if not is_stopping():
                time.sleep(0.65)
            return True

        # Wait briefly for Survey WebView to finish loading
        img = screencap()
        for _ in range(6):
            if is_stopping():
                _log("收到停止指令，立即中止问卷填写")
                return True
            if is_survey_webview(img):
                break
            time.sleep(0.6)
            img = screencap()

        if not is_survey_webview(img):
            _log("未检测到 Survey 问卷页面，直接结束")
            return True

        h, w = img.shape[:2]
        close_btn = (int(w * 0.969), int(h * 0.035))
        stale_scrolls = 0
        error_retries = 0
        prev_img = None

        for step in range(1, max_steps + 1):
            if is_stopping():
                _log("收到停止指令，立即退出问卷填写")
                return True

            img = screencap()
            if not is_survey_webview(img):
                _log("问卷窗口已关闭，结束自动填写")
                return True

            items = _ocr_items(context, img)
            all_text = " ".join(it["text"] for it in items)

            # 1. Completion check
            if any(kw in all_text for kw in COMPLETION_KEYWORDS):
                _log(f"第 {step} 步检测到问卷完成页，关闭弹窗返回主页")
                tap(close_btn[0], close_btn[1], delay=1.2)
                return True

            # 2. Resume / Confirm popup (e.g. "您之前已经回答了部分题目，是否继续上次作答？" + "取消 / 确认")
            confirm_btn = find_text_item(items, CONFIRM_DIALOG_BUTTONS)
            cancel_btn = find_text_item(items, CANCEL_DIALOG_BUTTONS)
            is_resume_dialog = any(kw in all_text for kw in RESUME_PROMPT_KEYWORDS) and not any(
                kw in all_text for kw in ("关闭问卷", "退出游戏", "可在主界面")
            )
            if confirm_btn and (cancel_btn or is_resume_dialog):
                bx, by, bw, bh = confirm_btn["box"]
                _log(f"第 {step} 步检测到确认弹窗，点击「{confirm_btn['text']}」")
                tap(bx + bw // 2, by + bh // 2, delay=1.3)
                stale_scrolls = 0
                error_retries = 0
                continue

            # 3. Landing consent + Start button
            start_btn = find_crimson_button(items, img, START_KEYWORDS)
            if start_btn:
                consent = find_text_item(items, CONSENT_KEYWORDS)
                if consent:
                    pos = find_consent_click(img, consent["box"])
                    if pos is not None:
                        _log(f"第 {step} 步勾选隐私同意 {pos} 并点击「{start_btn['text']}」")
                        tap(pos[0], pos[1], delay=0.4)
                bx, by, bw, bh = start_btn["box"]
                tap(bx + bw // 2, by + bh // 2, delay=1.4)
                stale_scrolls = 0
                error_retries = 0
                continue

            # 4. Detect all widgets on current viewport
            err_item = find_text_item(items, ERROR_KEYWORDS)
            rating_rows = find_rating_rows(items, img, default_rating=default_rating)
            matrix_rows = find_matrix_radio_rows(items, img, default_rating=default_rating)
            option_blocks = find_option_blocks(items, img)

            acted = False

            # 4a. Fill all visible unanswered rating rows (1..5 bars, default 4 = 比较满意)
            for r in rating_rows:
                if not r["answered"]:
                    _log(f"第 {step} 步填写评分条 y={r['cy']} -> {r['target_val']}")
                    if not tap(r["click"][0], r["click"][1], delay=0.25):
                        return True
                    acted = True

            # 4b. Fill all visible unanswered matrix radio rows (○ ○ ○ ○ ○ grid, default col 4 = 比较认同/满意)
            for mr in matrix_rows:
                if not mr["answered"]:
                    _log(f"第 {step} 步填写矩阵单选 y={mr['cy']} -> 第 {mr['target_col']} 列")
                    if not tap(mr["click"][0], mr["click"][1], delay=0.25):
                        return True
                    acted = True

            # 4c. Fill all visible unanswered vertical radio/checkbox blocks (only once per block!)
            for blk in option_blocks:
                if not blk["selected"]:
                    pick = blk["pick"]
                    _log(f"第 {step} 步勾选题目选项 -> {pick['text']}")
                    if not tap(pick["click"][0], pick["click"][1], delay=0.28):
                        return True
                    acted = True

            # 4d. If validation error is shown AND steps 4a-4c found nothing unanswered
            # (e.g. multi-select minimum >= 2 not met, or required open-ended textarea!)
            if err_item and not acted:
                err_y = err_item["box"][1]
                error_retries += 1
                _log(f"第 {step} 步处理校验提示「{err_item['text']}」at y={err_y} (第 {error_retries} 次)")
                if error_retries > 6:
                    _log("校验错误连续多次无法消除，安全退出避免死循环")
                    return True
                # Try picking an additional unselected checkbox in the block below error
                below_blocks = [b for b in option_blocks if b["bottom_y"] >= err_y]
                if below_blocks:
                    blk = below_blocks[0]
                    unselected = [
                        o for o in blk["options"]
                        if not o["selected"] and not any(kw in o["text"] for kw in AVOID_OPTION_KEYWORDS)
                    ] or [o for o in blk["options"] if not o["selected"]]
                    if unselected:
                        pick = unselected[0]
                        _log(f"补选多选校验项: {pick['text']}")
                        if not tap(pick["click"][0], pick["click"][1], delay=0.3):
                            return True
                        acted = True
                # Otherwise assume a required textarea / input box below the error badge
                if not acted:
                    input_x = int(w * 0.35)
                    input_y = min(int(h * 0.85), err_y + int(h * 0.12))
                    _log(f"尝试在必填文本框 ({input_x}, {input_y}) 输入「{fill_text}」")
                    if not tap(input_x, input_y, delay=0.5):
                        return True
                    if not is_stopping():
                        ctrl.post_input_text(fill_text).wait()
                        time.sleep(0.4)
                        tap(int(w * 0.92), int(h * 0.12), delay=0.4)
                    acted = True
            elif not err_item:
                error_retries = 0

            # 5. Look for crimson Submit / Next button
            action_btn = (
                find_crimson_button(items, img, SUBMIT_KEYWORDS)
                or find_crimson_button(items, img, NEXT_KEYWORDS)
            )
            if action_btn:
                bx, by, bw, bh = action_btn["box"]
                _log(f"第 {step} 步点击底部按钮「{action_btn['text']}」")
                if not tap(bx + bw // 2, by + bh // 2, delay=1.2):
                    return True
                stale_scrolls = 0
                prev_img = img
                continue

            # 6. No bottom button yet -> scroll down to reveal remaining questions / button
            if acted:
                prev_img = img
                if not swipe_down_page(h, w):
                    return True
                stale_scrolls = 0
                continue

            diff = _frame_diff(prev_img, img)
            if diff < 1.2:
                stale_scrolls += 1
                if stale_scrolls >= 3:
                    _log("连续多次滚动画面未变化且无按钮，关闭问卷避免死循环")
                    tap(close_btn[0], close_btn[1], delay=1.0)
                    return True
            else:
                stale_scrolls = 0
            prev_img = img
            if not swipe_down_page(h, w):
                return True

        _log(f"已达到最大步数上限 ({max_steps})，安全退出问卷任务")
        return True
