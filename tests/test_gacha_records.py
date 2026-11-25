import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('records',Path(__file__).resolve().parents[1]/'agent/gacha_records.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class RecordsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=module.Records(self.temp.name)

    def write(self,category,rows):
        path=self.store.archive(category);path.mkdir(parents=True,exist_ok=True)
        records=[]
        for index,(name,rarity,pool) in enumerate(rows,1):
            cells=[f'2026-10-15 10:00:{index:02d}',pool,name]
            records.append(dict(index=index,cells=cells,key=''.join(cells).replace(' ',''),rarity=rarity,type='活动'))
        (path/'活动.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records),encoding='utf-8')

    def test_categories_are_isolated_and_legacy_retained(self):
        self.write('legacy',[('旧角色','狂','旧池')])
        self.write('default-0',[('新角色','普','新池')])
        self.assertEqual(1,self.store.snapshot('legacy')['gold'])
        self.assertEqual(0,self.store.snapshot('default-0')['gold'])
        c=self.store.add('自定义/安全路径')
        self.assertNotIn('/',c['id'])
        self.assertEqual(0,self.store.snapshot(c['id'])['total'])

    def test_intervals_follow_consecutive_gold_within_selected_type(self):
        self.write('default-0',[('甲','普','A'),('乙','狂','A'),('丙','普','B'),('乙','狂','A'),('丁','狂','B')])
        data=self.store.snapshot('default-0')
        self.assertEqual(5,data['total']);self.assertEqual('1.7',data['average'])
        self.assertEqual(['1 抽','2 抽','—'],[h['Pulls'] for h in data['hits']])
        self.assertEqual(3,self.store.snapshot('default-0','A')['total'])
        self.assertEqual(['2 抽','—'],[h['Pulls'] for h in self.store.snapshot('default-0','A')['hits']])

    def test_export_import_roundtrip_idempotence_and_wrong_category_rejected(self):
        self.write('default-0',[('甲','狂','A'),('甲','狂','A')])
        export=Path(self.temp.name)/'export.xlsx'
        self.store.export('default-0',export)
        self.assertEqual(0,self.store.import_excel('default-0',export)['count'])
        with self.assertRaises(ValueError):self.store.import_excel('default-1',export)
        self.assertEqual([],self.store.read('default-1'))
        self.store.export('default-0',Path(self.temp.name)/'export.md')
        self.assertIn('|时间|',(Path(self.temp.name)/'export.md').read_text(encoding='utf-8'))

    def test_pool_order_matches_visible_records(self):
        self.write('default-0',[('甲','普','Z'),('乙','狂','A'),('丙','普','Z')])
        data=self.store.snapshot('default-0')
        self.assertEqual(['Z','A'],data['pools'])
        self.assertEqual('首狂', data['hits'][0]['Note'])

    def test_delete_backs_up_records_and_survives_refresh(self):
        self.write('default-0',[('甲','狂','A')])
        original=self.store.read('default-0')
        result=self.store.delete('default-0')
        backup=Path(result['backup'])/'records/活动.jsonl'
        self.assertEqual(original,[json.loads(line) for line in backup.read_text(encoding='utf-8').splitlines()])
        data=self.store.snapshot('default-0')
        self.assertNotEqual('default-0',data['selected_category'])
        self.assertNotIn('default-0',[c['id'] for c in data['categories']])
        self.store.delete('legacy')
        self.assertNotIn('legacy',[c['id'] for c in self.store.snapshot('default-1')['categories']])

    def test_duplicate_names_rejected(self):
        with self.assertRaises(ValueError):self.store.add('常驻')
        with self.assertRaises(StopIteration):self.store.archive('../outside')

    def test_global_summary_ignores_selected_type_and_pool(self):
        self.write('default-0',[('甲','狂','A'),('乙','普','B')])
        self.write('default-1',[('丙','狂','C')])
        snapshot=self.store.snapshot('default-0','B')
        self.assertEqual(1,snapshot['total'])
        self.assertEqual((3,2,'1.5'),(snapshot['all_total'],snapshot['all_gold'],snapshot['all_average']))

    def test_all_export_import_preserves_categories_and_is_idempotent(self):
        self.write('default-0',[('甲','狂','A')])
        custom=self.store.add('四合一')
        empty=self.store.add('空类型')
        self.write(custom['id'],[('乙','狂','B'),('乙','狂','B')])
        path=Path(self.temp.name)/'all.xlsx'
        self.assertEqual(3,self.store.export_all(path)['count'])
        other=module.Records(Path(self.temp.name)/'other')
        self.assertEqual(3,other.import_all(path)['count'])
        self.assertEqual(0,other.import_all(path)['count'])
        categories={c['name']:c['id'] for c in other.categories()}
        self.assertEqual(1,len(other.read('default-0')))
        self.assertEqual(2,len(other.read(categories['四合一'])))
        self.assertEqual([],other.read(categories['空类型']))

    def test_invalid_later_category_does_not_partially_import(self):
        from openpyxl import load_workbook
        self.write('default-0',[('甲','狂','A')])
        self.write('default-1',[('乙','狂','B')])
        path=Path(self.temp.name)/'all.xlsx';self.store.export_all(path)
        wb=load_workbook(path);wb['抽卡记录'].cell(3,6,'冲突名称');wb.save(path);wb.close()
        other=module.Records(Path(self.temp.name)/'other');other.categories()
        before=other.catalog.read_bytes()
        with self.assertRaises(ValueError):other.import_all(path)
        self.assertEqual(before,other.catalog.read_bytes())
        self.assertEqual([],list(other.root.rglob('*.jsonl')))

    def test_all_import_rolls_back_a_write_failure(self):
        from unittest.mock import patch
        self.write('default-0',[('甲','狂','A')])
        self.write('default-1',[('乙','狂','B')])
        path=Path(self.temp.name)/'all.xlsx';self.store.export_all(path)
        other=module.Records(Path(self.temp.name)/'other');other.categories()
        before=other.catalog.read_bytes()
        original=module.Records._replace_file
        calls=[]
        def fail_second(target, content):
            calls.append(target)
            if len(calls)==2: raise OSError('simulated disk failure')
            return original(target,content)
        with patch.object(module.Records,'_replace_file',side_effect=fail_second):
            with self.assertRaises(OSError):other.import_all(path)
        self.assertEqual(before,other.catalog.read_bytes())
        self.assertEqual([],list(other.root.rglob('*.jsonl')))

    def test_permanent_delete_removes_only_selected_records_and_reports(self):
        self.write('default-0',[('甲','狂','A')])
        self.write('default-1',[('乙','狂','B')])
        archive=self.store.archive('default-0')
        archive.with_suffix('.xlsx').write_bytes(b'test report')
        archive.with_suffix('.md').write_text('test report',encoding='utf-8')
        result=self.store.delete('default-0',permanent=True)
        self.assertTrue(result['permanent'])
        self.assertFalse(archive.exists())
        self.assertFalse(archive.with_suffix('.xlsx').exists())
        self.assertFalse(archive.with_suffix('.md').exists())
        self.assertFalse((self.store.root/'deleted-gacha').exists())
        self.assertEqual(1,len(self.store.read('default-1')))

    def test_permanent_delete_rejects_last_category(self):
        self.store.save_catalog([dict(id='only',name='唯一类型')])
        self.write('only',[('甲','狂','A')])
        with self.assertRaises(ValueError):self.store.delete('only',permanent=True)
        self.assertEqual(1,len(self.store.read('only')))

    def test_same_second_multifile_roundtrip_preserves_details_and_intervals(self):
        archive=self.store.archive('default-0');archive.mkdir(parents=True)
        rows=[]
        for index,(name,rarity) in enumerate([('甲','普'),('乙','狂'),('丙','普')],1):
            cells=['2026-10-1510:00:00','A',name]
            rows.append(dict(index=index,cells=cells,key=''.join(cells),rarity=rarity,type='活动'))
        for filename,records in [('活动.jsonl',rows[:2]),('导入.jsonl',rows[2:])]:
            (archive/filename).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records),encoding='utf-8')
        before=self.store.snapshot('default-0')
        self.assertEqual(['—'],[h['Pulls'] for h in before['hits']])
        export=Path(self.temp.name)/'same-second.xlsx'
        self.store.export('default-0',export)
        destination=module.Records(Path(self.temp.name)/'restored')
        self.assertEqual(3,destination.import_excel('default-0',export)['count'])
        after=destination.snapshot('default-0')
        self.assertEqual(before['details'],after['details'])
        self.assertEqual(before['hits'],after['hits'])
        self.assertEqual(0,destination.import_excel('default-0',export)['count'])

    def test_modified_visible_fields_with_stale_original_are_rejected_without_writes(self):
        from openpyxl import load_workbook
        self.write('default-0',[('甲','狂','A')])
        export=Path(self.temp.name)/'edited.xlsx'
        destination=module.Records(Path(self.temp.name)/'restored')
        for column,new_value in [('时间','2026-10-15 11:00:00'),('卡池','B'),('名称','乙')]:
            with self.subTest(column=column):
                self.store.export('default-0',export)
                wb=load_workbook(export)
                try:
                    ws=wb.active
                    columns={cell.value:cell.column for cell in ws[1]}
                    ws.cell(2,columns[column],new_value)
                    wb.save(export)
                finally:
                    wb.close()
                with self.assertRaisesRegex(ValueError,'明细已修改但原始列未同步'):
                    destination.import_excel('default-0',export)
                self.assertEqual([],destination.read('default-0'))
                self.assertFalse((destination.archive('default-0')/'导入.jsonl').exists())

    def test_visible_corrections_can_be_imported_after_removing_original_column(self):
        from openpyxl import load_workbook
        self.write('default-0',[('甲','狂','A')])
        export=Path(self.temp.name)/'corrected.xlsx'
        self.store.export('default-0',export)
        wb=load_workbook(export)
        try:
            ws=wb.active
            columns={cell.value:cell.column for cell in ws[1]}
            ws.cell(2,columns['名称'],'乙')
            ws.delete_cols(columns['原始列'])
            wb.save(export)
        finally:
            wb.close()
        destination=module.Records(Path(self.temp.name)/'restored')
        self.assertEqual(1,destination.import_excel('default-0',export)['count'])
        self.assertEqual('乙',destination.read('default-0')[0]['cells'][-1])

    def test_corrupted_row_skipped_without_raising(self):
        path = self.store.archive('default-0')
        path.mkdir(parents=True, exist_ok=True)
        # Normal row
        normal = dict(index=1, cells=['2026-10-15 10:00:01', 'A', '甲'], key='k1', rarity='狂', type='活动')
        # Corrupted rows (< 3 cells, non-list, etc.)
        corrupted1 = dict(index=2, cells=['2026-10-15 10:00:02', 'A'], key='k2', rarity='普', type='活动')
        corrupted2 = dict(index=3, cells='bad', key='k3', rarity='普', type='活动')
        (path / '活动.jsonl').write_text(
            json.dumps(normal, ensure_ascii=False) + '\n' +
            json.dumps(corrupted1, ensure_ascii=False) + '\n' +
            json.dumps(corrupted2, ensure_ascii=False) + '\n',
            encoding='utf-8'
        )
        # Reading must not raise ValueError; it should skip corrupted lines
        rows = self.store.read('default-0')
        self.assertEqual(1, len(rows))
        self.assertEqual('甲', rows[0]['cells'][-1])

    def test_snapshot_pity_and_pullcount_exposed(self):
        self.write('default-0', [('甲', '普', 'A'), ('乙', '狂', 'A'), ('丙', '普', 'A')])
        data = self.store.snapshot('default-0')
        self.assertEqual(1, data['current_pity'])
        self.assertEqual(1, len(data['hits']))
        self.assertIn('PullCount', data['hits'][0])
        self.assertIsNone(data['hits'][0]['PullCount'])  # first gold has unknown prior pulls
        self.assertIn('Id', data['summaries'][0])
        self.assertEqual('default-0', data['summaries'][0]['Id'])

    def test_up_win_rate_classification_and_skips_standard_or_unmapped(self):
        banner_dir = Path(self.temp.name) / 'resource/base/gacha'
        banner_dir.mkdir(parents=True, exist_ok=True)
        (banner_dir / 'up_banners.json').write_text(json.dumps({
            'version': 1,
            'standard_pools': ['混沌都市'],
            'banners': {'诸道无我': ['承霄']},
        }, ensure_ascii=False), encoding='utf-8')
        archive = self.store.archive('default-0')
        archive.mkdir(parents=True, exist_ok=True)
        rows = [
            dict(index=1, key='k1', rarity='狂', type='活动', cells=['2026-10-15 10:00:01', '诸道无我', '承霄']),
            dict(index=2, key='k2', rarity='狂', type='活动', cells=['2026-10-15 10:00:02', '诸道无我', '诺克斯']),
            dict(index=3, key='k3', rarity='狂', type='活动', cells=['2026-10-15 10:00:03', '未知新池', '某角色']),
            dict(index=4, key='k4', rarity='狂', type='常驻', cells=['2026-10-15 10:00:04', '混沌都市', '卓娅']),
        ]
        (archive / '活动.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
        data = self.store.snapshot('default-0')
        self.assertEqual(1, data['up_wins'])
        self.assertEqual(1, data['up_losses'])
        self.assertEqual('50.0%', data['up_rate'])
        statuses = {h['Name']: h['UpStatus'] for h in data['hits']}
        self.assertEqual('UP', statuses['承霄'])
        self.assertEqual('歪', statuses['诺克斯'])
        self.assertEqual('', statuses['某角色'])
        self.assertEqual('', statuses['卓娅'])

    def test_guaranteed_up_after_loss_is_excluded_from_fifty_fifty_rate(self):
        banner_dir = Path(self.temp.name) / 'resource/base/gacha'
        banner_dir.mkdir(parents=True, exist_ok=True)
        (banner_dir / 'up_banners.json').write_text(json.dumps({
            'version': 1,
            'standard_pools': [],
            'banners': {'诸道无我': ['承霄']},
        }, ensure_ascii=False), encoding='utf-8')
        archive = self.store.archive('default-0')
        archive.mkdir(parents=True, exist_ok=True)
        rows = [
            dict(index=1, key='g1', rarity='狂', type='活动', cells=['2026-10-15 10:00:01', '诸道无我', '诺克斯']),
            dict(index=2, key='g2', rarity='狂', type='活动', cells=['2026-10-15 10:00:02', '诸道无我', '承霄']),
            dict(index=3, key='g3', rarity='狂', type='活动', cells=['2026-10-15 10:00:03', '诸道无我', '卓娅']),
            dict(index=4, key='g4', rarity='狂', type='活动', cells=['2026-10-15 10:00:04', '诸道无我', '承霄']),
        ]
        (archive / '活动.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
        data = self.store.snapshot('default-0')
        self.assertEqual(0, data['up_wins'])
        self.assertEqual(2, data['up_losses'])
        self.assertEqual(2, data['up_guaranteed'])
        self.assertEqual('0.0%', data['up_rate'])
        # Ordered newest-first
        self.assertEqual(['大保底', '歪', '大保底', '歪'], [h['UpStatus'] for h in data['hits']])

        rows2 = rows + [
            dict(index=5, key='g5', rarity='狂', type='活动', cells=['2026-10-15 10:00:05', '诸道无我', '承霄']),
            dict(index=6, key='g6', rarity='狂', type='活动', cells=['2026-10-15 10:00:06', '诸道无我', '承霄']),
        ]
        (archive / '活动.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows2), encoding='utf-8')
        data2 = self.store.snapshot('default-0')
        self.assertEqual(2, data2['up_wins'])
        self.assertEqual(2, data2['up_losses'])
        self.assertEqual(2, data2['up_guaranteed'])
        self.assertEqual('50.0%', data2['up_rate'])

    def test_expected_up_excludes_standard_and_untracked_pools(self):
        banner_dir = Path(self.temp.name) / 'resource/base/gacha'
        banner_dir.mkdir(parents=True, exist_ok=True)
        (banner_dir / 'up_banners.json').write_text(json.dumps({
            'version': 1,
            'standard_pools': ['混沌都市'],
            'banners': {'诸道无我': ['承霄']},
        }, ensure_ascii=False), encoding='utf-8')

        # Keep total rows under 59 so self.write's HH:MM:{index:02d} stays valid SS (01..59).
        # Tracked pool: 1st gold 诺克斯 (OFF, excluded from interval avg) -> 4-pull 承霄 (大保底) -> 2-pull 承霄 (UP) -> 3-pull 承霄 (UP)
        # Known tracked intervals: [4, 2, 3] -> avg = 3.0; wins=2, losses=1 -> mult = 4/3 -> expected_up = 4.0
        rows_a = [('垫', '普', '诸道无我'), ('诺克斯', '狂', '诸道无我')]
        rows_a += [('垫', '普', '诸道无我')] * 3 + [('承霄', '狂', '诸道无我')]
        rows_a += [('垫', '普', '诸道无我')] * 1 + [('承霄', '狂', '诸道无我')]
        rows_a += [('垫', '普', '诸道无我')] * 2 + [('承霄', '狂', '诸道无我')]
        # Unknown pool in same category (must be excluded from expected_up)
        rows_a += [('垫', '普', '未知池')] * 9 + [('卓娅', '狂', '未知池')]
        self.write('default-0', rows_a)

        # Standard pool with very high intervals (must be completely excluded)
        rows_std = [('卓娅', '狂', '混沌都市')] + [('垫', '普', '混沌都市')] * 29 + [('席宁', '狂', '混沌都市')]
        self.write('default-3', rows_std)

        all_snap = self.store.snapshot('all')
        self.assertEqual(2, all_snap['up_wins'])
        self.assertEqual(1, all_snap['up_losses'])
        self.assertEqual(1, all_snap['up_guaranteed'])
        self.assertAlmostEqual(4.0, all_snap['expected_up'], places=4)
        self.assertEqual('4.0 抽', all_snap['expected_up_text'])
        self.assertEqual(3, all_snap['tracked_gold_count'])

        std_snap = self.store.snapshot('default-3')
        self.assertIsNone(std_snap['expected_up'])
        self.assertEqual('—', std_snap['expected_up_text'])
        self.assertEqual('未判定池不纳入计算', std_snap['expected_up_sub'])


if __name__=='__main__':unittest.main()
