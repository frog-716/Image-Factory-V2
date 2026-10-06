"""Offline transport double; every ID/image here is synthetic, never live proof."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from connect_feishu import Connection, TASKS, FEEDBACK, INPUT_FIELDS, digest
from lark_cli import UnknownWrite
from prepare_p0 import load_sources
from p0_fixture import fixture_profile


class MemoryCLI:
    def __init__(self, root, schema, config, assets, catalog):
        self.root, self.schema, self.config = root, schema, config
        self.records = {t['name']: {} for t in schema['tables']}
        self.attachments = {}
        self.writes = []
        self.unknown = False
        self.partial_create = False
        for asset in assets.values():
            product = deepcopy(asset['product_record'])
            product['商品状态'] = ['可用']
            material = deepcopy(asset['material_record'])
            token = 'synthetic-file-' + asset['sku']
            material['附件'][0]['file_token'] = token
            self.attachments[token] = Path(asset['path']).read_bytes()
            self.records['商品库'][product['record_id']] = product
            self.records['素材库'][material['record_id']] = material
        for code, component in catalog.items():
            record_id = 'synthetic-component-' + code
            self.records['提示词组件库'][record_id] = {'record_id': record_id, '组件名称': component['名称'],
                                                    '组件内容': component['组件内容'], '是否启用': True}

    def _journal(self, entry):
        if entry['state'] == 'unknown':
            self.unknown = True

    def call(self, args, write=False, attachment=False):
        if write and self.unknown:
            raise UnknownWrite('synthetic unresolved write')
        def arg(name):
            return args[args.index(name) + 1]
        table = next(k for k, v in self.config['tables'].items() if v['id'] == arg('--table-id'))
        command = args[1]
        data = {}
        if command == '+field-list':
            fields = deepcopy(next(t['fields'] for t in self.schema['tables'] if t['name'] == table))
            for f in fields:
                if f['type'] == 'link':
                    f['link_table'] = self.config['tables'][f['link_table']]['id']
            data = {'fields': fields}
        elif command in {'+record-list', '+record-get'}:
            ids = [args[i+1] for i, a in enumerate(args) if a == '--record-id']
            rows = list(self.records[table].values()) if command == '+record-list' else [
                self.records[table][i] for i in ids if i in self.records[table]]
            path = self.root / arg('--output')
            path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
            data = {'records_count': len(rows), 'has_more': False}
        elif command in {'+record-batch-create', '+record-batch-update'}:
            payload = json.loads((self.root / arg('--json')[1:]).read_text())
            self.writes.append((table, deepcopy(payload)))
            if command == '+record-batch-create':
                record_id = 'synthetic-new-' + str(len(self.writes))
                row = {k: (None if v == '' else deepcopy(v)) for k, v in payload['create_records'][0].items()}
                row.update(record_id=record_id)
                if table == TASKS:
                    row.update(最终提示词快照=None)
                else:
                    row.update(图片附件=[], 结果=row.get('结果'))
                self.records[table][record_id] = row
                data = {'record_id_list': [] if self.partial_create else [record_id]}
            else:
                for record_id, fields in payload['update_records'].items():
                    self.records[table][record_id].update({k: (None if v == '' else deepcopy(v)) for k, v in fields.items()})
        elif command == '+record-download-attachment':
            (self.root / arg('--output')).write_bytes(self.attachments[arg('--file-token')])
        elif command == '+record-upload-attachment':
            path = self.root / arg('--file')
            token = 'synthetic-upload-' + str(len(self.attachments))
            self.attachments[token] = path.read_bytes()
            self.records[table][arg('--record-id')][arg('--field-id')].append(
                {'file_token': token, 'name': path.name, 'size': path.stat().st_size})
            self.writes.append((table, {'attachment': arg('--record-id')}))
        else:
            raise AssertionError(command)
        return {'ok': True, 'data': data}


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        catalog, assets, tasks = load_sources(fixture_profile(self.root))
        schema = json.loads((ROOT / 'config/schema.json').read_text())
        config = {'base': {'base_token': 'synthetic-base'},
                  'tables': {t['name']: {'id': 'synthetic-table-' + str(i)} for i, t in enumerate(schema['tables'])}}
        self.cli = MemoryCLI(self.root, schema, config, assets, catalog)
        self.connection = Connection(self.root, self.cli, (catalog, assets, tasks), config)
        self.assets = assets

    def tearDown(self):
        self.temp.cleanup()

    def new(self):
        return self.connection.create(sku='484330', method='catalog-design', idea='宽留白')

    def package(self, task):
        return Path(self.connection.prepare(task)['package'])

    def test_new_task_and_package_use_returned_remote_id(self):
        task = self.connection.create(sku='484330', method='catalog-design', idea='')
        package = self.package(task)
        mapping = json.loads((package / '回填任务定位.json').read_text())
        self.assertEqual(mapping['remote_task_id'], task)
        self.assertEqual((package / 'inputs' / self.assets['484330']['filename']).read_bytes(),
                         Path(self.assets['484330']['path']).read_bytes())
        self.assertIn(task, (package / '使用说明.md').read_text())
        self.assertIsNone(self.cli.records[TASKS][task]['自由补充想法'])
        self.assertIn('无额外补充', (package / 'prompt.txt').read_text())
        self.connection.prepare(task, idea='')

    def test_copy_does_not_copy_snapshot_or_modify_history(self):
        task = self.new()
        self.cli.records[TASKS][task]['最终提示词快照'] = 'synthetic historical snapshot'
        self.cli.records[FEEDBACK]['synthetic-old-feedback'] = {'record_id': 'synthetic-old-feedback',
                   '关联任务': [{'id': task}], '结果': ['采用'], '一句话备注': 'synthetic historical feedback'}
        before = deepcopy(self.cli.records)
        copied = self.connection.create(source=task, method='catalog-design', idea='新想法')
        self.assertIsNone(self.cli.records[TASKS][copied]['最终提示词快照'])
        self.assertEqual(self.cli.records[TASKS][task], before[TASKS][task])
        self.assertEqual(self.cli.records[FEEDBACK], before[FEEDBACK])

    def test_idea_changes_draft_preserves_nonempty_snapshot_and_feedback(self):
        task = self.new()
        first = self.package(task)
        self.connection.mark_used(first)
        snapshot = self.cli.records[TASKS][task]['最终提示词快照']
        feedback_before = deepcopy(self.cli.records[FEEDBACK])
        second = Path(self.connection.prepare(task, idea='一条流动背景线')['package'])
        self.assertNotEqual((first / 'prompt.txt').read_bytes(), (second / 'prompt.txt').read_bytes())
        self.assertIn('一条流动背景线', (second / 'prompt.txt').read_text())
        self.assertEqual(self.cli.records[TASKS][task]['最终提示词快照'], snapshot)
        self.assertEqual(self.cli.records[FEEDBACK], feedback_before)
        with self.assertRaises(ValueError):
            self.connection.mark_used(second)

    def test_changed_inputs_cannot_be_frozen_from_stale_package(self):
        task = self.new()
        package = self.package(task)
        self.cli.records[TASKS][task]['自由补充想法'] = '改过但未准备'
        with self.assertRaises(ValueError):
            self.connection.mark_used(package)
        self.assertIsNone(self.cli.records[TASKS][task].get('最终提示词快照'))

    def test_revoked_asset_blocks_creation_before_write(self):
        asset = self.assets['484330']
        self.cli.records['素材库'][asset['record_id']]['允许用于生图'] = False
        with self.assertRaises(ValueError):
            self.new()
        self.assertEqual(self.cli.writes, [])

    def test_wrong_task_product_cannot_prepare(self):
        task = self.new()
        self.cli.records[TASKS][task]['商品'] = [{'id': 'synthetic-wrong-product'}]
        before = deepcopy(self.cli.writes)
        with self.assertRaises(ValueError):
            self.package(task)
        self.assertEqual(self.cli.writes, before)

    def test_picture_function_requires_single_fixed_selection(self):
        task = self.new()
        self.assertEqual(self.cli.records[TASKS][task]['图片功能'], ['版式有设计感'])
        for invalid in ['版式有设计感', [], ['商品看清楚', '版式有设计感'], ['任意自由文本']]:
            self.cli.records[TASKS][task]['图片功能'] = invalid
            writes = deepcopy(self.cli.writes)
            with self.assertRaises(ValueError):
                self.package(task)
            self.assertEqual(self.cli.writes, writes)

    def test_select_conversion_preserves_compatible_old_package_confirmation(self):
        task = self.new()
        package = self.package(task)
        row = self.cli.records[TASKS][task]
        old_inputs = {k: deepcopy(row.get(k)) for k in INPUT_FIELDS}
        old_inputs['图片功能'] = old_inputs['图片功能'][0]
        self.connection.state['tasks'][task]['packages'][0]['input_digest'] = digest(old_inputs)
        self.connection.mark_used(package)
        self.assertEqual(row['最终提示词快照'], (package / 'prompt.txt').read_text().rstrip('\n'))

    def test_ai_experiment_suggestions_cannot_change_production_prompt(self):
        task = self.new()
        self.cli.records[TASKS][task]['智能创意建议'] = '未经人工选择的AI建议：补鞋底并改原标记'
        package = self.package(task)
        self.assertNotIn('未经人工选择的AI建议', (package / 'prompt.txt').read_text())
        copied = self.connection.create(source=task, method='catalog-design')
        self.assertNotIn('智能创意建议', self.cli.records[TASKS][copied])
        self.assertIsNone(self.cli.records[TASKS][copied]['最终提示词快照'])

    def test_changed_component_content_blocks_new_draft(self):
        task = self.new()
        self.cli.records['提示词组件库']['synthetic-component-P01']['组件内容'] = 'unexpected change'
        with self.assertRaises(ValueError):
            self.package(task)
        self.assertNotIn('智能提示词草稿', self.cli.records[TASKS][task])

    def test_old_task_with_feedback_cannot_be_adopted(self):
        task = self.new()
        self.connection.state['tasks'].pop(task)
        self.cli.records[FEEDBACK]['old'] = {'record_id': 'old', '关联任务': [{'id': task}]}
        with self.assertRaises(ValueError):
            self.package(task)

    def test_feedback_attaches_to_new_task_and_does_not_overwrite_old(self):
        task = self.new()
        package = self.package(task)
        self.connection.mark_used(package)
        self.cli.records[FEEDBACK]['old'] = {'record_id': 'old', '结果': ['淘汰'], '一句话备注': 'old'}
        old = deepcopy(self.cli.records[FEEDBACK]['old'])
        result = self.connection.feedback(package, self.assets['484330']['path'], '采用', '')
        row = self.cli.records[FEEDBACK][result['record_id']]
        self.assertEqual(row['关联任务'], [{'id': task}])
        self.assertEqual(row['结果'], ['采用'])
        self.assertEqual(len(row['图片附件']), 1)
        self.assertIsNone(row['一句话备注'])
        self.assertEqual(self.cli.records[FEEDBACK]['old'], old)
        with self.assertRaises(ValueError):
            self.connection.feedback(package, self.assets['484330']['path'], '淘汰')

    def test_verification_is_labeled_and_cannot_claim_adoption(self):
        task = self.new()
        package = self.package(task)
        with self.assertRaises(ValueError):
            self.connection.feedback(package, self.assets['484330']['path'], '采用', verification=True)
        result = self.connection.feedback(package, self.assets['484330']['path'], verification=True)
        row = self.cli.records[FEEDBACK][result['record_id']]
        self.assertIn('非生成结果', row['图片名称'])
        self.assertIsNone(row['结果'])
        self.assertIsNone(self.cli.records[TASKS][task]['最终提示词快照'])

    def test_tampered_package_or_unconfirmed_prompt_cannot_return_result(self):
        task = self.new()
        package = self.package(task)
        with self.assertRaises(ValueError):
            self.connection.feedback(package, self.assets['484330']['path'])
        self.connection.mark_used(package)
        (package / 'request.json').write_text('{}')
        with self.assertRaises(ValueError):
            self.connection.feedback(package, self.assets['484330']['path'])

    def test_incomplete_create_acknowledgment_stops_without_retry(self):
        self.cli.partial_create = True
        with self.assertRaises(UnknownWrite):
            self.new()
        self.assertEqual(len(self.cli.writes), 1)
        with self.assertRaises(UnknownWrite):
            self.new()
        self.assertEqual(len(self.cli.writes), 1)


if __name__ == '__main__':
    unittest.main()
