"""Desktop archive API. No device access; category IDs isolate archives from game tracking types."""
import argparse
from collections import Counter, defaultdict
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import uuid

DEFAULTS = ['新角色', '限定', '联动', '常驻', '复刻']


class Records:
    def __init__(self, root):
        self.root = Path(root) / 'data'
        self.catalog = self.root / 'gacha-categories.json'

    def categories(self):
        if self.catalog.exists():
            return json.loads(self.catalog.read_text(encoding='utf-8'))
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
        categories = self.categories()
        if name in [c['name'] for c in categories] or name == '未分类（旧记录）':
            raise ValueError('该类型已存在')
        category = dict(id=uuid.uuid4().hex, name=name)
        self.save_catalog(categories + [category])
        return category

    def delete(self, category_id, permanent=False):
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
        moved = False
        try:
            if archive.exists():
                os.replace(archive, backup / 'records')
                moved = True
            if category_id == 'legacy':
                (self.root / '.gacha-legacy-hidden').write_text('hidden', encoding='utf-8')
            else:
                self.save_catalog([c for c in categories if c['id'] != category_id])
        except Exception:
            if moved:
                os.replace(backup / 'records', archive)
            raise
        return dict(backup=str(backup))

    def read(self, category_id):
        rows = []
        for file in sorted(self.archive(category_id).glob('*.jsonl')):
            for line in file.read_text(encoding='utf-8-sig').splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record.get('cells'), list) or len(record['cells']) < 3:
                    raise ValueError(f'档案 {file.name} 含不完整记录，请先检查原始档案')
                rows.append(record)
        return rows

    @staticmethod
    def time(row):
        return re.sub(r'^(\d{4}-\d{2}-\d{2})(\d{2}:)', r'\1 \2', row['cells'][0])

    def snapshot(self, category_id, pool=''):
        available = self.categories()
        if category_id != 'legacy' and category_id not in [c['id'] for c in available]:
            category_id = available[0]['id']
        rows = self.read(category_id)
        latest = sorted(rows, key=lambda r: (self.time(r), -r.get('index', 0)), reverse=True)
        pools = list(dict.fromkeys(r['cells'][1] for r in latest))
        ordered = sorted(rows, key=lambda r: (self.time(r), -r.get('index', 0)))
        since_gold, seen_gold, hits = 0, False, []
        for r in ordered:
            since_gold += 1
            if r.get('rarity') == '狂':
                hits.append(dict(Time=self.time(r), Pool=r['cells'][1], Name=r['cells'][-1],
                                 Pulls=str(since_gold) + ' 抽' if seen_gold else '—',
                                 Note='' if seen_gold else '无上一条狂记录'))
                since_gold = 0
                seen_gold = True
        if pool:
            rows = [r for r in rows if r['cells'][1] == pool]
            ordered = [r for r in ordered if r['cells'][1] == pool]
            hits = [h for h in hits if h['Pool'] == pool]
        rares = len(hits)
        categories = self.categories() + ([] if (self.root / '.gacha-legacy-hidden').exists() else [self.category('legacy')])
        summaries = []
        for c in categories:
            data = self.read(c['id'])
            gold = sum(r.get('rarity') == '狂' for r in data)
            summaries.append(dict(Name=c['name'], Total=len(data), Gold=gold,
                                  Average=f'{len(data)/gold:.1f}' if gold else '—'))
        return dict(selected_category=category_id, categories=categories, summaries=summaries, pools=pools, total=len(rows), gold=rares,
                    average=f'{len(rows)/rares:.1f}' if rares else '—', hits=list(reversed(hits)),
                    details=[dict(Time=self.time(r), Pool=r['cells'][1], Type=r.get('type') or '未判',
                                  Rarity=r.get('rarity') or '未判', Name=r['cells'][-1]) for r in reversed(ordered)])

    def export(self, category_id, destination, pool=''):
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

    def import_excel(self, category_id, source):
        from openpyxl import load_workbook
        wb = load_workbook(source, read_only=True, data_only=False)
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
                    if original and [self.time(dict(cells=cells)),cells[1],cells[-1]] != [value('时间'),value('卡池'),value('名称')]:
                        raise ValueError('明细已修改但原始列未同步，请移除原始列后再导入')
                    incoming.append(dict(key=re.sub(r'\s+','',''.join(cells)), cells=cells,
                                         rarity=value('稀有度'), type=value('追踪类型',ws.title)))
                    if len(incoming)>100000: raise ValueError('导入最多支持 100000 条记录')
        finally:
            wb.close()
        existing = self.read(category_id)
        identity = lambda r: ((r.get('type') or '未判'),r['key'])
        counts = Counter(identity(r) for r in existing)
        seen, added = Counter(), []
        for r in incoming:
            key=identity(r); seen[key]+=1
            if seen[key]>counts[key]: added.append(r)
        archive=self.archive(category_id); archive.mkdir(parents=True,exist_ok=True)
        target=archive/'导入.jsonl'
        old=target.read_text(encoding='utf-8') if target.exists() else ''
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
    parser.add_argument('operation',choices=['snapshot','add','export','import','delete'])
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
        else: result=records.import_excel(args.category,args.path)
        print(json.dumps(result,ensure_ascii=False))
    except Exception as e:
        print(json.dumps({'error':str(e)},ensure_ascii=False))
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
