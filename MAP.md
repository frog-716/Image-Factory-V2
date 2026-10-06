# 项目地图

先看[README](README.md)和[当前状态](docs/STATUS.md)。阶段A目标是飞书原生 Prompt Composer，当前停在安全连接，未部署、未启用。日常入口仅飞书；ChatGPT生图和反馈闭环等待后续验收。

| 位置 | 职责 |
|---|---|
| 飞书六表 | 商品与素材事实、26组件、任务、图片反馈、周度规划的业务正本 |
| 飞书原生工作流（待接通） | 触发检查→读取完整上下文→确定性校验→官方DeepSeek→只写草稿与待生成状态 |
| `config/schema.json` | 六表64字段；图片功能三选一；两个实验列已备份删除 |
| `config/prompt-components.csv` | 26个组件及来源；正式流程须自动匹配，不交给运营逐项选择 |
| `config/p0-methods.json` | 历史三个可读做法，保留用于验证 |
| `scripts/prepare_p0.py` | legacy / validation only：核实原图字节及历史本地包 |
| `scripts/prompt_rules.py` | legacy / validation only：历史确定性拼装和快照保护回归 |
| `scripts/connect_feishu.py` | legacy / validation only：历史手动连接、关联核验与对账；不替代原生Composer |
| `scripts/lark_cli.py` | 维护侧CLI薄调用层，写前留痕、未知结果停止；不接收DeepSeek Key |
| `tests/` | 33项独立离线回归，使用合成图片和ID；不等于新原生链路验收 |
| `docs/domain/`、`docs/adr/` | 领域模型与已保留的架构决定 |
| `docs/STATUS.md`、`docs/案例复盘.md`、`docs/经验与教训.md` | 当前状态、真实试错及产品纠偏 |
| `docs/运营使用速记.md`、`docs/使用流程.md` | 飞书填写和待验收的网页流程；不包含本地日常入口 |
| `docs/飞书AI小实验.md` | 已结束实验的质量与成本结论，保留历史、不继续使用两列 |
| `docs/长期积累/电商生图/` | 按需查阅的知识柜 |
| `docs/media/`、`docs/第三方许可/` | 两张既有脱敏截图与原始许可 |

关系：商品→获准素材；任务→商品/素材/组件；图片反馈→任务；周度规划→典型图片。阶段A仅写新任务的智能提示词草稿及任务状态，不能改商品事实、最终提示词快照或旧反馈。

安全连接未核实前，不保存Key、不调用AI、不启用流程。当前HTTP节点的普通文本请求头不等于Secret；不增加本地代理、Runtime、Runner或第七张表。

私有目录均被Git忽略：`private/`保留原图及批准清单，`out/`保留历史产物，`.local/`保存维护证据，`docs/internal/`保存内部回执。`.local/stage-a-20261006/`包含本轮六表、两个实验字段及两个启动器的可恢复备份；旧AI实验原始证据仍保留在`.local/ai-experiment-20261006/`。

历史交接包、阶段产物和旧Git历史在项目外可恢复归档，不作为现役上下文。历史本地包不再作为正式运营入口，也不删除或覆盖旧快照、旧反馈。
