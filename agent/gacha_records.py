"""Desktop archive API. No device access; category IDs isolate archives from game tracking types."""
import argparse
from contextlib import contextmanager
from io import BytesIO
from collections import Counter, defaultdict
import datetime
import functools
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
import uuid

DEFAULTS = ['新角色', '限定', '联动', '常驻', '复刻']


def _normalize_pool(pool):
    """规范化卡池名称中的各种分隔符与多余空白。"""
    if not pool:
        return ""
    text = str(pool).strip()
    text = re.sub(r"[\s\.\•\u2022\u25cf\u00b7]+", "·", text)
    return text.strip("· \t\r\n")


def _norm_banner_key(text):
    """Strip spaces and separator glyphs for banner/pool matching."""
    if not text:
        return ""
    return re.sub(r"[\s·\.\•\u2022\u25cf\u00b7\-—_]+", "", str(text).strip())


def _classify_up(pool, game_type, name, catalog):
    """Return 'UP', '歪', or '' (skipped when standard or unmapped banner)."""
    if not catalog or not pool or not name:
        return ""
    if game_type == "常驻":
        return ""
    norm_pool = _norm_banner_key(pool)
    if not norm_pool:
        return ""
    for std in catalog.get("standard_pools", set()):
        if norm_pool == std or std in norm_pool:
            return ""
    banners = catalog.get("banners", {})
    ups = banners.get(norm_pool)
    if ups is None:
        for b_key, b_ups in banners.items():
            if b_key and b_key in norm_pool:
                ups = b_ups
                break
    if not ups:
        return ""
    norm_name = _norm_banner_key(name)
    return "UP" if norm_name in ups else "歪"


def canonical_key(cells, fallback_key=""):
    """标准化去重键，与 gacha.py 保持完全统一。"""
    if isinstance(cells, list) and len(cells) >= 3:
        ts_digits = "".join(re.findall(r"\d+", str(cells[0]))[:6])
        pool = re.sub(r"[\s\·\.\•\u2022\u25cf\u00b7]+", "", str(cells[1]))
        name = str(cells[-1]).strip()
        try:
            from agent.gacha import _normalize_name
            name = _normalize_name(name)
        except Exception:
            pass
        return f"{ts_digits}{pool}{name}"
    return fallback_key

_RECORD_LOCK = threading.RLock()
_LOCK_STATE = threading.local()


@contextmanager
def _file_lock(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not hasattr(_LOCK_STATE, "roots"):
        _LOCK_STATE.roots = set()

    root_str = str(root)
    if root_str in _LOCK_STATE.roots:
        yield
        return

    with _RECORD_LOCK:
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
                    except Exception:
                        pass
            else:
                try:
                    import fcntl
                    fcntl.lockf(lock, fcntl.LOCK_EX)
                    locked = True
                except Exception:
                    pass
            _LOCK_STATE.roots.add(root_str)
            try:
                yield
            finally:
                _LOCK_STATE.roots.discard(root_str)
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


class Records:
    def __init__(self, root):
        self.root = Path(root) / 'data'
        self.catalog = self.root / 'gacha-categories.json'

    def categories(self):
        if self.catalog.exists():
            try:
                cats = json.loads(self.catalog.read_text(encoding='utf-8'))
                if cats:
                    return cats
            except Exception:
                pass
        result = [dict(id=f'default-{i}', name=n) for i, n in enumerate(DEFAULTS)]
        self.save_catalog(result)
        return result

    def save_catalog(self, data):
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.catalog.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, self.catalog)

    def category(self, category_id):
        if category_id == 'legacy':
            return dict(id='legacy', name='未分类（旧记录）')
        return next(c for c in self.categories() if c['id'] == category_id)

    def archive(self, category_id):
        self.category(category_id)  # only catalog IDs may become paths
        return self.root / ('record/抽卡记录' if category_id == 'legacy' else f'record/gacha/{category_id}')

    def add(self, name):
        name = name.strip()
        if not name or len(name) > 40 or any(ord(c) < 32 for c in name):
            raise ValueError('类型名称须为 1–40 个可见字符')
        with _file_lock(self.root):
            categories = self.categories()
            if name in [c['name'] for c in categories] or name == '未分类（旧记录）':
                raise ValueError('该类型已存在')
            category = dict(id=uuid.uuid4().hex, name=name)
            self.save_catalog(categories + [category])
            return category

    def delete(self, category_id, permanent=False):
        with _file_lock(self.root):
            category = self.category(category_id)
            categories = self.categories()
            if category_id != 'legacy' and len(categories) <= 1:
                raise ValueError('请至少保留一个池子类型')
            archive = self.archive(category_id)
            if permanent:
                # Validate every destructive target before deleting anything.
                record_root = (self.root / 'record').resolve()
                if not record_root.is_relative_to(self.root.resolve()):
                    raise ValueError('档案根目录指向外部位置，拒绝删除')
                paths = [archive, archive.with_suffix('.xlsx'), archive.with_suffix('.md')]
                for path in paths:
                    if path.is_symlink() or not path.resolve().is_relative_to(record_root):
                        raise ValueError('档案路径超出数据目录，拒绝删除')
                for path in paths:
                    if path.is_dir():
                        shutil.rmtree(path)
                    elif path.exists():
                        path.unlink()
                if category_id == 'legacy':
                    (self.root / '.gacha-legacy-hidden').write_text('hidden', encoding='utf-8')
                else:
                    self.save_catalog([c for c in categories if c['id'] != category_id])
                return dict(permanent=True)
            backup = self.root / 'deleted-gacha' / (datetime.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
            backup.mkdir(parents=True)
            (backup / 'category.json').write_text(json.dumps(category, ensure_ascii=False), encoding='utf-8')
            paths_to_move = [
                (archive, backup / 'records'),
                (archive.with_suffix('.xlsx'), backup / f'{archive.name}.xlsx'),
                (archive.with_suffix('.md'), backup / f'{archive.name}.md'),
            ]
            moved = []
            try:
                for src, dst in paths_to_move:
                    if src.exists():
                        os.replace(src, dst)
                        moved.append((src, dst))
                if category_id == 'legacy':
                    (self.root / '.gacha-legacy-hidden').write_text('hidden', encoding='utf-8')
                else:
                    self.save_catalog([c for c in categories if c['id'] != category_id])
            except Exception:
                for src, dst in reversed(moved):
                    if dst.exists():
                        os.replace(dst, src)
                raise
            return dict(backup=str(backup))

    def read(self, category_id, skipped=None):
        with _file_lock(self.root):
            rows = []
            cat_name = self.category(category_id)['name'] if skipped is not None else category_id
            for file in sorted(self.archive(category_id).glob('*.jsonl')):
                for line_no, line in enumerate(file.read_text(encoding='utf-8-sig').splitlines(), 1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except Exception:
                        if skipped is not None:
                            skipped.append(f'{cat_name}/{file.name} 第 {line_no} 行：JSON 解析失败')
                        continue
                    if not isinstance(record.get('cells'), list) or len(record['cells']) < 3:
                        # 容错跳过不完整/损坏记录，避免阻断整个分类读取
                        if skipped is not None:
                            skipped.append(f'{cat_name}/{file.name} 第 {line_no} 行：缺少时间/卡池/角色列')
                        continue
                    rows.append(record)
            return rows

    @staticmethod
    def time(row):
        return re.sub(r'^(\d{4}-\d{2}-\d{2})[.\s_T]*(\d{2}:)', r'\1 \2', row['cells'][0])

    def _load_up_banners(self):
        path = self.root.parent / 'resource/base/gacha/up_banners.json'
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding='utf-8-sig'))
            standard = {_norm_banner_key(x) for x in raw.get('standard_pools', []) if _norm_banner_key(x)}
            banners = {}
            for k, v in (raw.get('banners') or {}).items():
                nk = _norm_banner_key(k)
                if nk and isinstance(v, list):
                    banners[nk] = {_norm_banner_key(n) for n in v if _norm_banner_key(n)}
            return dict(standard_pools=standard, banners=banners)
        except Exception:
            return {}

    def _compute_hits(self, rows, catalog=None):
        ordered = sorted(rows, key=lambda r: (self.time(r), -r.get('index', 0)))
        since_gold, seen_gold, guaranteed_next, hits = 0, False, False, []
        pull_by_id = {}
        for r in ordered:
            since_gold += 1
            if r.get('rarity') == '狂':
                pulls_str = str(since_gold) + ' 抽' if seen_gold else '—'
                name = r['cells'][-1]
                raw_up = _classify_up(r['cells'][1], r.get('type'), name, catalog)
                if raw_up == '歪':
                    up_status = '歪'
                    guaranteed_next = True
                elif raw_up == 'UP':
                    if guaranteed_next:
                        up_status = '大保底'
                        guaranteed_next = False
                    else:
                        up_status = 'UP'
                        guaranteed_next = False
                else:
                    up_status = ''
                    if r.get('type') != '常驻':
                        guaranteed_next = False
                hits.append(dict(Time=self.time(r), Pool=r['cells'][1], Name=name,
                                 Pulls=pulls_str,
                                 PullCount=since_gold if seen_gold else None,
                                 UpStatus=up_status,
                                 Note='' if seen_gold else '首狂'))
                pull_by_id[id(r)] = str(since_gold) if seen_gold else '—'
                since_gold = 0
                seen_gold = True
        return ordered, hits, since_gold, pull_by_id

    def snapshot(self, category_id, pool=''):
        with _file_lock(self.root):
            available = self.categories()
            if not available:
                available = [dict(id=f'default-{i}', name=n) for i, n in enumerate(DEFAULTS)]
            is_all = category_id == 'all'
            if not is_all and category_id != 'legacy' and category_id not in [c['id'] for c in available]:
                category_id = available[0]['id']
            categories = available + ([] if (self.root / '.gacha-legacy-hidden').exists() else [self.category('legacy')])
            catalog = self._load_up_banners()
            cached_reads = {}
            skipped = []
            for c in categories:
                cached_reads[c['id']] = self.read(c['id'], skipped=skipped)

            if is_all:
                rows = []
                hits = []
                pull_by_id = {}
                for c in categories:
                    data = cached_reads[c['id']]
                    rows.extend(data)
                    _, c_hits, _, c_pulls = self._compute_hits(data, catalog=catalog)
                    hits.extend(c_hits)
                    pull_by_id.update(c_pulls)
                ordered = sorted(rows, key=lambda r: (self.time(r), -r.get('index', 0)))
                hits.sort(key=lambda h: h['Time'])
                since_gold = None
            else:
                rows = cached_reads.get(category_id)
                if rows is None:
                    rows = self.read(category_id, skipped=skipped)
                    cached_reads[category_id] = rows
                ordered, hits, since_gold, pull_by_id = self._compute_hits(rows, catalog=catalog)

            latest = sorted(rows, key=lambda r: (self.time(r), -r.get('index', 0)), reverse=True)
            pools = list(dict.fromkeys(r['cells'][1] for r in latest))

        if pool:
            rows = [r for r in rows if r['cells'][1] == pool]
            ordered = [r for r in ordered if r['cells'][1] == pool]
            hits = [h for h in hits if h['Pool'] == pool]
        rares = len(hits)
        summaries = []
        for c in categories:
            data = cached_reads[c['id']]
            gold = sum(r.get('rarity') == '狂' for r in data)
            types = [r.get('type') for r in data if r.get('type')]
            game_type = Counter(types).most_common(1)[0][0] if types else ''
            summaries.append(dict(Id=c['id'], Name=c['name'], GameType=game_type, Total=len(data), Gold=gold,
                                  Average=f'{len(data)/gold:.1f}' if gold else '—'))
        all_total = sum(item['Total'] for item in summaries)
        all_gold = sum(item['Gold'] for item in summaries)

        # 出狂间隔分布（排除首狂）
        known_intervals = [h['PullCount'] for h in hits if h['PullCount'] is not None]
        buckets = [0] * 8
        for iv in known_intervals:
            buckets[min(7, max(0, (iv - 1) // 10))] += 1
        known_sorted = sorted(known_intervals)
        median = known_sorted[len(known_sorted) // 2] if known_sorted else None
        best = known_sorted[0] if known_sorted else None
        worst = known_sorted[-1] if known_sorted else None

        # 各卡池小计
        pool_counts = defaultdict(lambda: [0, 0])
        for r in ordered:
            p = r['cells'][1]
            pool_counts[p][0] += 1
            if r.get('rarity') == '狂':
                pool_counts[p][1] += 1
        pool_summaries = [dict(Pool=p, Total=pool_counts[p][0], Gold=pool_counts[p][1]) for p in pools if p in pool_counts]

        up_wins = sum(1 for h in hits if h.get('UpStatus') == 'UP')
        up_losses = sum(1 for h in hits if h.get('UpStatus') == '歪')
        up_guaranteed = sum(1 for h in hits if h.get('UpStatus') == '大保底')
        up_total = up_wins + up_losses
        up_rate = f'{up_wins * 100 / up_total:.1f}%' if up_total else '—'
        if up_total and up_guaranteed:
            up_summary = f'{up_wins} 不歪 / {up_losses} 歪 · {up_guaranteed} 大保底'
        elif up_total:
            up_summary = f'{up_wins} 不歪 / {up_losses} 歪'
        elif up_guaranteed:
            up_summary = f'{up_guaranteed} 大保底'
        else:
            up_summary = ''

        tracked_known = [h['PullCount'] for h in hits if h.get('UpStatus') and h.get('PullCount') is not None]
        if up_total > 0 and tracked_known:
            tracked_avg_gold = sum(tracked_known) / len(tracked_known)
            expected_golds_per_up = 2.0 - (up_wins / up_total)
            expected_up_pulls = tracked_avg_gold * expected_golds_per_up
            expected_up_text = f'{expected_up_pulls:.1f} 抽'
            expected_up_sub = f'均金 {tracked_avg_gold:.1f} × {expected_golds_per_up:.2f}（计 {len(tracked_known)} 狂）'
        else:
            expected_up_pulls = None
            expected_up_text = '—'
            expected_up_sub = '未判定池不纳入计算'

        return dict(all_total=all_total, all_gold=all_gold, all_average=f'{all_total/all_gold:.1f}' if all_gold else '—',
                    selected_category=category_id, categories=categories, summaries=summaries, pools=pools,
                    pool_summaries=pool_summaries,
                    total=len(rows), gold=rares, current_pity=since_gold,
                    up_wins=up_wins, up_losses=up_losses, up_guaranteed=up_guaranteed, up_rate=up_rate, up_summary=up_summary,
                    expected_up=expected_up_pulls, expected_up_text=expected_up_text,
                    expected_up_sub=expected_up_sub, tracked_gold_count=len(tracked_known),
                    rate=f'{rares*100/len(rows):.1f}%' if rows else '—',
                    average=f'{len(rows)/rares:.1f}' if rares else '—',
                    buckets=buckets, median=median, best=best, worst=worst,
                    skipped=skipped,
                    hits=list(reversed(hits)),
                    details=[dict(Time=self.time(r), Pool=r['cells'][1], Type=r.get('type') or '未判',
                                  Rarity=r.get('rarity') or '未判', Name=r['cells'][-1],
                                  Pulls=pull_by_id.get(id(r), '')) for r in reversed(ordered)])

    def export(self, category_id, destination, pool=''):
        with _file_lock(self.root):
            rows = self.read(category_id)
            if pool:
                rows = [r for r in rows if r['cells'][1] == pool]
            rows.sort(key=lambda r: (self.time(r), -r.get('index', 0)), reverse=True)
            dest = Path(destination)
            name = self.category(category_id)['name']
            if dest.suffix.lower() == '.xlsx':
                from openpyxl import Workbook
                wb = Workbook()
                ws = wb.active
                ws.title = '抽卡记录'
                ws.append(['池子类型', '追踪类型', '时间', '卡池', '稀有度', '名称', '档案序号', '原始列'])
                for r in rows:
                    values = [name, r.get('type') or '未判', self.time(r), r['cells'][1], r.get('rarity') or '未判',
                              r['cells'][-1], r.get('index', 0), json.dumps(r['cells'], ensure_ascii=False)]
                    ws.append(values)
                    for cell in ws[ws.max_row]:
                        if isinstance(cell.value, str):
                            cell.data_type = 's'
                ws.freeze_panes = 'A2'
                ws.auto_filter.ref = ws.dimensions
                for col in 'ABCDEFG':
                    ws.column_dimensions[col].width = 23
                ws.column_dimensions['H'].hidden = True
                wb.save(dest)
            else:
                def escape(value):
                    return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')
                stats = self.snapshot(category_id, pool)
                lines = [f'# {name} · 抽卡记录', '', f"已记录 {len(rows)} 抽，狂 {stats['gold']} 个，样本平均 {stats['average']} 抽/狂。", '',
                         '|时间|游戏追踪类型|卡池|稀有度|角色|', '|---|---|---|---|---|']
                for r in rows:
                    lines.append('|'+'|'.join(escape(v) for v in [self.time(r),r.get('type'),r['cells'][1],r.get('rarity'),r['cells'][-1]])+'|')
                dest.write_text('\n'.join(lines)+'\n', encoding='utf-8')
            return dict(count=len(rows), path=str(dest))

    def export_all(self, destination):
        with _file_lock(self.root):
            from openpyxl import Workbook
            categories = self.categories() + ([] if (self.root / '.gacha-legacy-hidden').exists() else [self.category('legacy')])
            headers = ['池子类型', '追踪类型', '时间', '卡池', '稀有度', '名称', '档案序号', '原始列']
            dest = Path(destination)
            wb = Workbook()
            ws = wb.active
            ws.title = '抽卡记录'
            ws.append(headers)
            catalog = wb.create_sheet('类型目录')
            catalog.append(['池子类型'])
            lines = ['# 全部抽卡记录', '', '|池子类型|时间|追踪类型|卡池|稀有度|角色|', '|---|---|---|---|---|---|']
            count = 0
            for category in categories:
                catalog.append([category['name']])
                catalog.cell(catalog.max_row, 1).data_type = 's'
                rows = sorted(self.read(category['id']), key=lambda r: (self.time(r), -r.get('index', 0)), reverse=True)
                for row in rows:
                    values = [category['name'], row.get('type') or '未判', self.time(row), row['cells'][1], row.get('rarity') or '未判', row['cells'][-1], row.get('index', 0), json.dumps(row['cells'], ensure_ascii=False)]
                    ws.append(values)
                    for cell in ws[ws.max_row]:
                        if isinstance(cell.value, str): cell.data_type = 's'
                    lines.append('|' + '|'.join(str(values[i]).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ') for i in [0, 2, 1, 3, 4, 5]) + '|')
                    count += 1
            ws.freeze_panes = 'A2'
            ws.auto_filter.ref = ws.dimensions
            for col in 'ABCDEFG': ws.column_dimensions[col].width = 23
            ws.column_dimensions['H'].hidden = True
            if dest.suffix.lower() == '.xlsx': wb.save(dest)
            else: dest.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            wb.close()
            return dict(count=count, categories=len(categories), path=str(dest))

    def import_all(self, source):
        """Validate/merge every category in an isolated workspace, then commit with rollback."""
        with _file_lock(self.root):
            from openpyxl import load_workbook, Workbook
            groups, names = {}, []
            total_rows = 0
            if Path(source).stat().st_size > 32 * 1024 * 1024:
                raise ValueError('Excel 文件超过 32 MB')
            wb = load_workbook(BytesIO(Path(source).read_bytes()), read_only=True, data_only=False)
            try:
                for ws in wb:
                    iterator = ws.iter_rows()
                    header = next(iterator, None)
                    if header is None: continue
                    columns = {str(c.value): i for i, c in enumerate(header)}
                    if ws.title == '类型目录':
                        if '池子类型' not in columns: raise ValueError('类型目录格式无效')
                        for row in iterator:
                            if row[0].data_type == 'f': raise ValueError('类型不能使用公式')
                            if row[0].value is not None: names.append(str(row[0].value))
                        continue
                    if not all(k in columns for k in ['池子类型', '时间', '卡池', '稀有度', '名称']):
                        raise ValueError('全部导入需要带“池子类型”列的 Excel，请使用新版导出文件')
                    for row in iterator:
                        if all(c.value is None for c in row): continue
                        if any(c.data_type == 'f' for c in row): raise ValueError('不支持含公式的明细')
                        index = columns['池子类型']
                        name = str(row[index].value or '').strip()
                        if not name: raise ValueError('存在没有池子类型的记录，未导入')
                        if name not in groups: groups[name] = (list(columns), [])
                        if groups[name][0] != list(columns): raise ValueError('工作表列顺序不一致')
                        groups[name][1].append([cell.value for cell in row])
                        total_rows += 1
                        if total_rows > 100000: raise ValueError('最多导入 100000 条记录')
            finally: wb.close()
            names = list(dict.fromkeys(names + list(groups)))
            if len(names) > 200: raise ValueError('类型数量过多')
            for name in names:
                if not name.strip() or name != name.strip() or len(name) > 40 or any(ord(c) < 32 for c in name):
                    raise ValueError('池子类型名称无效')
            existing = self.categories()
            changes = {}
            total = 0
            with tempfile.TemporaryDirectory(prefix='mbcc-import-') as temporary:
                staged = Records(temporary)
                staged.save_catalog(existing)
                lookup = {c['name']: c['id'] for c in existing}
                lookup['未分类（旧记录）'] = 'legacy'
                for name in names:
                    if name not in lookup: lookup[name] = staged.add(name)['id']
                    category_id = lookup[name]
                    if name not in groups: continue
                    source_archive = self.root / ('record/抽卡记录' if category_id == 'legacy' else f'record/gacha/{category_id}')
                    if source_archive.exists(): shutil.copytree(source_archive, staged.archive(category_id))
                    book = Workbook()
                    sheet = book.active
                    sheet.title = '抽卡记录'
                    headers, rows = groups[name]
                    sheet.append(headers)
                    for row in rows:
                        sheet.append(row)
                        for cell in sheet[sheet.max_row]:
                            if isinstance(cell.value, str): cell.data_type = 's'
                    part = Path(temporary) / 'part.xlsx'
                    book.save(part); book.close()
                    total += staged.import_excel(category_id, part)['count']
                    staged_import = staged.archive(category_id) / '导入.jsonl'
                    if staged_import.exists():
                        changes[source_archive / '导入.jsonl'] = staged_import.read_bytes()
                changes[self.catalog] = staged.catalog.read_bytes()
                if '未分类（旧记录）' in names: changes[self.root / '.gacha-legacy-hidden'] = None
                before = {path: path.read_bytes() if path.exists() else None for path in changes}
                committed = []
                try:
                    for path, content in changes.items():
                        self._replace_file(path, content)
                        committed.append(path)
                except Exception:
                    for path in reversed(committed): self._replace_file(path, before[path])
                    raise
            return dict(count=total, categories=len(names))

    @staticmethod
    def _replace_file(path, content):
        if content is None:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + '.import-tmp')
        try:
            with temp.open('wb') as stream:
                stream.write(content); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, path)
        finally: temp.unlink(missing_ok=True)

    def import_excel(self, category_id, source):
        from openpyxl import load_workbook
        if Path(source).stat().st_size > 32 * 1024 * 1024:
            raise ValueError('Excel 文件超过 32 MB')
        wb = load_workbook(BytesIO(Path(source).read_bytes()), read_only=True, data_only=False)
        incoming = []
        try:
            for ws in wb:
                iterator = ws.iter_rows()
                header = next(iterator, None)
                if header is None: continue
                columns = {str(c.value): i for i, c in enumerate(header)}
                if not all(k in columns for k in ['时间', '卡池', '稀有度', '名称']):
                    raise ValueError(f'工作表 {ws.title} 缺少抽卡表头')
                for row in iterator:
                    if all(c.value is None for c in row): continue
                    if any(c.data_type == 'f' for c in row): raise ValueError('不支持含公式的明细')
                    def value(k, fallback=''):
                        i=columns.get(k)
                        return str(row[i].value) if i is not None and i < len(row) and row[i].value is not None else fallback
                    exported_category = value('池子类型')
                    if exported_category and exported_category != self.category(category_id)['name']:
                        raise ValueError(f'文件池子类型为“{exported_category}”，与当前选择不同；请先选择相同类型，避免混档')
                    original = value('原始列')
                    cells = json.loads(original) if original else [value('时间'),value('卡池'),value('名称')]
                    if not isinstance(cells, list) or len(cells) < 3 or not all(isinstance(x,str) for x in cells):
                        raise ValueError('原始列格式无效')
                    if not all([cells[0],cells[1],cells[-1]]): raise ValueError('明细存在空时间、卡池或角色')
                    cells[1] = _normalize_pool(cells[1])
                    if original and [self.time(dict(cells=cells)),cells[1],cells[-1]] != [value('时间'),_normalize_pool(value('卡池')),value('名称')]:
                        raise ValueError('明细已修改但原始列未同步，请移除原始列后再导入')
                    key = canonical_key(cells, fallback_key=re.sub(r'\s+','',''.join(cells)))
                    incoming.append(dict(key=key, cells=cells,
                                         rarity=value('稀有度'), type=value('追踪类型',ws.title)))
                    if len(incoming)>100000: raise ValueError('导入最多支持 100000 条记录')
        finally:
            wb.close()
        with _file_lock(self.root):
            existing = self.read(category_id)
            # 去重键口径与 gacha.py 保持完全一致：统一标准 canonical_key 统计出现次数
            identity = lambda r: canonical_key(r.get('cells'), r.get('key'))
            counts = Counter(identity(r) for r in existing)
            seen, added = Counter(), []
            for r in incoming:
                key=identity(r); seen[key]+=1
                if seen[key]>counts[key]: added.append(r)
            if not added:
                return dict(count=0)
            archive=self.archive(category_id); archive.mkdir(parents=True,exist_ok=True)
            target=archive/'导入.jsonl'
            old=target.read_text(encoding='utf-8-sig') if target.exists() else ''
            index=max((r.get('index',0) for r in existing),default=0)
            temp=target.with_suffix('.tmp')
            with temp.open('w',encoding='utf-8') as f:
                f.write(old.rstrip()+'\n' if old.strip() else '')
                for r in added:
                    index+=1;r['index']=index;f.write(json.dumps(r,ensure_ascii=False)+'\n')
                f.flush();os.fsync(f.fileno())
            os.replace(temp,target)
            return dict(count=len(added))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=['snapshot','add','export','import','delete','export-all','import-all'])
    parser.add_argument('--root',required=True)
    parser.add_argument('--category',default='legacy')
    parser.add_argument('--name',default='')
    parser.add_argument('--path',default='')
    parser.add_argument('--pool',default='')
    parser.add_argument('--permanent',action='store_true')
    args=parser.parse_args()
    records=Records(args.root)
    try:
        if args.operation=='snapshot': result=records.snapshot(args.category,args.pool)
        elif args.operation=='add': result=records.add(args.name)
        elif args.operation=='delete': result=records.delete(args.category, permanent=args.permanent)
        elif args.operation=='export': result=records.export(args.category,args.path,args.pool)
        elif args.operation=='export-all': result=records.export_all(args.path)
        elif args.operation=='import-all': result=records.import_all(args.path)
        else: result=records.import_excel(args.category,args.path)
        print(json.dumps(result,ensure_ascii=False))
    except Exception as e:
        print(json.dumps({'error':str(e)},ensure_ascii=False))
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
