---
name: cq-bibliometric-introduction-review-writing
description: Map a research field and draft a traceable systematic review or funnel-shaped SSCI introduction from a title, idea, bibliographic exports, or local full texts, with optional API search or API-free WoS strategy generation, all/focused corpus policies, directed research-gap briefs, theory-model packages, and auditable HTML/RIS delivery. Use for bibliometrics and Chinese academic writing. JWC💗XQ@Rednote drharry. Never bypass paywalls or fabricate unavailable evidence.
---

# CQ Bibliometric · Introduction · Review · Writing

This shared Codex/Claude skill builds auditable bibliometric analyses, systematic reviews, and funnel-shaped SSCI introductions.

Copyright mark: `JWC💗XQ@Rednote drharry`.

Run a staged, resumable workflow. Let Python collect, normalize, analyze, and index evidence; perform topic reasoning, evidence-card completion, synthesis, and writing yourself from local artifacts.

## Start safely

1. Locate this skill directory from the loaded `SKILL.md`; call it `SKILL_DIR`.
2. Use UTF-8 throughout. Never edit the user's original analysis program.
3. Run `python "$SKILL_DIR/scripts/review_pipeline.py" --help` before the first task. If dependencies are missing, install only those listed in `scripts/requirements.txt` after telling the user.
4. Create a separate task directory with `init`. Never put generated research data inside the skill directory.
5. Stop only at a genuine decision checkpoint. After approval, continue every deterministic and host-writing stage automatically until the next checkpoint. During automatic work say `正在自动继续，无需回复` and do not end the turn. At a checkpoint, give the exact replies the user can send.
6. First ask whether to use `api-search` or `strategy-only`. Never require credentials in strategy-only mode. Never ask the user to paste API keys into chat.
7. Run `doctor` for a new installation or after moving the skill. Run `status` before resuming an old task; manifest schema migration must not rewrite corpus or drafts.

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

- Run `analyze`. Use NMF as the only topic structure. Treat KMeans only as a gated heterogeneity diagnostic; never create a second topic taxonomy. Do not introduce LDA, BERTopic, or HDBSCAN. Inspect advanced-module status before interpreting the strategic map, citation age, or knowledge flow. Read [legacy-analysis-map.md](references/legacy-analysis-map.md) when comparing outputs with the user's v6.2 program.
- Prefer fractional network counting and inspect multi-seed NMF stability, soft-membership entropy and threshold sensitivity. Only stable signals may support strong bibliometric descriptions.
- Run `build-evidence`.
- Read [evidence-protocol.md](references/evidence-protocol.md) completely before filling cards or the claim ledger.
- Read the topic, trend, network and citation dossiers. Treat bursts, centrality and structural holes as organizing evidence, never as content or causal findings.
- Follow `citation_coverage.md` and `section_citation_quotas.json`. Cite 60% when eligible evidence is at most 100 records; for larger sets use the balanced enhanced target capped at 120. Meet every topic quota.
- Complete cards in manageable batches. Use exact page/paragraph anchors for full-text claims; label abstract-only and metadata-only evidence honestly.
- Complete the design-specific quality appraisal. Verify independent samples, risk of bias and claim-to-source semantic support; never collapse heterogeneous designs into one mechanical quality score.
- Read [semantic-protocol.md](references/semantic-protocol.md), then run `build-semantic --phase prepare`. Fill extraction files yourself from cards/full text in batches; run `compile` and `validate` before writing. This base workflow uses no embeddings.
- Synthesize topic dossiers, including counterevidence and method/context boundaries. Add content claims to both claim-ledger formats with unique IDs.

### 5. Outline, write, and audit

- Read [review-protocol.md](references/review-protocol.md) completely.
- Build the research-status map and a decision-complete outline from dossiers and the claim ledger. Ask the user to approve it; change `status: approved` only after approval.
- Before review prose, run `writing-brief --document review`; accept one/many broad or specific gap directions, or `--skip`. Read [gap-and-model-protocol.md](references/gap-and-model-protocol.md).
- Draft one section at a time into `06_review/sections/`, using visible APA 7 citations plus `[cite:R...,R...]` audit bindings. Every substantive knowledge-topic paragraph must cite related evidence. Any sentence saying that studies, literature, evidence, or the corpus shows something must carry traceable support.
- Distribute coverage evidence inside the approved narrative sections. Never create a post-hoc “expanded evidence”, “supplementary citations”, or similar section merely to meet coverage quotas.
- After merging `review_draft.md`, run `sync-references --document review`. It must rebuild the embedded reference list from the evidence actually used in the body; do not maintain a partial reference list by hand.
- When the user requests an SSCI introduction, run `write-introduction` to create its brief. Draft 8–12 continuous Chinese body paragraphs (3,000–5,000 Chinese characters) with no body headings/lists, save an evidence-marked audit source, then run `write-introduction --audit-source PATH`; it automatically synchronizes the final reference list and creates the clean version.
- Only after the review is complete ask whether to continue to the introduction. Run `writing-brief --document introduction`; store its preferences separately. Register official/authoritative social-context sources in `social_context_sources.jsonl` and ground the first paragraph in them.
- When proposing variables, create `theory_model_package.md` with variable roles, construct boundaries, theory-to-path mapping, alternatives, hypotheses, method fit, Mermaid model, and evidence levels. Never use method novelty as the gap.
- Run `validate`. Resolve unknown claim IDs, missing anchors, unsupported factual claims, omitted counterevidence, and exaggerated gap language before delivering `review_draft.md`.
- Run `export-deliverables --document review|introduction`. Read [deliverables-protocol.md](references/deliverables-protocol.md); verify clean/audit MD, single-file offline HTML and citation-matched RIS. Do not pre-generate DOCX; the HTML creates Word only when the user clicks its button.
- Report limitations caused by missing abstracts, inaccessible full text, OCR failure, source bias, date/language filters, or sparse evidence.

## Command reference

```text
python "$SKILL_DIR/scripts/review_pipeline.py" doctor
python "$SKILL_DIR/scripts/review_pipeline.py" credentials guide [--open-browser]
python "$SKILL_DIR/scripts/review_pipeline.py" credentials setup
python "$SKILL_DIR/scripts/review_pipeline.py" credentials status
python "$SKILL_DIR/scripts/review_pipeline.py" credentials test
python "$SKILL_DIR/scripts/review_pipeline.py" credentials update --name OPENALEX_API_KEY
python "$SKILL_DIR/scripts/review_pipeline.py" credentials delete --name OPENALEX_API_KEY
python "$SKILL_DIR/scripts/review_pipeline.py" wizard --task TASK --title IDEA
python "$SKILL_DIR/scripts/review_pipeline.py" init --task TASK --title IDEA
python "$SKILL_DIR/scripts/review_pipeline.py" search-strategy --task TASK --mode strategy-only|api-search
python "$SKILL_DIR/scripts/review_pipeline.py" validate-plan --task TASK
python "$SKILL_DIR/scripts/review_pipeline.py" search --task TASK [--confirm]
python "$SKILL_DIR/scripts/review_pipeline.py" ingest --task TASK INPUT...
python "$SKILL_DIR/scripts/review_pipeline.py" enrich-metadata --task TASK --source crossref --confirm
python "$SKILL_DIR/scripts/review_pipeline.py" corpus-policy --task TASK --mode all
python "$SKILL_DIR/scripts/review_pipeline.py" corpus-policy --task TASK --mode focused --output-task FOCUSED_TASK
python "$SKILL_DIR/scripts/review_pipeline.py" focus --task ALL_TASK --output-task FOCUSED_TASK
python "$SKILL_DIR/scripts/review_pipeline.py" download-oa --task TASK [--limit 100]
python "$SKILL_DIR/scripts/review_pipeline.py" extract --task TASK INPUT...
python "$SKILL_DIR/scripts/review_pipeline.py" expand-references --task TASK
python "$SKILL_DIR/scripts/review_pipeline.py" analyze --task TASK [--skip-kmeans] [--strategic-map auto --citation-age auto --knowledge-flow auto]
python "$SKILL_DIR/scripts/review_pipeline.py" build-evidence --task TASK
python "$SKILL_DIR/scripts/review_pipeline.py" build-semantic --task TASK --phase prepare|compile|validate [--budget balanced|exhaustive]
python "$SKILL_DIR/scripts/review_pipeline.py" semantic-embeddings --task TASK --dry-run
python "$SKILL_DIR/scripts/review_pipeline.py" sync-references --task TASK --document review|introduction [--draft PATH]
python "$SKILL_DIR/scripts/review_pipeline.py" writing-brief --task TASK --document review|introduction [--gap TEXT] [--skip]
python "$SKILL_DIR/scripts/review_pipeline.py" write-introduction --task TASK [--audit-source PATH]
python "$SKILL_DIR/scripts/review_pipeline.py" export-deliverables --task TASK --document review|introduction
python "$SKILL_DIR/scripts/review_pipeline.py" validate --task TASK
python "$SKILL_DIR/scripts/review_pipeline.py" status --task TASK
```

Use `status` whenever resuming an existing task. Preserve raw API responses, hashes, manifests, and conflict logs as provenance.
