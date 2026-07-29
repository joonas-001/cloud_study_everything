# 第四里程碑复习策略研究记录

> 状态：4A 固定策略已由项目所有者确认
> 检索日期：2026-07-28（Asia/Shanghai）
> 适用范围：`algorithm@0.2.0` 共同主干入口受限预览
> 不适用范围：个体遗忘参数拟合、长期掌握声明、正式技能包激活

## 1. 已确认策略

4A 使用透明、确定性、版本化的固定递增复习日程：

- 初始活动全部完成后，学习执行进入 `retention_pending`；
- 按完成时刻起第 `1、2、4、7、15` 天安排主动提取复习；
- 每个检查点通过后才安排下一个检查点；
- 第 15 天检查点通过后，学习执行进入 `completed`；
- `completed` 只表示本次受限流程完成，不表示掌握；
- 失败或用户选择“不确定”时保持 `retention_pending`，立即追加纠错任务；
- 纠错完成后的第 1 天安排同一阶段重测，通过后继续原序列；
- 错过到期时间只标记逾期并提高任务优先级，不记录为能力失败，也不重置日期。

策略使用主动提取和任务变体，不使用单纯重复阅读作为通过依据。4A 不开放用户自定义间隔。

## 2. 研究依据

### 2.1 艾宾浩斯遗忘曲线及复现

Murre 与 Dros 在 2015 年复现了艾宾浩斯的节省法遗忘曲线。实验在 20 分钟、1 小时、
9 小时、1 天、2 天和 31 天后重新学习无意义音节，结果支持遗忘在早期较快、之后趋缓，
但曲线并非完全平滑。

- 来源：Murre, J. M. J., & Dros, J. (2015).
  *Replication and Analysis of Ebbinghaus’ Forgetting Curve*. PLOS ONE, 10(7),
  e0120644.
- DOI：<https://doi.org/10.1371/journal.pone.0120644>
- 证据强度：同行评审的直接复现，但仍以单一被试和无意义音节为主。
- 限制：实验中的延迟是测量点，不是作者规定的通用复习日程；不能直接外推为算法技能的
  精确最佳间隔。

### 2.2 分散练习与目标保持时长

Cepeda 等人在 2008 年的大样本研究中发现，最优学习间隔随目标测试延迟增长；同一固定
间隔不适用于所有保持目标。

- 来源：Cepeda, N. J., Vul, E., Rohrer, D., Wixted, J. T., & Pashler, H. (2008).
  *Spacing Effects in Learning: A Temporal Ridgeline of Optimal Retention*.
  Psychological Science, 19(11), 1095–1102.
- DOI：<https://doi.org/10.1111/j.1467-9280.2008.02209.x>
- 证据强度：同行评审、超过 1,350 名参与者、测试延迟最长一年。
- 限制：主要材料是事实知识；结果支持递增间隔原则，但不唯一确定 4A 的具体日期。

### 2.3 教育实践中的分散学习与主动提取

美国教育科学研究院 2007 年实践指南把跨时间分散学习评为中等证据，并建议用主动提取
测验促进长期记忆。Dunlosky 等人的 2013 年综述把练习测试与分散练习评为高效学习技术，
同时指出复杂材料的直接研究相对较少。

- 来源：Pashler, H., Bain, P. M., Bottge, B. A., Graesser, A., Koedinger, K. R.,
  McDaniel, M., & Metcalfe, J. (2007).
  *Organizing Instruction and Study to Improve Student Learning*.
- 官方页面：<https://ies.ed.gov/ncee/wwc/PracticeGuide/1>
- 来源：Dunlosky, J., Rawson, K. A., Marsh, E. J., Nathan, M. J., &
  Willingham, D. T. (2013).
  *Improving Students’ Learning With Effective Learning Techniques*.
  Psychological Science in the Public Interest, 14(1), 4–58.
- DOI：<https://doi.org/10.1177/1529100612453266>
- 证据强度：政府实践指南与广泛研究综述相互支持。
- 限制：不能据此把一次或几次延迟复习解释为无限范围的长期掌握。

### 2.4 提取练习

Rowland 在 2014 年对测试效应进行了元分析，支持提取练习相较重复学习能够改善保持。
Roediger 与 Butler 的 2011 年综述进一步指出，反馈通常增强提取练习的效果。

- 来源：Rowland, C. A. (2014).
  *The Effect of Testing Versus Restudy on Retention: A Meta-Analytic Review of the
  Testing Effect*. Psychological Bulletin, 140(6), 1432–1463.
- DOI：<https://doi.org/10.1037/a0037559>
- 来源：Roediger, H. L., & Butler, A. C. (2011).
  *The Critical Role of Retrieval Practice in Long-Term Retention*.
  Trends in Cognitive Sciences, 15(1), 20–27.
- DOI：<https://doi.org/10.1016/j.tics.2010.09.003>
- 证据强度：元分析和同行评审综述。
- 限制：4A 没有独立人工、AI 或代码 Runner，反馈和正确性验证能力受限。

## 3. 策略解释与证据边界

`1、2、4、7、15` 天是基于早期遗忘较快、后期逐渐放缓和分散提取原则形成的产品化固定
规则，不是艾宾浩斯原始实验给出的标准答案，也不声称是每位用户或每类算法任务的最优
时间表。

4A 的复习结果最多形成 `retained_limited` 证据。代码不执行，自述和自评不能变成
`verified` 或不受限的 `retained` 证据。

## 4. 后续自适应曲线规划

后续版本可以在积累足够的真实复习结果后评估自适应曲线模型，但实施前必须另行确认：

- 使用幂函数、指数函数或其他模型及其证据；
- 目标回忆概率和不同活动类型的阈值；
- 冷启动参数、最小样本量和异常数据处理；
- 成功、失败、不确定和逾期分别如何更新参数；
- 如何验证个体预测校准和避免虚假精确性；
- 隐私、可解释性、版本迁移和回退方案；
- 策略变化对应的新技能包补丁版本。

在这些决定和验证完成前，4A 不采集或展示未经校准的“预测记忆率”。
