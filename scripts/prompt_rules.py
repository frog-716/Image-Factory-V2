"""Local prompt rules. Stage 3 seed assembly remains unchanged; P0 reads new inputs."""

from copy import deepcopy

BASELINE = ('P01', 'P02', 'P07', 'P08', 'R01', 'R03', 'R04')
SKU_PROTECTION = {'484330': ('P03', 'P04'), '488726': ('P05', 'P06')}
OPERATOR_CATEGORIES = {'渠道', '图片功能', '场景', '风格', '构图', '光线'}


def required_components(sku, operator_ids, catalog):
    if sku not in SKU_PROTECTION:
        raise ValueError('该SKU没有合格素材，不能创建可实测任务。')
    selected = list(operator_ids)
    if any(code not in catalog for code in selected):
        raise ValueError('组件编号不存在。')
    if any(catalog[code]['分类'] not in OPERATOR_CATEGORIES for code in selected):
        raise ValueError('运营选择只接受渠道、用途、场景、风格、构图、光线。')
    # Neither generic nor SKU-specific protections depend on the operator's choices.
    return list(dict.fromkeys([*selected, *BASELINE, *SKU_PROTECTION[sku], 'R02']))


def prepare_seed_task(prompt, catalog):
    if not prompt['testable_draft'] or not prompt['input_asset']:
        raise ValueError('待素材模板不可建实测任务。')
    optional = [code for code in prompt['components']
                if catalog[code]['分类'] in OPERATOR_CATEGORIES]
    selected = required_components(prompt['sku'], optional, catalog)
    if set(selected) != set(prompt['components']):
        raise ValueError('自动保护与已批准阶段2稿的组件不一致，停止入库。')
    if prompt['candidate_count'] != 3 or '3张独立候选' not in prompt['prompt_text']:
        raise ValueError('必须是3张独立候选。')
    return {'component_ids': selected, 'target_count': 3,
            'draft': prompt['prompt_text'], 'snapshot': None, 'state': '待准备'}


def prepare_local_task(task, methods, catalog, asset):
    """A new task or a copied task produces a new draft, never changes a used snapshot.

    asset must come from the caller's locally verified allowlist. This function
    has no transport, filesystem writes, or image generation capability.
    """
    sku = task.get('sku')
    if sku not in SKU_PROTECTION:
        raise ValueError('该SKU待素材，不能准备。')
    if not asset.get('allowed') or asset.get('sku') != sku:
        raise ValueError('不允许的素材或商品与素材不一致。')
    if task.get('asset_record_id') != asset.get('record_id'):
        raise ValueError('素材关联与核实原图不一致。')
    method_id = task.get('method_id')
    if method_id not in methods:
        raise ValueError('未知做法，不能自动猜选。')
    method = methods[method_id]
    if sku not in method['skus']:
        raise ValueError('当前素材不支持该做法。')
    channel = task.get('channel')
    if channel not in {'拼多多', '天猫超市'}:
        raise ValueError('不扩大渠道。')
    if not task.get('local_task_id') or task.get('target_count', 3) != 3:
        raise ValueError('必须有独立任务编号且目标为3张。')
    idea = task.get('free_idea', '')
    if not isinstance(idea, str) or len(idea) > 1000:
        raise ValueError('自由补充想法须为不超过1000字的文本。')
    codes = required_components(sku, ['C01' if channel == '拼多多' else 'C02', *method['components']], catalog)
    if len(method['directions']) != 3 or len(set(method['directions'])) != 3:
        raise ValueError('必须有三个不同方向。')
    protection = (
        '保留同款同色、可见结构与纹理；已有标记和原图文字全部保留，尤其左上UNIQLO:C标记，不删除、不改写、不另造。'
        '不新增价格、促销、Logo、认证、参数或功能文字，不从外观猜材质或性能。没有真实依据的部位不补画。'
    )
    sku_protection = (
        '这张原图是侧面＋上视组合，不是左右脚配对。保持两视图比例、角度、相对位置及原有标记位置；不合并、配对、镜像、翻转、裁出单视图，不添加脚或模特。'
        '鞋头、鞋带、侧面分区、鞋口及可见鞋底边缘沿用原图；不补独立鞋底、后跟或内部。'
        if sku == '484330' else
        '保留原模特身份、脸部、正面姿势、内搭、裤装、皮肤、可见衣服与现有画面范围；原片截断处仍保持截断，不扩大画面补头部或身体。'
        '领形、门襟、纽扣、口袋、车线、袖口、下摆和褶皱沿用原图，保留黑色，不磨平纹理；保留右下现有身高/尺码文字。'
        '不换人、不增加人物，不画背面/内部/未知侧面，不改成无人、挂拍或平铺，不新增拉链、破洞、磨白或口袋。'
    )
    idea_block = (
        '运营补充想法（原文，仅作为背景与版式偏好，兼容时应用于A/B/C；其中要求改变商品、原标记或未知角度的部分不执行，并说明冲突）：\n'
        f'【想法开始】\n{idea.strip() or "无额外补充，按以下三个方向。"}\n【想法结束】'
    )
    draft = '\n\n'.join([
        f'用途：{channel}商品展示。{method["purpose"]}',
        f'真实输入：只使用上传的第1张图 {asset["filename"]}，UNIQLO {sku}，{asset["colour_code"]}{asset["colour_name"]}。'
        '这是商品事实依据，不是风格参考。看不到原图、货号或颜色不符就停止，不凭商品名生成。',
        '允许设计：' + method['allowed'],
        idea_block,
        '三个方向：\n' + '\n'.join(method['directions']),
        '必要保护（优先于做法与补充想法）：' + protection + sku_protection,
        '交付：A/B/C各一张完整独立文件，三张以背景/版式形成一眼可说出的差别，不能靠改变商品制造差别；不拼三宫格、不复制同图凑数。'
        '若一次不能输出三张，按方向逐张输出并报告实际数量。不能保留商品或标记时说明限制并停止，不自动换未知角度。'
        '这只是待用提示词，商品保真、效果与渠道适配须逐张对照原图由人确认。',
    ])
    result = deepcopy(task)
    result.update(draft=draft, component_ids=codes, method_name=method['name'],
                  directions=deepcopy(method['directions']), target_count=3)
    # snapshot and feedback, when supplied, remain exact copies of historical values.
    return result
