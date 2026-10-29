# CuO 控制中心

原生 HTML / CSS / JavaScript 管理界面，由现有 FastAPI 服务托管，无额外 Node 运行依赖。页面位置 `/console/`，后台接口 `/console/api/*`，业务数据使用现有 `/admin/*`。

## 访问生产服务

已部署至 CuCl 的 `/serve/workspace/program/cuo/backend/console`，沿用 `cuo-backend.service` 开机启动，服务器监听 `127.0.0.1:8080`。

在本机 PowerShell 中运行并保持终端打开：

```powershell
ssh -N -o ServerAliveInterval=30 -L 127.0.0.1:9080:127.0.0.1:8080 cucl
```

访问 <http://127.0.0.1:9080/console/>。登录使用服务器私有 `var/config/src/backend/Integration/console/routes_config.toml` 中的 `console_admin_token`，不要将密钥提交到仓库或聊天。当前使用 SSH 隧道，不对公网开放管理接口。关闭隧道不影响服务器上的机器人服务。

## 功能

- 总览：真实数据库累计数量、最近七个业务日消息趋势、任务状态、机器人连接状态。
- 任务记录：最近 500 条，搜索、状态筛选、只读详情、导出当前筛选结果；暂未开放任务重试和发送决策。
- 群成员：查看资料和福缘，通过既有串行队列修改显示名称；“改福缘”支持直接输入正负整数和 ±1、±10 快捷调整，提交后等待执行结果并刷新列表；版本冲突不会覆盖其他修改。排队超过等待时间时，可在任务记录确认结果，福缘修改记录保留修改前后数值。
- 众声录、周易、消息档案：查看、搜索、详情、JSON 导出；查询限最近 500 条。
- 偏好：模型名称、模型超时、消息分段长度、OneBot 超时；写入 `/serve/data/cuo/console-settings.json`，原子替换，0600 权限，后续请求立即生效，重启后保留。
- 模型地址、API 密钥、数据库连接和群注册仍在服务器配置中管理，不通过网页编辑或回显。

网页目前手动刷新，不自动刷新表单或覆盖正在阅读的记录。

### 福缘管理接口

`POST /admin/{gid}/commands`，复用管理员 Bearer 鉴权或控制台会话与 `X-Cuo-Request: console` 请求头：

```json
{"operation":"fortune","user_id":"123456","fortune":20,"expected_version":"成员查询返回的 version"}
```

`fortune` 为目标值，允许范围为 JavaScript 安全整数（±9007199254740991）；接口返回 202 和 `task_id`。通过 `GET /admin/{gid}/commands/{task_id}` 查询执行结果，`business_status=completed` 且 `result.status=ok` 才表示修改完成；`result.fortune_before` 与 `result.fortune_after` 为审计数值。`version_conflict` 表示成员已变化或不存在，本次修改未执行，应重新读取成员后再提交。

## 鉴权与维护

登录成功换取内存中随机会话；HttpOnly / SameSite Strict cookie，有效期 8 小时，服务重启后失效。同源请求要求 `X-Cuo-Request: console`，未配置跨域许可。登录全局限 10 次/分钟；已有 Bearer 管理 API 保持兼容。若以后改为公网访问，应另行配置 HTTPS 与访问边界，不能直接暴露现有 8080 端口。

界面静态文件更新无需重启。Python 文件更新需要重启 `cuo-backend.service`，部署前先确认无运行中任务。

2026-10-27 部署前的三个原文件保存在 `/serve/backup/cuo-console-20261027-124710/`：`Main.py`、`Infrastructure/admin.py`、`config/settings.py`。恢复这三个文件并重启服务即可回退到未安装控制中心的后端。该副本只用于临时回滚，不替代异地备份。

## 检查

```bash
python -m pytest Test/tests/test_console.py -q
node --check console/app.js
```

覆盖：未登录访问、错误密钥、CSRF 请求头、登出与会话失效、登录限流、参数范围、持久化、版本冲突、敏感字段注入拒绝及原 Bearer 接口兼容。生产只读验收读取各表和设置，不修改群数据、不发送测试消息。
