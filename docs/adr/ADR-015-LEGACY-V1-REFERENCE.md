# ADR-015 · V1 旧仓如何用于 V2

状态：Accepted

## 决策

旧仓 `frog-716/Image-Factory` 不作为 V2 的整体架构模板。
V2 新项目从零建立。

旧仓只作为：
1. 飞书接入参考
2. 稳定性与恢复经验参考
3. 失败案例与对抗性经验库

## 允许选择性复用

- `factory/lark.py`
  - 已配置 lark-cli 复用
  - typed shortcuts
  - 附件超时
  - 结构化错误
  - 写入超时后不盲重试
- `factory/state.py`
  - journal-before-write
  - unknown write 对账思想
- `factory/metrics.py`
  - 原始数字校验
  - 防重复导入
  - 不把相关性误写成因果
- `docs/05-对抗性审查.md`
  - 超时、重复写入、错误交付、输入漂移等经验
- `docs/research/2026-09-28-ecommerce-shoe-scene-workflow.md`
  - “背景生成后硬贴商品”为什么失败
- 相应的 Gateway / 附件 / 幂等测试思想

## 禁止作为 V2 蓝图继续沿用

- 8 张旧表
- 流程/流程步骤表
- Workflow Engine 主生产架构
- Runner / Runtime 生图队列
- Codex 作为生产必经节点
- 自动背景合成
- 本机 Human UI 审核 App
- Demo/Production 重状态机
- 旧 Build Kit
- 旧生产提示词 00~07

原因：这些东西主要解决“自动生产和恢复”，而 V2 真正问题是“运营如何选对素材、表达创意、用 GPT 产出好图、留下轻反馈”。
