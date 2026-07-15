# CQ Bibliometric · Introduction · Review · Writing

> 从研究主题、题录或合法全文出发，完成可追溯文献计量、系统综述与 SSCI 漏斗型绪论。  
> Build traceable bibliometric analyses, systematic reviews, and funnel-shaped SSCI introductions from a topic, bibliographic records, or lawfully available full texts.

**JWC💗XQ@Rednote drharry**

<!-- CQ_DOC_FACTS {"doc_version":"2026-07-15","skill_schema":12,"sections":["purpose","platform","installation","quickstart","acquisition","workflow","records","corpus","analysis","evidence","gaps","writing","delivery","commands","troubleshooting","integrity"],"topic_model":"NMF","kmeans_role":"diagnostic-only","focus":"task-specific","embedding":"disabled-by-default","pregenerated_docx":false,"variants":["evidence-aware","publication"],"brand":"JWC💗XQ@Rednote drharry"} -->

[中文说明](#中文说明) · [English Guide](#english-guide) · [官方链接](#官方链接与版本说明--official-links-and-version-notes)

---

## 中文说明

### 1. 技能定位

`cq-bibliometric-introduction-review-writing` 是一套兼容 Codex 与 Claude Code 的 Agent Skill。它把确定性的检索、题录解析、计量分析、证据索引和审计交给本地 Python，把检索词推理、逐篇语义抽取、理论比较、综合判断和学术写作交给当前宿主模型。

它遵循“证据先于写作”：事实性论断必须能够回溯到当前任务的文献、摘要或全文锚点；计量信号、理论库知识和模型常识不能冒充实证证据。技能不会绕过付费墙，也不会编造文献、DOI、页码或研究结论。

主要能力包括：

- 中英文检索计划、核心/扩展/前沿查询族和可复制的 WoS 检索式；
- OpenAlex API 自动检索，或完全不需要 API 的“仅生成策略＋本地导入”；
- RIS、WoS tagged text、CNKI/EndNote/PubMed 导出、BibTeX、CSV、XLSX、JSONL 等题录对齐；
- PDF、DOCX、TXT、Markdown 及目录递归处理，扫描 PDF 和旧 DOC 按环境优雅降级；
- 通用任务级聚焦、元数据覆盖审计、NMF、网络、突现、战略图、引文年龄和知识流；
- Tier A–D 证据分层、语义证据卡、Research Gap、理论支持和研究设计匹配；
- 系统综述与 SSCI 绪论的证据提示版、投稿正文版、HTML 和引用 RIS。

### 2. 正式支持环境

| 项目 | 支持范围 |
|---|---|
| 操作系统 | macOS 13+；Windows 10/11；Ubuntu 22.04/24.04、Debian 12、Fedora 当前稳定版 |
| 架构 | x64、ARM64、Intel/Apple Silicon |
| Python | 3.10–3.13 |
| Windows 终端 | PowerShell、CMD、Git Bash、WSL2 |
| 宿主 | 对应平台官方提供的 Codex 与 Claude Code CLI、桌面或 IDE 界面 |

Alpine/musl、Windows 8.1、WSL1 和 Python 3.9 以下仅尽力兼容。OCR、LibreOffice、GUI、安全凭据库、字体或浏览器不可用时，相关模块标记为 `skipped-unavailable`，不会使无关的核心流程崩溃。

### 3. 安装

解压发布包后进入其顶层目录。先安装核心依赖：

```text
python -m pip install -r cq-bibliometric-introduction-review-writing/scripts/requirements-core.txt
```

再使用跨平台安装器。以下命令会为 Codex 和 Claude 安装用户级技能，并按“符号链接 → Windows junction → 受管副本”自动降级：

```text
python cq-bibliometric-introduction-review-writing/scripts/install_skill.py install --host both --scope user --mode auto
```

检查、修复或卸载：

```text
python cq-bibliometric-introduction-review-writing/scripts/install_skill.py status --host both --scope user
python cq-bibliometric-introduction-review-writing/scripts/install_skill.py repair --host both --scope user --mode auto
python cq-bibliometric-introduction-review-writing/scripts/install_skill.py uninstall --host both --scope user
```

项目级安装可把 `--scope user` 改为 `--scope project`。Codex 入口为 `$cq-bibliometric-introduction-review-writing`；Claude Code 入口为 `/cq-bibliometric-introduction-review-writing`。安装后运行：

```text
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py doctor --json
```

可选依赖：需要 OCR 时安装 `requirements-ocr.txt`；只有数据满足效应量综合前提且需要相应工具时才安装 `requirements-meta.txt`。基础安装不包含 embedding、PyTorch 或本地模型，也不会自动下载模型。

### 4. 五分钟快速开始

推荐直接在 Codex 或 Claude 中输入：

```text
使用 $cq-bibliometric-introduction-review-writing。
我的研究主题是“……”。请建立独立任务目录，先生成并展示检索计划；不要在我确认前搜索。
```

Claude Code 将 `$技能名` 改为 `/cq-bibliometric-introduction-review-writing` 即可。首次任务会要求选择：

1. `API自动检索`：确认检索计划后由 OpenAlex 获取记录；
2. `仅生成检索策略`：不检查密钥、不联网，生成中英文关键词、核心/扩展/前沿查询及 WoS 检索式，然后导入用户已有题录和全文。

只有真正需要用户决定时才暂停。典型可复制回复包括：

- `批准检索计划`
- `全部语料` 或 `聚焦语料`
- `确认聚焦语料`
- 综述缺口方向或 `跳过`
- `结合本地理论库与LLM推荐`、`仅使用本地理论库`、`仅由LLM推荐理论` 或 `跳过理论支持`
- `确认提纲`
- `确认综述` 或具体修改意见
- 绪论缺口/研究问题、`跳过` 或 `不写绪论`

分析、证据扩展、分节写作、引用补足、参考文献同步、验证和 HTML 导出在已获批准的阶段内自动连续执行，不会因“下一批将继续”而无故停止。

### 5. 获取模式与 API 凭据

#### API 自动检索

OpenAlex 检索需要 API key。不要把密钥发到聊天、命令参数、项目文件或日志。运行：

```text
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py credentials guide --open-browser
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py credentials setup --input auto
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py credentials status
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py credentials test
```

日后替换或删除：

```text
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py credentials update --name OPENALEX_API_KEY --input auto
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py credentials delete --name OPENALEX_API_KEY
```

macOS 优先使用 Keychain；Windows 使用 Credential Manager/keyring；Linux 使用 Secret Service/keyring。没有可用安全后端时可用不回显终端输入完成当前命令，但不会把完整密钥写入项目。环境变量若覆盖安全存储，`status` 会提示来源而不显示完整值。

Crossref 联系邮箱和 Unpaywall 邮箱用于礼貌请求与 OA 查询，不是 API key；Semantic Scholar key 是可选增强。OpenAlex 额度和价格可能调整，执行大规模或付费全文下载前应查看官方 usage 页面。技能默认只下载明确合法的 OA 文件；OpenAlex 付费内容必须先展示数量和预计成本并再次确认。

#### 无 API 策略模式

该模式仍会把中文题目翻译成学术英文，检查中英文概念对齐，并输出：

- `search_plan.json/md`；
- 核心、扩展、前沿三个 WoS `TS=` 查询版本；
- 中文数据库关键词组合；
- 纳入/排除边界和种子文献召回建议。

它不会弹出凭据配置，也不会发送网络请求。随后可直接递归导入本地题录和全文。Crossref 元数据补全必须另行确认；拒绝后保持离线。

### 6. 标准工作流与检查点

```text
研究题目或思路
  → 中英文检索计划与WoS式
  → 用户批准检索计划
  → API检索，或本地题录/全文导入
  → 去重、元数据覆盖与冲突审计
  → 用户选择全部语料或聚焦语料
  → 全文提取与一跳参考文献候选
  → NMF及条件式高级计量分析
  → 证据分层、语义抽取与质量评价
  → Research Gap、理论支持与研究设计匹配
  → 研究现状地图与提纲批准
  → 综述缺口简报、分节写作与逐句审计
  → HTML综述草稿供用户审阅
  → 用户确认综述
  → 独立询问绪论缺口或研究问题
  → SSCI漏斗型绪论
  → 证据提示版与投稿正文版
  → 文内—文末—RIS同步验证
  → 离线HTML与RIS交付
```

任务默认存放在技能目录之外的 `review-tasks/任务名/`。`manifest.json` 保存参数、版本、随机种子、输入哈希、来源时间、阶段状态和推荐下一步。恢复任务时先运行：

```text
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py status --task "任务目录"
```

`status` 会显示 `requires_user_input`、检查点、可接受回复、下一条命令和能否自动继续。历史任务迁移只补充状态字段，不重写原始语料和草稿。

### 7. 题录、全文与元数据

支持的题录包括 RIS、ENW、BibTeX、NBIB、WoS tagged text、CSV、XLSX、JSONL 和现有 NET 格式；未知表格先产生列映射建议。支持用户合法持有的 PDF、DOCX、TXT、Markdown，目录可递归读取；旧 DOC 在检测到 LibreOffice 时转换。

统一记录保留 DOI、OpenAlex/UT/PMID 等标识、题名、作者、机构、年份、期刊、摘要、关键词、来源主题、各数据库被引数、年度被引历史、参考文献、OA 状态和完整来源追踪。不同来源的被引数分别保存，绝不相加。

去重优先使用稳定标识，但相同 DOI 只有在题名、年份和作者相容时才合并；期刊整期、专著或章节 DOI 与文章题名冲突时保留记录并标记 `doi-scope-conflict`。低置信匹配进入待确认队列，不静默删除。

PDF 按页保留锚点，DOCX 按段落、标题和表格保留锚点。扫描件、OCR、参考文献解析失败都会进入质量报告。参考文献扩展默认一跳、候选最多 200 篇，必须经用户确认才并入主语料。

`metadata-coverage.csv/md` 会说明标题、作者、年份、摘要、关键词、DOI、被引数、年度被引历史和参考文献的覆盖率。源数据没有的字段保持缺失，不推造年份或引用变化；相应高级分析会降级而不是伪造结果。

### 8. 全量与通用聚焦语料

- `全部语料`：去重后的全部记录进入计量分析，零排除；但并非每篇都能支持正文论断。
- `聚焦语料`：保留原始全量任务，另建透明派生任务。

新任务不存在直播电商、LARP 或任何领域专用硬编码。宿主依据当前问题生成 `focus_plan.json/md`，其中包含中英文核心概念、必要组合、相邻机制、明确排除项和低置信规则。脚本只执行已确认规则并把记录分为：

- `core`：符合核心问题；
- `theory-supplement`：对象不完全一致，但具有机制或理论迁移价值；
- `needs-review`：信息不足或规则冲突；
- `excluded`：命中明确排除条件或经用户确认排除。

派生任务继承获取模式和已确认状态，但不复制密钥、临时错误或过期正文哈希。

### 9. 科学分析框架

#### NMF与KMeans

NMF 是唯一主题体系，用于主题命名、dossier、引用配额和综述组织。主题数通过重构误差、c-NPMI、一致性、多样性、排他性、最小主题规模、分层重抽样和多随机种子敏感性综合选择。

KMeans 只用于识别同一 NMF 主题内部的方法、情境或结果异质性，不生成第二套主题，也不决定综述章节。只有稳定且提供增量结构时才形成辅助写作证据。技能不使用 LDA、BERTopic 或 HDBSCAN。

稳定 NMF 可支持经过限定的主题结构描述；已收敛但稳定性不足的 NMF 可以在明确警告下作为探索性正文骨架，并由宿主根据内容重新命名，但不得声称其代表稳定的领域知识结构。未收敛、严重失衡、文本覆盖不足或结果为空时改用研究问题和语义证据组织正文。

#### 条件式高级分析

- 战略图：内部密度、外部联系中心度和 bootstrap 象限稳定性；左下象限不能仅凭位置称为“新兴”。
- SNA与结构洞：共词、合作、本地引文、共被引、耦合网络的中心性、社群、Burt constraint、effective size、参与系数和桥接机会。
- 突现与演化：关键词、2–4元上下文短语、主题占比和年度引用序列；年度数据不足时只报告增长信号。
- Citation age：引用年龄、中位数、同步半衰期和知识基础新近度；年份覆盖不足时不分类“持续经典”或“短期浪花”。
- Knowledge flow：NMF软归属与有向本地引文边结合；少于门槛时只输出覆盖报告。
- 条件式元分析：只有效应量、方差、结局定义和独立样本可比时才运行随机效应综合，否则回退结构化叙事综合。

中心性、突现、战略象限、高被引、结构洞和知识流只能帮助组织问题，不能直接证明理论重要性或因果关系。

### 10. 证据层级、语义分析与Token控制

文献先满足论断对象、机制、结果、方向、情境和研究设计适配，再按来源分层：

| 层级 | 默认用途 |
|---|---|
| Tier A | 同行评审期刊实证论文；系统综述/元分析；理论史所需权威专著；主要会议型学科的正式同行评审全文会议论文 |
| Tier B | 学位论文、一般正式会议全文、有完整方法的机构报告和补充性学术章节 |
| Tier C | 预印本、工作论文、早期研究、未明确同行评审的会议材料 |
| Tier D | 撤稿、错误匹配、编辑性整期记录、无法确认来源或纯元数据记录，不支持正式正向论断 |

全文/摘要证据等级与出版层级分别记录：完整学位论文可能比期刊摘要更能支持方法细节，但 Tier B/C 不能单独支撑强概括性结论。低层证据只在高层不足、提供独特情境、新兴现象或反例时有理由回退。

默认无 embedding 的宿主语义流程分两遍：逐篇抽取研究问题、理论、变量、关系、设计、样本、情境、方法、主要/不显著/反向结果、局限和锚点；再只复核矛盾、术语不一致、低置信关系和高影响论断。抽取按文件哈希缓存。

计量分析处理全部选定语料，但宿主只读取分层代表文献、反例、全文和高不确定性记录；按章节加载局部 dossier 和 claim ledger。默认 `balanced` 预算不降低最低引用、主题覆盖、反例和全文优先规则。

### 11. Research Gap、理论与研究设计

Gap 分为：

- A级解释性缺口：理论假设失效、竞争解释、机制缺失、边界失效、构念失配或真正可比的结果矛盾；
- B级证据与推断缺口：测量、因果方向、偏倚、精度、样本独立性、外部效度或意向—行为断裂；
- C级分布性研究机会：特定国家、平台、样本、变量组合或方法研究较少。

“研究较少”“换一个国家”“首次使用某方法”只能先成为 C 级机会。只有说明其如何损害理论边界、可信推断或重要实践决策，才可能升级。每条正式缺口按“已有知识 → 当前解释 → 失效位置 → 知识后果 → 新解释需求 → 可检验问题 → 识别性设计 → 贡献”审计。

方法不写死为 PLS-SEM、ANN 或 fsQCA。技能先判断研究目标属于描述、解释、因果、预测、配置、过程、测量还是证据综合，再选择设计、数据结构、主要方法、辅助方法和稳健性检查。用户指定的方法只是待审查偏好；方法复杂或流行不构成贡献。

理论库是可选增强，可脱离研究任务独立管理：

```text
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py theory-library init
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py theory-library ingest "理论资料目录"
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py theory-library verify --phase prepare
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py theory-library status
```

任务进入缺口解释、竞争机制或模型构建时，用户可选择本地库、LLM推荐、二者结合或跳过。理论库为空、损坏、无匹配或候选无法核验时，技能自动采用“机制—边界—竞争解释”的理论中性叙事并继续写作。理论模块永不阻断综述、绪论、RIS 或 HTML。

### 12. 写作顺序与质量规则

固定顺序为：

1. 询问综述希望突出的缺口方向，允许 `跳过`；
2. 生成系统综述、同步参考文献、完成逐句/原子论断审计并提供 HTML 草稿；
3. 等待用户 `确认综述` 或提出修改；
4. 综述确认后，独立询问绪论希望突出的缺口或研究问题；
5. 用户可给出一个或多个方向、回复 `跳过`，或选择 `不写绪论`；
6. 撰写 8–12 个连续自然段、约 3,000–5,000 汉字、正文无小标题和列表的 SSCI 漏斗型绪论。

绪论遵循“问题为什么重要 → 已经知道什么 → 哪项解释或推断失败 → 本研究如何修复 → 理论与实践贡献”。第一段的现实社会背景优先使用官方统计、监管机构或权威调查，并登记来源、发布日期和检索日期。

解释型综述采用“理论定位 → 构念比较 → 机制整合 → 分歧与边界 → 综合判断”。每节采用“问题 → 共识 → 分歧/反例 → 解释 → 边界 → 过渡”，不能逐篇摘要，也不能只解释 NMF 词项。

一个句子包含多个对象、机制或结果时拆成原子论断，每组文献紧邻其真正支持的内容。包含“研究表明”“既有文献”“一些研究”“语料显示”等证据触发语句时必须有可追溯引用。综合性论断通常至少需要三项独立研究，并考虑研究质量和反例。

### 13. 证据提示版、投稿版与交付

综述和绪论各生成：

- 证据提示版：保留“摘要级、邻近证据、证据边界”等审慎说明，便于核验；
- 投稿正文版：不出现“聚焦语料、摘要证据、当前任务、record ID”等内部流程语言。

投稿版不是机械删词。充分支持的论断保留；部分支持的核心关系改写为“本研究提出/有待检验”；不受支持且非必要的论断删除。投稿版不得提高证据确定性。

最终交付包括审计/清洁 Markdown、单文件离线 HTML、正文实际引用文献对应的 RIS 和任务索引 HTML。不会预生成 DOCX。HTML 中：

- “导出 Word”在浏览器端即时生成 DOCX；
- “导出 PDF”调用浏览器打印界面并使用 A4 样式；
- 不依赖在线 CDN；
- 导出前清除内部 ID、审计标记、空括号、连续分号和异常标点。

最终验证要求可见文内引文、审计绑定、文末 APA 7 参考文献和 RIS 的记录集合一致；正文或审计哈希变化后必须重新验证。正式成果不能通过绕过验证导出。

### 14. 常用高级命令

以下 `<PIPELINE>` 指发布包中 `cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py`：

```text
python <PIPELINE> doctor --json
python <PIPELINE> wizard --task TASK --title "研究题目" --mode api-search|strategy-only
python <PIPELINE> validate-plan --task TASK
python <PIPELINE> search-strategy --task TASK --mode api-search|strategy-only
python <PIPELINE> search --task TASK --confirm
python <PIPELINE> ingest --task TASK FILE_OR_FOLDER...
python <PIPELINE> extract --task TASK FILE_OR_FOLDER...
python <PIPELINE> corpus-policy --task TASK --mode all|focused
python <PIPELINE> focus-plan --task TASK --phase prepare|validate
python <PIPELINE> focus --task TASK --output-task FOCUSED --spec focus_plan.json
python <PIPELINE> analyze --task TASK --language auto --nmf-structure auto
python <PIPELINE> build-evidence --task TASK
python <PIPELINE> build-semantic --task TASK --phase prepare|compile|reconcile|validate
python <PIPELINE> synthesize-effects --task TASK --phase prepare|compile|validate
python <PIPELINE> build-gaps --task TASK --phase prepare|compile|validate
python <PIPELINE> recommend-design --task TASK --phase prepare|compile|validate
python <PIPELINE> theory-support --task TASK --mode combined|local-only|llm-only|skip
python <PIPELINE> audit-writing --task TASK --document review|introduction
python <PIPELINE> sync-references --task TASK --document review|introduction
python <PIPELINE> build-publication --task TASK --document review|introduction --phase prepare|compile|validate
python <PIPELINE> document-approval --task TASK --document review --status approved|revision-requested
python <PIPELINE> validate --task TASK
python <PIPELINE> export-deliverables --task TASK --document review|introduction --variant evidence-aware|publication|both
python <PIPELINE> status --task TASK
```

建议普通用户通过宿主对话使用技能；命令行主要用于诊断、恢复和高级控制。

### 15. 常见问题

**缺少 OpenAlex key**：选择无 API 模式，或运行 `credentials setup`；不要把 key 粘贴到聊天。  
**检索结果太多或太杂**：建立当前任务专用 `focus_plan`，不要直接删原始语料。  
**聚焦后文献太少**：扩充 `theory-supplement` 和写作证据候选，但明确直接与邻近证据边界。  
**没有摘要或全文**：仍可完成题录级计量分析，但不能把元数据当作内容结论。  
**NMF不稳定**：可在满足收敛和覆盖条件时作为探索性组织骨架，不能写成稳定领域结构。  
**知识流或半衰期未运行**：检查本地引文边、参考文献年份和年度引用历史覆盖，数据不足时正确结果就是降级。  
**理论库不可用**：技能自动切换为理论中性机制叙事，不会停止写作。  
**恢复任务**：运行 `status --task TASK`，按 `user_prompt` 或 `next_command` 继续。  
**最终HTML被阻止**：先解决过期审计、引用集合不一致、未知文献、因果夸大或用户确认缺失。

### 16. 学术诚信与边界

- 只处理用户合法持有、开放获取或机构合法授权的全文。
- 不绕过登录、机构授权、验证码或付费墙。
- 不伪造题录、引文、DOI、页码、原文锚点、研究结果或现实统计。
- 元数据、摘要和全文证据必须区分；投稿版可删除流程提示，但不能改变证据强度。
- 计量结构、理论库和LLM知识不能替代当前任务的内容证据。
- 自动生成文本需要作者进行事实核验、学术判断和最终署名负责。
- PRISMA风格流程和日志有助于复现，但不自动等同于满足特定学科的注册或报告规范。

---

## English Guide

### 1. Purpose

`cq-bibliometric-introduction-review-writing` is an Agent Skill shared by Codex and Claude Code. Local Python handles deterministic retrieval, normalization, bibliometrics, indexing, and audits; the active host model handles query reasoning, semantic extraction, theory comparison, synthesis, and scholarly prose.

The workflow is evidence-first. Factual claims must trace to records, abstracts, or anchored full text in the current task. Bibliometric signals, theory-library knowledge, and model background knowledge are not empirical evidence. The skill never bypasses paywalls or fabricates papers, DOIs, pages, or findings.

It supports bilingual search plans and WoS queries; OpenAlex or API-free acquisition; multi-format bibliographic and full-text ingestion; task-specific focusing; NMF, gated advanced bibliometrics, evidence tiers, semantic synthesis, gap/design audits, optional theory support, systematic reviews, SSCI introductions, publication variants, offline HTML, and citation-matched RIS.

### 2. Supported environment

| Item | Supported range |
|---|---|
| Operating systems | macOS 13+; Windows 10/11; Ubuntu 22.04/24.04, Debian 12, current Fedora |
| Architectures | x64, ARM64, Intel/Apple Silicon |
| Python | 3.10–3.13 |
| Windows shells | PowerShell, CMD, Git Bash, WSL2 |
| Hosts | Officially available Codex and Claude Code CLI, desktop, or IDE surfaces on each platform |

Alpine/musl, Windows 8.1, WSL1, and Python below 3.10 are best effort only. Missing OCR, LibreOffice, GUI, credential stores, fonts, or browser components degrade the affected module to `skipped-unavailable` without crashing unrelated core stages.

### 3. Installation

From the extracted release root, install core dependencies:

```text
python -m pip install -r cq-bibliometric-introduction-review-writing/scripts/requirements-core.txt
```

Install the skill for both hosts at user scope:

```text
python cq-bibliometric-introduction-review-writing/scripts/install_skill.py install --host both --scope user --mode auto
```

Inspect, repair, or uninstall:

```text
python cq-bibliometric-introduction-review-writing/scripts/install_skill.py status --host both --scope user
python cq-bibliometric-introduction-review-writing/scripts/install_skill.py repair --host both --scope user --mode auto
python cq-bibliometric-introduction-review-writing/scripts/install_skill.py uninstall --host both --scope user
```

Use `--scope project` for project installation. Invoke `$cq-bibliometric-introduction-review-writing` in Codex or `/cq-bibliometric-introduction-review-writing` in Claude Code. Then run:

```text
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py doctor --json
```

Install `requirements-ocr.txt` only for OCR and `requirements-meta.txt` only when quantitative synthesis requires it. The base installation contains no embeddings, PyTorch, or model weights and never downloads a model automatically.

### 4. Five-minute start

Prompt the host with:

```text
Use $cq-bibliometric-introduction-review-writing.
My topic is “...”. Create a separate task directory and show the search plan first. Do not search before I approve it.
```

Use the slash-form skill name in Claude Code. Choose either API search or strategy-only mode. The latter performs no credential check or network request and moves directly to local export/full-text ingestion.

The workflow pauses only for genuine decisions. Typical replies are: approve the search plan; choose all or focused corpus; confirm the focus plan; provide or skip review-gap preferences; select combined/local/LLM/skip theory support; approve the outline; confirm or revise the review; then independently provide, skip, or decline an introduction focus.

Once a checkpoint is approved, analysis, evidence expansion, section drafting, citation completion, reference synchronization, validation, and HTML export continue automatically until the next real decision.

### 5. Acquisition and credentials

OpenAlex API search requires a key. Never place it in chat, command arguments, project files, or logs:

```text
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py credentials guide --open-browser
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py credentials setup --input auto
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py credentials status
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py credentials test
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py credentials update --name OPENALEX_API_KEY --input auto
python cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py credentials delete --name OPENALEX_API_KEY
```

The workflow prefers Keychain on macOS, Credential Manager/keyring on Windows, and Secret Service/keyring on Linux. If persistent storage is unavailable, a non-echoing terminal prompt can be used for the current command without writing the full secret to the project. Environment-variable overrides are reported by source, never by full value.

Crossref and Unpaywall emails are polite identification/OA lookup fields, not API keys. Semantic Scholar is optional. OpenAlex quotas and prices may change; inspect the official usage page before large retrieval or paid content download. The default is direct lawful OA only, and paid OpenAlex content requires a separate count-and-cost confirmation.

Strategy-only mode still translates Chinese topics into academic English, checks bilingual concept equivalence, and writes `search_plan.json/md`, three WoS query variants, Chinese database term combinations, scope rules, and seed-recall advice. It never opens the credential dialog or sends a request. Crossref enrichment remains opt-in.

### 6. Workflow and checkpoints

```text
Topic or idea
  → bilingual search plan and WoS strategies
  → search-plan approval
  → API retrieval or local records/full text
  → deduplication, metadata coverage, conflict audit
  → all-corpus or focused-corpus decision
  → full-text extraction and one-hop reference candidates
  → NMF and gated advanced bibliometrics
  → evidence tiers, semantic extraction, quality appraisal
  → gap audit, optional theory support, design matching
  → research map and outline approval
  → review brief, section writing, sentence/atomic audit
  → review HTML preview and user approval
  → independent introduction focus checkpoint
  → SSCI funnel-shaped introduction
  → evidence-aware and publication variants
  → in-text/reference/RIS synchronization
  → offline HTML and RIS delivery
```

Tasks live outside the skill, normally under `review-tasks/task-name/`. The manifest preserves parameters, versions, random seeds, input hashes, source dates, stage states, and recommended next action. Resume with `status --task TASK`; migrations add state without rewriting the corpus or drafts.

### 7. Records, full text, and metadata

Supported records include RIS, ENW, BibTeX, NBIB, WoS tagged text, CSV, XLSX, JSONL, and legacy NET. Unknown tables first receive a mapping proposal. Lawfully held PDF, DOCX, TXT, Markdown, and recursive directories are supported; legacy DOC uses LibreOffice only when available.

The unified record preserves stable identifiers, titles, authors, institutions, dates, venues, abstracts, terms, source topics, source-specific citation counts, yearly citation history, references, OA status, and provenance. Citation counts from different providers are never added together.

Shared DOIs merge only when title, date, and authorship are compatible. Issue-, book-, or chapter-level DOI collisions remain separate as `doi-scope-conflict`. Low-confidence matches enter a review queue rather than being silently deleted.

PDF pages and DOCX paragraphs retain anchors. OCR and reference-parsing failures appear in a quality report. Reference expansion is one hop and at most 200 candidates by default; candidates join the corpus only after approval. Missing source fields remain missing, and dependent analyses degrade rather than inventing dates or histories.

### 8. All versus task-specific focused corpus

All-corpus mode sends every deduplicated record to bibliometric analysis with zero exclusions, but does not treat every record as usable prose evidence. Focused mode preserves the full task and creates an auditable derivative.

New tasks contain no domain-specific livestream-commerce, LARP, or other vocabulary. The host creates a current-task `focus_plan.json/md` with bilingual core concepts, required combinations, adjacent mechanisms, explicit exclusions, and low-confidence rules. Deterministic classification is `core`, `theory-supplement`, `needs-review`, or `excluded`. Derived tasks inherit stable acquisition and approval state, never credentials, transient errors, or stale writing hashes.

### 9. Scientific analysis

NMF is the only topic system. Candidate topic counts are judged through reconstruction, c-NPMI, coherence, diversity, exclusivity, minimum size, stratified resampling, and random-seed/preprocessing sensitivity. KMeans is only a gated heterogeneity diagnostic and never creates a second topic taxonomy. LDA, BERTopic, and HDBSCAN are not used.

A stable NMF can support qualified structural descriptions. A converged but unstable NMF may serve as an explicitly exploratory writing scaffold after host semantic renaming, but cannot be presented as a stable field structure. Failed, severely imbalanced, or low-coverage models are replaced by research-question and semantic-evidence organization.

Strategic maps, network/structural-hole analysis, bursts, topic evolution, citation age, knowledge flow, and conditional meta-analysis run only when their coverage thresholds are met. Sparse yearly histories, reference years, local directed citations, independent samples, or comparable effects cause a transparent downgrade. Centrality, bursts, quadrants, citation counts, and knowledge flow organize inquiry; they do not prove theoretical importance or causality.

### 10. Evidence, semantics, and token control

Claim fit—object, mechanism, outcome, direction, context, and design—comes before source tier. Tier A covers primary peer-reviewed journal evidence, reviews/meta-analyses for consensus, authoritative theory history, and full peer-reviewed proceedings in conference-primary fields. Tier B covers theses, ordinary full proceedings, and method-complete reports. Tier C covers preprints and early/unconfirmed materials. Tier D covers retractions, bad matches, editorial issue records, and metadata-only/unknown sources that cannot support positive formal claims.

Publication tier and full-text/abstract level are separate. Lower tiers are used only for documented shortage, unique contexts, emerging phenomena, or counterevidence, and cannot alone support strong generalizations.

The default no-embedding semantic workflow first extracts questions, theories, variables, relations, designs, samples, contexts, methods, findings, null/reverse results, limitations, and anchors; a second pass reconciles only contradictions and high-impact uncertainty. Hash caching and section-local dossiers reduce token use without lowering citation, counterevidence, or full-text priorities.

### 11. Gaps, theory, and design

Level A gaps concern explanatory failure; Level B gaps concern measurement, identification, bias, precision, independence, or external validity; Level C describes distributional opportunities. “Few studies,” a new country, or a previously unused method begins at Level C and upgrades only when it demonstrably damages theoretical boundaries, credible inference, or consequential decisions.

Each formal gap follows: known evidence → current explanation → failure point → knowledge consequence → required explanation/evidence → testable question → identifying design → contribution.

Methods are not hard-coded to PLS-SEM, ANN, or fsQCA. The skill distinguishes descriptive, explanatory, causal, predictive, configurational, process, measurement, and evidence-synthesis goals; chooses design before estimator; checks data and identification assumptions; and reports alternatives. User-named methods are preferences that still require fit review.

The external theory library can be maintained without a research task. During gap, mechanism, or model work, users may combine local and LLM candidates, use either source alone, or skip theory support. Empty, corrupt, unmatched, or unverified theory support automatically falls back to mechanism–boundary–competing-explanation prose. Theory support never blocks review, introduction, RIS, or HTML.

### 12. Writing order and quality

The workflow first collects review-gap preferences, writes and audits the review, and presents its HTML preview. Only after the user confirms the review does it independently ask which gap or question the introduction should emphasize. The user may provide one or more directions, skip, or decline the introduction.

The Chinese SSCI introduction uses 8–12 continuous body paragraphs and roughly 3,000–5,000 Chinese characters without body headings or lists. Its logic is importance → knowledge baseline → explanatory/inferential failure → study repair → theoretical/practical contribution. The opening social context must be traceable to official or authoritative sources.

Explanatory reviews organize theory position → construct comparison → mechanism integration → disagreement/boundary → synthesis. Each section follows question → consensus → disagreement/counterevidence → explanation → boundary → transition. It must synthesize rather than list papers or NMF terms.

Compound sentences are decomposed into atomic claims, and each citation group sits next to the exact object, mechanism, or outcome it supports. Evidence-trigger language requires traceable citations. Broad claims normally require at least three independent studies, with quality and counterevidence considered.

### 13. Variants and delivery

Each review and introduction has an evidence-aware version and a publication version. The latter removes reader-facing workflow language but does not mechanically erase caveats: supported claims remain, essential partial claims become explicit propositions to test, and unsupported nonessential claims are removed. Certainty can never increase during conversion.

Final artifacts are audit/clean Markdown, self-contained offline HTML, citation-matched RIS, and a task index. No DOCX is pre-generated. The HTML creates Word client-side when clicked and opens A4 browser printing for PDF. It uses no CDN and removes internal IDs and punctuation residue before export.

Visible citations, audit bindings, APA references, and RIS record sets must match. Changed prose or stale audits require revalidation, and final export cannot bypass failed validation.

### 14. Advanced commands

Use the same command set shown in the Chinese section under “常用高级命令”. Run `status` before resuming and prefer host conversation for ordinary work; direct CLI use is mainly for diagnostics, recovery, and advanced control.

### 15. Troubleshooting

- Missing key: use strategy-only mode or secure `credentials setup`; never paste a key in chat.
- Excessive/noisy results: build a current-task focus plan and preserve the master corpus.
- Sparse focused evidence: expand theory-supplement and writing-evidence candidates while retaining direct/adjacent boundaries.
- Missing abstracts/full text: metadata bibliometrics remain possible, but metadata cannot become content evidence.
- Unstable NMF: use it only as an exploratory scaffold when convergence and coverage allow.
- Skipped knowledge flow/half-life: inspect local directed-citation, reference-year, and yearly-history coverage; downgrade is the scientifically correct outcome when sparse.
- Unavailable theory library: the workflow continues with theory-neutral mechanism prose.
- Resume: run `status --task TASK` and follow `user_prompt` or `next_command`.
- Blocked final HTML: resolve stale audits, citation-set mismatch, unknown records, causal overclaiming, or missing approval.

### 16. Integrity and boundaries

- Use only user-held, OA, or institution-authorized full text.
- Never bypass authentication, access control, CAPTCHAs, or paywalls.
- Never fabricate records, citations, DOIs, pages, anchors, findings, or social statistics.
- Preserve metadata/abstract/full-text distinctions; publication prose may hide workflow labels but not change support strength.
- Bibliometrics, theory libraries, and LLM knowledge never replace current-task evidence.
- Authors remain responsible for verification, scholarly judgment, and final submission.
- PRISMA-style logs support reproducibility but do not automatically satisfy field-specific registration/reporting rules.

---

## 官方链接与版本说明 / Official links and version notes

- [OpenAlex API 设置 / API settings](https://openalex.org/settings/api)
- [OpenAlex 用量 / Usage](https://openalex.org/settings/usage)
- [OpenAlex Authentication & Pricing](https://developers.openalex.org/guides/authentication)
- [OpenAlex API overview](https://developers.openalex.org/api-reference/introduction)
- [Codex Skills](https://developers.openai.com/codex/skills/)
- [Claude Code Skills](https://code.claude.com/docs/en/slash-commands)

文档核对日期 / Documentation verification date: **2026-07-15**. 服务额度、价格和宿主安装位置可能变化，应以上述官方页面为准。

## 发布包结构 / Release layout

```text
CQ-BIRW-release-2026-07-15/
├── readme.md
├── CQ-Bibliometric-Introduction-Review-Writing- UserManual.html
├── RELEASE-MANIFEST.json
├── SHA256SUMS.txt
└── cq-bibliometric-introduction-review-writing/
    ├── SKILL.md
    ├── agents/
    ├── assets/
    ├── references/
    └── scripts/
```

发布技能目录不包含任务数据、测试、缓存、凭据或用户资料。README 和用户说明 HTML 具有相同的中英文信息架构、命令、默认值、支持矩阵、限制和官方链接；HTML 只增加离线导航与排版。

**JWC💗XQ@Rednote drharry**
