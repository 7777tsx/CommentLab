# CommentLab

CommentLab 是一个面向普通个人和内容创作者的发布前沟通风险模拟系统。它通过多种受众 Agent 模拟帖子发布后的评论、回复和热度变化，识别误解、负面情绪、阵营争吵和话题跑偏风险，在保持发布者人设的前提下生成改写版本，并使用同一批受众进行反事实重模拟。

> 本系统用于发布前沟通风险压力测试，模拟结果不代表真实舆情预测。

## 第一版边界

- 输入为 500 字以内中文短文本和简版发布者画像。
- 面向个人创作者，不面向政府、学校行政或大型企业危机公关。
- 不判断观点对错，不做事实核查。
- 不读取链接、图片、视频、账号历史或真实用户画像。
- 平台无关，不模拟某个具体平台的语言风格。
- 不使用外部评论语料。数据集、平台风格和语料检索留作后续阶段。

## 系统流程

```text
内容分析 Agent
→ 受众规划 Agent
→ 用户确认受众比例
→ 评论生成 Agent（三轮）
→ Python 热度模拟工具
→ 风险诊断 Agent
→ 人设保持改写 Agent
→ 相同受众反事实重模拟
→ 对比评估 Agent
```

评论生成每轮批量处理多个 Persona。约 50 个潜水用户完全由 Python 规则模拟点赞，避免额外模型调用。正常完整流程约 11 次模型调用；相同请求写入 SQLite 缓存。

## Agent 与工具

- **内容分析 Agent**：提取核心信息、模糊表达、缺失信息、潜在误解和人设冲突。
- **受众规划 Agent**：从 12 种预设 Persona 中规划受众构成。
- **评论生成 Agent**：按不同阅读深度、信任和情绪倾向批量生成评论、回复或沉默行为。
- **热度模拟工具**：计算潜水点赞、回复数、热度和可见评论，全程不调用模型。
- **风险诊断 Agent**：识别误解、负面情绪、对立和跑题，定位原文片段与误解链。
- **人设保持改写 Agent**：不改变观点、不添加事实，保留个人表达风格。
- **对比评估 Agent**：比较同一受众和随机配置下改写前后的模拟结果。

## 安装

服务器需要 Python 3.10 或更高版本。

服务器缺少系统 `python3-venv` 时，使用项目独立 Conda 环境：

```bash
cd ~/Big_task
~/miniconda3/bin/conda create -y -n commentlab python=3.12 pip
~/miniconda3/envs/commentlab/bin/python -m pip install \
  -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

如果系统已提供 `python3-venv`，也可以在项目中创建 `.venv`。

## 配置

复制环境变量模板并填写 OpenAI-compatible 服务：

```bash
cp .env.example .env
```

```env
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
LLM_TEMPERATURE=0.4
LLM_TIMEOUT=30
DEMO_MODE=true
DATABASE_PATH=commentlab.db
```

任何一项必要模型配置为空时，系统都会进入 `DEMO_MODE`，不会因为缺少密钥而崩溃。真实密钥不得提交到 Git 或出现在截图中。

## DEMO_MODE

`DEMO_MODE=true` 时，Agent 使用符合相同 Pydantic 契约的确定性启发式实现。它不是静态页面：三轮状态推进、Persona 激活、潜水点赞、热度、风险权重、反事实一致性和 SQLite 持久化仍会真实执行。

内置三个课堂案例：

1. `最近会适当减少更新，大家不用多想。`
2. `有些人真的应该学会尊重别人，不要什么事情都来指手画脚。`
3. `我承认这件事处理得不够好，但当时的情况真的很复杂，希望大家不要只看结果。`

## 运行

```bash
~/miniconda3/envs/commentlab/bin/streamlit run app.py \
  --server.address 0.0.0.0 --server.port 8502
```

当前课程服务器上的 `8501` 已被其他进程占用，因此使用 `8502`。在 VS Code Remote SSH 的“端口”面板转发 `8502`，然后打开：

```text
http://127.0.0.1:8502
```

如果端口被其他进程占用，使用 `8502`，不要终止其他用户的服务。

## 测试

```bash
cd ~/Big_task
~/miniconda3/envs/commentlab/bin/python -m pytest -q
```

测试覆盖数据契约、500 字限制、比例归一化、热度、潜水点赞、随机种子、三轮模拟、无效回复、25/75 风险权重、风险阈值、SQLite、缓存、结构化 JSON 修复、DEMO_MODE、历史加载、三个案例和反事实受众一致性。

## SQLite

数据库包含：

- `projects`：项目输入、改写与完整结果快照；
- `personas`：实际模拟使用的受众配置；
- `comments`：改写前后全部评论和内部分析字段；
- `reports`：前后风险报告和对比报告；
- `llm_cache`：相同模型请求的结构化输出缓存。

历史结果直接从 `projects.result_json` 恢复，不再次调用模型。

## 课堂演示建议

1. 提前启动 Streamlit，并确认侧栏显示 `DEMO_MODE` 或可用模型名。
2. 选择“容易被视为辩解的回应”案例。
3. 展示内容初步分析和受众比例。
4. 运行三轮模拟，查看高热评论、风险句和误解链。
5. 打开改写对比，说明前后使用相同 Persona、seed、轮数和热度规则。
6. 从历史结果重新打开刚才的项目，展示无需再次调用模型。

## 降级与失败处理

- 模型调用超时为 30 秒，失败后重试一次。
- 结构化输出由 Pydantic 校验；非法 JSON 可修复尾随逗号和代码围栏。
- 单个 Agent 阶段连续失败后使用本地降级结果，已有流程状态不会丢失。
- 缺少模型配置时自动进入 DEMO_MODE。
- 相同输入和模型配置优先读取 SQLite 缓存。

## 评测建议

- **功能完整性**：确认输入到反事实对比的完整闭环。
- **结构稳定性**：统计字段缺失、非法 JSON、重复评论和无效回复。
- **Persona 区分度**：人工判断各 Persona 的阅读方式和表达是否不同。
- **风险点覆盖率**：系统识别的主要风险点 / 人工标注主要风险点。
- **改写有效性**：比较误解、负面、对立回复、跑题和高频追问变化。
- **人设保持**：人工按原语气、观点保留、官方化程度和作者一致性打 1 至 5 分。

## 两人分工建议

- 成员 A：LangChain、Pydantic、提示词、六条 Agent 链、模型调试和 token 优化。
- 成员 B：Streamlit、SQLite、比例调整、潜水用户、热度、排序、历史和测试。
- 共同完成 Persona 模板、风险标准、案例、评测、报告与答辩。

## 局限

模拟不能精准预测真实舆论，风险等级也不是客观概率。LLM 可能产生同质化或偏负面的输出；改写后风险降低不表示真实发布一定不会引发争议。第一版不做事实核查，也不学习具体平台的评论语言。

## 参考

- [Social Simulacra](https://arxiv.org/abs/2208.04024)
- [S3](https://arxiv.org/abs/2307.14984)
- [OASIS](https://arxiv.org/abs/2411.11581)
- [LangChain Structured Output](https://docs.langchain.com/oss/python/langchain/structured-output)
