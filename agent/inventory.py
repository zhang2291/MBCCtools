"""仓库只读扫描。运行期只截图和滑动，绝不点击物品或确认使用。"""
import datetime
import hashlib
from dataclasses import asdict
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import sys
import time

import numpy as np
from PIL import Image
from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.pipeline import JOCR, JOr, JRecognitionType, JTemplateMatch

ROOT = Path(__file__).resolve().parent.parent
COLUMNS = (290, 454, 616, 779, 942, 1105)
_session = None


def _log(message):
    print(f'[MBCCtools-inventory] {message}', file=sys.stderr, flush=True)


def _params(argv):
    raw = getattr(argv, 'custom_action_param', {})
    return json.loads(raw) if isinstance(raw, str) and raw else raw or {}


def _root():
    return Path(os.environ.get('MBCC_DATA_DIR', str(ROOT / 'data'))) / 'inventory'


def parse_quantity(text):
    """只接受完整整数；不能把 OCR 噪声中的数字拼成库存。"""
    text = text.strip().replace(',', '').replace('，', '')
    return int(text) if re.fullmatch(r'[0-9]+', text) else None


def _results(detail):
    return getattr(detail, 'filtered_results', None) or getattr(detail, 'all_results', None) or []


def _box(result):
    box = getattr(result, 'box', None)
    if hasattr(box, 'x'):
        return [box.x, box.y, box.w, box.h]
    return list(box) if box is not None else None


def _ocr(context, image, roi):
    return _results(context.run_recognition_direct(JRecognitionType.OCR, JOCR(roi=roi, threshold=.75), image))


def _number(context, image, roi, only_rec=False):
    results = _results(context.run_recognition_direct(JRecognitionType.OCR, JOCR(roi=roi, threshold=.75, only_rec=only_rec), image))
    values = {parse_quantity(r.text) for r in results
              if getattr(r, 'score', 0) >= .75}
    values.discard(None)
    return next(iter(values)) if len(values) == 1 else None


def _snapshot(controller):
    controller.post_screencap().wait()
    array = controller.cached_image
    if array is None or array.size == 0:
        raise ValueError('仓库截图为空')
    # Maa 截图是 BGR；保持该顺序给 Maa，写 PNG 时才转 RGB。
    if array.shape[:2] != (720, 1280):
        array = np.array(Image.fromarray(array).resize((1280, 720)))
    return array


def _save_image(path, image):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image[:, :, :3][:, :, ::-1]).save(path)


def _same_page(a, b):
    # 排除顶栏动态体力和背景，只比较物品列表。
    difference = np.abs(a[185:644:4, 290:1240:4].astype(float)
                        - b[185:644:4, 290:1240:4].astype(float))
    return bool(difference.mean() < 1.5 or
                ((difference.max(axis=2) > 20).mean() < .015 and np.median(difference) < 4))


def _swipe(controller, down):
    # 纵向半页，保留重叠；不得改成点击物品探测。
    # 等滑动和惯性滚动结束再截图，不能把滑动前的旧帧当作底部稳定画面。
    start, end = (605, 455) if down else (455, 605)
    controller.post_swipe(1220, start, 1220, end, 1500).wait()
    time.sleep(.65)
    return _snapshot(controller)


def _cards(context, image):
    """逐格找浅色卡片顶边；不由数量反推整行，避免把数量栏当下一行。"""
    cards = []
    for x in COLUMNS:
        # 顶边跨越整张卡，且比上下邻域亮；物品图标和背景一般没有这种细长边。
        gray = image[:, x+5:x+100].min(axis=2).astype(float)
        contrast = gray - (np.roll(gray, 3, axis=0)+np.roll(gray, -3, axis=0))/2
        strength = contrast.mean(axis=1)
        coverage = (contrast > 35).mean(axis=1)
        groups = []
        for y in range(184, 483):
            if strength[y] < 60 or coverage[y] < .70:
                continue
            if groups and y-groups[-1][-1] <= 4:
                groups[-1].append(y)
            else:
                groups.append([y])
        for group in groups:
            top = max(group, key=lambda y: strength[y])
            bottom = top+172
            end = min(bottom-4, 644)
            if end-(bottom-29) < 15:
                continue  # 数字也被底部遮挡，下一页再识别
            quantity_crop = image[bottom-29:end, x+48:x+130]
            white = quantity_crop.min(axis=2) > 140
            ys, xs = np.where(white)
            # 白像素极少说明数字区域为空或被遮挡，跳过 OCR 节省时间。
            if white.sum() < 15:
                cards.append((x, top, None))
                continue
            if len(xs):
                quantity_crop = quantity_crop[max(0,ys.min()-2):ys.max()+3, max(0,xs.min()-2):xs.max()+3]
            enlarged = np.repeat(np.repeat(quantity_crop, 3, axis=0), 3, axis=1)
            quantity = _number(context, enlarged, [0, 0, enlarged.shape[1], enlarged.shape[0]], only_rec=True)
            cards.append((x, top, quantity))
    return sorted(cards, key=lambda card: (card[1], card[0]))


def merge_item(items, item):
    """滚动重叠是同一库存，不能相加；不同读数保留冲突用于复核。"""
    key = item['id']
    existing = items.get(key)
    if existing is None:
        items[key] = item
    elif existing['quantity'] != item['quantity']:
        existing['conflicting_quantities'] = sorted(set(
            existing.get('conflicting_quantities', [existing['quantity']]) + [item['quantity']]), key=lambda value: -1 if value is None else value)
    return items[key]


def _catalog():
    path = ROOT / 'resource/base/image/仓库/catalog.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    return data['items']


@lru_cache(maxsize=512)
def _template_color(template):
    path = ROOT / 'resource/base/image' / template
    return np.array(Image.open(path).convert('RGB').resize((16, 16))).astype(float)


def _color_matches(image, match, template):
    box = _box(match)
    if box is None:
        return False
    x, y, w, h = box
    patch = image[y:y+h, x:x+w, :3][:, :, ::-1]
    if not patch.size:
        return False
    actual = np.array(Image.fromarray(patch).resize((16, 16))).astype(float)
    # Maa TemplateMatch 默认灰度；同轮廓蓝/紫物品必须再核对颜色。
    return float(np.abs(actual-_template_color(template)).mean()) <= 10


def _match_card(context, image, category, catalog, roi):
    remaining = [entry for entry in catalog if entry['category'] == category]
    candidates = []
    while remaining:
        any_of = [dict(recognition=JRecognitionType.TemplateMatch,
                       **asdict(JTemplateMatch(template=[entry['template']], roi=roi,
                                              threshold=[entry.get('threshold', .88)])),
                       sub_name=entry['id']) for entry in remaining]
        detail = context.run_recognition_direct(JRecognitionType.Or, JOr(any_of=any_of), image)
        sub_results = getattr(getattr(detail, 'best_result', None), 'sub_results', None)
        if not sub_results or len(sub_results) > len(remaining):
            raise ValueError('模板批量识别返回了无效的子结果')
        for index, sub in enumerate(sub_results):
            entry = remaining[index]
            if sub.name != entry['id'] or (index < len(sub_results)-1 and sub.hit):
                raise ValueError('模板批量识别的子结果顺序或名称不一致')
            if len(sub_results) < len(remaining) and index == len(sub_results)-1 and not sub.hit:
                raise ValueError('模板批量识别在命中前意外终止')
            matches = _results(sub)
            best = getattr(sub, 'best_result', None)
            if not matches and best is not None:
                matches = [best]
            for match in matches:
                score = float(getattr(match, 'score', 0))
                if score >= entry.get('threshold', .88) and _color_matches(image, match, entry['template']):
                    candidates.append((score, entry))
        remaining = remaining[len(sub_results):]
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return candidates


def _scan_page(context, image, category, catalog, output, page, match_cache=None):
    cards = _cards(context, image)
    folder = _root() / 'captures' / _session['run_id'] / category
    _save_image(folder / f'page-{page:02}.png', image)
    if match_cache is None:
        match_cache = {}
    for x, y, quantity in cards:
        if getattr(context.tasker, 'stopping', False):
            raise InterruptedError('用户停止')
        crop = image[y+16:y+134, x+8:x+126]
        # 半页滚动会重复显示上一页的物品，相同图标裁图可复用模板匹配结果。
        # 数量仍逐页 OCR，且 merge_item 继续检查跨页数量冲突。
        crop_digest = hashlib.sha256(crop.tobytes()).hexdigest()
        # The recognition ROI is wider than the saved icon crop; key the exact ROI and
        # category so visually identical cards from different categories never cross-contaminate.
        match_key = (category, hashlib.sha256(image[y:y+145, x:x+136].tobytes()).hexdigest())
        candidates = match_cache.get(match_key)
        if candidates is None:
            candidates = _match_card(context, image, category, catalog, [x, y, 136, 145])
            match_cache[match_key] = candidates
        if (candidates and not candidates[0][1].get('ambiguous', False)
                and (len(candidates) == 1 or candidates[0][0]-candidates[1][0] >= candidates[0][1].get('min_margin', .025))):
            score, entry = candidates[0]
            merge_item(output['items'], dict(id=entry['id'], name=entry['name'],
                       category=category, quantity=quantity, score=round(score, 4)))
        else:
            digest = crop_digest[:16]
            path = folder / f'unknown-{digest}.png'
            _save_image(path, crop)
            output['unknown'][digest] = dict(quantity=quantity, image=str(path), page=page)
    return len(cards)


def _atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def export_session(session):
    """latest 如实报告本轮 partial；另存 last-complete，绝不伪装为完整快照。"""
    categories = session['categories']
    session['status'] = 'complete' if (set(categories) == {'道具', '消耗品'} and
        all(value['status'] == 'complete' for value in categories.values()) and
        all(value is not None for value in session['currencies'].values())) else 'partial'
    base = _root()
    _atomic_json(base / 'history' / f"{session['run_id']}.json", session)
    _atomic_json(base / 'latest.json', session)
    if session['status'] == 'complete':
        _atomic_json(base / 'last-complete.json', session)
    lines = ['# 仓库资源汇总', '', f"采集时间：{session['captured_at']}",
             f"状态：{'完整' if session['status']=='complete' else '部分识别，未识别不代表库存为零'}", '']
    for name, amount in session['currencies'].items():
        lines.append(f"- {name}：{amount if amount is not None else '未识别'}")
    for category, data in categories.items():
        lines.extend(['', f'## {category}', '', '| 物品 | 数量 |', '|---|---:|'])
        for item in data['items'].values():
            count = ' / '.join(map(str, item['conflicting_quantities'])) if 'conflicting_quantities' in item else str(item['quantity']) if item['quantity'] is not None else '未识别'
            lines.append(f"| {item['name']} | {count} |")
        lines.extend(['', f"未识别图标：{len(data['unknown'])}；结束原因：{data['reason']}"])
    (base / 'latest.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return session


@AgentServer.custom_action('InventoryBegin')
class InventoryBegin(CustomAction):
    def run(self, context, argv):
        global _session
        now = datetime.datetime.now().astimezone()
        _session = dict(version=1, run_id=now.strftime('%Y%m%d-%H%M%S-%f'),
                        captured_at=now.isoformat(), status='partial',
                        currencies={'异方晶': None, '狄斯币': None}, categories={})
        return True


@AgentServer.custom_action('InventoryScanCategory')
class InventoryScanCategory(CustomAction):
    def run(self, context, argv):
        if _session is None:
            return False
        params = _params(argv)
        category = params.get('category')
        if category not in ('道具', '消耗品'):
            return False
        output = dict(status='partial', reason='扫描中', items={}, unknown={}, pages=0)
        _session['categories'][category] = output
        _log(f'开始识别{category}，只截图和滑动，不打开物品')
        try:
            controller = context.tasker.controller
            image = _snapshot(controller)
            # 分类标题必须匹配，防止入口失败后在其他页面滑动。
            title = ''.join(getattr(r, 'text', '') for r in _ocr(context, image, [260, 75, 420, 80]))
            if category not in title:
                output['reason'] = '未确认仓库分类页面'
                return False
            catalog = _catalog()
            match_cache = {}
            for name, roi in [('异方晶', [866, 30, 93, 37]), ('狄斯币', [1012, 30, 114, 37])]:
                value = _number(context, image, roi)
                if value is not None:
                    _session['currencies'][name] = value
            # 游戏打开分类时默认就在顶部，直接识别当前页，不再额外向上滑动。
            still, count = 0, 0
            for page in range(min(40, max(1, int(params.get('max_pages', 24))))):
                if getattr(context.tasker, 'stopping', False):
                    output['reason'] = '用户停止'
                    return False
                count += _scan_page(context, image, category, catalog, output, page, match_cache)
                output['pages'] += 1
                _log(f'{category}第{page+1}页：已识别{len(output["items"])}种，未知图标{len(output["unknown"])}个')
                newer = _swipe(controller, True)
                still = still+1 if _same_page(image, newer) else 0
                image = newer
                if still >= 2:
                    output['reason'] = '已到列表底部'
                    if count and not output['unknown'] and not any('conflicting_quantities' in i or i['quantity'] is None for i in output['items'].values()):
                        output['status'] = 'complete'
                    break
            else:
                output['reason'] = '达到最大扫描页数'
            if not count:
                output['reason'] = '没有读到有效物品数量'
            return bool(count)
        except InterruptedError:
            output['reason'] = '用户停止'
            return False
        except Exception as exc:
            output['reason'] = f'扫描失败：{type(exc).__name__}: {exc}'
            return False
        finally:
            export_session(_session)
            _log(f'{category}扫描结束：{output["reason"]}；结果{output["status"]}')


@AgentServer.custom_action('InventoryExport')
class InventoryExport(CustomAction):
    def run(self, context, argv):
        if _session is None:
            return False
        export_session(_session)
        return True

