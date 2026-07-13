# 宿主语义证据协议

## 原则

- 默认由 Codex/Claude 读取证据卡、摘要或全文并结构化提取；不下载或运行 embedding 模型。
- 只提取原文明确支持的研究问题、理论、变量、关系、设计、样本、情境、方法、结果、局限和重复数据线索。
- 全文证据使用 `page:n` 或 `paragraph:n`；摘要证据使用 `abstract`。
- 相关、因果、中介、调节、不显著和反向结果必须分开编码。

## 操作

1. 运行 `build-semantic --phase prepare`，按 batch 读取 `05_evidence/semantic/batches/`。
2. 对每篇文献填写 `extractions/<record_id>.json`，设置 `host_review_status: completed`。
3. 运行 `compile`，生成理论—变量、机制路径、方法—情境—结果、反向/不显著证据矩阵。
4. 对语义 claim 标记 `supported/partial/unsupported`，然后运行 `validate`。
5. `unsupported` 禁止定稿；`partial` 必须缩小措辞；强概括默认需至少3项独立研究。

## 写作优先级

全文/摘要内容证据 → 宿主语义综合 → NMF主题结构 → 引文年龄/知识流 → 战略图/KMeans/网络辅助信号。

Embedding 只保留扩展协议。`semantic-embeddings --dry-run` 只估算规模，不安装依赖、不检测 GPU、不下载权重。
