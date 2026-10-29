# CuO 源码与配置约定

本文件记录已确认的管理原则和源码格式。现已推广至 backend 的运行配置及 AI 调用点。运行配置由小配置装配，纯规则代码无需建立空配置。

## 一、管理原则与优先级

1. **去敏优先。** 群号、真实消息记录、昵称、密钥及其他私有运行信息不得提交到代码仓库或混入公开文档、测试样本和模板。运行配置与运行数据留在私有目录，示例使用空值、占位符或明确的合成数据。提交前检查实际待提交内容；Git 忽略规则不能清除已经被跟踪的敏感文件。
2. **方便管理。** 配置应便于前端查找、展示、校验和修改；字段应说明用途、类型、范围、是否敏感及生效方式。密钥按只写字段处理，不回显真实值，不写入日志或报错内容。
3. **结构化。** 配置按源码归属组织，同一配置值只维护一处，字段名称能独立表达所属模块及具体用途。

真实聊天记录和昵称等业务数据不因去敏而全部搬入配置文件；它们仍存放在私有业务数据库或运行数据目录中。配置中只保存必要的运行设置与资源位置。

## 二、目录与文件职责

以下路径均以 CuO 应用根目录为基准，即同时包含 `src`、`ops`、`var` 的目录。

| 位置 | 职责 |
| --- | --- |
| `src/backend` | 后端源码、配置读取与校验代码 |
| `src/frontend` | 前端源码 |
| `var/config` | 私有运行配置，保存实际值，不提交 Git |
| `var/config/config_index.json` | 配置索引，只记录字段、所属小配置、使用者和管理元数据，不重复保存实际值 |
| `ops/config-templates` | 可提交的安全配置模板及索引模板，不包含真实私有信息 |

小配置按照源码在 CuO 应用根目录下的相对目录创建，名称为 `<代码文件名去掉扩展名>_config.toml`：

```text
src/backend/Function/divine/son_function/AI_divine.py
var/config/src/backend/Function/divine/son_function/AI_divine_config.toml
```

每个源码文件都检查配置依赖；只有确实需要独立配置的文件才创建小配置。纯规则文件不创建空配置文件。共享配置只维护一份，由索引列出使用者。

总索引是唯一字段结构定义，保存位置、说明、类型、范围、敏感属性及模型结构。Core 在启动时读取它，用于校验小配置并提供前端字段定义；真实值只写在小配置中。

## 三、命名约定

模块专用配置字段使用小写下划线命名，采用“模块＋调用点或具体用途＋参数含义”。名称要说明单位和边界，避免只有 `timeout`、`attempts`、`files` 等脱离上下文难以理解的名称。

| 示例 | 含义 |
| --- | --- |
| `divine_ai_request_timeout_seconds` | divine 应事 AI 单次调用总超时，单位秒 |
| `divine_ai_request_attempt_limit` | 最多调用次数，包含第一次 |
| `divine_ai_response_max_tokens` | 模型输出 token 上限 |
| `divine_candidate_excerpt_character_limit` | 每段候选聊天摘录的字符上限 |
| `divine_tarot_card_image_files` | 塔罗牌名称与图片文件名对应表 |

内存配置对象使用大写下划线名称，例如 `DIVINE_AI_CONFIG`、`DIVINE_TAROT_IMAGE_CONFIG`。

配置命名不应擅自改变外部协议或既有持久化字段。例如模型 API 请求仍使用 `max_tokens`，已保存占卜快照中的 `repeat_cost` 不因配置重命名而改变。

## 四、Python 文件顶部格式

每个文件最前面使用英文半角三单引号 `'''` 写模块说明，不使用逐行 `#`。说明包含文件用途，以及“配置字段名＋中文用途”。共享配置字段也按相同格式列出。

顶部不重复列配置文件位置，不展开长调用链，不填写真实值。具体路径在配置加载代码及总索引中查看。说明结束后空一行，与 import 部分分开。

```python
'''
本文件用途：根据聊天候选素材生成应事内容。

配置字段：
divine_ai_enabled                    启用应事 AI；关闭时使用固定应事内容
divine_ai_api_key                    此调用点专用的 LiteLLM 虚拟 Key
divine_ai_base_url                   LiteLLM 接口地址
divine_ai_model_name                 LiteLLM 中配置的模型名称
divine_ai_request_timeout_seconds    单次调用总超时
divine_ai_request_attempt_limit      最多调用次数，包含第一次
divine_ai_response_max_tokens        模型输出 token 上限
divine_ai_evidence_prompt_file       应事提示词文件
divine_ai_advice_min_characters      应事内容最少字符数
divine_ai_advice_max_characters      应事内容最多字符数
'''

# xxxx

from Core.module_config import DivineAIConfig, load_module_config

DIVINE_AI_CONFIG = load_module_config(
    "src/backend/Function/divine/son_function/AI_divine_config.toml",
    DivineAIConfig,
)
```

没有独立配置的文件，在“配置字段”下写“无独立外部配置。”；若通过其他模块使用配置，列出实际字段名及用途。顶部说明、加载代码、配置字段和索引应同步更新。

## 五、AI 接入约定

- 每个 AI 调用点分配独立的 LiteLLM 虚拟 Key。同一模块有多个调用点时，分别配置，便于 LiteLLM 按 Key 统计用量。
- CuO 不额外设置 `usage_id`。真实 Key 只保存在私有小配置中，源码、说明、索引与模板不保存真实 Key。
- 调用点使用自己的接口地址、模型名称和专用 Key，不悄悄回退到共享 Key，也不使用 LiteLLM 管理主密钥进行业务调用。
- 模板连接参数留空，AI 默认关闭。填入有效配置并启用后才能调用模型；启用时缺少必要配置应明确报错，错误不回显密钥。
- Divine 应事 AI 关闭或没有候选素材时使用固定应事内容；客户端在调用结束后关闭，失败重试也使用同一调用点配置。

## 六、读取、生效与前端管理

配置在启动加载模块时读取并校验，之后使用内存配置对象。启动不会重写小配置文件；正常业务调用不重复读取 TOML 或查总索引。

默认配置根目录是应用根目录下的 `var/config`，可用 `CUO_CONFIG_ROOT` 显式指定。配置内的相对资源路径相对于 CuO 应用根目录解析，不依赖执行命令时的工作目录。

当前 divine 试点统一采用修改配置后重启生效。缺失配置不自动回退到模板。首次部署从安全模板建立私有配置，不覆盖已有运行配置。

前端管理应读取结构化字段定义和索引元数据，不解析 Python 顶部说明。后续编辑接口应按字段类型、范围及敏感属性校验，保存到对应私有小配置，并明确提示生效方式。当前已提供配置索引元数据，尚未实现新的前端编辑接口。

## 七、当前试点边界

当前改造覆盖 divine 及必要的配置读取、校验、模板和测试。Divine AI 已使用独立 LiteLLM 配置；共享数据库等仍沿用现有配置体系。配置读取与校验已迁入 `Core/configuration.py`、`Core/module_config.py`，共享运行设置由 `Core/settings.py` 装配；原 `src/backend/config` 目录已移除。

本约定不代表已完成全仓库去敏审计、生产配置填写、LiteLLM 虚拟 Key 创建或生产部署。推广到其他模块前，先验收 divine 的效果。

## 后端推广状态

新增 16 份模块配置，涵盖数据库连接与群映射、NapCat、启动、消息发送、归档、控制台、聊天、总结范围、总结正文、图片识别、意图识别、昵称分词、工作簿和重试。原 divine 配置继续保留。

其他五个 AI 调用点分别使用专用 LiteLLM Key；不再从共享 `ctx.model` 调用。模板默认关闭 AI，地址、模型、Key 留空，必须在私有配置填写后启用。当前没有创建生产虚拟 Key。

前端运行设置页已连接 `/console/api/configuration` 模块配置接口。敏感字段不回显；留空保留原值，更新时校验版本，保存后重启生效。旧 `/console/api/settings` 写入接口明确停用，不再写 `console-settings.json`。新增接口覆盖新增模块与 divine；所有字段结构均由配置根目录中的 `config_index.json` 提供。

`Settings.load` 已改为读取模块 TOML，不再读取旧环境配置或群 JSON。生产切换前需将旧值逐项迁移到私有小配置；当前空模板不构成可启动的生产配置。不得直接覆盖原有私有配置。数据库集成验证需要独立测试库。

## 同目录部署示例

每份 `var/config` 下的运行 TOML 都有同目录的 `*.example.toml`。示例包含安全默认值，允许提交；实际 `*_config.toml` 继续被 Git 忽略。

首次部署将 `xxx_config.example.toml` 复制为 `xxx_config.toml`，填写私有参数，不覆盖已有配置。超时、重试、资源相对路径等使用示例默认值；Key、群映射、数据库连接、机器人账号、管理凭据和私有昵称词表留空。AI 默认关闭，配置专用 LiteLLM Key 后再启用。空的必需部署参数须补齐才可启动。

示例文件不会被运行时自动加载，也不作为缺失配置时的回退。

部署时须同时提供不含真实值的 `config_index.json` 和各私有小配置；安全索引模板在 `ops/config-templates/config_index.json`。不存在索引时启动报错，不回退到另一套源码字段清单。

## 配置根目录映射

`var/config` 与 CuO 应用根目录对应，一级目录为 `src`、`ops`。例如 `src/backend/Function/divine/divine.py` 对应 `var/config/src/backend/Function/divine/divine_config.toml`；将来 ops 脚本的配置位于 `var/config/ops` 下的对应路径。当前没有需要迁移的 ops 小配置，保留目录占位。

`config_index.json` 是配置根目录的总索引，仍放在根目录。`CUO_CONFIG_ROOT` 仍指向 `var/config`，不要改为 `var/config/src`。部署模板采用相同目录层级。小配置内部的资源相对路径仍以 CuO 应用根目录为基准。

已有部署需将私有 `var/config/backend` 移至 `var/config/src/backend`，并同步新版索引。保留原值，不用示例覆盖真实配置。
