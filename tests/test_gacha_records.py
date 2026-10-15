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
        self.assertEqual('无上一条狂记录', data['hits'][0]['Note'])

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


if __name__=='__main__':unittest.main()
