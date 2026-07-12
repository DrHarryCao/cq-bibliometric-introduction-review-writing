# CQ Bibliometric · Introduction · Review · Writing

> 可追溯的文献计量、系统综述与 SSCI 漏斗式引言写作技能  
> An auditable skill for bibliometric analysis, systematic reviews, and funnel-shaped SSCI introductions

**JWC💗XQ@Rednote drharry**

[中文](#中文说明) · [English](#english)

---

## 中文说明

### 项目简介

`cq-bibliometric-introduction-review-writing` 是一个面向 Codex/Claude 类智能体的学术研究技能。它可以从研究标题、初步想法、文献数据库导出文件或本地全文出发，构建分阶段、可恢复、可审计的研究工作流，辅助完成：

- 文献检索策略设计与中英文检索式生成；
- 多来源文献导入、字段规范化、去重与语料筛选；
- 文献计量分析、主题识别、趋势分析与知识网络分析；
- 全文提取、证据卡片、主张台账和语义支持核验；
- 系统性文献综述与 SSCI 漏斗式中文引言写作；
- 研究缺口、理论模型、变量关系与假设方向设计；
- 可审计 Markdown、离线 HTML、RIS 等交付物导出。

它强调“证据先于写作”：研究结论应能回溯到文献记录、全文位置或明确标注的摘要级证据，而不是由模型凭空生成。

### 核心特点

- **双模式检索**：支持 API 检索，也支持完全不配置 API 的 WoS 检索策略生成。
- **中英文协同**：为中文研究主题生成语义对齐的英文标题、概念词和检索式。
- **可恢复工作流**：任务状态、原始响应、哈希和清单均保留，可中断后继续。
- **可审计证据链**：将正文主张绑定到证据卡片、全文锚点和文献记录。
- **语料策略明确**：支持全量语料与聚焦语料，避免探索性检索污染核心研究范围。
- **写作前质量控制**：检查引文覆盖、反向证据、研究设计差异和语义支持关系。
- **合规获取全文**：仅处理用户提供、开放获取或机构合法授权的全文，不绕过付费墙。
- **多格式交付**：输出干净版与审计版 Markdown、单文件离线 HTML 和 RIS。

### 安装

将技能目录复制或克隆到 Codex 技能目录：

```bash
git clone <YOUR_REPOSITORY_URL>
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R cq-bibliometric-introduction-review-writing \
  "${CODEX_HOME:-$HOME/.codex}/skills/"
```

安装 Python 依赖：

```bash
python3 -m pip install -r \
  "${CODEX_HOME:-$HOME/.codex}/skills/cq-bibliometric-introduction-review-writing/scripts/requirements.txt"
```

然后重新启动 Codex，或重新加载技能列表。

### 快速开始

在 Codex 中直接说明研究主题，例如：

```text
使用 $cq-bibliometric-introduction-review-writing，围绕“社交商务环境中的信息过载与消费者决策”设计检索方案并开展可追溯综述。
```

首次运行时，技能会要求选择：

1. `api-search`：通过受支持的学术 API 获取记录；
2. `strategy-only`：不使用 API，只生成可复制到 WoS 等数据库的检索策略，并等待用户导入文献文件。

常用命令：

```bash
SKILL_DIR="${CODEX_HOME:-$HOME/.codex}/skills/cq-bibliometric-introduction-review-writing"

python "$SKILL_DIR/scripts/review_pipeline.py" doctor
python "$SKILL_DIR/scripts/review_pipeline.py" wizard \
  --task /path/to/review-task \
  --title "Your research idea"
python "$SKILL_DIR/scripts/review_pipeline.py" status \
  --task /path/to/review-task
```

建议通过 Codex 调用本技能，由智能体负责阅读协议、执行命令、完成证据综合并在关键决策点征求确认；命令行主要用于诊断、恢复和高级使用。

### 工作流概览

```text
研究问题
  → 双语检索计划与审核
  → API 检索或数据库导出文件导入
  → 去重、语料选择与元数据核验
  → 全文提取与参考文献扩展
  → 文献计量分析与主题档案
  → 证据卡片、主张台账与语义核验
  → 综述大纲审批
  → 分节写作、引文同步与质量审计
  → Markdown / HTML / RIS 交付
```

### 支持的输入

- 研究标题、关键词或研究构想；
- WoS、CNKI、EndNote、PubMed 等数据库导出记录；
- RIS、BibTeX、CSV、XLSX 等书目文件；
- 用户合法持有的 PDF、DOCX 或本地全文目录；
- 已有综述提纲、理论方向或指定研究缺口。

### 主要输出

- 双语检索计划与多版本 WoS 检索式；
- 检索、筛选、去重和元数据覆盖报告；
- 描述统计、主题趋势、共现/合作/引文网络等分析结果；
- 证据卡片、主张台账、研究质量评估和主题档案；
- 系统综述草稿、SSCI 引言和理论模型方案；
- 干净版/审计版 Markdown、单文件离线 HTML 与引用匹配的 RIS。

### 学术诚信与使用边界

- 不编造不可获得的文献、引文、页码、DOI 或研究结论。
- 不绕过付费墙、机构登录或出版商访问控制。
- 元数据、摘要和全文证据必须区分标注。
- 文献计量结构信号不能替代论文内容证据，也不能直接支持因果结论。
- 自动生成的综述和引言需要作者进行学术判断、事实核验和最终署名负责。
- 若用于系统综述，应根据目标领域另行确认正式报告规范与注册要求；生成流程记录不等于自动满足 PRISMA 等规范。

---

## English

### Overview

`cq-bibliometric-introduction-review-writing` is an academic research skill for Codex/Claude-style agents. Starting from a title, an early-stage idea, bibliographic exports, or locally available full texts, it builds a staged, resumable, and auditable workflow for:

- bilingual search planning and database-ready query generation;
- multi-source ingestion, normalization, deduplication, and corpus screening;
- bibliometric, topic, trend, and knowledge-network analysis;
- full-text extraction, evidence cards, claim ledgers, and semantic support checks;
- systematic review and funnel-shaped SSCI introduction drafting;
- research-gap direction, theory-model, variable, and hypothesis development;
- delivery of auditable Markdown, offline HTML, and RIS files.

The skill follows an evidence-before-prose principle: substantive statements should be traceable to bibliographic records, anchored full-text passages, or transparently labeled abstract-level evidence.

### Key features

- **Two acquisition modes**: use supported scholarly APIs or generate WoS strategies without requiring an API.
- **Bilingual alignment**: create semantically aligned English titles, concepts, synonyms, and queries for Chinese research ideas.
- **Resumable execution**: preserve task state, raw responses, hashes, manifests, and conflict logs.
- **Auditable evidence chain**: bind manuscript claims to evidence cards, source records, and full-text anchors.
- **Explicit corpus policies**: maintain either an all-record corpus or a screened focused derivative.
- **Pre-writing quality controls**: inspect citation coverage, counterevidence, study-design differences, and claim support.
- **Lawful full-text handling**: use user-provided, open-access, or institution-authorized content only.
- **Multiple deliverables**: export clean and audit Markdown, single-file offline HTML, and citation-matched RIS.

### Installation

Clone the repository and copy the skill folder into the Codex skills directory:

```bash
git clone <YOUR_REPOSITORY_URL>
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R cq-bibliometric-introduction-review-writing \
  "${CODEX_HOME:-$HOME/.codex}/skills/"
```

Install the Python dependencies:

```bash
python3 -m pip install -r \
  "${CODEX_HOME:-$HOME/.codex}/skills/cq-bibliometric-introduction-review-writing/scripts/requirements.txt"
```

Restart Codex or reload its skill list afterward.

### Quick start

Ask Codex to use the skill with a concrete topic:

```text
Use $cq-bibliometric-introduction-review-writing to design a search plan and build an auditable review of information overload and consumer decision-making in social commerce.
```

For a new project, choose one acquisition mode:

1. `api-search` retrieves records through supported scholarly APIs;
2. `strategy-only` makes no API requests, generates database-ready strategies, and waits for user-supplied exports.

Useful commands:

```bash
SKILL_DIR="${CODEX_HOME:-$HOME/.codex}/skills/cq-bibliometric-introduction-review-writing"

python "$SKILL_DIR/scripts/review_pipeline.py" doctor
python "$SKILL_DIR/scripts/review_pipeline.py" wizard \
  --task /path/to/review-task \
  --title "Your research idea"
python "$SKILL_DIR/scripts/review_pipeline.py" status \
  --task /path/to/review-task
```

The recommended interface is Codex: the agent reads the protocols, runs deterministic stages, synthesizes evidence, and pauses at genuine decision checkpoints. Direct CLI use is mainly intended for diagnostics, recovery, and advanced operation.

### Workflow at a glance

```text
Research question
  → bilingual search plan and approval
  → API search or bibliographic-export ingestion
  → deduplication, corpus selection, and metadata checks
  → full-text extraction and reference expansion
  → bibliometric analysis and topic dossiers
  → evidence cards, claim ledger, and semantic validation
  → outline approval
  → section drafting, citation synchronization, and audit
  → Markdown / HTML / RIS delivery
```

### Supported inputs

- Research titles, keywords, or early-stage ideas;
- exports from WoS, CNKI, EndNote, PubMed, and related databases;
- RIS, BibTeX, CSV, and XLSX bibliographic files;
- lawfully available PDF/DOCX files or local full-text directories;
- existing outlines, theory directions, or user-selected research gaps.

### Main outputs

- Bilingual search plans and multiple WoS query variants;
- search, screening, deduplication, and metadata-coverage reports;
- descriptive, topic-trend, co-occurrence, collaboration, and citation-network analyses;
- evidence cards, claim ledgers, quality appraisals, and topic dossiers;
- systematic-review drafts, SSCI introductions, and theory-model packages;
- clean/audit Markdown, single-file offline HTML, and citation-matched RIS.

### Research integrity and limitations

- Never fabricate unavailable papers, citations, page numbers, DOIs, or findings.
- Never bypass paywalls, institutional authentication, or publisher access controls.
- Keep metadata-only, abstract-only, and full-text evidence explicitly distinguished.
- Do not treat bibliometric structure as content evidence or causal proof.
- Authors remain responsible for scholarly judgment, factual verification, and the final submitted work.
- For formal systematic reviews, confirm the reporting and registration requirements applicable to the target field; workflow records alone do not establish PRISMA compliance.

---

## Repository layout / 仓库结构

```text
.
├── readme.md
└── cq-bibliometric-introduction-review-writing/
    ├── SKILL.md
    ├── agents/
    ├── assets/
    ├── references/
    ├── scripts/
    └── tests/
```

`readme.md` is repository-facing documentation and is intentionally kept outside the distributable skill folder.  
`readme.md` 是面向 GitHub 的展示文档，刻意与可分发的技能包分开存放。

## Copyright / 版权标识

**JWC💗XQ@Rednote drharry**

