# 部署

服务用户 cuo；代码 /serve/workspace/program/cuo/backend；生产配置 /serve/config/cuo/backend.env 和 groups.json；持久文件 /serve/data/cuo。不部署 UnknowFunction、本地 .venv、测试数据和缓存。服务器使用 Linux 虚拟环境。

PostgreSQL 使用 CuO 数据库，cuo 角色通过本机 Unix socket 的 peer 认证连接。数据库管理员通过 sudo -u postgres 管理；应用角色不使用超级用户权限。

systemd 定义见本目录 cuo-backend.service。服务只监听 127.0.0.1:8080，单 worker。NapCat 使用 ws://127.0.0.1:8080/onebot/ws、数组消息格式、reportSelfMessage=true，连接令牌与 backend.env 的 ONEBOT_TOKEN 一致。QQ 登录须由账号持有人扫码完成。

首次启动前在后端目录，以 cuo 用户设置 CUO_ENV_FILE=/serve/config/cuo/backend.env 后运行 .venv/bin/python -m scripts.migrate。更新前备份代码、数据库和永久数据；迁移拒绝未标记版本的非空 schema，不强制覆盖。

检查：systemctl status cuo-backend；curl http://127.0.0.1:8080/ready。ready=true 表示后端可服务，onebot_connected 单独表示 QQ 链路。日志用 journalctl -u cuo-backend 查看，不公开配置文件或包含用户聊天的数据。

本机管理隧道：ssh -N -L 8080:127.0.0.1:8080 <ssh_host>。管理接口需 Bearer ADMIN_TOKEN；令牌只在服务器受限配置中保存。不要把测试令牌用于生产。

停止/恢复：sudo systemctl stop cuo-backend；恢复已备份的匹配代码与配置后 sudo systemctl start cuo-backend。停止服务不会删除数据库、工作簿或 NapCat 登录态。需要数据库回滚时先做当前备份并验证恢复方案，不能仅切换源码就假定 schema 兼容。
