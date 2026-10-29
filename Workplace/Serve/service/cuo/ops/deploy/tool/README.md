# 本地同步与部署

两个独立 Python 脚本，在本机运行。要求 Python 3.11+、系统 SSH 及已配置的 SSH 目标；服务器需要非交互 sudo、Git、rsync、Python 3.11+ 和现有 CuO 服务环境。本机不需要安装项目依赖。

在这个目录打开终端，依次执行：

```powershell
python sync.py
python deploy.py
```

- `sync.py`：从 GitHub 首次 clone 或 fetch 最新默认分支到 `/serve/repos/CuO`，检出暂存版本。不会重启或更新正式服务。
- `deploy.py`：自动读取暂存提交，备份当前源码和数据库，更新 `/serve/service/cuo` 内的 `src`、`ops`、`pyproject.toml`、`.gitignore`，重启后检查服务及 OneBot 连接。`var`、README、systemd 单元和生产配置不覆盖，正式工作目录不变。
- 本地尚未提交、推送的代码不参与同步；两个脚本都不代替你提交或推送 Git。

可选操作：

```powershell
python sync.py --ref origin/main
python sync.py --ref <提交号或标签>
python deploy.py --dry-run
python deploy.py --commit <完整提交号>
python deploy.py --migrate
```

`--migrate` 才会运行数据库结构升级，默认不执行。两者可用 `--host 别名` 选择 SSH 目标。

部署前会检查仓库是否干净、版本是否匹配、运行目录、依赖声明和 Python 语法。依赖要求变化时，先停止部署并提示准备依赖，不自动升级生产环境。

备份及发布记录保存在 `/serve/service/cuo/var/backups/deploy-<时间>/`，当前成功发布记录为 `var/deployed-version.json`。未尝试迁移前失败会恢复旧源码并启动服务；一旦尝试数据库迁移后失败，停止服务并保留备份，需先核查数据库再恢复，不自动覆盖数据库。

仅运行帮助或创建这些工具不会部署；`deploy.py --dry-run` 仅预览差异。正式部署操作可能短暂停服。

## 运维参数配置

同步和部署分别读取 `var/config/ops/deploy/tool/sync_config.toml`、`deploy_config.toml`。首次使用先复制同目录 `.example.toml`，填写 SSH 目标、仓库地址及实际目录。脚本不再内置真实 SSH 别名或仓库地址；这些字段默认留空。

`--config` 可指定配置文件，`CUO_CONFIG_ROOT` 可指定根目录，`--host` 可临时覆盖 SSH 目标。运行 `--help` 不需要配置，也不会连接服务器。填写配置本身不会执行部署。

迁移脚本的 SQL 文件路径位于 `var/config/ops/database/scripts/migrate_config.toml`；解卦资料构建输出路径位于 `var/config/ops/build_readings_config.toml`。数据库版本标记和固定业务规则仍由代码控制，不作为普通运维参数编辑。
