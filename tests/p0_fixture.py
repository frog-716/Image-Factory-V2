"""Synthetic neutral pixels and fake identifiers; no business image in tests."""
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw


def fixture_profile(directory):
    directory = Path(directory)
    assets = []
    tasks = []
    for sku, name, colour, code in [('484330', 'synthetic-shoe.png', '深米色', '32'),
                                    ('488726', 'synthetic-jacket.png', '黑色', '09')]:
        image = Image.new('RGB', (1200, 1600), '#ededed')
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((300, 400, 700, 1200), fill='#888888')
        drawing.text((30, 30), 'SYNTHETIC TEST ONLY - NOT A PRODUCT', fill='black')
        path = directory / name
        image.save(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        asset_id, product_id = 'fake-asset-' + sku, 'fake-product-' + sku
        assets.append({'sku': sku, 'file': str(path), 'canonical_file': str(path),
                       'filename': name, 'sha256': digest, 'allowed': True,
                       'record_id': asset_id, 'colour_code': code, 'colour_name': colour,
                       'source_page': 'synthetic fixture', 'source_image': 'synthetic fixture',
                       'material_record': {'record_id': asset_id, '允许用于生图': True,
                                           '关联商品': [{'id': product_id}],
                                           '素材说明': digest, '附件': [{'name': name}]},
                       'product_record': {'record_id': product_id, '货号': sku}})
        tasks.append({'record_id': 'fake-task-' + sku, '任务名称': '合成测试 ' + sku,
                      '渠道': ['拼多多']})
    result = directory / 'sources.json'
    result.write_text(json.dumps({'assets': assets, 'tasks': tasks,
                                 'base': {}, 'evidence': '合成测试数据，非真实飞书资源'}, ensure_ascii=False))
    return result
