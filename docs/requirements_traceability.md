# CommentLab 需求追踪矩阵

本表以 `选题报告_代码版.md` 为产品需求源，以 Goal 明确修订为最高优先级。

| 报告章节 | 分类 | 第一版落实位置 | 验收证据 | 状态 |
|---|---|---|---|---|
| 一、项目基本信息 | Implement | `app.py`、`README.md` | Streamlit 可运行，输入和输出闭环完整 | 已完成 |
| 二、选题背景 | Document | `README.md` | 说明发布前沟通风险问题 | 已完成 |
| 三、项目目标用户 | Document | `README.md`、`app.py` | 明确面向个人创作者，不面向组织公关 | 已完成 |
| 四、核心使用场景 | Implement | `data/demo_cases.json`、Agent 提示词 | 观点类、道歉/回应类案例可运行 | 已完成 |
| 五、项目核心定位 | Implement | `services/orchestrator.py`、`app.py` | 模拟、诊断、改写、反事实验证闭环 | 已完成 |
| 六、相关研究与空白 | Research only | `README.md` | 仅作为研究背景简述 | 已完成 |
| 七、用户需求与约束 | Implement | 全局 | 功能边界审计与端到端测试 | 已完成 |
| 八、系统功能设计 | Implement | `app.py`、`chains/`、`simulation/` | 四步页面和三轮评论模拟测试 | 已完成 |
| 九、风险分析体系 | Implement | `chains/risk_chain.py` | 四类风险均有评分与证据 | 已完成 |
| 十、综合风险等级 | Implement | `models/schemas.py`、`chains/risk_chain.py` | 0.25/0.75 权重和阈值单测 | 已完成 |
| 十一、风险诊断输出 | Implement | `chains/risk_chain.py`、`app.py` | 风险片段、原因、误解链、方向、总结 | 已完成 |
| 十二、保持人设的改写 | Implement | `chains/rewrite_chain.py` | 改写约束与三案例端到端测试 | 已完成 |
| 十三、反事实二次模拟 | Implement | `services/orchestrator.py` | Persona、seed、轮数等一致性测试 | 已完成 |
| 十四、Agent 架构 | Implement | `chains/`、`simulation/heat.py` | 六类链和规则工具均可调用 | 已完成 |
| 十五、LangChain 实现 | Implement | `services/llm_client.py`、`chains/` | Pydantic 结构化输出、固定链式流程 | 已完成 |
| 十六、Token 控制 | Implement | `chains/comment_chain.py`、缓存 | 每轮批量调用、上下文限量、缓存 | 已完成 |
| 十七、核心数据结构 | Implement | `models/schemas.py` | Pydantic 模型测试 | 已完成 |
| 十八、SQLite 设计 | Implement | `services/database.py` | CRUD、缓存、历史加载测试 | 已完成 |
| 十九、Streamlit 页面 | Implement | `app.py` | 四步交互和历史查看 | 已完成 |
| 二十、数据来源 | Deferred | 无运行代码 | 后续评论风格增强阶段；第一版不接外部语料 | 已延期 |
| 二十一、评测方案 | Implement / Document | `tests/`、`README.md` | 功能、结构化输出、Persona、改写评测说明 | 已完成 |
| 二十二、两人分工 | Document | `README.md` | 保留建议分工 | 已完成 |
| 二十三、开发阶段 | Document | 本追踪表、`README.md` | 实施顺序可追踪 | 已完成 |
| 二十四、项目目录 | Implement | 项目目录 | 目录与报告一致 | 已完成 |
| 二十五、演示案例 | Implement | `data/demo_cases.json` | 三个案例均通过端到端测试 | 已完成 |
| 二十六、局限与风险 | Document | `README.md`、`app.py` | 界面免责声明和局限章节 | 已完成 |
| 二十七、创新点 | Document | `README.md` | 创新点说明 | 已完成 |
| 二十八、预期成果 | Implement | 全局 | 代码、Demo、数据库、案例、文档齐全 | 已完成 |
| 二十九、一句话介绍 | Document | `README.md`、`app.py` | 首页可见 | 已完成 |
| 三十、参考资料 | Research only | `README.md` | 保留必要参考链接 | 已完成 |

## Goal 修订

- 最终风险分：原文分析 `25%`，模拟结果 `75%`。
- 第一版平台无关，不处理平台语言风格。
- 第一版不接入或下载任何外部评论数据，不实现数据导入脚本。
- 无 API 密钥时必须由 DEMO_MODE 跑通真实 Python 模拟、热度和持久化流程。

## 完成证据

- `python -m pytest -q`：26 项测试全部通过。
- 三个演示案例：改写前后均生成 14 条评论和 10 个发言 Persona；风险分别为 `中 → 低`、`高 → 低`、`高 → 低`，受众一致性全部通过。
- SQLite 审计：3 个项目、36 条 Persona、84 条评论、9 份报告成功写入并恢复。
- Playwright 页面审计：四步流程从输入运行到改写对比，无浏览器控制台错误，页面显示受众一致性通过。
- Streamlit 健康检查：服务器端口 `8502` 返回 `ok`。

