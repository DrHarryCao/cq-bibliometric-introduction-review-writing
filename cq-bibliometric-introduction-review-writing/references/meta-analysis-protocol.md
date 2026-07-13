# 条件式效应量综合协议

只在结局定义、效应指标、方差信息及样本独立性可比时运行。允许的指标为相关系数、Hedges g、OR和RR；不从含糊摘要推造效应量。

1. `synthesize-effects --phase prepare` 生成提取表。宿主仅填写文献明确报告或可透明换算的值、方差、结局、sample ID和锚点。
2. `compile` 按结局和指标分组，去除重复sample ID，至少3项独立研究才使用REML随机效应。
3. 报告汇总效应、95%CI、预测区间、τ²、Q、I²与leave-one-out。
4. 亚组至少两组且每组至少3项；数值元回归和Egger信号至少10项独立研究才运行，并标记为探索性。
5. `validate` 核查record ID、锚点、重复样本和指标可比性。不满足时输出 `skipped-insufficient-data` 并回退结构化叙事综合。

合并结果是条件性证据，不能消除构念、设计、偏倚风险和外部效度差异。
