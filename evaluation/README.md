# CommentLab 评测

## 轻量现实案例评测

```bash
cd /home/s2025013242/Big_task_v1
~/miniconda3/envs/commentlab/bin/python -m evaluation.runner \
  --feedback-only --limit 7
```

轻量流程执行原文内容分析、受众规划、三轮评论模拟和风险诊断，然后生成改写稿，并只重新分析改写文本的风险。它不会对改写稿重新生成评论、热度或对比报告。

每条案例自动检查五项：风险等级、关键风险句、主要争议、改写忠实度、改写后文本风险是否下降。前七条现实案例另外检查模拟评论是否覆盖真实评论的主要争议，该附加指标不参与五分制总分。

## 数据隔离

- `data/eval_cases.json` 的前七条包含固定背景卡，不进行实时联网检索。
- `annotations.real_comments` 是隐藏参考，只在模拟完成后参与评分。
- `build_business_input()` 明确排除全部 `annotations`，防止真实评论或答案进入 Agent 生成流程。

## 其他运行方式

```bash
# 30 条轻量评测
~/miniconda3/envs/commentlab/bin/python -m evaluation.runner --feedback-only

# 完整评测：包括改写后评论重模拟和对比 Agent
~/miniconda3/envs/commentlab/bin/python -m evaluation.runner

# 不调用真实模型的流程冒烟测试
~/miniconda3/envs/commentlab/bin/python -m evaluation.runner \
  --demo --feedback-only --limit 7 --output-dir /tmp/commentlab-eval-smoke
```

报告写入 `evaluation/results/latest_report.md`，逐项证据写入 `latest_summary.json`，每条案例的完整反馈保存在对应编号目录。

关键词分数用于快速回归，不替代人工复核。尤其要人工检查改写是否只是增加免责声明、是否保留了原有冒犯表达，以及小幅风险降分是否具有实际意义。
