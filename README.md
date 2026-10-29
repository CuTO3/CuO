# 氧化铜 CuO

氧化铜（CuO）是一个 QQ 群机器人项目：群消息经 NapCat 上报到后端，后端解析意图、串行排队执行，再把结果发回群里。仓库同时保存产品需求文档与各模块的设计实现文档。

## 功能范围

| 模块 | 说明 |
|---|---|
| 周易 | 每日占卜：六爻与卦象、塔罗、校对过的《周易》原文、约 30 字生活化解读，末尾给出卦运与福缘 |
| 众声录 | 群聊总结：按事件分段，保留原话与接梗，保存历史并支持按日期查询 |
| 鸿爪录 | 群名片变迁记录：本地分词、六槽对齐、写入工作簿并上传群文件 |
| 清谈录 | 普通聊天：人格设定与对话风格 |
| 府库 | 数据层：群 schema 下的五张表，统一任务日志、缓存与事务 |
| 大千录 | Minecraft 开服，本期不实现 |

## 目录结构

```text
Requirement/        产品需求（白皮书）
Solution/           设计实现文档（氧化铜主流程、意图识别、消息接收与发送、周易、众声录、鸿爪录、府库、清谈录人设）
Workplace/
└── backend/        后端源码
    └── console/    Web 控制中心静态资源，由 FastAPI 托管
```

后端技术栈：Python 3.12、FastAPI、PostgreSQL、NapCat（OneBot 11 反向 WebSocket）、DeepSeek。

## 本地运行

```bash
cd Workplace/backend
python -m venv .venv
.venv/Scripts/pip install -e ".[test]"      # Linux 用 .venv/bin/pip
```

1. 当前应用位于 `Workplace/Serve/service/cuo`。将应用 `var/config` 下各 `*_config.example.toml` 复制为同目录的 `*_config.toml`，不要覆盖已有配置。
2. 在小配置中填写数据库、群映射、各调用点的 LiteLLM 配置和 NapCat 参数，真实值不提交。配置根目录通过 `CUO_CONFIG_ROOT` 指定，默认为应用的 `var/config`。详见应用 `src/README.md`。
3. 初始化数据库：`.venv/bin/python -m scripts.migrate`。
4. 启动：`.venv/bin/python -m uvicorn Main:app --host 127.0.0.1 --port 8080`。

systemd 单元与部署说明见 `Workplace/backend/Test/deploy/`。

## Web 控制中心

已部署简约浅色管理台，提供运行总览、任务筛选、成员显示名称修改、内容档案和运行参数管理。访问与维护见 [控制中心说明](Workplace/backend/console/README.md)。服务器继续监听 `127.0.0.1:8080`，通过 SSH 将其映射至本机 9080 后访问 `/console/`；登录使用现有 `ADMIN_TOKEN`。

## 测试

```bash
cd Workplace/backend
.venv/Scripts/python -m pytest Test/tests/test_rules.py -q
```

`Test/tests/test_rules.py` 是纯规则测试（卦象查表、取辞、概率、分词、长文本切分），不需要数据库；`test_integration.py` 与 `test_summary_cutoff.py` 需要独立的 PostgreSQL，通过 `CUO_TEST_DSN` 指定。

## 隐私与数据

- 仓库不包含真实群号、QQ 号、群名片或群聊原文。文档中的群号、成员昵称统一写成 `<group_id>`、`<成员A>` 一类的占位符，示例聊天为合成内容。
- 真实 NapCat 抓包样本、鸿爪录运行工作簿、本地昵称保护词表 `Function/memento/nickname_dictionary.txt` 都在 `.gitignore` 中排除；词表格式见 `Function/memento/nickname_dictionary.example.txt`。
- 模型密钥、OneBot token、数据库口令只保存在部署环境的配置文件里，日志不记录这些内容。

## 开发状态

`Requirement/` 与 `Solution/` 中的条目分为“已定”和“初稿方案”，初稿部分仍会逐项调整。代码与文档并行推进，NapCat 字段、图片缓存、文件上传等行为需要真实环境联调，文档未把待验证内容写成已完成结论。
