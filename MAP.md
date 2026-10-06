# 项目地图

先看[README](README.md)和[当前状态](docs/STATUS.md)。阶段A/B/C完整MVP已按两款真实任务验收：飞书任务→原生AI Prompt→ChatGPT网页生图→飞书回填与用户评价。日常使用飞书和ChatGPT网页；草稿自动回写，冻结、回填、评价与任务状态由人操作。

| 位置 | 职责 |
|---|---|
| 飞书六表 | 商品与素材事实、26组件、任务、图片反馈、周度规划的业务正本 |
| 飞书原生工作流 | 条件触发→查找可用商品→查找匹配获准素材→原生AI生成文本→仅写草稿与待生成状态 |
| `config/schema.json` | 六表64字段；图片功能三选一；两个实验列已备份删除 |
| `config/prompt-components.csv` | 26个组件及来源保留；本轮工作流不读取，运营不用手选 |
| `config/p0-methods.json` | 历史三个可读做法，保留用于验证 |
| `scripts/prepare_p0.py` | legacy / validation only：核实原图字节及历史本地包 |
| `scripts/prompt_rules.py` | legacy / validation only：历史确定性拼装和快照保护回归 |
| `scripts/connect_feishu.py` | legacy / validation only：历史手动连接、关联核验与对账；不替代原生Composer |
| `scripts/lark_cli.py` | 维护侧CLI薄调用层，写前留痕、未知结果停止；不接收DeepSeek Key |
| `tests/` | 33项独立离线回归，使用合成图片和ID；不等于新原生链路验收 |
| `docs/domain/`、`docs/adr/` | 领域模型与已保留的架构决定 |
| `docs/STATUS.md`、`docs/案例复盘.md`、`docs/经验与教训.md` | 当前状态、真实试错及产品纠偏 |
| `docs/运营使用速记.md`、`docs/使用流程.md` | 已验收的任务、网页生图、冻结与人工反馈流程；不包含本地日常入口 |
| `docs/飞书AI小实验.md` | 已结束实验的质量与成本结论，保留历史、不继续使用两列 |
| `docs/长期积累/电商生图/` | 按需查阅的知识柜 |
| `docs/media/`、`docs/第三方许可/` | 两张既有脱敏截图、阶段A/B历史架构配图与原始许可 |

关系：商品→获准素材；任务→商品/素材/组件；图片反馈→任务；周度规划→典型图片。阶段A仅写新任务草稿与状态；阶段B冻结实际使用的完整Prompt；阶段C每图一条反馈，正确关联本轮任务并记录用户评价。旧快照、旧反馈和商品事实不覆盖。

本轮采用原生内置节点，不需要外部API Key；节点页面未显示模型名称或选择入口，不猜底层模型。AI Agent只保留为未来周度方案。没有本地代理、Runtime、Runner或第七张表。

私有目录均被Git忽略：`private/`保留原图及批准清单，`out/`保留历史产物，`.local/`保存维护证据，`docs/internal/`保存内部回执。`.local/stage-a-20261006/`包含本轮六表、两个实验字段及两个启动器的可恢复备份；旧AI实验原始证据仍保留在`.local/ai-experiment-20261006/`。

历史交接包、阶段产物和旧Git历史在项目外可恢复归档，不作为现役上下文。历史本地包不再作为正式运营入口，也不删除或覆盖旧快照、旧反馈。

原生链路证据与私有工作流定义在`.local/native-composer-20261006/`：六表备份、两条真实任务、逐轮AI结果、节点输入输出、实际模型/额度界面与回归结果。首轮及修订记录保留，不用最终成功覆盖试错证据。

阶段B六张真实独立候选、发送原文与冻结核验在`.local/stage-b-20261006/`；阶段C附件字节、关联任务与用户评价证据在`.local/stage-c-20261006/`。内部真实UX观察在`docs/internal/`，均不公开。
