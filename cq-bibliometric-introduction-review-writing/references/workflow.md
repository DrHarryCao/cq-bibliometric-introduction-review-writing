# 分阶段工作流

## 检索和筛选的透明性

`search` 和 `ingest` 会维护 `07_logs/prisma_flow.*` 与 `screening_log.jsonl`。它们记录查询、去重、导入、排除原因和种子文献召回，但不得因生成了流程文件就声称已完全遵循 PRISMA 2020。

`search_plan.json` 可增加 `seed_papers` 数组（题名或 DOI）。若已知核心文献未被召回，在调整检索式或说明合理排除之前不得定稿语料。

## 目录与阶段门

| 目录 | 内容 | 继续条件 |
|---|---|---|
| `00_plan` | 题目、概念组、查询与纳排边界 | 用户批准检索计划 |
| `01_sources` | API 原始响应与缓存 | 查询完成且日志可追溯 |
| `02_corpus` | JSONL 权威语料及可读视图 | 用户确认合并和纳入范围 |
| `03_fulltext` | 原件、提取文本、锚点、参考文献 | 失败/OCR 文件已说明 |
| `04_analysis` | 表格、Markdown、参数和图形 | 检查样本与模型适用性 |
| `05_evidence` | 卡片、dossiers、claim ledger | 内容证据与反例已覆盖 |
| `06_review` | 提纲、分节稿、合并稿 | 用户批准提纲且审计通过 |
| `07_logs` | 冲突、验证、运行事件 | 始终保留 |

## 查询设计

将题目拆为对象、核心构念、机制/结果、方法、情境五组概念。每组保留中文、英文、缩写、历史术语和排除词。建立：

1. 核心查询：高精度定义研究边界。
2. 扩展查询：补同义词、相邻理论、替代测量。
3. 前沿查询：补最近三至五年的机制、方法和新情境。

查询不要伪装成系统综述注册。记录数据库、检索日期、查询原文、过滤器和返回数。300–800 是默认分析规模而非质量目标；若合格文献较少，应诚实缩小语料。

## 中文输入翻译门

检测到中文字符时，由当前 Codex/Claude 直接完成学术语义翻译，不调用额外翻译 API。检索计划必须满足：

- `title_zh` 保留原文，`title_en` 为不含中文的英文译题。
- `translation_status` 为 `completed`。
- 至少一个概念组同时含 `zh` 与 `en` 术语。
- 至少各有一个 `family=core`、`language=zh/en` 的中英文查询；两条查询分开保存，不把双语混成一条。
- 执行 `validate-plan` 成功后才让用户确认；`search` 会重复执行相同校验并在 API 请求前阻止不完整计划。

示例：

```json
{
  "title_zh": "数字化转型对企业创新的影响",
  "title_en": "The impact of digital transformation on firm innovation",
  "translation_status": "completed",
  "concepts": [{"name": "数字化转型", "zh": ["数字化转型"], "en": ["digital transformation"]}],
  "queries": [
    {"id": "Q01-ZH", "family": "core", "language": "zh", "query": "数字化转型 企业创新"},
    {"id": "Q01-EN", "family": "core", "language": "en", "query": "digital transformation firm innovation"}
  ]
}
```

## 交互节点

- 检索前：确认概念、年份、语种、类型和目标规模。
- 检索后：询问用户导出文件，并展示去重/冲突摘要。
- 全文前：询问路径及是否允许本地 OCR。
- 引文扩展后：只展示候选，等待用户选择。
- 写作前：确认语料边界和提纲。
