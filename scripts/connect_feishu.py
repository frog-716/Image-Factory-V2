"""Explicit, local-first Feishu task preparation. No model, queue or listener."""
import argparse
from copy import deepcopy
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from PIL import Image
from lark_cli import LarkCLI, CLIError, UnknownWrite
from prepare_p0 import ROOT, load_sources, read, save, sha, verify_image, build_package
from prompt_rules import prepare_local_task

TASKS = '生图任务'
FEEDBACK = '成图与反馈'
INPUT_FIELDS = ('商品', '渠道', '图片功能', '选择素材', '自由补充想法', '目标图片数量')
COPY_FIELDS = (*INPUT_FIELDS, '所处版面', '场景', '风格')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def fields_match(row, expected):
    # Base can normalize an explicitly empty text cell to null/omitted.
    return all(row.get(key) == value or (value == '' and row.get(key) is None)
               for key, value in expected.items())


class Connection:
    def __init__(self, root=ROOT, cli=None, sources=None, config=None):
        self.root = Path(root)
        self.local = self.root / '.local/feishu-connect/runtime'
        self.local.mkdir(parents=True, exist_ok=True)
        self.cli = cli or LarkCLI(self.root)
        self.config = config or read(self.root / 'private/base.local.json')
        self.token = self.config['base']['base_token']
        self.catalog, self.assets, _ = sources or load_sources()
        self.methods = read(ROOT / 'config/p0-methods.json')
        self.state_path = self.local / 'state.json'
        self.state = read(self.state_path) if self.state_path.exists() else {'tasks': {}, 'feedback': {}}

    def persist(self):
        temp = self.state_path.with_suffix('.tmp')
        with temp.open('w') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        temp.replace(self.state_path)

    def args(self, command, table):
        return ['base', command, '--base-token', self.token,
                '--table-id', self.config['tables'][table]['id']]

    def rows(self, table, ids=None, fields=None):
        output = self.local / (uuid.uuid4().hex + '.ndjson')
        args = self.args('+record-get' if ids is not None else '+record-list', table)
        for record_id in ids or []:
            args += ['--record-id', record_id]
        if fields is None:
            schema = read(ROOT / 'config/schema.json')
            fields = next(t['fields'] for t in schema['tables'] if t['name'] == table)
            fields = [f['name'] for f in fields]
        for field in fields:
            args += ['--field-id', field]
        manifest = self.cli.call(args + ['--format', 'ndjson', '--output',
                                        str(output.relative_to(self.root))])['data']
        records = [json.loads(line) for line in output.read_text().splitlines() if line.strip()]
        if manifest['has_more'] or manifest['records_count'] != len(records):
            raise ValueError('读取不完整，停止，不能据部分记录判断安全。')
        if ids is not None and {r['record_id'] for r in records} != set(ids):
            raise ValueError('记录ID未完整读回。')
        return records

    def row(self, table, record_id):
        return self.rows(table, [record_id])[0]

    def check_fields(self, table):
        actual = self.cli.call(self.args('+field-list', table))['data']['fields']
        actual = {f['name']: f for f in actual}
        expected = next(t['fields'] for t in read(ROOT / 'config/schema.json')['tables'] if t['name'] == table)
        if set(actual) != {f['name'] for f in expected}:
            raise ValueError('六表字段与核实模型不符，停止，不自动改表。')
        for field in expected:
            live = actual[field['name']]
            if live['type'] != field['type']:
                raise ValueError('字段类型变化，停止。')
            if field['type'] == 'link' and live.get('link_table') != self.config['tables'][field['link_table']]['id']:
                raise ValueError('关联目标不符。')
        return actual

    def write(self, table, payload, *, create=False):
        # Immutable request bytes are saved before transport journals and sends it.
        path = self.local / (uuid.uuid4().hex + '-request.json')
        save(path, payload)
        response = self.cli.call(self.args('+record-batch-create' if create else '+record-batch-update', table)
                                 + ['--json', '@' + str(path.relative_to(self.root))], write=True)['data']
        if response.get('ignored_fields') or (create and len(response.get('record_id_list', [])) != 1):
            self.uncertain('部分成功或新ID响应不完整，先只读核对，禁止重发。')
        return response

    def uncertain(self, reason):
        self.cli._journal({'operation': uuid.uuid4().hex, 'state': 'unknown', 'reason': reason})
        raise UnknownWrite(reason)

    def update(self, table, record_id, fields):
        if table == TASKS and '最终提示词快照' in fields:
            raise ValueError('普通更新不允许写历史快照。')
        self.write(table, {'update_records': {record_id: fields}})

    def components(self, codes):
        rows = self.rows('提示词组件库')
        if len(rows) != 26:
            raise ValueError('组件数量变化，停止。')
        ids = []
        for code in codes:
            component = self.catalog[code]
            matches = [r for r in rows if r['组件名称'] == component['名称']]
            if (len(matches) != 1 or matches[0]['是否启用'] is not True
                    or matches[0]['组件内容'] != component['组件内容']):
                raise ValueError('组件停用或内容变化，需人工核对，不猜测。')
            ids.append({'id': matches[0]['record_id']})
        return ids

    def request(self, row, method=None):
        material_ids = row.get('选择素材') or []
        candidates = [a for a in self.assets.values() if material_ids == [{'id': a['record_id']}]]
        if len(candidates) != 1:
            raise ValueError('任务必须选一张现有批准原图。')
        asset = candidates[0]
        if row.get('商品') != [{'id': asset['product_record']['record_id']}]:
            raise ValueError('任务商品与素材不一致。')
        functions = row.get('图片功能') or []
        if not isinstance(functions, list) or len(functions) != 1:
            raise ValueError('图片功能必须从三个固定做法中单选。')
        method = method or next((k for k, v in self.methods['methods'].items()
                                 if v['name'] == functions[0]), None)
        channel = row.get('渠道') or []
        if len(channel) != 1:
            raise ValueError('只允许一个已支持渠道。')
        return {'local_task_id': 'FEISHU-' + row['record_id'], 'remote_task_id': row['record_id'],
                'task_name': row['任务名称'], 'sku': asset['sku'], 'asset_record_id': asset['record_id'],
                'channel': channel[0], 'method_id': method,
                'free_idea': row.get('自由补充想法') or '',
                'target_count': row.get('目标图片数量'), 'snapshot': row.get('最终提示词快照'),
                'mapping_status': '真实飞书任务；本地显式准备',
                'source_task_record_id': self.state['tasks'].get(row['record_id'], {}).get('source')}

    def live_asset(self, asset):
        material = self.row('素材库', asset['record_id'])
        product = self.row('商品库', asset['product_record']['record_id'])
        attachments = material.get('附件') or []
        if (material.get('允许用于生图') is not True
                or product.get('货号') != asset['sku'] or product.get('商品状态') != ['可用']
                or material.get('关联商品') != [{'id': product['record_id']}]
                or len(attachments) != 1 or attachments[0]['name'] != asset['filename']
                or asset['sha256'] not in (material.get('素材说明') or '')):
            raise ValueError('实时商品/素材许可、关联或版本变化，停止。')
        path = self.local / (uuid.uuid4().hex + '-' + asset['filename'])
        self.cli.call(self.args('+record-download-attachment', '素材库') +
                      ['--record-id', asset['record_id'], '--file-token', attachments[0]['file_token'],
                       '--output', str(path.relative_to(self.root))], attachment=True)
        verify_image(path, asset['sha256'])
        return dict(asset, path=str(path), base_config=self.config,
                    record_evidence='本次实时读回商品/素材，并下载核验原图SHA256')

    def create(self, sku=None, method=None, idea=None, channel=None, source=None, name=None):
        self.check_fields(TASKS)
        source_row = self.row(TASKS, source) if source else None
        if source_row:
            request = self.request(source_row, method)
            fields = {k: deepcopy(source_row[k]) for k in COPY_FIELDS if source_row.get(k) is not None}
        else:
            if sku not in self.assets:
                raise ValueError('该商品待素材，不创建任务。')
            asset = self.assets[sku]
            request = {'local_task_id': 'preflight', 'sku': sku, 'asset_record_id': asset['record_id'],
                       'method_id': method, 'channel': channel or '拼多多', 'free_idea': idea or '', 'target_count': 3}
            fields = {'商品': [{'id': asset['product_record']['record_id']}],
                      '选择素材': [{'id': asset['record_id']}]}
        request.update(method_id=method or request['method_id'],
                       free_idea=request['free_idea'] if idea is None else idea,
                       channel=channel or request['channel'], target_count=3)
        prepared = prepare_local_task(request, self.methods['methods'], self.catalog, self.assets[request['sku']])
        self.live_asset(self.assets[request['sku']])
        fields.update({'任务名称': name or f'{request["sku"]} · 新方向 · {datetime.now().strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:6]}',
                       '图片功能': [prepared['method_name']], '渠道': [request['channel']], '目标图片数量': 3,
                       '自由补充想法': request['free_idea'], '任务状态': ['待准备'],
                       '选择提示词组件': self.components(prepared['component_ids'])})
        # Never copy snapshot, draft, operator, feedback or creation time.
        record_id = self.write(TASKS, {'create_records': [fields]}, create=True)['record_id_list'][0]
        self.state['tasks'][record_id] = {'source': source, 'packages': [], 'created_by_connector': True}
        self.persist()  # Keep real ID even if subsequent read/prepare fails.
        row = self.row(TASKS, record_id)
        if row.get('最终提示词快照') or not fields_match(row, fields):
            self.uncertain('新任务字段读回不符，先核对，不重建。')
        if source_row != (self.row(TASKS, source) if source else None):
            raise ValueError('复制期间原任务发生变化，停止检查。')
        return record_id

    def adopt(self, record_id):
        """An operator can create/copy a fresh row directly in Feishu."""
        if record_id in self.state['tasks']:
            return
        row = self.row(TASKS, record_id)
        protected_path = self.local.parent / 'protected-records.json'
        protected = read(protected_path) if protected_path.exists() else []
        if record_id in protected or row.get('最终提示词快照') or any(
                {'id': record_id} in (f.get('关联任务') or []) for f in self.rows(FEEDBACK)):
            raise ValueError('该记录有历史或属于受保护旧任务，请复制为新任务。')
        self.state['tasks'][record_id] = {'source': None, 'packages': [], 'created_by_connector': False}
        self.persist()

    def prepare(self, record_id, idea=None, method=None):
        self.check_fields(TASKS)
        self.adopt(record_id)
        before = self.row(TASKS, record_id)
        row = deepcopy(before)
        if idea is not None:
            row['自由补充想法'] = idea
        request = self.request(row, method)
        asset = self.live_asset(self.assets[request['sku']])
        prepared = prepare_local_task(request, self.methods['methods'], self.catalog, asset)
        components = self.components(prepared['component_ids'])
        current = self.row(TASKS, record_id)
        if any(current.get(k) != before.get(k) for k in (*INPUT_FIELDS, '最终提示词快照', '智能提示词草稿')):
            raise ValueError('准备期间有人修改任务，停止；重新读取后再准备。')
        fields = {'智能提示词草稿': prepared['draft'], '图片功能': [prepared['method_name']],
                  '选择提示词组件': components}
        if idea is not None:
            fields['自由补充想法'] = idea
        if not before.get('最终提示词快照'):
            fields['任务状态'] = ['待生成']
        self.update(TASKS, record_id, fields)
        after = self.row(TASKS, record_id)
        if after.get('最终提示词快照') != before.get('最终提示词快照') or not fields_match(after, fields):
            self.uncertain('草稿读回不符或快照变化，停止，不自动重发。')
        request['snapshot'] = after.get('最终提示词快照')
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        output = self.root / 'out/feishu' / record_id / stamp
        result = build_package(request, self.methods, self.catalog, {request['sku']: asset}, output)
        entry = {'package': str(output.resolve()), 'prompt_sha256': result['draft_sha256'],
                 'input_digest': digest({k: after.get(k) for k in INPUT_FIELDS}),
                 'record_id': record_id, 'image_sha256': asset['sha256']}
        self.state['tasks'][record_id]['packages'].append(entry)
        self.persist()
        return result

    def package(self, directory):
        directory = Path(directory).resolve()
        request = read(directory / 'request.json')
        record_id = request.get('remote_task_id')
        entries = self.state['tasks'].get(record_id, {}).get('packages', [])
        entry = next((e for e in entries if e['package'] == str(directory)), None)
        if entry is None or sha(directory / 'prompt.txt') != entry['prompt_sha256']:
            raise ValueError('准备包未登记或Prompt已被替换，不能回填。')
        asset = self.assets.get(request.get('sku'))
        if asset is None or entry['image_sha256'] != asset['sha256']:
            raise ValueError('准备包商品或原图版本不符。')
        verify_image(directory / 'inputs' / asset['filename'], entry['image_sha256'])
        for line in (directory / 'CHECKSUMS.sha256').read_text().splitlines():
            expected, name = line.split('  ', 1)
            path = (directory / name).resolve()
            if not path.is_relative_to(directory) or sha(path) != expected:
                raise ValueError('准备包内容/校验不符。')
        row = self.row(TASKS, record_id)
        prompt = (directory / 'prompt.txt').read_text().rstrip('\n')
        return directory, entry, row, prompt

    def mark_used(self, directory):
        self.check_fields(TASKS)
        _, entry, row, prompt = self.package(directory)
        existing = row.get('最终提示词快照')
        if existing:
            if existing != prompt:
                raise ValueError('已有不同快照，不能覆盖；请复制新任务。')
            return row['record_id']
        inputs = {k: row.get(k) for k in INPUT_FIELDS}
        legacy_inputs = deepcopy(inputs)
        if isinstance(inputs.get('图片功能'), list) and len(inputs['图片功能']) == 1:
            legacy_inputs['图片功能'] = inputs['图片功能'][0]
        if row.get('智能提示词草稿') != prompt or entry['input_digest'] not in {digest(inputs), digest(legacy_inputs)}:
            raise ValueError('任务已变化；该包不能作为当前使用快照。')
        self.write(TASKS, {'update_records': {row['record_id']: {'最终提示词快照': prompt, '任务状态': ['待回传']}}})
        after = self.row(TASKS, row['record_id'])
        if after.get('最终提示词快照') != prompt:
            self.uncertain('使用快照未确认，停止，先对账。')
        return row['record_id']

    def feedback(self, directory, file, result=None, note='', verification=False):
        self.check_fields(FEEDBACK)
        directory, entry, row, prompt = self.package(directory)
        if result not in {None, '采用', '淘汰'}:
            raise ValueError('结果只能采用、淘汰或未评价。')
        if verification and result is not None:
            raise ValueError('链路验收不是生成结果，不填写采用/淘汰。')
        if not verification and row.get('最终提示词快照') != prompt:
            raise ValueError('先确认实际使用该Prompt；已有不同快照时不能把结果串到此任务。')
        file = Path(file).resolve()
        with Image.open(file) as image:
            image.verify()
        file_sha = sha(file)
        key = digest([row['record_id'], file_sha])
        if key in self.state['feedback']:
            raise ValueError('同一任务已有这张图的回填记录，不能重复写或覆盖旧反馈。')
        title = ('链路验收（非生成结果）' if verification else '生成结果') + ' · ' + file.name
        fields = {'图片名称': title, '关联任务': [{'id': row['record_id']}],
                  '一句话备注': ('仅核对附件与新任务关联；不算成图、不评价。' if verification else '') + note}
        if result is not None:
            fields['结果'] = [result]
        record_id = self.write(FEEDBACK, {'create_records': [fields]}, create=True)['record_id_list'][0]
        self.state['feedback'][key] = {'record_id': record_id, 'task_id': row['record_id'],
                                     'file_sha256': file_sha, 'status': 'attachment_pending'}
        self.persist()  # A failed upload never loses its existing feedback row.
        upload = self.local / (uuid.uuid4().hex + file.suffix.lower())
        shutil.copyfile(file, upload)
        self.cli.call(self.args('+record-upload-attachment', FEEDBACK) +
                      ['--record-id', record_id, '--field-id', '图片附件',
                       '--file', str(upload.relative_to(self.root))], write=True, attachment=True)
        actual = self.row(FEEDBACK, record_id)
        attachments = actual.get('图片附件') or []
        if not fields_match(actual, fields) or len(attachments) != 1:
            self.uncertain('图片反馈关联/附件未确认，停止对账。')
        downloaded = self.local / (uuid.uuid4().hex + file.suffix.lower())
        self.cli.call(self.args('+record-download-attachment', FEEDBACK) +
                      ['--record-id', record_id, '--file-token', attachments[0]['file_token'],
                       '--output', str(downloaded.relative_to(self.root))], attachment=True)
        if sha(downloaded) != file_sha:
            self.uncertain('回填附件字节不一致，停止对账。')
        self.state['feedback'][key]['status'] = 'verified'
        self.persist()
        return {'record_id': record_id, 'task_id': row['record_id'], 'verification_only': verification,
                'file_sha256': file_sha, 'result': result}


def interactive(connection):
    def choose(title, values, labels):
        print('\n' + title)
        for i, label in enumerate(labels, 1):
            print(f'{i}. {label}')
        selected = input('选择序号：').strip()
        if not selected.isdigit() or not 1 <= int(selected) <= len(values):
            raise ValueError('没有选中有效项。')
        return values[int(selected) - 1]
    action = choose('飞书准备与回填（手动运行，不生图）', ['new', 'copy', 'prepare', 'used', 'feedback'],
                    ['新建任务', '复制任务（不带旧快照和反馈）', '按当前想法准备新包', '确认已使用这份Prompt', '回填一张生成图'])
    if action in {'new', 'copy'}:
        source = None
        if action == 'copy':
            rows = connection.rows(TASKS)
            source = choose('复制哪条任务？', [r['record_id'] for r in rows], [r['任务名称'] for r in rows])
            sku = None
        else:
            sku = choose('商品', ['484330', '488726'], ['484330 鞋', '488726 茄克'])
        keys = list(connection.methods['methods'])
        method = choose('做法', keys, [connection.methods['methods'][k]['name'] for k in keys])
        channel = choose('渠道', ['拼多多', '天猫超市'], ['拼多多', '天猫超市'])
        idea = input('补充一句想法（可留空）：')
        task = connection.create(sku=sku, source=source, method=method, channel=channel, idea=idea)
        return connection.prepare(task)
    if action == 'prepare':
        rows = connection.rows(TASKS)
        task = choose('准备哪条新任务？', [r['record_id'] for r in rows], [r['任务名称'] for r in rows])
        print('读取飞书当前自由想法；旧任务有历史时须复制。')
        return connection.prepare(task)
    packages = [entry for task in connection.state['tasks'].values() for entry in task['packages']]
    if not packages:
        raise ValueError('还没有连接过的准备包，请先准备。')
    selected = choose('选择实际使用的准备包版本（最新在前）', list(reversed(packages)),
                      [read(Path(e['package']) / 'request.json')['task_name'] + ' / ' + Path(e['package']).name
                       for e in reversed(packages)])
    package = selected['package']
    if action == 'used':
        if input('仅在确实使用这份Prompt后，输入“已使用”：').strip() != '已使用':
            raise ValueError('未确认实际使用，不写快照。')
        return {'record_id': connection.mark_used(package)}
    file = Path(input('生成图文件路径（可拖入文件）：').strip().strip('"\''))
    result = choose('你的判断', [None, '采用', '淘汰'], ['尚未评价', '采用', '淘汰'])
    return connection.feedback(package, file, result, input('一句话备注（可留空）：'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('interactive', help='普通运营菜单：新建、复制、准备、确认使用、回填')
    new = sub.add_parser('new', help='创建独立飞书任务')
    new.add_argument('--sku', required=True)
    copy = sub.add_parser('copy', help='复制创作输入，不带旧快照/反馈')
    copy.add_argument('--source', required=True)
    for p in (new, copy):
        p.add_argument('--method', choices=['clear-product', 'wear-environment', 'catalog-design'], required=True)
        p.add_argument('--idea')
        p.add_argument('--channel', choices=['拼多多', '天猫超市'])
        p.add_argument('--name')
    prepare = sub.add_parser('prepare', help='读取当前想法并回写新草稿，交付本地包')
    prepare.add_argument('--task', required=True)
    prepare.add_argument('--idea', help='可选：先改当前新任务的想法')
    prepare.add_argument('--method', choices=['clear-product', 'wear-environment', 'catalog-design'])
    used = sub.add_parser('used', help='仅在真正使用该Prompt时确认一次快照')
    used.add_argument('--package', type=Path, required=True)
    used.add_argument('--confirm-used', action='store_true', required=True)
    feedback = sub.add_parser('feedback', help='一图一反馈，关联包中真实任务')
    feedback.add_argument('--package', type=Path, required=True)
    feedback.add_argument('--file', type=Path, required=True)
    feedback.add_argument('--result', choices=['采用', '淘汰'])
    feedback.add_argument('--note', default='')
    feedback.add_argument('--verification', action='store_true', help='只验收链路，不算生成结果，结果留空')
    args = parser.parse_args()
    local = ROOT / '.local/feishu-connect/runtime'
    local.mkdir(parents=True, exist_ok=True)
    with (local / 'operation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        connection = Connection()
        if args.action == 'interactive':
            result = interactive(connection)
        elif args.action in {'new', 'copy'}:
            result = {'record_id': connection.create(sku=getattr(args, 'sku', None), method=args.method,
                      idea=args.idea, channel=args.channel, source=getattr(args, 'source', None), name=args.name)}
        elif args.action == 'prepare':
            result = connection.prepare(args.task, args.idea, args.method)
        elif args.action == 'used':
            result = {'record_id': connection.mark_used(args.package)}
        else:
            result = connection.feedback(args.package, args.file, args.result, args.note, args.verification)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, FileNotFoundError, FileExistsError, CLIError, UnknownWrite, BlockingIOError) as error:
        raise SystemExit('未完成：' + str(error))
