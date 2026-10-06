"""LEGACY / VALIDATION ONLY: historical P0 local preparation.

Retained to validate approved materials and historical packages, not for daily
operations. No network client, Lark transport, or model call.
"""
import argparse
import csv
import hashlib
import html
import json
import shutil
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image
from prompt_rules import prepare_local_task

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def save(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def verify_image(path, expected_sha):
    if sha(path) != expected_sha:
        raise ValueError('原图SHA256不一致，拒绝替换或隔离参考。')
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        image.load()
        if image.size != (1200, 1600):
            raise ValueError('原图尺寸不符。')


def load_sources(profile_path=None):
    """Public code reads an ignored local allowlist; no handoff/cache dependency."""
    profile = read(profile_path or ROOT / 'private/p0-sources.local.json')
    with (ROOT / 'config/prompt-components.csv').open(encoding='utf-8-sig', newline='') as f:
        catalog = {c['组件编号']: c for c in csv.DictReader(f)}
    if len(catalog) != 26:
        raise ValueError('沿用26组件，不增减组件。')
    tasks = profile['tasks']
    assets = {}
    for sku in ['484330', '488726']:
        asset = next(a for a in profile['assets'] if a['sku'] == sku)
        path = ROOT / asset['file']
        verify_image(path, asset['sha256'])
        verify_image(ROOT / asset['canonical_file'], asset['sha256'])
        record = asset['material_record']
        product = asset['product_record']
        if (product['货号'] != sku or record['允许用于生图'] is not True
                or record['关联商品'] != [{'id': product['record_id']}]
                or record['record_id'] != asset['record_id'] or asset.get('allowed') is not True
                or asset['sha256'] not in record['素材说明']
                or record['附件'][0]['name'] != path.name):
            raise ValueError('原图与正式素材/商品关联不符。')
        assets[sku] = dict(asset, sku=sku, path=str(path), filename=path.name,
                           record_id=record['record_id'], allowed=True,
                           record_evidence=profile.get('evidence', '本地批准清单；非实时远端核对'),
                           base_config=profile.get('base', {}))
    return catalog, assets, tasks


def default_requests(assets, tasks):
    result = []
    for sku, method in [('484330', 'catalog-design'), ('488726', 'wear-environment')]:
        source = next(t for t in tasks if sku in t['任务名称'] and t['渠道'] == ['拼多多'])
        result.append({'local_task_id': f'P0-{sku}-001', 'task_name': f'UNIQLO {sku} · P0新方向对照',
                       'sku': sku, 'asset_record_id': assets[sku]['record_id'], 'channel': '拼多多',
                       'method_id': method, 'free_idea': '', 'target_count': 3,
                       'remote_task_id': None, 'source_task_record_id': source['record_id'],
                       'snapshot': None,
                       'mapping_status': '本地新任务；旧任务仅供定位，尚未创建/复制飞书新任务'})
    return result


def build_package(task, methods_config, catalog, assets, output):
    sku = task.get('sku')
    if sku not in assets:
        raise ValueError('SKU没有核实素材。')
    asset = assets[sku]
    verify_image(asset['path'], asset['sha256'])
    prepared = prepare_local_task(task, methods_config['methods'], catalog, asset)
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=False)  # Never overwrite an earlier package/snapshot.
    inputs = directory / 'inputs'
    inputs.mkdir()
    image_path = inputs / asset['filename']
    shutil.copyfile(asset['path'], image_path)
    verify_image(image_path, asset['sha256'])
    (directory / 'prompt.txt').write_text(prepared['draft'] + '\n')
    save(directory / 'request.json', task)
    save(directory / 'prepared.json', prepared)
    save(directory / '素材与来源.json', {k: v for k, v in asset.items()
                                       if k not in {'path', 'base_config', 'material_record', 'product_record'}})
    selected = {code: catalog[code] for code in prepared['component_ids']}
    save(directory / '组件引用.json', {'selected': selected, 'research_sources': methods_config['sources'],
                                     'note': '引用现有组件，只压缩必要保护并展开三方向，不串接26条。'})
    config = asset.get('base_config', {})
    base = config.get('base', {}).get('url')
    start = (base + '?table=' + config['tables']['生图任务']['id'] + '&view=' + config['tables']['生图任务']['view_id']) if base else None
    feedback = (base + '?table=' + config['tables']['成图与反馈']['id'] + '&view=' + config['tables']['成图与反馈']['view_id']) if base else None
    mapping = {'local_task_id': task['local_task_id'], 'task_name': task['task_name'],
               'remote_task_id': task.get('remote_task_id'), 'source_task_record_id': task.get('source_task_record_id'),
               'start_url': start, 'feedback_url': feedback,
               'rule': '旧任务仅作定位参照，不能把本次新Prompt或结果写进旧快照/反馈。每张新结果只关联本包登记的新任务；远端ID为空时先创建新任务，不能猜ID。'}
    save(directory / '回填任务定位.json', mapping)
    (directory / '方向说明.md').write_text('# 三张比较方向\n\n本包未生图；首轮人工效果与采用/淘汰见项目案例复盘，不附带业务样片。\n\n' +
        '\n\n'.join(prepared['directions']) + '\n\n共同保留：同款同色、可见结构、已有标记、当前素材范围。\n' +
        '素材角色：只上传inputs中这一张核实原图，它提供商品事实；没有风格参考或成品样片。\n')
    licenses = directory / '来源许可'
    licenses.mkdir()
    for source in [ROOT / 'docs/第三方许可/MIT-Buluu.txt',
                   ROOT / 'docs/第三方许可/CC0来源说明.md',
                   ROOT / 'docs/第三方许可/yang0-LICENSE.txt']:
        shutil.copyfile(source, licenses / source.name)
    connected = bool(task.get('remote_task_id'))
    task_instruction = (
        f'4. 本包关联的新飞书任务ID：**{task["remote_task_id"]}**。实际使用Prompt时确认快照，回填时每图一条，关联这个新任务；不覆盖旧反馈。\n\n'
        if connected else
        f'4. 本地任务是**{task["local_task_id"]}**，尚无远端新任务ID。先创建新飞书任务并重新准备，不能回写旧任务或猜ID。\n\n'
    )
    state_text = '已定位新飞书任务 · 未生图' if connected else '本地待用包 · 未生图 · 尚无远端新任务ID'
    feedback_instruction = (
        f'本包的真实新任务ID：{html.escape(task["remote_task_id"])}。回填时关联这个新任务，不覆盖旧反馈。'
        if connected else f'先按本地任务 {html.escape(task["local_task_id"])} 保存；创建飞书新任务后重新准备，不回写旧任务。'
    )
    (directory / '使用说明.md').write_text(
        f'# {sku}生成准备包\n\n1. 上传`inputs/{asset["filename"]}`到GPT，作为第1张输入图。\n'
        '2. 复制`prompt.txt`全部文字，要求A/B/C各一张独立图；不能一次输出时逐张执行。\n'
        '3. 与原图对照颜色、结构、已有标记和未知部分，再判断三方向是否有用；原图更好也可以保留原图。\n' +
        task_instruction +
        (f'[准备入口]({start}) · [反馈入口]({feedback})\n\n' if base else '未配置远端入口；不假装已有连接。\n\n') +
        '本包未生图。改想法需重新准备新的包；旧快照不变。已有使用快照与新Prompt不同时，复制新任务再使用；不覆盖快照。\n')
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{sku}生成准备包</title><style>body{{font:17px/1.7 system-ui;margin:32px auto;max-width:850px;padding:0 20px;color:#202526}}img{{width:150px;float:right;margin:0 0 20px 20px}}pre{{white-space:pre-wrap;border:1px solid #ccc;padding:20px;font:15px/1.7 system-ui}}a{{color:#176745}}</style>
<h1>{sku} · {html.escape(prepared['method_name'])}</h1><p>{state_text}</p>
<img src="inputs/{asset['filename']}" alt="实际核实原图，不是生成样片"><ol><li>将<a download href="inputs/{asset['filename']}">这张原图</a>上传GPT。</li>
<li>复制下面的完整提示词，生成3张独立候选。</li><li>与原图对照商品与已有标记，再选图并写一句原因。</li>
<li>{feedback_instruction} {('<a href="' + html.escape(feedback) + '">反馈入口</a>') if feedback else ''}</li></ol>
<p><a href="prompt.txt" download>下载完整Prompt</a> · <a href="方向说明.md">方向说明</a> · <a href="回填任务定位.json">任务定位</a></p>
<pre>{html.escape(prepared['draft'])}</pre><footer>来源：buluslan / Buluu@新西楼、<a href="https://github.com/yang0/handraw-style">yang0</a>、JeremyGDM；署名、来源与许可随包保留。</footer></html>'''
    (directory / '打开使用.html').write_text(page)
    checksums = '\n'.join(f'{sha(p)}  {p.relative_to(directory)}' for p in sorted(directory.rglob('*')) if p.is_file())
    (directory / 'CHECKSUMS.sha256').write_text(checksums + '\n')
    archive = directory.with_suffix('.zip')
    with archive.open('xb') as stream, ZipFile(stream, 'w', ZIP_DEFLATED) as z:
        for file in sorted(directory.rglob('*')):
            if file.is_file():
                z.write(file, str(Path(directory.name) / file.relative_to(directory)))
    return {'sku': sku, 'local_task_id': task['local_task_id'], 'package': str(directory.relative_to(ROOT)) if directory.is_relative_to(ROOT) else str(directory),
            'zip': str(archive), 'zip_sha256': sha(archive), 'image_sha256': asset['sha256'],
            'draft_sha256': sha(directory / 'prompt.txt'), 'component_ids': prepared['component_ids'],
            'remote_task_id': task.get('remote_task_id'), 'state': state_text}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, help='新建/复制的本地任务JSON；不接受环境API密钥')
    parser.add_argument('--interactive', action='store_true', help='普通运营在本机选择做法与商品、补一句想法')
    parser.add_argument('--output', type=Path, default=ROOT / 'out/p0', help='新输出目录，已有包不覆盖')
    args = parser.parse_args()
    catalog, assets, tasks = load_sources()
    config = read(ROOT / 'config/p0-methods.json')
    if args.request and args.interactive:
        parser.error('--request与--interactive只能选一个')
    if args.interactive:
        print('本地准备新包；不生图、不改飞书或旧反馈。')
        print('1 商品看清楚　2 穿搭换环境（茄克）　3 版式有设计感（鞋）')
        method = {'1': 'clear-product', '2': 'wear-environment', '3': 'catalog-design'}.get(input('选择做法 [1/2/3]：').strip())
        sku = input('商品货号 [484330/488726]：').strip()
        channel = {'1': '拼多多', '2': '天猫超市'}.get(input('渠道 [1 拼多多 / 2 天猫超市]：').strip())
        idea = input('写一句想法（可留空）：').strip()
        if sku not in assets:
            raise ValueError('该商品没有获准素材。')
        stamp = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S-%f')
        local_id = f'P0-{sku}-{stamp}'
        request = {'local_task_id': local_id, 'task_name': f'UNIQLO {sku} · {local_id}',
                   'sku': sku, 'asset_record_id': assets[sku]['record_id'], 'channel': channel,
                   'method_id': method, 'free_idea': idea, 'target_count': 3,
                   'remote_task_id': None, 'source_task_record_id': None, 'snapshot': None,
                   'mapping_status': '独立本地新任务，未创建飞书记录'}
        requests = [request]
        args.output = args.output / '自备包' / local_id
    else:
        requests = [read(args.request)] if args.request else default_requests(assets, tasks)
    result = []
    for request in requests:
        directory = args.output if args.request or args.interactive else args.output / request['sku']
        result.append(build_package(request, config, catalog, assets, directory))
    if args.interactive:
        print('\n已准备完成。打开这个说明页即可拿到原图和完整Prompt：')
        print(args.output.resolve() / '打开使用.html')
        print('同名ZIP在文件夹旁。先按包内的新任务编号保存结果；飞书新任务尚未接通。')
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, FileNotFoundError, FileExistsError) as error:
        raise SystemExit('准备未完成：' + str(error))
