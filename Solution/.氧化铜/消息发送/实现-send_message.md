# 消息发送

## 1. 模块综述

`send_message.py` 是 Main 统一调用的发送子函数，负责把一个已保存的动作转换为 NapCat 请求并返回执行结果。支持发送群文字和上传群文件。conversation、summary、divine、memento 均不得自行调用 NapCat。

Main 负责动作顺序、发送前后日志和恢复；发送子函数负责输入校验、协议转换和回执判断，不决定重试，不重新执行业务，不修改福缘或 Excel。

未实现。本稿明确执行路径，实际 NapCat 回执、文件可见路径、超时和长消息限制仍需联调。官方列有 `send_group_msg` 和 `upload_group_file` 支持：[NapCat 请求接口](https://napneko.github.io/develop/api)。应用动作格式是本项目约定，不是直接透传的 OneBot 请求。

## 2. 代码结构

```text
Main.py
receiver.py
Function/
└── send_message/
    └── send_message.py
Infrastructure/
└── onebot_client.py
database/
```

- send_message.py：动作参数检查、文字切分准备、文件校验、单动作发送及结果归类。
- onebot_client.py：连接、请求序列化、echo 与等待者映射、超时、断线通知。
- receiver.py：网络回执分流给 onebot_client；回执不进入业务任务队列。
- Main.py：读取 log.result.actions，逐个调用发送函数并更新日志。
- 府库：日志事务及查询，不增加 outbox 表。

## 3. 标准 IO

### 3.1 业务模块返回 Main

纯文字：

```json
{
  "status": "ok",
  "result_id": "业务结果UUID",
  "actions": [{"type": "send_message", "text": "生成的回复"}],
  "error_code": null
}
```

鸿爪录：

```json
{
  "status": "ok",
  "result_id": "改名记录UUID",
  "actions": [
    {"type": "upload_file", "path": "鸿爪录工作簿的绝对路径", "name": "鸿爪录.xlsx"},
    {"type": "send_message", "text": "鸿爪已录，《鸿爪录》已更新。"}
  ],
  "error_code": null
}
```

业务模块不得返回目标群号、任意 NapCat API 名称或脚本。目标群来自 Main 的任务上下文。actions=[] 表示没有需要发送的内容，Main 可直接结束任务。

### 3.2 Main 准备动作

发送前调用本模块的 prepare_actions(group_id, task_id, actions)，不产生网络请求。它校验全部动作、切分长文字、为文件建立稳定快照，返回规范化动作列表；任何动作校验失败则整个列表不开始发送。

规范化动作示例：

```json
{
  "action_id": "任务UUID:0:0",
  "type": "send_message",
  "payload": {"text": "准备好的回复"},
  "status": "pending",
  "attempt": 0,
  "receipt": null,
  "error": null
}
```

action_id 为 `task_id:原动作序号:分段序号`，从0开始。文件分段序号为0；同任务恢复读取已保存列表，不重新生成序号、重新切分或更改正文。

### 3.3 单动作发送函数

```python
async def run(group_id: str, task_id: str, action: dict) -> dict:
    ...

outcome = await send_message.run(
    group_id=request["group_id"],
    task_id=request["task_id"],
    action=action,)
```

只接受 Main 已标记 sending 的一个规范化动作，不接受任意原始协议对象。task_id、action_id 及 group_id 必须与日志一致。

```json
{
  "action_id": "任务UUID:0:0",
  "status": "sent",
  "receipt": {"message_id": "7654321"},
  "error": null
}
```

status 仅为 sent、failed、unknown。failed 的 error 包含 code、message、safe_to_retry；unknown 一律禁止自动重发。函数不直接把 log 标记 completed；由 Main 结合全部动作判断。

## 4. 完整执行路径

```text
业务模块完成并保存结果
→ Main 调用 prepare_actions
→ Main 将规范化 actions 写入 log.result，提交成功
→ 依序读取动作
→ 已 sent：跳过
→ pending 或已批准重试：写 sending、attempt、echo，提交
→ 调用 send_message.run
→ onebot_client 发出请求并等待 receiver 分流的回执
→ Main 将 sent/failed/unknown 与回执写入 log
→ sent 才继续下一动作
→ 全部 sent 后将任务标记 completed
```

发送前写日志失败则不发送。发送成功但回执状态写库失败，停止后续动作；不能重做当前发送。恢复时若数据库仍为 sending，则按结果不明处理，人工核对或可靠回执确认后继续。

Main 只能更新本任务的动作字段，不能用过期的完整 result 覆盖刚保存的 summary_id、divination_id 或昵称历史。写入采用事务内重新读记录、修改对应 action_id、提交；不持有数据库事务等待网络。

## 5. 文字发送

### 5.1 校验与协议转换

text 必须是非空字符串，纯空白为 invalid_text。保留原文换行和标点，不再调用 AI 改写。

使用 OneBot 消息段数组，将正文封装为单个 text 段。即使正文包含 `[CQ:...]`，也只是文字，不能解析成 @全体、图片或其他动作。初期不提供任意段透传、私聊、撤回和群管理功能。

调用 `send_group_msg`，参数包括可信 group_id 和 text 段数组。内部 ID 使用字符串；协议需要整数时由适配层在数字格式验证后转换，不用浮点数。

初稿不自动 @ 请求者，不增加回复引用，避免每段长消息都通知用户。以后需要时增加明确的结构化选项，不从 AI 正文解析控制命令。

### 5.2 长消息切分初稿

每段显示文本上限1500个 Unicode 码点；多段时正文上限1480，预留20个字符写 `(1/3)\n`。这是应用初稿阈值，不是已验证的 QQ 协议上限。

正文≤1500时保持单段。超过时，在接下来1480字符窗口中优先找最后一个空行，其次最后一个换行；没有则按字符边界切开。分隔符归前段，不删除字符；每次切分必须至少消费1个字符。完成后添加序号，验证每段实际长度≤1500；预留空间不足则报配置错误，不截断内容。

准备阶段一次性生成所有段，保存其正文和序号。恢复不能根据新配置重新切分，否则已发第1段与重算第2段可能重复或漏字。

各段按顺序发送，一段失败就暂停后续段。序号仅用于用户阅读，不能作为发送成功证据。

## 6. 文件上传

> 路径更新：依据Main文档2.1节，待发送快照放在独立永久数据根下的groups/{group_id}/outgoing/{task_id}/{action_index}/，生产根规划为/serve/data/cuo。下文旧data/{group_id}/outgoing写法由此替代。Function/send_message/cache只保存可重建的临时校验数据，不作为未完成上传的唯一副本。

### 6.1 文件快照

path 必须是由业务代码产生的绝对路径，且处于配置允许的输出目录；不能直接上传聊天里任意给出的路径。拒绝目录、缺失文件、符号链接解析后越出允许目录的文件。name 只允许文件名，不含路径分隔符和控制字符。

prepare_actions 将文件复制到 `data/{group_id}/outgoing/{task_id}/{原动作序号}/{name}`，计算 SHA-256，并将 snapshot_path、sha256、byte_size、name 保存为 payload。复制完成后校验快照与复制时源文件内容一致；准备过程失败不生成可发送动作。

该目录属于待发送文件，不属于04:00清空的今日消息缓存。源鸿爪录后续改变不会影响已经排队的快照。重试前再次核对快照哈希，缺失或变化返回 file_snapshot_invalid，不能拿当前最新工作簿冒充旧任务文件。

快照至少保留到任务 completed 且确认无恢复引用；具体保留天数另由清理配置管理，初始化函数不得删除未完成任务的快照。

### 6.2 NapCat 可见路径

`upload_group_file` 的 file 参数必须指向 NapCat 能访问的位置。初稿要求 Python 与 NapCat 共用上传目录：同机直接使用共享绝对路径，容器或不同路径通过配置的本地根目录→NapCat挂载根目录映射。

没有共享目录映射时返回 upload_path_unavailable，不把 Python 机器上的路径直接当作远程存在。远程文件传输不是隐含功能，需单独接入后再启用。

上传 name 使用“鸿爪录.xlsx”等业务显示名。不能自动删除旧群文件或假设同名上传会覆盖；同名行为以联调结果记录。成功回执不一定含 file_id，允许 receipt 保留实际返回字段，不能伪造外部文件编号。

### 6.3 上传后通知

只有 upload_file 动作为 sent，才执行后续 send_message。“上传失败但仍发送已更新”属于验收失败。

上传已成功、通知失败时只恢复通知；通知完成后任务才 completed。文件上传是否会额外产生群提示由 QQ 决定，本项目预制通知是一项独立动作。

## 7. 回执和超时

每次尝试使用唯一 echo：`action_id:attempt`。onebot_client 在请求发出前登记等待者；receiver 收到相同 echo 的回执直接分发，不等待 Main 任务队列。

初稿网络等待上限20秒。上传或消息被接口接受但返回“异步处理中”不能直接标为 sent；适配器必须按该接口的明确完成回执处理。若没有可靠的完成查询或最终回执，则标 unknown，待联调建立验证方法。

| 情况 | 结果 |
|---|---|
| 发送前确认无连接，任何字节都未发出 | failed，可由 Main 重试 |
| 文件/群号/正文校验失败 | failed，不自动重试 |
| 明确完成成功回执 | sent，保存实际回执 |
| 明确拒绝且确认未执行 | failed，按错误类型决定可否重试 |
| 请求可能已发出后超时或断线 | unknown，不自动重试 |
| 回执格式无法判定、接口只返回受理状态 | unknown，不伪装成功 |

成功响应格式、retcode 含义和上传完成语义必须使用实际版本 fixture 验证，不能把所有非零代码都假设为“肯定没执行”。echo 只能关联请求，不是 NapCat 的幂等键；重复发送相同 echo 不保证 QQ 端去重。

迟到的匹配成功回执可以补全 unknown 为 sent；只允许更新该 action_id 对应尝试，不能覆盖另一次明确成功的结果。人工重发必须保留原尝试和批准记录，并说明可能重复，不抹去 unknown 历史。

## 8. 日志状态与恢复

动作初稿字段：action_id、type、payload、status、attempt、echo、started_at、finished_at、receipt、error、attempt_history。attempt_history 保存每次尝试的时间与结果，不含鉴权信息。

任务状态对应：

- 全部 sent，或 actions=[]：log.status=completed。
- 任一 failed：log.status=failed，step 指向失败动作；后续动作保持 pending。
- 任一 unknown，或重启发现遗留 sending：log.status=needs_review，后续动作不发送。
- 业务结果已生成：business_status 保持 completed，不因发送失败改成业务未完成。

恢复读取数据库原列表，只跳过 sent；failed 必须由 Main 根据错误码和策略批准，发送子函数本身不循环重试。任何发送恢复都不调用 conversation 重新生成、不调用 memento 重新写表、不调用 divine 重新结算。

本群中的任务和动作只能使用所属 schema 的日志。不能把另一群 action_id 或外部传入的文件动作拿来发送。

## 9. 回显与消息保存

发送成功后，Main 根据 message_id 与 receiver 保存的回显关联，将 messages.generated_by 标为 conversation、summary、divine 或 memento。映射来源为任务日志，不能从正文猜测。

回显先到时 receiver 先保存“自身消息、来源待匹配”，稍后补关联；回执先到时保留日志映射，等待回显。没有回显时仍保留发送日志，不伪造一个真实接收事件。

上传回执不是群聊天消息，不强制往 messages 插入文件记录；若 NapCat 后续上报文件消息，再由 receiver 保存。自身回显不能触发新的功能请求。

## 10. 标准错误码初稿

| code | 含义 | 自动重试 |
|---|---|---|
| invalid_action | 类型未知或动作结构非法 | 否 |
| invalid_target | 目标群未登记或与日志不符 | 否 |
| invalid_text | 空文本或文本类型错误 | 否 |
| file_snapshot_invalid | 文件缺失、哈希不一致或非法路径 | 否 |
| upload_path_unavailable | NapCat 无可用共享路径映射 | 否 |
| not_connected | 已确认请求尚未发出 | Main 可批准 |
| rejected | 已确认被拒绝且未执行 | 根据回执分类 |
| delivery_unknown | 已发出后超时、断线或回执不明确 | 否，核查 |

发送失败不尝试通过同一个失败通道继续刷“发送失败”消息；错误记录在日志和管理端。对用户的业务错误文案仍由 Main 的现有文案表决定。

## 11. 验收样例

1. conversation 返回一句文字，Main 先持久化动作，再调用发送，收到完成回执后才标 completed。
2. memento 返回文件加通知，验证调用顺序；上传失败时通知调用次数为0。
3. 上传成功、通知失败，恢复时文件上传次数仍为1。
4. 三段总结第2段失败，恢复不重发第1段；unknown 时第2段也不自动重发。
5. 包含 `[CQ:at,qq=all]` 的正文通过 text 段原样发送，不触发 @全体。
6. 原工作簿在准备后被修改，上传仍使用原任务快照；快照被篡改则停止。
7. Main 保存 sending 失败时，实际网络调用次数为0。
8. 成功发送但状态保存失败，重启后进入 needs_review，不自动重复发送。
9. 动作回执不进入业务队列，Main等待发送时 receiver 仍能接收其他消息。
10. 对同一已 sent 动作恢复，网络调用次数为0；不会重复结算福缘或生成新结果。
11. 04:00 初始化不删除未完成上传快照，也不改变任务的目标群和业务日期。

## 12. 实现顺序

先实现动作校验和准备、长文字切分与文件快照 → 用伪 onebot_client 验证单动作结果分类 → 接府库动作日志与 Main 顺序执行 → 接 receiver 的 echo 回执分流 → 真实 NapCat 验证文字、上传、超时与同名文件行为。

本次只编写 Markdown，未发送实际 QQ 消息、上传文件或创建发送代码。
