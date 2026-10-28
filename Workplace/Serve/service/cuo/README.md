# CuO · 氧化铜

基于 NapCat / OneBot、FastAPI、PostgreSQL 和模型网关的 QQ 群机器人。

## 目录

- `src/backend/Workflow`：接收、分析、路由和发送，由 `main.py` 衔接。
- `src/backend/Core`：任务队列、上下文、业务日期、结果、缓存与每日归档。
- `src/backend/Integration`：NapCat、PostgreSQL、模型网关和控制台接口。
- `src/backend/Function`：清谈录、周易、鸿爪录与众声录。
- `src/frontend`：管理控制台页面。
- `ops/tests`：规则、集成、控制台和图片处理测试。
- `ops/database`：业务数据库迁移。
- `ops/deploy`：systemd 服务原稿和部署路径模板。
- `var`：运行配置与数据占位，不包含真实生产内容。

## 本地环境与测试

需要 Python 3.12 及以上；当前服务器使用 Python 3.14。

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest ops/tests/test_rules.py -q
```

Windows 使用 `.venv/Scripts/python`。数据库集成测试需显式设置 `CUO_TEST_DSN`，必须指向独立测试库。

## Divine 固定解卦资料（readings-v1）

`hexagrams.json` 保存原文、64 卦固定卦义、卦题与主题；`readings.json` 以“本卦编号:动爻列表”为键覆盖 4096 种组合，无动爻以 0 表示，例如 `11:3` 是泰卦九三动、变临卦。每条记录保存主断辞、辅助断辞、完整解卦、卦题、主题、签语、应事兜底和福缘范围。

新卦从目录选取并保存完整快照。卦运方向与范围使用该记录的 fortune；解卦和签语不调用 AI。AI 只在真实候选聊天中生成与固定卦意相关的应事，没有相关证据时可以弃选，由程序输出不冒认经历的“今日一应”。无素材时不调用模型。已保存结果直接返回原内容；未完成草稿保留既有卦运结算，继续生成时统一使用固定资料兜底和新模板。

目录初版标记 `initial_rule_composed`：64 卦卦义经固定编写，组合解释以主断辞选择规则、爻位和吉凶规则编排，含泰九三等专项释义；不是 4096 篇逐条人工校订的古文注解。尤其复杂条件断辞与多爻变化仍须逐条校订。编辑 readings.json 可直接修订每个组合的内容和结算；重新生成会覆盖这些修改，需先保留校订内容。生成命令：在项目根目录设置 `PYTHONPATH=src/backend`，运行 `python -m ops.build_readings`。

新模板：本卦 → 变卦 | 卦题（无变化省去箭头与变卦）；塔罗与图片；主断辞；解卦；应事；卦运与福缘；收尾签语。重复占卜仍另扣 2 点。改动不涉及数据库结构或生产部署。

## 部署配置

1. 参考 `ops/deploy/deploy.env.example` 指定代码、Python 环境和生产配置位置。
2. 按 `src/backend/.env.example` 和 `src/backend/config/groups.example.json` 创建服务器专用配置，保存到 `var/config`。
3. 为业务库创建专用数据库角色，并显式运行 `ops.database.scripts.migrate`。
4. 通过 systemd 原稿部署，入口为 `Workflow.main:app`。修改路径时同时调整服务单元。

Python 依赖见 `pyproject.toml`；第三方程序位于根目录 `software` 的对应占位目录，需另行安装。
原始消息与持久任务保存在 PostgreSQL；众声录读取标准化 JSONL 缓存。业务日期按北京时间凌晨四点切换。

当前导出的是服务器回退后的实际代码，尚未包含讨论中的 Console 模型下拉选择改造。
