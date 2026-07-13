---
name: cq-bibliometric-introduction-review-writing
description: Map a research field and draft a traceable systematic review or funnel-shaped SSCI introduction from a title, idea, bibliographic exports, or local full texts, with optional API search or API-free WoS strategy generation, explanatory/evidential gap audits, dynamic research-design and method matching, a user-managed non-blocking theory library, theory-model packages, and auditable HTML/RIS delivery. Use for bibliometrics and Chinese academic writing. JWC💗XQ@Rednote drharry. Never bypass paywalls or fabricate unavailable evidence.
---

# CQ Bibliometric · Introduction · Review · Writing

This shared Codex/Claude skill builds auditable bibliometric analyses, systematic reviews, and funnel-shaped SSCI introductions.

Copyright mark: `JWC💗XQ@Rednote drharry`.

Run a staged, resumable workflow. Let Python collect, normalize, analyze, and index evidence; perform topic reasoning, evidence-card completion, synthesis, and writing yourself from local artifacts.

## Start safely

1. Locate this skill directory from the loaded `SKILL.md`; call it `SKILL_DIR`.
2. Use UTF-8 throughout. Never edit the user's original analysis program.
3. Read [platform-compatibility.md](references/platform-compatibility.md), then run the platform-appropriate `review_pipeline.py doctor --json` before the first task. If dependencies are missing, install core requirements only; OCR and quantitative-synthesis dependencies are optional groups.
4. Create a separate task directory with `init`. Never put generated research data inside the skill directory.
5. Stop only at a genuine decision checkpoint. After approval, continue every deterministic and host-writing stage automatically until the next checkpoint. During automatic work say `正在自动继续，无需回复` and do not end the turn. At a checkpoint, give the exact replies the user can send.
6. First ask whether to use `api-search` or `strategy-only`. Never require credentials in strategy-only mode. Never ask the user to paste API keys into chat.
7. Run `doctor` for a new installation or after moving the skill. Run `status` before resuming an old task; manifest schema migration must not rewrite corpus or drafts.
8. The skill contains no built-in theory content. A user may manage the external theory library independently with `theory-library`, without creating a review task. Read [theory-library-protocol.md](references/theory-library-protocol.md) before importing, verifying, recommending, or writing with theories.

## Workflow

### 1. Frame and approve the search

- Ask for a title or research idea if absent.
- Run `init --task <task-dir> --title <idea>`.
- Read [workflow.md](references/workflow.md) and [api-sources.md](references/api-sources.md).
- Inspect `source_language`. When the input contains Chinese, translate it yourself without calling an external translation API: preserve `title_zh`, write a faithful academic-English `title_en`, create paired `zh`/`en` concept terms, and include separately tagged Chinese and pure-English core queries. Set `translation_status: completed` only after checking semantic equivalence.
- Expand `00_plan/search_plan.json` into bilingual concepts, synonyms, exclusions, core/extended/frontier query families, date/language/type boundaries, and inclusion criteria. Keep Chinese and English queries separate so each hit is auditable.
- Run `validate-plan --task <task-dir>`. Do not ask for approval until it passes. The validator must block Chinese-origin plans lacking an English title, bilingual concepts, or both Chinese and English core queries.
- Explain the plan in `search_plan.md`, estimate breadth where possible, and ask the user to approve it. Only then set `approved: true` or run `search --confirm`.
- Run `search-strategy --mode strategy-only|api-search`. Always produce the three WoS query variants. Read [search-strategy-protocol.md](references/search-strategy-protocol.md).
- In strategy-only mode, do not open a credential dialog or send network requests. Move directly to recursive `ingest` and `extract` paths supplied by the user.

### 2. Search and align user exports

- Run `search`. If the OpenAlex key is missing, the command must automatically open the native credential dialog, securely store the masked input, and continue after the dialog succeeds. Do not instruct ordinary users to configure environment variables. Use the stored Unpaywall email for OA enrichment and optional Semantic Scholar key only when configured.
- Maintain a PRISMA-style protocol and screening log. Invite seed papers when available and report recall; do not claim full PRISMA compliance merely because a flow file exists.
- Review bilingual translation equivalence, synonym coverage, deduplication confidence, corrections/retractions and suspected non-independent samples before treating the corpus as final.
- After search, explicitly ask whether the user has WoS, CNKI, EndNote, PubMed, CSV/XLSX, RIS, BibTeX, or other exports.
- Run `ingest` for supplied files. Read [schema.md](references/schema.md) when interpreting mappings, conflicts, deduplication, or source-specific citation counts.
- Show the ingest report and resolve material ambiguous mappings before analysis.
- After local import, offer `enrich-metadata --source crossref --confirm`; without explicit confirmation remain offline. Read `metadata-coverage.md` before interpreting disabled analyses.
- Ask the user to select `corpus-policy --mode all|focused`. All means zero exclusions but does not make every record direct content evidence. Focused mode preserves the full task and creates a screened derivative.
- When broad exploratory queries contaminate a field-specific corpus, create a derived task with `focus --task <all-task> --output-task <focused-task>`. Preserve the all-record task; analyze only the direct core and retain screened adjacent theory records in its separate theory pool.
- If the user wants available full text downloaded, first run `download-oa --dry-run --limit N` and show the inventory. Run `download-oa --limit N` for explicit OA URLs. Use `--allow-paid-openalex-content` only after a separate confirmation of count and estimated cost.

### 3. Process full text and references

- Ask for individual PDF/DOCX files, multiple paths, or a directory. Run `extract` on supplied content.
- Review `extraction_report.json`. Never treat scanned/failed documents as read; after explicit approval, rerun affected PDFs with `extract --ocr` only if lawful and Tesseract is locally available.
- Run `expand-references --depth 1 --max-candidates 200` after extraction. Present the candidate Markdown to the user; it is not part of the corpus until the user selects and imports records.
- Never bypass institutional login or a paywall. Prefer user-provided files and lawful OA locations.

### 4. Analyze and build evidence

- Read [analysis-protocol.md](references/analysis-protocol.md), then run `analyze --language auto --nmf-structure auto`. Use NMF as the only topic structure. A converged but unstable NMF may organize sections as an explicitly exploratory framework after host semantic renaming, but it cannot support strong claims about the field's stable knowledge structure. Treat KMeans only as a gated heterogeneity diagnostic; never create a second topic taxonomy. Do not introduce LDA, BERTopic, or HDBSCAN. Inspect advanced-module status before interpreting the strategic map, citation age, or knowledge flow. Read [legacy-analysis-map.md](references/legacy-analysis-map.md) when comparing outputs with the user's v6.2 program.
- Prefer fractional network counting. Inspect true resampling/bootstrap NMF stability, c-NPMI, diversity, exclusivity, soft-membership entropy, preprocessing sensitivity, threshold sensitivity and network null-model comparisons. Only converged and reproducible signals may support strong bibliometric descriptions.
- Run `build-evidence`.
- Read [evidence-protocol.md](references/evidence-protocol.md) completely before filling cards or the claim ledger.
- Read the topic, trend, network and citation dossiers. Treat bursts, centrality and structural holes as organizing evidence, never as content or causal findings.
- Follow `citation_coverage.md` and `section_citation_quotas.json`. Cite 60% when eligible evidence is at most 100 records; for larger sets use the balanced enhanced target capped at 120. Meet every topic quota.
- Complete cards in manageable batches. Use exact page/paragraph anchors for full-text claims; label abstract-only and metadata-only evidence honestly.
- Complete the design-specific quality appraisal. Verify independent samples, risk of bias and claim-to-source semantic support; never collapse heterogeneous designs into one mechanical quality score.
- Read [semantic-protocol.md](references/semantic-protocol.md), then run `build-semantic --phase prepare`. Fill extraction files yourself from cards/full text in batches; run `compile`, selective `reconcile`, and `validate` before writing. This base workflow uses no embeddings.
- If comparable effect data may exist, read [meta-analysis-protocol.md](references/meta-analysis-protocol.md) and run `synthesize-effects --phase prepare|compile|validate`. Treat `skipped-insufficient-data` as the correct outcome and continue with structured narrative synthesis.
- Synthesize topic dossiers, including counterevidence and method/context boundaries. Add content claims to both claim-ledger formats with unique IDs.

### 5. Outline, write, and audit

- Read [review-protocol.md](references/review-protocol.md) completely.
- Build the research-status map and a decision-complete outline from dossiers and the claim ledger. Ask the user to approve it; change `status: approved` only after approval.
- Before review prose, run `writing-brief --document review`; accept one/many broad or specific gap directions, or `--skip`. Read [gap-and-model-protocol.md](references/gap-and-model-protocol.md).
- Run `build-gaps --phase prepare`; use semantic/full-text evidence to complete `gap_ledger.jsonl`, then run `compile` and `validate`. Treat A-level explanatory and B-level evidential gaps as potential core contributions. Treat “few studies”, a new context, or an unused method as C-level opportunities unless they demonstrably change theory boundaries, credible inference, or consequential decisions. If no A/B gap survives, say so and deliver explicitly downgraded opportunities with warnings rather than inventing a gap.
- When gap/model work makes theory support useful, ask exactly once whether to use `combined`, `local-only`, `llm-only`, or `skip`, then run `theory-support`. Read [theory-library-protocol.md](references/theory-library-protocol.md). If enabled, run `theory-recommend --phase prepare`, complete the local/LLM fit ledger with source checks, then run `compile` and `validate`. Theory support is always fail-open: empty/corrupt libraries, unverified theories, no fit, or module errors must produce a degradation log and automatically continue with evidence-grounded mechanism/boundary prose. Never block review, introduction, RIS, or HTML because of theory status.
- Run `recommend-design --phase prepare|compile|validate` automatically after gap audit. Read the method catalog through [gap-and-model-protocol.md](references/gap-and-model-protocol.md). Select design before estimator; combine corpus method evidence with the general method library. User-named methods are preferences requiring fit checks, never defaults.
- Draft one section at a time into `06_review/sections/`, using visible APA 7 citations plus `[cite:R...,R...]` audit bindings. Before prose, map each smallest verifiable claim to its exact supporting records. Immediately run `audit-writing --source SECTION --scope SECTION_ID`; resolve both `citation_repair_queue.jsonl` and `citation_attribution_queue.jsonl` before merging. Never leave one large citation cluster to support heterogeneous objects, mechanisms, media, or outcomes, and never copy all paragraph-end citations into every sentence. Every substantive knowledge-topic paragraph must cite related evidence.
- Distribute coverage evidence inside the approved narrative sections. Never create a post-hoc “expanded evidence”, “supplementary citations”, or similar section merely to meet coverage quotas.
- After merging `review_draft.md`, run `sync-references --document review`. It must rebuild the embedded reference list from the evidence actually used in the body; do not maintain a partial reference list by hand.
- After the review is synchronized and its full-text sentence audit passes, run `export-deliverables --document review --draft` to create a clearly marked HTML preview. Stop and accept only `确认综述` or concrete revision instructions. Record the decision with `document-approval --document review --status approved|revision-requested`.
- Only after current review approval ask independently which gap(s) or research question(s) the introduction should emphasize. Accept specific directions, `跳过`, or `不写绪论`; never inherit the review brief as the introduction default. Run `writing-brief --document introduction`, then draft 8–12 continuous Chinese body paragraphs (3,000–5,000 Chinese characters) with no body headings/lists. Register official/authoritative social-context sources in `social_context_sources.jsonl`, ground the first paragraph in them, and run `write-introduction --audit-source PATH`.
- When proposing variables, create `theory_model_package.md` with audited gap IDs, variable roles, construct boundaries, theory-to-path mapping, alternatives, discriminating predictions, hypotheses, question-to-design-to-method fit, identification assumptions, robustness, Mermaid model, and evidence levels. Never use method novelty as the gap or prefill a fixed method combination.
- Run final `audit-writing --document review|introduction`, complete the sentence- and atomic-claim support ledgers, then run `validate`. A `supported` sentence must have evidence IDs, evidence level, support scope and an audit note. Resolve pending/unsupported factual sentences, unknown claim IDs, missing anchors, causal-design mismatch, omitted counterevidence, and exaggerated gap language before delivering.
- After the evidence-aware version passes, run `build-publication --document review|introduction --phase prepare`. Rewrite only the queued passages: remove reader-facing workflow/evidence-level wording, retain supported claims, turn essential partial claims into explicit testable propositions, and delete unsupported nonessential claims. Record explicit host decisions for rewritten factual sentences in `05_evidence/publication_support_reviews.jsonl`; never bulk-mark generated ledger rows. Then run `compile` and `validate`. Publication prose must never upgrade evidence certainty.
- Run `export-deliverables --document review|introduction --variant both` only after current validation passes. Read [deliverables-protocol.md](references/deliverables-protocol.md); verify evidence-aware and publication MD/HTML/RIS sets. Use `--draft` only for a visibly marked preview that cannot overwrite final deliverables. Do not pre-generate DOCX; each HTML creates Word only when the user clicks its button.
- Report limitations caused by missing abstracts, inaccessible full text, OCR failure, source bias, date/language filters, or sparse evidence.

## Command reference

Use `<PYTHON> <PIPELINE>` below; `PIPELINE` is the absolute path to `scripts/review_pipeline.py`. See [platform-compatibility.md](references/platform-compatibility.md) for Bash, PowerShell and CMD syntax.

```text
<PYTHON> scripts/install_skill.py install|status|repair|uninstall --host codex|claude|both --scope project|user --mode auto
<PYTHON> <PIPELINE> doctor [--json] [--repair]
<PYTHON> <PIPELINE> credentials setup --input auto|gui|terminal
<PYTHON> <PIPELINE> wizard|init|search-strategy|validate-plan|search|ingest|extract ...
<PYTHON> <PIPELINE> analyze --task TASK --language auto --bootstrap-runs 5 --nmf-structure auto|strict|off
<PYTHON> <PIPELINE> build-evidence --task TASK
<PYTHON> <PIPELINE> build-semantic --task TASK --phase prepare|compile|reconcile|validate
<PYTHON> <PIPELINE> synthesize-effects --task TASK --phase prepare|compile|validate
<PYTHON> <PIPELINE> build-gaps|recommend-design ...
<PYTHON> <PIPELINE> theory-library init|status|ingest|verify|promote|search|show|update|disable|export|import ...
<PYTHON> <PIPELINE> theory-support --task TASK --mode combined|local-only|llm-only|skip
<PYTHON> <PIPELINE> theory-recommend --task TASK --phase prepare|compile|validate
<PYTHON> <PIPELINE> sync-references --task TASK --document review|introduction
<PYTHON> <PIPELINE> audit-writing --task TASK --document review|introduction [--source FILE --scope SECTION_ID]
<PYTHON> <PIPELINE> build-publication --task TASK --document review|introduction --phase prepare|compile|validate
<PYTHON> <PIPELINE> document-approval --task TASK --document review --status approved|revision-requested
<PYTHON> <PIPELINE> validate --task TASK
<PYTHON> <PIPELINE> export-deliverables --task TASK --document review|introduction --variant evidence-aware|publication|both
<PYTHON> <PIPELINE> status --task TASK
```

Use `status` whenever resuming an existing task. Preserve raw API responses, hashes, manifests, and conflict logs as provenance.
