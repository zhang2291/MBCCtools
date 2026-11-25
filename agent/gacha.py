"""MBCCtools AgentServer —— 方案二的自定义识别/动作实现入口。

由 MFAAvalonia / MaaPiCli 按 interface.json 的 "agent" 段作为子进程拉起，
最后一个命令行参数是 AgentClient 下发的连接标识符（socket id），需原样传给
AgentServer.start_up()。

自定义识别名与 pipeline 里的 custom_recognition 字段一一对应（大小写敏感）。
"""

import datetime
import json
import pathlib
import os
import numpy as np
import functools
from contextlib import contextmanager
import re
import sys
import threading
import time

try:
    import cv2
except ImportError:  # Android 无 OpenCV Python 包时用 numpy 放大
    cv2 = None

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition
from maa.pipeline import JOCR, JRecognitionType, JTemplateMatch


def _log(msg):
    # AgentServer 由 UI 以子进程方式拉起，stderr 会进 UI 日志
    print(f"[MBCCtools-agent] {msg}", file=sys.stderr, flush=True)


def _parse_param(argv):
    """custom_*_param 在协议里是任意 JSON，框架整包透传，绑定层给的是字符串。
    识别器与动作节点的字段名不同，这里一并取。"""
    raw = getattr(argv, "custom_recognition_param", None)
    if raw is None:
        raw = getattr(argv, "custom_action_param", None)
    if isinstance(raw, str):
        try:
            return json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as e:
            _log(f"custom_*_param 不是合法 JSON: {e} / {raw!r}")
            return {}
    return raw or {}


def _as_rect(value, default):
    if value is None:
        return default
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return [int(v) for v in value]
    return default


def _as_x_range(value):
    """badge_x 是 [x0, x1] 两个数，不是四元 rect，别复用 _as_rect"""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return [int(value[0]), int(value[1])]
    return None


def _as_point(value, default):
    """点位参数 [x, y]。形状与 _as_x_range 一样，但含义是坐标不是区间，别混用"""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return [int(value[0]), int(value[1])]
    return default


# 禁闭者静态稀有度映射字典（涵盖狂/危/普已知角色，用于混合校验与加速）
# 纯净字典，只收录标准规范角色全名
KNOWN_SINNERS = {
    # 狂级 (SSR)
    "诺克斯": "狂", "哈梅尔": "狂", "卓娅": "狂", "白逸": "狂", "兰利": "狂", "迪蒙": "狂",
    "伊琳娜": "狂", "夏音": "狂", "观星者": "狂", "娜恰": "狂", "恩菲尔": "狂", "黛伦": "狂",
    "嗷呜": "狂", "爱缇": "狂", "渡鸦": "狂", "卡门奈特": "狂", "罗睺": "狂", "可可莉克": "狂",
    "瑟琳": "狂", "曼提斯": "狂", "雷温": "狂", "珀尔夫人": "狂", "曜": "狂", "杜若": "狂",
    "毕安卡": "狂", "000": "狂", "席宁": "狂", "克莱门汀": "狂", "赛托": "狂", "蜜莉": "狂",
    "承霄": "狂", "荒噬·伊琳娜": "狂", "达芙蒂尔": "狂", "法露儿": "狂", "凯因": "狂", "莎缇拉": "狂",
    "L.L.": "狂",
    # 危级 (SR)
    "麦昆": "危", "堇": "危", "温蒂": "危", "卡瓦卡瓦": "危", "李维": "危", "辰砂": "危",
    "卡斯洛": "危", "奥利弗": "危", "赫罗": "危", "琳": "危", "九十九": "危", "莱塔": "危",
    "切尔西伯爵": "危", "莓丝": "危", "优利卡": "危", "狼獾": "危", "拉弥亚": "危", "维多利亚": "危",
    "诺玛": "危", "雅可": "危", "蓟": "危", "多芙": "危", "伊格尼": "危", "简": "危",
    "妮诺": "危", "瑞思": "危", "希格林德": "危", "安": "危", "露薇娅·蕾": "危", "艾可": "危",
    "泽斐尔": "危", "阿依果": "危", "黎莎洛": "危", "多莉": "危", "福克斯先生": "危", "克里斯蒂娜": "危",
    "派因": "危", "烟烟": "危", "艾瑞尔": "危", "戈蓝": "危", "卡米利安": "危", "艾恩": "危",
    "米拉": "危", "泰特拉": "危", "卡西娅": "危", "梅露辛": "危", "舒鲁玛": "危",
    "啵啡": "危", "无患子": "危", "萨妮": "危", "嘟嘟": "危", "依唯": "危", "海莉": "危",
    "尤尼": "危", "肖恩": "危", "卡兹安": "危", "帕加茜": "危", "卢米尼塔": "危", "玛蒂尔达": "危",
    "露莉艾卡": "危", "普希拉": "危",
    # 普级 (R)
    "琼": "普", "蔻蔻": "普", "德莫莉": "普", "芙洛拉": "普", "玛奇朵": "普", "澈": "普",
    "昙": "普", "艾米潘": "普", "丽莎": "普", "开尔文": "普", "胡椒": "普",
    "海拉": "普", "佩姬": "普", "雷比尼斯": "普",
}

# 常见 OCR 错别字/漏字别名纠错字典
OCR_NAME_ALIASES = {
    # 简繁及形近字纠错
    "卡茲安": "卡兹安",
    "县": "昙",
    "克斯蒂娜": "克里斯蒂娜",
    "雷比妮斯": "雷比尼斯",
    "诺克断": "诺克斯",
    "澈澈": "澈",
    "澈县": "澈",
    # 常见 OCR 繁体或异体字规范
    "溫蒂": "温蒂",
    "蘭利": "兰利",
    "切爾西伯爵": "切尔西伯爵",
    "福克斯先生": "福克斯先生",
    "露薇婭·蕾": "露薇娅·蕾",
    "愛緹": "爱缇",
    "觀星者": "观星者",
    "麥昆": "麦昆",
    "萊塔": "莱塔",
    "狼獾": "狼獾",
    "瑪奇朵": "玛奇朵",
}


def _normalize_name(name):
    if not name:
        return ""
    stripped = name.strip()
    stripped = re.sub(r"^[·\s\-_]+|[·\s\-_]+$", "", stripped)
    return OCR_NAME_ALIASES.get(stripped, stripped)


def _normalize_pool(pool):
    """规范化卡池名称中的已知分隔符（.、•、· 统一为 ·）、首尾及内部多余空白与全角/半角差异。"""
    if not pool:
        return ""
    text = str(pool).strip()
    text = re.sub(r"[\s\.\•\u2022\u25cf\u00b7]+", "·", text)
    return text.strip("· \t\r\n")


def _levenshtein(s1, s2):
    """计算两个字符串的 Levenshtein 编辑距离。"""
    if s1 == s2:
        return 0
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    if not s2:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for c1 in s1:
        curr = [prev[0] + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr.append(min(curr[-1] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def _match_fuzzy_candidate(incoming_name, incoming_rarity, cand_name, cand_rarity):
    """角色名三级模糊规则（仅限同时间戳 + 已匹配卡池范围内）：
    1 字角色：仅精确匹配 + 已验证极小别名表，严禁模糊合并（防止 澈 ↔ 琼 误并）；
    2 字角色：编辑距离 <= 1 时，必须强制视觉稀有度一致（防止 海拉[普] ↔ 海莉[危] 误并）；
    3 字及以上角色：同秒同池条件下允许编辑距离 <= 1（覆盖 卡茲安 → 卡兹安 等场景）。
    """
    n1 = _normalize_name(incoming_name)
    n2 = _normalize_name(cand_name)
    if n1 == n2:
        return True
    dist = _levenshtein(n1, n2)
    if len(n1) == 1 or len(n2) == 1:
        return False
    if len(n1) == 2 and len(n2) == 2:
        if dist <= 1:
            r1 = incoming_rarity or KNOWN_SINNERS.get(n1)
            r2 = cand_rarity or KNOWN_SINNERS.get(n2)
            if r1 and r2 and r1 == r2:
                return True
        return False
    return dist <= 1


def _log_pending_review(session, raw_cells, reason, candidates=None):
    """待复核文件隔离：多候选冲突或无法归并的异常行写入 pending_review.log，
    按原始签名去重，禁止以 .jsonl 结尾存放在归档目录内，避免被 glob('*.jsonl') 误读。"""
    try:
        log_file = session.path / "pending_review.log"
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sig = re.sub(r"\s+", "", "".join(str(c) for c in raw_cells))
        cand_str = f" | 候选: {candidates}" if candidates else ""
        entry = f"[{ts}] [{reason}] cells={list(raw_cells)} | sig={sig}{cand_str}\n"
        # 简单防重复记录
        if log_file.exists():
            existing = log_file.read_text(encoding="utf-8")
            if sig in existing:
                return
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        _log(f"写入待复核日志失败: {e}")


def _split_merged_names(text):
    """若 OCR 将垂直相邻的两行角色名粘连为单个文本框（例如 '琳琼'、'昙琼'、'澈县'、'澈澈'），
    尝试将其拆分为两个标准角色名并返回 (name1, name2)，否则返回 None。"""
    text = (text or "").strip()
    if not text or len(text) < 2:
        return None
    norm = _normalize_name(text)
    if norm in KNOWN_SINNERS:
        return None
    for i in range(1, len(text)):
        p1 = _normalize_name(text[:i])
        p2 = _normalize_name(text[i:])
        if p1 in KNOWN_SINNERS and p2 in KNOWN_SINNERS:
            return p1, p2
    return None


def _rect_of(value):
    """识别结果里的 box 在不同绑定版本可能是 Rect 对象或 [x,y,w,h] 列表，统一成列表"""
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return [int(v) for v in value]
    if all(hasattr(value, a) for a in ("x", "y", "w", "h")):
        return [int(value.x), int(value.y), int(value.w), int(value.h)]
    return None


# 累计记录：按追踪类型分文件存放在该目录下（<类型>.jsonl，如 活动.jsonl；
# 类型没识别出来的落 未判.jsonl）。出新卡池后跑一次就把没见过的追加进去
DEFAULT_ARCHIVE = "record/抽卡记录"
# focus 只能引用固定路径（占位符替换不了动态值），所以摘要也覆盖同一个文件
DEFAULT_REPORT = "record/抽卡记录.md"


class _RecordSession:
    """一次采集会话。path 是分类型档案目录，写入时按当前追踪类型落 <类型>.jsonl。

    store_counts 是开跑前从目录下所有档案读到的"每条记录出现过几次"，run_counts 是本次
    已经看到的次数；本次第 n 次看到某条记录时，只有 n > store_counts 才算新记录 ——
    这样十连里同秒重复的同名条目（实测存在）不会被误判成已采过。
    """

    def __init__(self, path, ts, store_counts, by_timestamp=None):
        self.path = path
        self.ts = ts
        self.store_counts = store_counts
        self.by_timestamp = by_timestamp or {}
        self.run_counts = {}
        self.last_page = None
        self.last_keys = None
        self.back_keys = None
        self.stall_retries = 0
        self.attempts = 0
        self.new_count = 0
        self.extra_ocr_budget = 2
        self.cross_page_buffer = []
        # 页头追踪类型，由 GachaRecordPoolType 在采集前写入；没识别出来保持 None
        self.pool_type = None
        self.status = "running"
        self.finish_reason = ""
        self.pages = 0
        self.known_count = 0
        self.started = time.time()

    def file_for(self, pool_type):
        """当前类型对应的累计档案；类型没识别出来时落 未判.jsonl"""
        return self.path / f"{pool_type or '未判'}.jsonl"


_sessions = {}


def _write_progress(session, state, page=None):
    """给 PC / 手机界面看的实时进度：<档案目录的上一级>/.progress.json，原子替换。
    state: running / finishing / done。写失败不影响采集。"""
    try:
        target = session.path.parent / ".progress.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "category": session.path.name,
            "state": state,
            "page": page if page is not None else session.last_page,
            "pages": session.pages,
            "new": session.new_count,
            "known": session.known_count,
            "pool_type": session.pool_type,
            "status": session.status,
            "reason": session.finish_reason,
            "elapsed": round(time.time() - session.started, 1),
            "updated": time.time(),
        }
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, target)
    except Exception:
        pass


def _project_root():
    # interface.json 与 agent/ 同级；不依赖 CWD，手动跑脚本时路径也一致
    return pathlib.Path(__file__).resolve().parent.parent


def _data_root():
    return pathlib.Path(os.environ.get("MBCC_DATA_DIR", str(_project_root() / "data")))


_THREAD_LOCK = threading.RLock()


@contextmanager
def _archive_lock():
    root = _data_root()
    root.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCK:
        lock_file = root / ".gacha.lock"
        with open(lock_file, "a+b") as lock:
            locked = False
            if os.name == "nt":
                import msvcrt
                for _ in range(10):
                    try:
                        lock.seek(0)
                        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                        locked = True
                        break
                    except Exception:
                        time.sleep(0.02)
                if not locked:
                    try:
                        lock.seek(0)
                        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                        locked = True
                    except Exception as e:
                        _log(f"⚠ 获取文件锁失败: {e}")
            else:
                try:
                    import fcntl
                    # POSIX record locks interoperate with Android FileChannel locks.
                    fcntl.lockf(lock, fcntl.LOCK_EX)
                    locked = True
                except Exception as e:
                    _log(f"⚠ 获取文件锁失败: {e}")
            try:
                yield
            finally:
                if locked:
                    if os.name == "nt":
                        import msvcrt
                        try:
                            lock.seek(0)
                            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                        except Exception:
                            pass
                    else:
                        try:
                            import fcntl
                            fcntl.lockf(lock, fcntl.LOCK_UN)
                        except Exception:
                            pass


def _locked(method):
    @functools.wraps(method)
    def call(*args, **kwargs):
        with _archive_lock():
            return method(*args, **kwargs)
    return call


def _load_store(archive_dir):
    """读档案目录下所有 <类型>.jsonl，返回全局 canonical_key->出现次数、总条数与时间戳索引。

    身份键含时间+卡池+名称，跨类型不可能撞，全局一份去重计数即可。
    特别注意：历史记录文件中可能存在旧版点号时间戳或未归一化错字，统一用 _row_sig 重新推导标准 Key，
    保证无论历史档案何时生成，去重计数键恒定一致。
    同时构建 by_timestamp[ts_norm] -> list[dict(pool, name, rarity, key)] 供受约束内存模糊去重。"""
    counts = {}
    by_timestamp = {}
    total = 0
    with _archive_lock():
        for fp in sorted(archive_dir.glob("*.jsonl")):
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                    except (json.JSONDecodeError, KeyError, TypeError):
                        continue
                    cells = record.get("cells", [])
                    key = _row_sig(cells) if cells else record.get("key")
                    if key:
                        counts[key] = counts.get(key, 0) + 1
                    if isinstance(cells, list) and len(cells) >= 3:
                        ts_digits = "".join(re.findall(r"\d+", str(cells[0]))[:6])
                        if ts_digits:
                            pool_norm = _normalize_pool(cells[1])
                            name_norm = _normalize_name(cells[-1])
                            rarity = record.get("rarity")
                            if ts_digits not in by_timestamp:
                                by_timestamp[ts_digits] = []
                            by_timestamp[ts_digits].append({
                                "pool": pool_norm,
                                "name": name_norm,
                                "rarity": rarity,
                                "key": key,
                            })
                    total += 1
    return counts, total, by_timestamp


def _get_session(archive):
    archive = str(archive)
    session = _sessions.get(archive)
    if session is not None:
        return session
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    root = _data_root() / archive
    root.mkdir(parents=True, exist_ok=True)
    store_counts, total, by_timestamp = _load_store(root)
    session = _RecordSession(root, ts, store_counts, by_timestamp)
    _sessions[archive] = session
    _log(f"抽卡记录会话开始 -> {root}（已有 {total} 条）")
    return session


def _read_page_number(context, image, page_roi, min_score):
    """读底栏 ◀ 页码 ▶ 中间的数字，返回 int；读不到返回 None。

    页码渲染偏小（实测最小 8x12 像素，原尺寸直接 OCR 会把 '2' 读成 'C' 0.41），
    所以把该区域裁出来放大 4 倍再识别（实测放大后 0.96~1.0）。
    None 意味着这一眼读不出页码：不在记录页、或页面切换的中间帧。
    注：实测末页是"页码停住不再前进"（走 no_advance 那条），不是显示成 "-"——
    2026-10-10 常驻池末页与活动池第 50 页都是如此。"""
    x, y, w, h = page_roi
    crop = image[y:y + h, x:x + w]
    if not crop.size:
        return None
    try:
        if cv2 is not None:
            crop = cv2.resize(crop, (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
        else:
            from PIL import Image as _PILImage
            pil_im = _PILImage.fromarray(crop[:, :, ::-1] if crop.ndim == 3 and crop.shape[2] == 3 else crop)
            enlarged = pil_im.resize((w * 4, h * 4), _PILImage.BICUBIC)
            crop = np.array(enlarged)[:, :, ::-1] if crop.ndim == 3 and crop.shape[2] == 3 else np.array(enlarged)
    except Exception:
        crop = np.repeat(np.repeat(crop, 4, axis=0), 4, axis=1)
    detail = context.run_recognition_direct(
        JRecognitionType.OCR,
        JOCR(roi=[0, 0, crop.shape[1], crop.shape[0]]),
        crop,
    )
    results = getattr(detail, "all_results", None) or getattr(detail, "filtered_results", None) or []
    best = None
    for result in results:
        text = (getattr(result, "text", "") or "").strip()
        score = float(getattr(result, "score", 0.0))
        # 兼容 PaddleOCR 偶发将单独数字 '1' 误识别为 'I', 'l', '|'
        text_norm = re.sub(r"[Il|]", "1", text)
        digits = re.findall(r"\d+", text_norm)
        if not digits or score < min_score:
            continue
        val = int(digits[0])
        if best is None or score > best[0]:
            best = (score, val)
    return best[1] if best else None


def _probe_back(context, page_roi, min_score, back_point, page_no):
    """判停前的对照点击：点一次 ◀ 再看页码，区分"真到底"和"输入失灵"。

    末页没有任何可辨识的图像特征——2026-10-10 逐像素实测：末页的 ▶ 与可用页完全一致
    （最大像素差 0），游戏既不隐藏也不置灰，点它只是不动。但同一次实验里 ◀ / ▶ 在非末页
    都有响应，所以"点 ◀ 后页码变了"能反证输入通道是通的，剩下的可能就是列表到头。

    返回 (结论, 点击后的页码)：
        ok      通道正常（页码变了）→ 判定到达末页
        stall   点了没反应（页码没变）→ 疑似输入失灵
        unknown 点后读不到页码（离开记录页 / 中间帧）→ 状态不明
    注意本函数会真的翻回上一页；调用方都在收尾路径上，翻不翻回去无所谓。
    调用方在第 1 页会跳过本函数：那一页的 ◀ 本来就不可用，点了没反应说明不了任何事。
    """
    ctrl = context.tasker.controller
    ctrl.post_click(back_point[0], back_point[1]).wait()
    time.sleep(0.8)
    ctrl.post_screencap().wait()
    after = _read_page_number(context, ctrl.cached_image, page_roi, min_score)
    if after is None:
        return "unknown", after
    return ("ok" if after != page_no else "stall"), after


def _rarity_by_row(context, image, row_boxes, rarity_dir, tiers, floor, cell_names=None, badge_roi=None):
    """优先根据角色名查静态稀有度表确定（0ms 开销），仅未命中行使用 JTemplateMatch 识别。
    如果整页角色全部命中静态字典，直接跳过 JTemplateMatch，实现单页 0ms 稀有度匹配。"""
    n_rows = len(row_boxes)
    rarities = [None] * n_rows
    unresolved_rows = []

    # 第一阶段：优先查静态字典（含常见 OCR 别名纠错）
    if cell_names:
        for idx in range(min(n_rows, len(cell_names))):
            norm_name = _normalize_name(cell_names[idx])
            if norm_name in KNOWN_SINNERS:
                rarities[idx] = KNOWN_SINNERS[norm_name]
            else:
                unresolved_rows.append(idx)
        if len(cell_names) < n_rows:
            unresolved_rows.extend(range(len(cell_names), n_rows))
    else:
        unresolved_rows = list(range(n_rows))

    # 如果整页所有行均已通过静态表命中稀有度，或者没有提供 tiers，直接 0ms 返回！
    if not unresolved_rows or not tiers:
        return rarities

    # 第二阶段：仅对未命中角色（新角色或 OCR 错字）执行 TemplateMatch
    if badge_roi:
        effective_roi = badge_roi
    else:
        unresolved_y = [row_boxes[i][1] for i in unresolved_rows]
        unresolved_h = [row_boxes[i][3] for i in unresolved_rows]
        min_y = max(0, min(unresolved_y) - 6)
        max_y = max(unresolved_y[i] + unresolved_h[i] for i in range(len(unresolved_rows))) + 6
        effective_roi = [850, min_y, 65, max(1, max_y - min_y)]

    best = {row: {} for row in unresolved_rows}
    for tier in tiers:
        match_param = JTemplateMatch(template=[f"{rarity_dir}/{tier}"], roi=effective_roi, threshold=[0.3])
        detail = context.run_recognition_direct(
            JRecognitionType.TemplateMatch,
            match_param,
            image,
        )
        for result in (getattr(detail, "all_results", None) or []):
            box = _rect_of(getattr(result, "box", None))
            if box is None:
                continue
            cy = box[1] + box[3] / 2.0
            score = float(getattr(result, "score", 0.0))
            for row in unresolved_rows:
                rx, ry, rw, rh = row_boxes[row]
                if ry - 4 <= cy <= ry + rh + 4:
                    if score > best[row].get(tier, 0.0):
                        best[row][tier] = score
                    break

    for row in unresolved_rows:
        scores = best[row]
        if not scores:
            rarities[row] = None
            continue
        tier = max(scores, key=scores.get)
        top = scores[tier]
        image_tier = tier if top >= floor else f"未知:{tier}:{top:.2f}"
        rarities[row] = image_tier
        name_str = cell_names[row] if cell_names and row < len(cell_names) else f"第{row+1}行"
        _log(f"GachaRecordPage 模板匹配兜底：角色「{name_str}」识别为【{image_tier}】(分值={top:.2f})")

    return rarities


def _ocr_rows(context, image, roi, min_score, line_tol, badge_x=None):
    """整页 OCR 后按 y 聚成行，返回 (行文本, 行外接框) 两组等长列表。

    行内按 x 排序，所以一行的 cells 就是"时间 / 卡池 / 角色名"这类列的原始顺序，
    不做语义解析。给了 badge_x（徽章列的横范围）就在 OCR 前对副本填充纯色背景，
    消除纯 CPU 推理时的无效检测框开销，并剔除残余碎片。
    """
    ocr_image = image
    if badge_x and image is not None:
        try:
            ocr_image = image.copy()
            bx0 = max(0, badge_x[0] - 2)
            bx1 = min(image.shape[1], badge_x[1] + 2)
            by0 = max(0, roi[1])
            by1 = min(image.shape[0], roi[1] + roi[3])
            fill_color = (25, 25, 25) if image.ndim == 3 else 25
            ocr_image[by0:by1, bx0:bx1] = fill_color
        except Exception:
            ocr_image = image

    detail = context.run_recognition_direct(
        JRecognitionType.OCR,
        JOCR(roi=roi),
        ocr_image,
    )
    results = getattr(detail, "all_results", None) or getattr(detail, "filtered_results", None) or []

    items = []
    for result in results:
        text = (getattr(result, "text", "") or "").strip()
        box = _rect_of(getattr(result, "box", None))
        if not text or box is None:
            continue
        score = float(getattr(result, "score", 0.0))
        # 降阈放行范围（0.35 ~ min_score）严格限制在角色名列（x > 850）或命中已知角色/别名
        if score < min_score:
            is_char_col = (box[0] > 850 or box[0] + box[2] > 850)
            norm_text = _normalize_name(text)
            is_known = norm_text in KNOWN_SINNERS or norm_text in OCR_NAME_ALIASES
            if not (score >= 0.35 and (is_char_col or is_known)):
                continue
        if badge_x and badge_x[0] <= box[0] + box[2] / 2.0 <= badge_x[1]:
            continue

        split_pair = None
        # 仅对位于角色名列且高度满足两行特征（box[3] >= 28）的候选尝试拆分
        if (box[0] > 850 or box[0] + box[2] > 850) and box[3] >= 28:
            split_pair = _split_merged_names(text)
        if split_pair:
            name1, name2 = split_pair
            h = box[3]
            half_h = max(1, h // 2)
            box1 = [box[0], box[1], box[2], half_h]
            box2 = [box[0], box[1] + half_h, box[2], h - half_h]
            cy1 = box[1] + h * 0.25
            cy2 = box[1] + h * 0.75
            items.append((cy1, box[0], box1, name1))
            items.append((cy2, box[0], box2, name2))
        else:
            items.append((box[1] + box[3] / 2.0, box[0], box, text))
    items.sort()

    # 结合固定表格行区域与网格槽位划分，彻底避免两行合并或拆分成多行
    rx, ry, rw, rh = roi
    if 250 <= rh <= 450 and rw >= 500:
        slot_h = rh / 10.0
        slots = [[] for _ in range(10)]
        for cy, cx, box, text in items:
            k = int((cy - ry) / slot_h)
            k = max(0, min(9, k))
            slots[k].append((cx, text, box))

        # 检查边界溢出：如果 slot k 包含 2 个角色名（x > 850 区域）而 slot k+1 没有，向下转移
        for k in range(9):
            names_k = [c for c in slots[k] if c[0] > 850]
            if len(names_k) >= 2 and not any(c[0] > 850 for c in slots[k + 1]):
                lower = max(names_k, key=lambda c: c[2][1])
                slots[k].remove(lower)
                slots[k + 1].append(lower)

        repaired_rows = []
        for k in range(10):
            if slots[k]:
                slots[k].sort(key=lambda c: c[0])
                repaired_rows.append((ry + (k + 0.5) * slot_h, slots[k]))
    else:
        # 回退模式（用于非标准测试桩）
        rows = []
        for cy, cx, box, text in items:
            if rows and abs(cy - rows[-1][0]) <= line_tol:
                rows[-1][1].append((cx, text, box))
            else:
                rows.append([cy, [(cx, text, box)]])
        repaired_rows = []
        i = 0
        while i < len(rows):
            cy, cells = rows[i]
            cells.sort(key=lambda c: c[0])
            if len(cells) == 2 and i + 1 < len(rows):
                next_cy, next_cells = rows[i + 1]
                if len(next_cells) == 1 and abs(next_cy - cy) <= line_tol * 2.0 and next_cells[0][0] > cells[1][0]:
                    repaired_rows.append([cy, cells + next_cells])
                    i += 2
                    continue
            if len(cells) == 1 and repaired_rows and len(repaired_rows[-1][1]) == 2:
                prev_cy, prev_cells = repaired_rows[-1]
                if abs(cy - prev_cy) <= line_tol * 2.0 and cells[0][0] > prev_cells[1][0]:
                    repaired_rows[-1][1] = prev_cells + cells
                    i += 1
                    continue
            repaired_rows.append([cy, cells])
            i += 1

    cells_list = []
    box_list = []
    for _, cells in repaired_rows:
        cells.sort(key=lambda c: c[0])
        row_texts = [c[1] for c in cells]
        if row_texts:
            # 处理 OCR 偶发将时间戳与卡池名粘连在同一个文本框的情况（如 2024-02-08 22:19:29光影留痕）
            m = re.match(r"^(\d{4}-\d{2}-\d{2}[.\s_T]*\d{2}:\d{2}:\d{2})\s*(.+)$", row_texts[0])
            if m:
                ts = re.sub(r"^(\d{4}-\d{2}-\d{2})[.\s_T]*(\d{2}:\d{2}:\d{2})$", r"\1 \2", m.group(1))
                remainder = m.group(2).strip()
                row_texts = [ts, remainder] + row_texts[1:]
            elif re.match(r"^\d{4}-\d{2}-\d{2}[.\s_T]*\d{2}:\d{2}:\d{2}$", row_texts[0]):
                row_texts[0] = re.sub(r"^(\d{4}-\d{2}-\d{2})[.\s_T]*(\d{2}:\d{2}:\d{2})$", r"\1 \2", row_texts[0])
            # 规范化卡池名与角色名写回记录本体
            if len(row_texts) >= 3:
                row_texts[1] = _normalize_pool(row_texts[1])
                row_texts[-1] = _normalize_name(row_texts[-1])
        cells_list.append(tuple(row_texts))
        boxes = [c[2] for c in cells]
        x0 = min(b[0] for b in boxes)
        y0 = min(b[1] for b in boxes)
        x1 = max(b[0] + b[2] for b in boxes)
        y1 = max(b[1] + b[3] for b in boxes)
        box_list.append([x0, y0, x1 - x0, y1 - y0])
    return cells_list, box_list


def _row_sig(cells):
    """一条记录的身份键：统一去除空白与时间分隔符，且规范化卡池与角色名。
    保证跨设备、跨运行、不管 OCR 空格、点号还是错字变体，Key 恒定一致。"""
    if len(cells) >= 3:
        ts_digits = re.findall(r"\d+", str(cells[0]))
        if len(ts_digits) >= 6:
            ts = "".join(ts_digits[:6])
        else:
            ts = re.sub(r"[\s\.\_T\-:]+", "", str(cells[0]))
        pool = re.sub(r"[\s\·\.\•\u2022\u25cf\u00b7]+", "", str(cells[1]))
        name = _normalize_name(str(cells[-1]).strip())
        return f"{ts}{pool}{name}"
    return re.sub(r"[\s\·\.\•\u2022\u25cf\u00b7]+", "", "".join(str(c) for c in cells))


# 实测与官方卡池类型：活动/常规/限定/返场限定/定向/综合/统合/常驻/特选/新手 等
# 记录页页头对应「{类型}追踪 · 近期抽卡记录(UTC+8)」。
DEFAULT_POOL_TYPES = [
    "活动",
    "常规",
    "限定",
    "返场限定",
    "定向",
    "综合",
    "统合",
    "常驻",
    "特选",
    "新手",
]
# OCR 把小字号的「综合」标签读成"统合"（置信度 1.0，形近字），类型匹配要把别名算上
TYPE_ALIASES = {"综合": ["统合"]}


def _match_type(text, types):
    """按包含匹配类型词（text 需已去空白），命中别名也算，返回规范类型名；没命中返回 None。"""
    # 优先按长度倒序匹配已知列表，保证「返场限定」优先于「限定」
    for t in sorted(types, key=len, reverse=True):
        if t in text:
            return t
    for t, aliases in TYPE_ALIASES.items():
        if t in types and any(a in text for a in aliases):
            return t
    # 动态匹配：若文本含「XX追踪」，直接提取前面的类型名（例如 新卡池名追踪）
    m = re.search(r"([\u4e00-\u9fa5·A-Za-z0-9]{2,8})追踪", text)
    if m:
        extracted = m.group(1).replace("·", "").strip()
        if extracted:
            return extracted
    return None


@AgentServer.custom_recognition("GachaRecordPoolType")
class GachaRecordPoolType(CustomRecognition):
    """识别记录页页头的追踪类型，写进会话，随每条记录存档、导出时作「类型」列。

    页头是「{类型}追踪 · 近期抽卡记录(UTC+8)」的形态，按"包含"匹配四种类型
    （OCR 掉首字也能对上）；types 参数可覆盖清单，游戏改文案时不用动代码。
    开跑时跑一次：翻页不换池，类型整轮不变，本次采到的记录都归这个类型。
    未命中返回 None（不在记录页 / 文案变了）。此时也要把会话里的旧类型清掉，
    否则同一进程内第二次跑会把上一次的类型错挂到这次的记录上。
    类型识别不出来不阻断采集（父节点 on_error 照走），记录落 未判.jsonl。
    """

    def analyze(self, context, argv):
        param = _parse_param(argv)
        archive = param.get("archive") or DEFAULT_ARCHIVE
        session = _get_session(archive)

        roi = [argv.roi.x, argv.roi.y, argv.roi.w, argv.roi.h]
        if tuple(roi) == (0, 0, 0, 0):
            roi = _as_rect(param.get("roi"), roi)

        detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(roi=roi),
            argv.image,
        )
        results = getattr(detail, "all_results", None) or getattr(detail, "filtered_results", None) or []
        min_score = float(param.get("min_score", 0.5))
        types = param.get("types") or DEFAULT_POOL_TYPES

        best = None
        for result in results:
            text = (getattr(result, "text", "") or "").strip()
            box = _rect_of(getattr(result, "box", None))
            score = float(getattr(result, "score", 0.0))
            if not text or box is None or score < min_score:
                continue
            matched = _match_type(re.sub(r"\s+", "", text), types)
            if matched and (best is None or score > best[0]):
                best = (score, matched, text, box)

        if best is None:
            # 门卫检查：是否处于抽卡记录页面（含有「近期抽卡记录」、「抽卡记录」或「追踪」）
            gate_found = any(
                "近期抽卡记录" in (getattr(r, "text", "") or "")
                or "抽卡记录" in (getattr(r, "text", "") or "")
                or "追踪" in (getattr(r, "text", "") or "")
                for r in results
            )
            if gate_found:
                session.pool_type = None
                _log(f"GachaRecordPoolType 在 roi={roi} 未精确匹配追踪类型，按「未判」继续采集")
                box = [roi[0], roi[1], roi[2], roi[3]]
                for r in results:
                    b = _rect_of(getattr(r, "box", None))
                    if b:
                        box = b
                        break
                return self.AnalyzeResult(
                    box=box,
                    detail={"type": None, "text": "未判", "score": 0.5},
                )

            session.pool_type = None
            _log(f"GachaRecordPoolType 在 roi={roi} 没认出追踪类型（{types}），且未见记录页门卫")
            return None

        session.pool_type = best[1]
        _log(f"GachaRecordPoolType 追踪类型={best[1]}（原文「{best[2]}」，置信度 {best[0]:.2f}）")
        return self.AnalyzeResult(
            box=best[3],
            detail={"type": best[1], "text": best[2], "score": best[0]},
        )


@AgentServer.custom_recognition("GachaRecordFirstPage")
class GachaRecordFirstPage(CustomRecognition):
    """判断记录列表是否已回到第 1 页：点一次 ◀ 后行内容不再变化 = 已在第 1 页（◀ 已禁用）。

    水位线按"记录内容已存在"停，前提是从第 1 页往下扫；开跑停在中间页时第一屏全是旧记录，
    会被当成到底、一条新的都采不到还不报错，所以先把列表翻回顶部。
    早期实现读底栏页码，实测页码渲染大小不一（'2' 有时只有 8x12 像素）、OCR 读成 'C' 0.41，
    靠不住；改用行内容比对，行签名与上一眼相同就未命中放行，交给采集节点。
    本节点动作是点 ◀，坐标在抽卡页上紧挨「追踪一次」按钮，所以先过记录页门卫
    （页头「近期抽卡记录」），不在记录页绝不命中、绝不点击。
    参数与 GachaRecordPage 相同（roi 取列表区域），上一眼的行签名存会话的 back_keys。
    """

    def analyze(self, context, argv):
        param = _parse_param(argv)
        archive = param.get("archive") or DEFAULT_ARCHIVE
        session = _get_session(archive)

        roi = _rect_of(argv.roi) or [0, 0, argv.image.shape[1], argv.image.shape[0]]
        if tuple(roi) == (0, 0, 0, 0):
            h, w = argv.image.shape[0], argv.image.shape[1]
            roi = _as_rect(param.get("roi"), [0, 0, w, h])

        min_score = float(param.get("min_score", 0.5))
        line_tol = int(param.get("line_tol", 14))
        badge_x = _as_x_range(param.get("badge_x"))
        gate_roi = _as_rect(param.get("gate_roi"), [411, 210, 420, 55])
        gate_text = param.get("gate_text") or "近期抽卡记录"
        page_roi = _as_rect(param.get("page_roi"), [735, 625, 65, 36])

        # 门卫：不在记录页（页头没有「近期抽卡记录」）绝不命中。本节点的动作是点 ◀，
        # 坐标在抽卡页上紧挨「追踪一次」按钮，一旦在错误页面点击可能误触抽卡。
        if not _ocr_find(context, argv.image, gate_roi, [gate_text], min_score):
            return None

        # 优先前置检查页码：若已是第 1 页，0 点击、0 等待直接放行！
        page_no = _read_page_number(context, argv.image, page_roi, min_score)
        if page_no == 1:
            session.back_keys = None
            _log("GachaRecordFirstPage 当前底栏已是第 1 页，直接跳过回首页")
            return None
        if page_no is not None and page_no > 1:
            _log(f"GachaRecordFirstPage 当前在第 {page_no} 页，点击 ◀ 翻回上一页")
            return self.AnalyzeResult(box=roi, detail={"page": page_no})

        rows, _ = _ocr_rows(context, argv.image, roi, min_score, line_tol, badge_x)
        keys = [_row_sig(cells) for cells in rows]
        if not keys:
            # 读不到行（空池）：不点 ◀，交给采集节点的门卫与路由
            return None

        if keys == session.back_keys:
            # ◀ 点击可能延迟生效，首帧往往还是旧页：重截一帧确认，变了就继续翻
            time.sleep(0.6)
            ctrl = context.tasker.controller
            ctrl.post_screencap().wait()
            rows2, _ = _ocr_rows(context, ctrl.cached_image, roi, min_score, line_tol, badge_x)
            keys2 = [_row_sig(cells) for cells in rows2]
            if not keys2 or keys2 == keys:
                session.back_keys = None
                return None  # 内容稳定 = 已在第 1 页
            keys = keys2

        session.back_keys = keys
        return self.AnalyzeResult(box=roi, detail={"rows": len(rows)})


def _log_corrupted_row(session, cells, key):
    try:
        log_file = session.path / "异常行.log"
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] 页码尝试: {session.attempts} | 键: {key} | 列数: {len(cells)} | 原文: {list(cells)}\n")
    except Exception as e:
        _log(f"写入异常行日志失败: {e}")


@AgentServer.custom_recognition("GachaRecordPage")
class GachaRecordPage(CustomRecognition):
    """读抽卡记录列表页当前可见的记录，追加进累计档案。

    两种采集方式由 stop_on_known 切换：
      完整识别（默认）：从第 1 页完整翻到最后一页，每页逐行与档案去重比对，只追加
                        没见过的记录。不会漏页，列表长时较慢。
      识别到已知停止：  从第 1 页往下扫，撞见第一条档案里已有的记录就立即停止——
                        出新卡池后跑一次只补最上面的新页，快，但中断过的采集会漏页。
    "翻到最后一页"的判定靠页码：每页读完翻页，下一眼读页码——页码前进 = 翻页成功；
    页码不变 = 点击延迟/丢失，重试翻页（最多 3 次，每次都先重截确认）；页码消失
    （游戏在末页后再翻会显示"-"）= 列表到头。页码区域裁出后放大 4 倍再 OCR，
    实测小字号也能 0.96~1.0 可靠读出。

    pipeline 参数（写在 custom_recognition_param 里）:
        archive:        str    分类型档案目录，默认 record/抽卡记录；开跑前读目录下所有
                               <类型>.jsonl 统计已有记录（去重计数），写入时按当前追踪类型
                               落 <类型>.jsonl
        roi:            [x,y,w,h] 列表区域，不写就是全屏；节点自身的 roi 优先
        gate_roi:       [x,y,w,h] 页头识别区域，默认 [414,218,425,60]，覆盖「…近期抽卡记录(UTC+8)」
        gate_text:      str    门卫关键词，默认 近期抽卡记录（只有记录页的页头有这行字）
        page_roi:       [x,y,w,h] 底栏页码区域，默认 [735,625,65,36]
        min_score:      float  OCR 置信度下限，默认 0.5
        line_tol:       int    判定"同一行"的 y 中心容差像素，默认 14
        badge_x:        [x0,x1] 徽章列的横向范围，用来剔掉该列里偶尔被 OCR 读出来的碎片，不给就不剔
        rarity_dir:     str  徽章模板根目录，相对 image/，默认 "抽卡"
        rarity_tiers:   [str] 有哪几档，对应 rarity_dir 下的同名子目录（如 抽卡/狂/*.png）；不给就不判档
        rarity_floor:   float 最高分低于它就算未匹配，落成 "未知:档:分值" 提醒补图，默认 0.5
        max_pages:      int    单次运行最多识别次数（防失控的兜底），默认 100
        stop_on_known:  bool  true = 识别到已知停止；缺省 false = 完整识别
        next_fresh:     str  每页读完（无论有无新记录）都去的节点，默认 抽卡记录翻页
        next_done:      str  判停（页码消失/同页/空页/不在记录页）时去的节点，默认 抽卡记录汇总
        next_last:      str  确认到达末页（含单页列表）时去的节点，默认 抽卡记录末页
        next_overflow:  str  达到 max_pages 时去的节点，默认 抽卡记录汇总
        back_point:     [x,y] 底栏 ◀ 的坐标，默认 [711,645]；判停时点它反证输入通道
        max_stall_retries: int 页码不动时连续重试翻页的上限，默认 2
    每条记录附带 type 字段 = GachaRecordPoolType 在本轮采集前识别出的追踪类型（未识别为 null）。
    路由是本设计的核心：识别几乎总是命中，"接下来去哪"由 override_next 按结果动态改写——
    每页读完都走 next_fresh 翻页继续，判停（页码消失/同页/空页/不在记录页）走 next_done 汇总
    导出，识别次数用尽走 next_overflow。
    绝不靠"未命中 + 超时"推进流程：那会触发框架的 error handling loop 检测（实测直接终止任务），
    还要白等 timeout。所以「翻页」节点不做识别（DirectHit + 定点 roi，roi 即点击点），
    翻页有没有生效一律交回页码仲裁，只有页码确实不再前进才收尾；收尾前再点一次 ◀
    反证输入通道（实测末页的 ▶ 与可用态像素级一致，图像上看不出"到底"，只能这样反证）。
    """

    def _route(self, context, argv, next_node, box, detail):
        """把本节点的 next 改写成 next_node 并以命中收场。

        override_next 是任务级持久的，所以每条路径都显式设置一次，保证下一轮状态确定；
        万一改写失败（节点名对不上），节点自身的静态 next 仍然兜底，流程不会断。
        """
        if not context.override_next(argv.node_name, [next_node]):
            _log(f"GachaRecordPage override_next({next_node}) 失败，沿用节点静态 next")
        return self.AnalyzeResult(box=box, detail=detail)

    def _fresh_row_indices(self, session, rows, keys):
        """对整页行执行精确匹配与受约束内存模糊去重。
        返回 (fresh_indices, hit_known_count)。"""
        valid_items = []
        for index, (cells, key) in enumerate(zip(rows, keys)):
            if len(cells) < 3:
                _log(f"GachaRecordPage ⚠️ 警告：第 {session.attempts} 页第 {index + 1} 行字段不足 3 列 (原文: {cells})，记录至异常行日志并跳过")
                _log_corrupted_row(session, cells, key)
                continue
            ts_digits = "".join(re.findall(r"\d+", str(cells[0]))[:6])
            valid_items.append({
                "index": index,
                "cells": list(cells),
                "key": key,
                "ts_norm": ts_digits,
                "pool_norm": _normalize_pool(cells[1]),
                "name_norm": _normalize_name(cells[-1]),
            })

        if not valid_items:
            return [], 0

        # 按连续相同 ts_norm 分组
        groups = []
        curr_group = [valid_items[0]]
        for item in valid_items[1:]:
            if item["ts_norm"] == curr_group[0]["ts_norm"]:
                curr_group.append(item)
            else:
                groups.append(curr_group)
                curr_group = [item]
        groups.append(curr_group)

        fresh_indices = []
        hit_known_count = 0

        for grp in groups:
            ts_norm = grp[0]["ts_norm"]
            hist_list = session.by_timestamp.get(ts_norm, [])
            cand_consumed = [False] * len(hist_list)

            # 1. 精确匹配优先扣减历史配额
            unmatched = []
            for item in grp:
                key = item["key"]
                session.run_counts[key] = session.run_counts.get(key, 0) + 1
                if session.run_counts[key] <= session.store_counts.get(key, 0):
                    hit_known_count += 1
                    for c_idx, cand in enumerate(hist_list):
                        if not cand_consumed[c_idx] and cand["key"] == key:
                            cand_consumed[c_idx] = True
                            break
                else:
                    unmatched.append(item)

            # 2. 受约束模糊匹配
            for item in unmatched:
                name_norm = item["name_norm"]
                pool_norm = item["pool_norm"]
                matching_cands = []
                for c_idx, cand in enumerate(hist_list):
                    if cand_consumed[c_idx]:
                        continue
                    pool_dist = _levenshtein(pool_norm, cand["pool"])
                    if pool_dist > 1 and pool_norm not in cand["pool"] and cand["pool"] not in pool_norm:
                        continue
                    if _match_fuzzy_candidate(name_norm, None, cand["name"], cand.get("rarity")):
                        matching_cands.append((c_idx, cand))

                if len(matching_cands) == 1:
                    c_idx, cand = matching_cands[0]
                    cand_consumed[c_idx] = True
                    hit_known_count += 1
                    canon_key = cand["key"]
                    session.run_counts[canon_key] = session.run_counts.get(canon_key, 0) + 1
                    keys[item["index"]] = canon_key
                    _log(f"GachaRecordPage 内存模糊去重命中：[{name_norm}] 归并至历史记录 [{cand['name']}] (key={canon_key})")
                elif len(matching_cands) > 1:
                    _log_pending_review(session, item["cells"], "多候选冲突", [c[1]["name"] for c in matching_cands])
                    fresh_indices.append(item["index"])
                else:
                    fresh_indices.append(item["index"])

        if hit_known_count > 0 and not fresh_indices:
            _log(f"GachaRecordPage 第 {session.attempts} 页：全部 {hit_known_count} 行均已在库中（去重跳过）")
        elif hit_known_count > 0:
            _log(f"GachaRecordPage 第 {session.attempts} 页：{hit_known_count} 行已在库中，新增 {len(fresh_indices)} 行")

        return fresh_indices, hit_known_count

    def _scan_fresh(self, session, rows, keys, rarities):
        """整页逐行与档案去重比对：出现次数超过已存次数的才算新记录
        （十连里同秒重复的同名条目靠这个计数规则保留）。"""
        fresh_indices, _ = self._fresh_row_indices(session, rows, keys)
        return [(rows[index], keys[index], rarities[index]) for index in fresh_indices]

    def analyze(self, context, argv):
        t_page_start = time.perf_counter()
        t_page_no_cost = 0.0
        t_rows_cost = 0.0
        t_dedup_cost = 0.0
        t_rarity_cost = 0.0

        param = _parse_param(argv)
        archive = param.get("archive") or DEFAULT_ARCHIVE
        session = _get_session(archive)

        next_fresh = param.get("next_fresh") or "抽卡记录翻页"
        next_done = param.get("next_done") or "抽卡记录汇总"
        next_last = param.get("next_last") or "抽卡记录末页"
        next_overflow = param.get("next_overflow") or "抽卡记录汇总"
        gate_roi = _as_rect(param.get("gate_roi"), [411, 210, 420, 55])
        gate_text = param.get("gate_text") or "近期抽卡记录"
        page_roi = _as_rect(param.get("page_roi"), [735, 625, 65, 36])
        back_point = _as_point(param.get("back_point"), [711, 645])
        max_stall = int(param.get("max_stall_retries", 2))
        stop_on_known = bool(param.get("stop_on_known"))
        min_score = float(param.get("min_score", 0.5))
        line_tol = int(param.get("line_tol", 14))
        badge_x = _as_x_range(param.get("badge_x"))

        roi = _rect_of(argv.roi) or [0, 0, argv.image.shape[1], argv.image.shape[0]]
        if tuple(roi) == (0, 0, 0, 0):
            h, w = argv.image.shape[0], argv.image.shape[1]
            roi = _as_rect(param.get("roi"), [0, 0, w, h])

        if session.attempts == 0:
            session.store_counts, _, session.by_timestamp = _load_store(session.path)
        session.attempts += 1
        if session.attempts > int(param.get("max_pages", 100)):
            _log(f"GachaRecordPage 达到 max_pages，转汇总导出（本次已新增 {session.new_count} 条）")
            session.status = "partial"
            session.finish_reason = "达到最大采集页数"
            return self._route(context, argv, next_overflow, roi,
                               {"reason": "max_pages", "new": session.new_count})

        ctrl = context.tasker.controller
        image = argv.image
        outcome = None
        rows = boxes = keys = rarities = None
        fresh = []
        page_no = None
        hit_known_count = 0
        for attempt in range(2):
            t0 = time.perf_counter()
            page_no = _read_page_number(context, image, page_roi, min_score)
            t_page_no_cost += time.perf_counter() - t0

            # 翻页页码先验：若处于多页采集阶段
            if session.last_page is not None and session.attempts > 1:
                if attempt == 0 and page_no == session.last_page:
                    time.sleep(0.25)
                    ctrl.post_screencap().wait()
                    image = ctrl.cached_image
                    t0 = time.perf_counter()
                    page_no = _read_page_number(context, image, page_roi, min_score)
                    t_page_no_cost += time.perf_counter() - t0
                    if page_no == session.last_page:
                        # 仍未变，进入 attempt == 1 等待 0.5s，避免直接判定 no_advance
                        continue
                elif attempt == 1 and page_no == session.last_page:
                    time.sleep(0.5)
                    ctrl.post_screencap().wait()
                    image = ctrl.cached_image
                    t0 = time.perf_counter()
                    page_no = _read_page_number(context, image, page_roi, min_score)
                    t_page_no_cost += time.perf_counter() - t0
                    if page_no == session.last_page:
                        outcome = ("no_advance", {"page": page_no})
                        break
                elif attempt == 0 and (page_no is None or page_no != session.last_page + 1):
                    time.sleep(0.25)
                    ctrl.post_screencap().wait()
                    image = ctrl.cached_image
                    t0 = time.perf_counter()
                    retry_page = _read_page_number(context, image, page_roi, min_score)
                    t_page_no_cost += time.perf_counter() - t0
                    if retry_page is not None:
                        page_no = retry_page
                        if page_no == session.last_page:
                            continue

            if page_no is not None and session.last_page is not None and page_no > session.last_page + 1:
                _log(f"GachaRecordPage ⚠️ 警告：检测到页码非连续跳变（从第 {session.last_page} 页直接跳至第 {page_no} 页）")

            t0 = time.perf_counter()
            rows, boxes = _ocr_rows(context, image, roi, min_score, line_tol, badge_x)
            t_rows_cost += time.perf_counter() - t0

            # 若非末页检测到结构缺失（仅解析出 8~9 行），消耗预算尝试重截重试 1 次
            if len(rows) in (8, 9) and session.extra_ocr_budget > 0 and attempt == 0:
                session.extra_ocr_budget -= 1
                _log(f"GachaRecordPage 检测到表格疑似缺失行 (仅 {len(rows)} 行)，消耗重试预算 (剩余 {session.extra_ocr_budget} 次) 重截重试")
                time.sleep(0.3)
                ctrl.post_screencap().wait()
                image = ctrl.cached_image
                t0 = time.perf_counter()
                retry_rows, retry_boxes = _ocr_rows(context, image, roi, min_score, line_tol, badge_x)
                t_rows_cost += time.perf_counter() - t0
                if len(retry_rows) > len(rows):
                    rows, boxes = retry_rows, retry_boxes

            keys = [_row_sig(cells) for cells in rows]

            if not rows:
                if not _ocr_find(context, image, gate_roi, [gate_text], min_score):
                    outcome = ("off_page", {})
                    session.status = "partial"
                    session.finish_reason = "脱离抽卡记录页"
                    rows = boxes = keys = rarities = None
                else:
                    outcome = ("empty", {})
            elif page_no is not None and page_no == session.last_page:
                outcome = ("no_advance", {"page": page_no})
            elif page_no is None and session.last_keys and keys == session.last_keys:
                outcome = ("no_advance", {"page": session.last_page})
            else:
                if page_no is None:
                    page_no = (session.last_page or 0) + 1
                    _log(f"GachaRecordPage 底栏页码读数为空，根据记录行内容变化推导为第 {page_no} 页")
                session.last_page = page_no
                session.last_keys = keys

                # 优先跑内存受约束模糊去重与精确匹配（< 1ms）
                t0 = time.perf_counter()
                fresh_indices, hit_known_count = self._fresh_row_indices(session, rows, keys)
                t_dedup_cost += time.perf_counter() - t0

                if stop_on_known and not fresh_indices:
                    outcome = ("known_stop", {})
                    session.status = "completed"
                    session.finish_reason = "命中已知历史记录（增量采集完成）"
                    fresh = []
                    break

                if fresh_indices:
                    t0 = time.perf_counter()
                    cell_names = [rows[index][-1] if len(rows[index]) >= 3 else "" for index in fresh_indices]
                    badge_roi = None
                    if badge_x:
                        img_h, img_w = image.shape[:2]
                        bx0 = max(0, badge_x[0] - 8)
                        bx1 = min(img_w, badge_x[1] + 8)
                        by0 = max(0, roi[1] - 4)
                        by1 = min(img_h, roi[1] + roi[3] + 4)
                        badge_roi = [bx0, by0, bx1 - bx0, by1 - by0]
                    fresh_rarities = _rarity_by_row(
                        context, image, [boxes[index] for index in fresh_indices],
                        param.get("rarity_dir", "抽卡"),
                        param.get("rarity_tiers") or [],
                        float(param.get("rarity_floor", 0.5)),
                        cell_names=cell_names,
                        badge_roi=badge_roi,
                    )
                    t_rarity_cost += time.perf_counter() - t0
                    unknown = [r for r in fresh_rarities if r and r.startswith("未知")]
                    if unknown:
                        _log(f"GachaRecordPage 有徽章没匹上任何档，需要往对应目录补图: {unknown}")
                    fresh = [(rows[index], keys[index], rarity)
                             for index, rarity in zip(fresh_indices, fresh_rarities)]
                else:
                    _log(f"GachaRecordPage 第 {page_no} 页均为已知记录，跳过稀有度识别")
                    fresh = []

                outcome = None
            if outcome is None:
                break
            if attempt == 0:
                time.sleep(0.5)
                ctrl.post_screencap().wait()
                image = ctrl.cached_image

        t_page_total = time.perf_counter() - t_page_start
        if page_no is not None:
            _log(f"⏱️ GachaRecordPage 第 {page_no} 页耗时统计: 总计 {t_page_total:.2f}s "
                 f"(页码OCR: {t_page_no_cost:.2f}s | 表格OCR: {t_rows_cost:.2f}s | "
                 f"模糊去重: {t_dedup_cost * 1000:.1f}ms | 稀有度: {t_rarity_cost:.2f}s)")

        if outcome is not None:
            reason, detail = outcome
            if reason == "no_advance" and session.stall_retries < max_stall:
                session.stall_retries += 1
                _log(f"GachaRecordPage 页码停在第 {detail.get('page')} 页，"
                     f"重试翻页（第 {session.stall_retries}/{max_stall} 次）")
                return self._route(context, argv, next_fresh,
                                   boxes[0] if boxes else roi, {"reason": reason, **detail})
            session.stall_retries = 0

            done_target = next_done
            if reason == "empty":
                session.status = "completed"
                session.finish_reason = "空记录页采集完成"
            elif reason == "no_advance":
                page_now = detail.get("page")
                if page_now is not None and page_now <= 1:
                    detail["probe"] = "single_page"
                    done_target = next_last
                    session.status = "completed"
                    session.finish_reason = "单页列表采集完成"
                    _log("GachaRecordPage 判停：停在第 1 页，▶ 无响应即列表只有一页")
                else:
                    verdict, after = _probe_back(
                        context, page_roi, min_score, back_point, page_now)
                    detail["probe"] = verdict
                    detail["probe_page"] = after
                    if verdict == "ok":
                        done_target = next_last
                        session.status = "completed"
                        session.finish_reason = "确认到达末页"
                        _log(f"GachaRecordPage 判停：点 ◀ 页码回到 {after}，输入通道正常，判定为最后一页")
                    elif verdict == "stall":
                        session.status = "partial"
                        session.finish_reason = "翻页无响应且反证失败（疑似输入失灵）"
                        _log(f"GachaRecordPage ⚠ 判停：点 ◀ 后页码仍是 {after}，疑似输入通道失灵")
                    else:
                        session.status = "partial"
                        session.finish_reason = "状态不明（脱离记录页）"
                        _log("GachaRecordPage ⚠ 判停：点 ◀ 后读不到页码，状态不明")
            _write_progress(session, "finishing", detail.get("page"))
            _log(f"GachaRecordPage 判停（{reason}），转 {done_target} 导出")
            return self._route(context, argv, done_target,
                               boxes[0] if boxes else roi, {"reason": reason, **detail})

        # 本页正常读完
        session.stall_retries = 0
        total = sum(session.store_counts.values())
        if fresh:
            target = session.file_for(session.pool_type)
            with _archive_lock():
                with open(target, "a", encoding="utf-8") as f:
                    for cells, key, rarity in fresh:
                        session.new_count += 1
                        total += 1
                        session.store_counts[key] = session.store_counts.get(key, 0) + 1
                        f.write(json.dumps(
                            {"index": total, "key": key, "rarity": rarity,
                             "type": session.pool_type, "cells": list(cells)},
                            ensure_ascii=False,
                        ) + "\n")
                        _log(f"GachaRecordPage 写入新增记录: {cells} (key={key}, rarity={rarity})")
            _log(f"GachaRecordPage 第 {page_no} 页：采到 {len(rows)} 行，新增 {len(fresh)} 条 -> {target.name}，累计 {total} 条")
        else:
            _log(f"GachaRecordPage 第 {page_no} 页：{len(rows)} 行均在库中（或已归并），无新增，继续翻页")

        session.pages += 1
        session.known_count += hit_known_count
        _write_progress(session, "running", page_no)

        if stop_on_known and (hit_known_count >= 2 or (len(fresh) == 0 and hit_known_count >= 1)):
            session.status = "completed"
            session.finish_reason = "命中已知历史记录（增量采集完成）"
            _write_progress(session, "finishing", page_no)
            _log(f"GachaRecordPage 第 {page_no} 页在增量模式下命中已知历史记录 (已知 {hit_known_count} 条，新增 {len(fresh)} 条)，保存新增后收尾")
            return self._route(context, argv, next_done, boxes[-1],
                               {"page": page_no, "rows": len(rows), "new_rows": len(fresh),
                                "total": total, "archive": str(session.path), "status": session.status})

        return self._route(context, argv, next_fresh, boxes[-1],
                           {"page": page_no, "rows": len(rows), "new_rows": len(fresh),
                            "total": total, "archive": str(session.path)})


def _ocr_find(context, image, roi, targets, min_score, aliases=None):
    """在 roi 里找包含任一 target 的文字（去掉全部空白后按包含匹配，aliases 为每个
    target 的 OCR 误读别名），取置信度最高的一条。

    返回 (score, target, 原文, box)，找不到返回 None 并把 OCR 候选写进日志便于排查。"""
    aliases = aliases or {}
    detail = context.run_recognition_direct(JRecognitionType.OCR, JOCR(roi=roi), image)
    results = getattr(detail, "all_results", None) or getattr(detail, "filtered_results", None) or []
    best = None
    seen = []
    for result in results:
        text = re.sub(r"\s+", "", (getattr(result, "text", "") or ""))
        box = _rect_of(getattr(result, "box", None))
        score = float(getattr(result, "score", 0.0))
        if not text or box is None:
            continue
        seen.append((text, round(score, 2)))
        if score < min_score:
            continue
        for t in targets:
            names = [t] + list(aliases.get(t, []))
            if any(n in text for n in names) and (best is None or score > best[0]):
                best = (score, t, text, box)
                break
    if best is None and seen:
        _log(f"_ocr_find 在 roi={roi} 没匹配到 {targets}，OCR 候选: {seen}")
    return best


@AgentServer.custom_action("GachaRecordBeginRun")
class GachaRecordBeginRun(CustomAction):
    """一次任务运行的起点：丢弃同进程内可能残留的上一轮会话。

    AgentServer 进程常驻，上一轮若没走到汇总导出（用户手动停止、流程中断），
    _sessions 里会留下带旧去重计数 / 翻页状态的会话——下一轮判断会出错。
    入口节点先跑本动作，保证每轮都从全新会话开始（档案不动，
    去重计数由 _get_session 重新从档案统计）。
    """

    @_locked
    def run(self, context, argv):
        param = _parse_param(argv)
        archive = param.get("archive") or DEFAULT_ARCHIVE
        old = _sessions.pop(archive, None)
        if old is not None:
            _log(f"GachaRecordBeginRun 丢弃残留会话（上轮新增 {old.new_count} 条）")
        return True


_SHEET_BAD_CHARS = re.compile(r"[\\/*?:\[\]]")
# OCR 常把日期与时间之间那个空格吃掉（实测 10 行里 3 行），明细保留原样，导出层补回来
_TIME_FIX = re.compile(r"^(\d{4}-\d{2}-\d{2})[.\s_T]?(\d{2}:)")


def _record_time(rec):
    """导出层排序用；不补回那个空格，字符串排序就会把同一条记录排到错的位置"""
    cells = rec["cells"]
    return _TIME_FIX.sub(r"\1 \2", cells[0]) if len(cells) >= 3 else ""


def _sheet_name(pool, used):
    """Excel 工作表名不许带 \\ / * ? : [ ] 且最长 31 字符，卡池名要清洗并去重"""
    cleaned = _SHEET_BAD_CHARS.sub("_", pool)[:31] or "未命名"
    if cleaned in used:
        n = 2
        while f"{cleaned[:28]}_{n}" in used:
            n += 1
        cleaned = f"{cleaned[:28]}_{n}"
    used.add(cleaned)
    return cleaned


def _type_order(groups):
    """xlsx 分表与摘要分组的展示顺序：四个追踪类型按固定序，其余（含「未判」）排后面。"""
    return (
        [t for t in DEFAULT_POOL_TYPES if t in groups]
        + sorted(t for t in groups if t not in DEFAULT_POOL_TYPES and t != "未判")
        + (["未判"] if "未判" in groups else [])
    )


def _write_report(path, groups, session, total):
    """给 UI 弹窗看的 Markdown 摘要。只放分档计数和出货清单——几百行表格塞进弹窗没人看。"""
    counts = {}
    for recs in groups.values():
        for rec in recs:
            key = rec["rarity"] or "未判"
            counts[key] = counts.get(key, 0) + 1
    order = sorted(counts, key=lambda t: -counts[t])
    rare = [t for t in order if t != order[0]]

    status_tag = ""
    if session.status != "completed":
        status_tag = f" ⚠️【采集状态：部分完成 ({session.finish_reason or '未确认到达末页'})】"

    lines = [
        f"# 抽卡记录{status_tag}",
        "",
        f"本次新增 {session.new_count} 条，累计 {total} 条 · 完整明细见 `{path.with_suffix('.xlsx').name}`",
        "",
        "## 各类型",
        "",
        "| 类型 | 抽数 | " + " | ".join(order) + " |",
        "| --- | --- | " + " | ".join(["---"] * len(order)) + " |",
    ]
    for type_name in _type_order(groups):
        recs = groups[type_name]
        row = [str(sum(1 for r in recs if (r["rarity"] or "未判") == t)) for t in order]
        lines.append(f"| {type_name} | {len(recs)} | " + " | ".join(row))

    hits = [(rec, type_name) for type_name, recs in groups.items() for rec in recs
            if (rec["rarity"] or "未判") in rare]
    hits.sort(key=lambda x: (_record_time(x[0]), -x[0].get("index", 0)), reverse=True)
    lines += ["", f"## 出货（{'、'.join(rare)}，最近 {min(len(hits), 60)} 条）", ""]
    if hits:
        lines += ["| 时间 | 类型 | 卡池 | 稀有度 | 名称 | 档案序号 |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for rec, type_name in hits[:60]:
            cells = rec["cells"]
            name_ = cells[-1] if len(cells) >= 3 else " ".join(cells)
            pool_ = cells[1] if len(cells) >= 3 else ""
            lines.append(f"| {_record_time(rec)} | {type_name} | {pool_} "
                         f"| {rec['rarity']} | {name_} | {rec['index']} |")
        if len(hits) > 60:
            lines.append(f"\n更早的 {len(hits) - 60} 条见 xlsx。")
    else:
        lines.append("没有出货。")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@AgentServer.custom_action("GachaRecordExport")
class GachaRecordExport(CustomAction):
    """收尾：把分类型档案目录转成 Excel（一个追踪类型一张表）+ Markdown 摘要，并结束会话。

    pipeline 参数（写在 custom_action_param 里）:
        archive:  str  与识别器同一个值，指向分类型档案目录（<类型>.jsonl 所在处）
        excel:    str  导出路径，默认 archive 加 .xlsx 后缀（固定名字，每次覆盖）
        report:   str  Markdown 摘要的固定路径，默认 record/抽卡记录.md；界面侧直接读这个文件，
                       不走 focus 弹窗（2026-10-10 起 pipeline 里不再有引用它的 focus）
    JSONL 是累计档案本体，Excel 与摘要都只是它的一个视图，随时可重建。
    """

    @_locked
    def run(self, context, argv):
        try:
            from openpyxl import Workbook
        except ImportError:
            # interface.json 的 child_exec 写的是裸 "python"，而 PATH 里还有第二个解释器
            # （F:\Python 装的是 MaaFw 5.10.4、没有 openpyxl）。解析到它时不能让节点抛异常
            # 打断流程，只跳过 xlsx，摘要与 JSONL 档案照常。
            Workbook = None
            _log(f"缺 openpyxl，跳过 xlsx。当前解释器 {sys.executable}；"
                 f"补依赖：\"{sys.executable}\" -m pip install openpyxl")

        param = _parse_param(argv)
        archive = param.get("archive") or DEFAULT_ARCHIVE
        session = _sessions.pop(archive, None)
        if session is None:
            _log("GachaRecordExport 没有进行中的会话（识别节点没跑过或已收尾）")
            return True
        if not any(session.path.glob("*.jsonl")):
            _log(f"GachaRecordExport 档案目录为空: {session.path}")
            return True

        pattern = param.get("excel") or f"{archive}.xlsx"
        out = _data_root() / pattern.format(ts=session.ts)
        out.parent.mkdir(parents=True, exist_ok=True)
        groups = {}
        total = 0
        for fp in sorted(session.path.glob("*.jsonl")):
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    total += 1
                    # 一个追踪类型一张表；没认出类型的记录落进「未判」
                    groups.setdefault(rec.get("type") or "未判", []).append(rec)

        if Workbook is not None:
            wb = Workbook()
            wb.remove(wb.active)
            used = set()
            for type_name in _type_order(groups):
                ws = wb.create_sheet(_sheet_name(type_name, used))
                ws.append(["时间", "卡池", "稀有度", "名称", "档案序号"])
                # 档案是"单次采集内部新在前、多次采集按跑的先后追加"，直接倒出来顺序是乱的，按时间与序号重排
                for rec in sorted(groups[type_name], key=lambda r: (_record_time(r), -r.get("index", 0)), reverse=True):
                    cells = rec["cells"]
                    # 实测列序为 时间 / 卡池 / 名称；列数不足就把原文并到名称里，不做猜测
                    time_, pool_, name_ = (
                        (cells[0], cells[1], cells[-1]) if len(cells) >= 3 else ("", "", " / ".join(cells))
                    )
                    ws.append([_record_time(rec), pool_, rec["rarity"], name_, rec["index"]])
            wb.save(out)

        report = param.get("report") or DEFAULT_REPORT
        report_path = _data_root() / report
        _write_report(report_path, groups, session, total)
        _write_progress(session, "done")
        _log(
            f"抽卡记录导出：本次新增 {session.new_count} 条 / 累计 {total} 条 / {len(groups)} 个追踪类型 "
            f"-> {out.name} + {report_path.name}"
        )
        return True
