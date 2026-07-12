# 与原 v6.2 程序的关系

原始文件 SHA-256：`2aeae1150a8fb3d69b9fc7fe6493e9450ba85a7fe0e3dd3711475324809ddf92`。技能不修改或导入该 GUI 单文件，而是把可复用思想重写为无 GUI、无外部 LLM 依赖的模块。

| v6.2 能力 | 技能实现 |
|---|---|
| RIS/ENW/NET 解析和标准字段 | 扩展为统一 JSONL，并新增 WoS、NBIB、BibTeX、CSV/XLSX |
| 描述统计、主题和聚类 | NMF 是唯一主题结构；KMeans 仅是受门控的异质性诊断；不使用 LDA/BERTopic/HDBSCAN |
| 热点、突现、主题趋势与演化 | Kleinberg 关键词/上下文短语/可用年度引用突现，以及主题趋势、生命周期与演化 |
| 共词、作者、引文、共引与耦合网络 | 增加社群、核心—边缘、Burt constraint/effective size、参与系数、brokerage 和结构洞机会 |
| 前沿信号和 gap 候选 | `frontier_signals/gap_candidates`，附内容证据警告 |
| 大型/紧凑 LLM 证据包 | 改为卡片 → dossier → claim ledger → 分节索引 |
| 内置 provider 写作 | 删除；由调用技能的 Codex/Claude 分节读取本地证据写作 |

由于统一模式、去重和模型选择不同，除导入数量和基础统计外，不承诺与 v6.2 的主题编号或网络边逐项完全相同。大型共引网络对结构洞计算使用最多 250 个高权重节点的可审计 backbone。每次运行保存参数以便解释差异。
