# 消息接收 receive

## 1. 模块综述

代码文件使用已确定的 `receiver.py`，与 `Main.py` 同级；入口函数为 `receive_event()`。它负责接收 NapCat 事件、保存消息、检测昵称变化和真实 @、建立任务日志。它不调用 intention 或其他业务模块，不调用 AI，不发送回复。

本文为实现规格，尚未编写业务代码或完成 NapCat 联调。传输方式、字段缺失和特殊事件的适配以真实样本验收；已确定的数据约定以 `../../府库/实现-府库.md` 为准。

```text
NapCat → receiver.py → 府库：messages / members / log
                              ↓
                         Main 逐个执行
```

业务任务串行，接收和入库持续进行。Main 等待 DS 回复时，receiver 仍须接收新消息。

## 2. 代码结构

```text
Main.py
receiver.py
database/
├── database.py
├── cache.py
└── initialize.py
Infrastructure/
└── onebot_client.py
```

Main 启动 FastAPI 服务及业务 worker，注册 receiver 的连接入口，不分别启动两套程序。receiver 使用府库的 `PGsql_read`、`PGsql_write` 和共享事务；接收后的缓存由府库更新。

传输初稿采用反向 WebSocket，路由 `/onebot/ws`。连接验证后保存当前 self_id，事件 self_id 必须与配置的机器人一致。鉴权 token 只在后端配置，日志不打印 token。

## 3. 标准 IO

### 3.1 输入

```python
async def receive_event(event: dict, received_at: datetime) -> dict:
    ...
```

event 是已解析的完整协议事件，received_at 由接收入口生成，必须带时区。不接受由用户文本指定的群号、用户 ID 或 opt。

普通群消息输入示例（合成，不是已采集的 NapCat fixture）：

```json
{
  "post_type": "message",
  "message_type": "group",
  "self_id": 10001,
  "group_id": "<group_id>",
  "user_id": "<user_id>",
  "message_id": 7654321,
  "time": 1792891200,
  "sender": {"user_id": "<user_id>", "card": "<nickname_card>", "nickname": "群友甲"},
  "message": [
    {"type": "at", "data": {"qq": "10001"}},
    {"type": "text", "data": {"text": " 无事退朝"}}
  ]
}
```

使用消息段数组模式。text、at、reply、image 等段结构参考 [NapCat 消息格式文档](https://napneko.github.io/develop/msg)；未知段保留，不据此拒绝整条消息。

### 3.2 返回

返回内部接收结果，不作为 QQ 回复：

```json
{
  "status": "accepted",
  "message_row_id": 321,
  "task_ids": ["改名任务UUID", "消息请求UUID"],
  "cache_status": "ready",
  "reason": null
}
```

status 为 accepted、duplicate、ignored、invalid。数据库失败抛出明确存储异常，不能返回 accepted。cache_status 为 ready、dirty、not_applicable；PG 提交后缓存失败仍为 accepted，并标 dirty。

## 4. 事件分流

WebSocket 读循环先区分动作回执和上报事件，不能把所有 JSON 都当聊天：

| 内容 | 行为 |
|---|---|
| 带已登记 echo 的动作回执 | 交 onebot_client 唤醒对应等待者，不写聊天记录 |
| 心跳、连接状态 | 更新连接状态，不创建用户任务 |
| 允许群的普通群消息 | 执行本文消息流程 |
| 本机器人群消息回显 | 保存或补全记录，不创建请求和改名任务 |
| 非允许群、私聊 | ignored，不触发功能 |
| 通知类事件 | 已实现的适配器处理；未支持则记录类型，不猜字段或伪造消息 |
| 非法 JSON、缺失关键身份 | invalid，记录脱敏错误，不调用业务 |

网络读循环与按群入库处理解耦，动作回执不能排在用户任务后等待，否则 Main 的发送请求会等待自身队列。初稿使用有界入站队列，最多1000条；满时关闭连接并报警，不静默丢掉某一条继续运行。协议是否自动补发需实测，不能宣称连接重建即可恢复全部丢失消息。

同一群的入站处理按接收顺序串行；其他业务仍由 Main 单 worker 执行。仅接收入库流程可与模型请求同时进行。

## 5. 身份、时间与正文提取

1. 检查 group_id 在后端允许列表中，self_id 与登录账号匹配，user_id、message_id 存在。
2. ID 统一转换为字符串，不经浮点数。sender.user_id 若存在但与事件 user_id 不同，标记 invalid，不猜哪个正确。
3. 有有效 time 时将 Unix 时间转换为带时区时间；time 缺失才使用 received_at，并记录 time_source=received。time 存在但格式非法时拒绝，不能悄悄改成当前时间。
4. business_date=`(北京时间 sent_at - 4小时).date()`。message 的任务 triggered_at 保留原 sent_at。
5. nickname 优先非空 sender.card，再取 sender.nickname。两者都缺失时保留已有 members.nickname；新成员使用明确占位“群友”，并标 nickname_observed=false，不生成虚构改名。
6. segments 保留完整消息段；messages.text 按顺序拼接 text 段原文。segments 是完整信息来源，text 不是图片、@、回复的替代品。
7. 给 Main 的 text 使用单独派生值：移除指向机器人自身的 at 段；其他 at 显示为已知名字或 `@用户ID`；非文本段用 `[图片]`、`[表情]`、`[回复]` 等占位，详细数据仍放 params/消息记录。不得把非文本内容默默当成用户没说话。

仅 @ 无其他内容的任务 text 为空，仍入队，由 intention 返回 empty_input。仅 @ 加图片不能在这里调用识图，应交下游明确处理；当前 conversation 不支持时返回不支持提示，不能编造图片内容。

原事件保存在 messages.processing.raw_event，派生值存在 processing.receiver，字段含 request_text、at_bot、time_source、nickname_observed、receiver_version。后续更新 processing 的其他分支必须合并，不能覆盖原事件。

## 6. @ 判定

只检查顶层 message 数组中的真实 at 段：

```text
type == at 且 str(data.qq) == 配置的机器人 self_id
```

- 普通文本“@氧化铜”、机器人名字、引用内的 @、转发内嵌的 @ 不触发。
- `qq=all` 不当作专门 @ 机器人。
- 一条消息多次 @ 机器人只创建一个 message 任务。
- 发言 user_id 等于机器人自身时，即使带 at，也不触发请求。
- 原始 at 段留在 messages.segments，不为提取请求正文而修改原始事件。

## 7. 昵称观察与首次记录

昵称检测先查 members，再写当前新值；不能先覆盖旧名后进行比较。

| 状态 | 行为 |
|---|---|
| 没有成员记录，有可信昵称 | 创建 members 基础行，fortune=0、slots六个null；建立 memento 初创任务 |
| 有记录，昵称未变 | 不建立改名任务 |
| 有记录，有可信新昵称且不同 | 保存旧新昵称快照，建立 memento 改名任务，更新当前观察昵称 |
| 昵称字段缺失 | 不视为改名，不覆盖有效旧名 |
| 本机器人回显 | 不建立 memento 任务 |

display_name、slots、sheet_name、fortune 不由 receiver 的改名更新覆盖。首次记录的初创备注及 Excel 操作由 memento 执行，receiver 不写 Excel。

改名任务 params 保存 old_nickname、new_nickname、is_initial、observation_message_id、observation_row_id、observed_at。memento 必须使用任务保存的观察快照；由于 receiver 已更新 members.nickname，不能在执行时仅比较当前 members.nickname 与 new_nickname 后错误跳过任务。

乱序消息规则初稿：读取同用户历史 messages 中已验证昵称观察的最大 `(sent_at,id)`，与本条比较；较旧事件仍存消息，但不回退 members.nickname，不生成迟到的伪改名。同秒用接收记录 id 稳定排序。不能拿 members.updated_at 判断昵称新旧，因为福缘结算也会更新该时间。

仅首次创建空占位成员但没有可信昵称时，不建初创任务；后续首次有可信昵称且没有初创/改名日志、未绑定槽位时再建立初创。已有工作表的导入绑定由鸿爪录处理，不通过昵称猜测。

## 8. 原子入库和任务建立

在同一群 schema 内使用一个事务：

```text
BEGIN
→ 对 message_id 去重并插入 messages
→ 按本条观察时间判断成员昵称是否有效、是否变化
→ 必要时创建或更新 members 的观察昵称
→ 需要初创/改名时插入 memento 类型 log
→ 真实 @ 且非自身回显时插入 message 类型 log
COMMIT
→ 府库提交后更新对应业务日期缓存
→ 通知 Main 有新任务（唤醒信号可丢，任务不能只存信号里）
```

普通消息即使没 @ 也保存；昵称变更同样不要求 @。一条消息同时改名和 @：一条 messages、两条 log。改名失败不能阻止独立的请求任务执行，不属于 multiple_intents。

message_id 在当前单机器人群 schema 内唯一。重复事件返回 duplicate，不重新覆盖成员、不重新建任务；如果后续回显用于补充 generated_by，使用受控补全流程，不当作新任务。

数据库唯一冲突只能在确认已有相同消息时转为 duplicate。其他异常全部回滚。PGsql_write 通过 transaction 共享当前事务；不能拆成三次独立提交。

### 8.1 日志字段映射

| log 字段 | 消息请求任务 | 改名任务 |
|---|---|---|
| task_id | 稳定 UUID | 另一个稳定 UUID |
| request_type | message，待 intention 更新 | memento |
| user_id / message_id | 原发送者和消息ID | 相同 |
| triggered_at | 原 sent_at | 本次有效观察时间 |
| created_at | received_at | received_at |
| business_date | 原业务日期 | 原业务日期 |
| original_text | 原 text 段正文 | 原 text 段正文 |
| params | request_text、消息行id、segments引用、入队排序信息 | 旧新昵称快照、初创标记、入队排序信息 |
| status / business_status | pending / pending | pending / pending |
| step | queued | queued |

初稿 task_id 采用 UUID5，固定命名空间 `75234efe-7d82-4b2d-a6ae-65078672cff8`，名称为规范 JSON 数组 `[self_id,group_id,message_id,trigger_type]`，JSON separators 固定为逗号和冒号。重复上报取得同一任务ID，改名与请求因为 trigger_type 不同而不同。唯一约束仍是最终保障。

### 8.2 排序

params.queue 保存 batch_seq 和 order；batch_seq 为该 messages.id，改名 order=0，请求 order=1。同群入站串行并在同一事务写完两个任务，Main 按 created_at、batch_seq、order、task_id 取任务，不能仅按随机 UUID 排序。无消息的系统任务由 Main 使用自身入队时刻及内部顺序，排序规则必须统一，不能插进同一批两条任务之间。

## 9. 媒体、回显与缓存

> 路径更新：今日messages.jsonl位于Function/summary/cache/{group_id}/{business_date}/，由府库统一写入；替代下文旧的代码根data路径。receiver不另建一份今日消息缓存，其他模块也通过府库访问同一副本。

receiver 对图片、语音、视频和文件保留原始段及定位信息，在 processing.media 中标 pending，不调用模型。媒体下载/描述由后续独立任务处理；首期文本闭环即使尚未接入媒体任务，也必须保存段，不假装支持识图。URL 过期的刷新机制另行 NapCat 联调。

本机器人回显保存消息，使用 Main 发送回执中的 message_id 关联原任务，补 generated_by。回显先于回执到达时先标自身消息、来源待匹配，回执落库后补全。自身回显始终不触发业务，来源暂缺也不能递归回复自己。

文件缓存仅由府库提交后维护：今日消息写到 data/{group}/{business_date}/messages.jsonl；迟到消息写入其原日期或标旧日缓存失效。04:00 切换不停止入库，也不把上一日任务强行转到新日。

缓存失败不重新接收或重新执行业务，返回 accepted/cache_status=dirty；下一次读取回退 PG。PG 失败不能先写缓存再宣布成功。

## 10. 错误处理

| 情况 | 接收层处理 |
|---|---|
| 连接鉴权或 self_id 不匹配 | 拒绝连接或事件，不入库 |
| 非允许群或私聊 | ignored |
| 缺失群号、用户、消息标识，或非法消息数组 | invalid，记录脱敏诊断 |
| 文本为空但有有效段 | 保存；是否触发由真实 at 决定 |
| 重复消息 | duplicate，无新任务 |
| 数据库失败 | 回滚，抛出错误；连接层报告接收失败 |
| PG 成功、缓存失败 | accepted，缓存 dirty |
| memento 后续失败 | Main 记录该任务失败，继续请求任务 |

普通调试日志只记录类型、消息标识和错误码，不打印 token、完整敏感配置。接收失败不直接向群里发送错误，因为发送职责统一属于 Main。

协议不保证重放时，数据库断连、进程崩溃和入站队列溢出都可能产生缺失时段；记录健康状态并在恢复后核查，不宣称端到端绝不丢消息。

## 11. 验收样例

| 输入 | messages | log |
|---|---|---|
| 已知成员普通文字，昵称未变 | 新增1条 | 不新增 |
| 新成员普通文字，有可信名片 | 新增1条 | 初创memento 1条 |
| 已知成员改名后普通文字 | 新增1条 | memento 1条 |
| 昵称未变，真实 @机器人 | 新增1条 | message 1条 |
| 改名且真实 @机器人 | 新增1条 | memento在前，message在后 |
| 同一消息重复上报 | 不重复 | 不重复 |
| 文本含“@氧化铜”但无at段 | 新增1条 | 无请求任务 |
| at全体、at其他用户 | 新增1条 | 无请求任务 |
| 引用/转发内部at机器人 | 新增1条 | 无请求任务 |
| 机器人自己发送的消息 | 新增或补全1条 | 不触发 |
| 旧昵称事件迟到 | 新增1条 | 不回退成员状态 |
| PG提交前失败 | 不新增 | 不新增 |
| PG提交后缓存失败 | 已保存 | 已保存，正常可执行 |

额外验证：两个接收事件按顺序执行，前一任务尚未处理时后一消息再次使用新昵称不会重复产生改名；同日消息处理跨过04:00保持原业务日期；Main等待模型时仍能存入下一条消息；发送动作回执不会被业务队列阻塞。

## 12. 实现顺序

先采集脱敏真实事件并确认数组格式 → 实现身份、时间、正文提取 → 实现五表事务和重复消息处理 → 实现昵称观察与任务快照 → 实现真实at判定与入队 → 接府库缓存 → 接反向WebSocket和回执分流 → 联调 Main。

本次只补文档，不代表以上样例已通过。正式编码时先用合成fixture完成单元测试，再以真实NapCat数据验证字段和回显行为。
