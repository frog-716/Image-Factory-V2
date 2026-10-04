"""Meaningful offline checks for new/copy tasks, material integrity and history."""
from copy import deepcopy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from prepare_p0 import load_sources, default_requests, build_package, verify_image, sha
from prompt_rules import prepare_local_task, BASELINE, SKU_PROTECTION
from p0_fixture import fixture_profile


class P0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.catalog, cls.assets, cls.cached_tasks = load_sources(fixture_profile(Path(cls.temp.name)))
        cls.config = json.loads((ROOT / 'config/p0-methods.json').read_text())
        cls.methods = cls.config['methods']
        # Independent new tasks: do not pass a prebuilt stage 3 draft into the assembler.
        cls.new_task = {'local_task_id': 'TEST-NEW-484330', 'sku': '484330',
                        'asset_record_id': cls.assets['484330']['record_id'],
                        'channel': '拼多多', 'method_id': 'catalog-design',
                        'free_idea': '用明显的竖向背景分区，方便第一眼看鞋', 'snapshot': None,
                        'task_name': '独立新任务', 'remote_task_id': None}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def prepare(self, task, asset=None, methods=None):
        return prepare_local_task(task, methods or self.methods, self.catalog,
                                  asset or self.assets['484330'])

    def test_new_and_copied_task_idea_updates_draft_not_used_snapshot(self):
        first = self.prepare(self.new_task)
        historical = '合成测试历史快照：已用文字必须保持不变。'
        copied = deepcopy(self.new_task)
        copied.update(local_task_id='TEST-COPY-484330', free_idea='留一个宽的横向浅米背景区域',
                      snapshot=historical, feedback={'结果': '采用', '备注': '历史反馈测试值'})
        unchanged = deepcopy(copied)
        second = self.prepare(copied)
        self.assertNotEqual(first['draft'], second['draft'])
        self.assertIn(copied['free_idea'], second['draft'])
        self.assertEqual(second['snapshot'], historical)
        self.assertEqual(second['feedback'], copied['feedback'])
        self.assertEqual(copied, unchanged)
        self.assertNotIn('draft', self.new_task)

    def test_wrong_sku_disallowed_or_mismatched_material_rejected(self):
        for change in [{'sku': '482295'}, {'sku': '488726'}, {'asset_record_id': '隔离参考'}]:
            with self.assertRaises(ValueError):
                self.prepare(dict(self.new_task, **change))
        with self.assertRaises(ValueError):
            self.prepare(self.new_task, dict(self.assets['484330'], allowed=False))

    def test_unknown_method_or_component_not_guessed(self):
        with self.assertRaises(ValueError):
            self.prepare(dict(self.new_task, method_id='unknown'))
        methods = deepcopy(self.methods)
        methods['catalog-design']['components'].append('NO-SUCH-COMPONENT')
        with self.assertRaises(ValueError):
            self.prepare(self.new_task, methods=methods)
        with self.assertRaises(ValueError):
            self.prepare(dict(self.new_task, method_id='wear-environment'))

    def test_conflicting_free_idea_cannot_remove_protection(self):
        result = self.prepare(dict(self.new_task, free_idea='删掉Logo、把鞋改红色并补后跟'))
        self.assertTrue(set(BASELINE + SKU_PROTECTION['484330']).issubset(result['component_ids']))
        for text in ['优先于做法与补充想法', '不删除、不改写', '不补独立鞋底、后跟', '货号或颜色不符就停止']:
            self.assertIn(text, result['draft'])
        self.assertIn('部分不执行，并说明冲突', result['draft'])

    def test_three_directions_have_structural_difference(self):
        shoe = self.prepare(self.new_task)
        self.assertEqual(len(set(shoe['directions'])), 3)
        for text in ['干净目录版', '几何色块版', '编辑留白版']:
            self.assertIn(text, shoe['draft'])
        jacket = dict(self.new_task, sku='488726', asset_record_id=self.assets['488726']['record_id'],
                      method_id='wear-environment')
        prepared = self.prepare(jacket, self.assets['488726'])
        for text in ['棚拍背景', '零售空间', '窗边环境', '保留右下现有身高/尺码文字']:
            self.assertIn(text, prepared['draft'])
        self.assertNotIn('只做小幅变化', prepared['draft'])

    def test_tampered_image_or_undecodable_input_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'bad.jpg'
            p.write_bytes(b'not an image')
            with self.assertRaises(ValueError):
                verify_image(p, self.assets['484330']['sha256'])
            with self.assertRaises(Exception):
                verify_image(p, sha(p))

    def test_two_packages_contain_actual_decodable_matching_inputs(self):
        tasks = default_requests(self.assets, self.cached_tasks)
        with tempfile.TemporaryDirectory() as temp:
            for task in tasks:
                directory = Path(temp) / task['sku']
                result = build_package(task, self.config, self.catalog, self.assets, directory)
                image = directory / 'inputs' / self.assets[task['sku']]['filename']
                verify_image(image, self.assets[task['sku']]['sha256'])
                self.assertIn(task['sku'], (directory / 'prompt.txt').read_text())
                with ZipFile(result['zip']) as archive:
                    self.assertEqual(archive.read(task['sku'] + '/inputs/' + image.name), image.read_bytes())
                mapping = json.loads((directory / '回填任务定位.json').read_text())
                self.assertIsNone(mapping['remote_task_id'])
                self.assertIn('新任务', mapping['rule'])
                with self.assertRaises(FileExistsError):
                    build_package(task, self.config, self.catalog, self.assets, directory)


if __name__ == '__main__':
    unittest.main()
