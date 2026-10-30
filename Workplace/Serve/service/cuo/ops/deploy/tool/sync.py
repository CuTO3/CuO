'''
本文件用途：通过 SSH 执行受检的 Git 同步或部署。

配置字段：
ops_deploy_ssh_host    运维参数
ops_deploy_repository_url    运维参数
ops_deploy_repository_directory    运维参数
ops_deploy_lock_file    运维参数
ops_deploy_ssh_connect_timeout_seconds    运维参数
ops_deploy_git_timeout_seconds    每条 Git 命令的超时（秒）
'''

import argparse
import base64
import json
import subprocess
from pathlib import Path
import os
import tomllib

REMOTE_SOURCE = r"""
import fcntl
import json
import os
import signal
import sys
from pathlib import Path
import subprocess

CFG=REQUEST['config']
REPO=Path(CFG['ops_deploy_repository_directory'])
URL=CFG['ops_deploy_repository_url']

def execute(args, capture=False):
    process=subprocess.Popen(list(map(str,args)),start_new_session=True,
                             stdout=subprocess.PIPE if capture else None,text=True)
    try:
        output,_=process.communicate(timeout=CFG['ops_deploy_git_timeout_seconds'])
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.communicate()
        raise RuntimeError('Git 命令超时，已停止本次同步并释放部署锁；请检查服务器到仓库的网络。') from None
    if process.returncode:raise RuntimeError('Git 命令失败，请检查上方 Git 错误；正式服务未修改。')
    return output or ''
def run(*args):
    execute(args)
def git(*args):
    return execute(['git','-C',str(REPO),*args],capture=True).strip()
def main(request):
    ref=request.get('ref')
    if ref and (ref.startswith('-') or any(c.isspace() for c in ref)):
        raise ValueError('Invalid Git ref')
    with open(CFG['ops_deploy_lock_file'],'a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('已有同步或部署任务正在运行，本次未执行。请等待其结束后重试；不要删除锁文件。',file=sys.stderr,flush=True)
            return 75
        if not (REPO/'.git').is_dir():
            if REPO.exists():raise RuntimeError('repos exists without Git; refusing overwrite')
            REPO.parent.mkdir(parents=True,exist_ok=True)
            run('git','-c','credential.helper=','clone',URL,REPO)
        if git('remote','get-url','origin').rstrip('/').removesuffix('.git')!=URL.removesuffix('.git'):
            raise RuntimeError('Unexpected repository origin')
        if git('status','--porcelain','--untracked-files=all'):
            raise RuntimeError('Server repos has local changes; refusing overwrite')
        run('git','-C',REPO,'-c','credential.helper=','fetch','--prune','origin')
        if not ref:
            run('git','-C',REPO,'remote','set-head','origin','-a')
            ref='origin/HEAD'
        commit=git('rev-parse','--verify',ref+'^{commit}')
        run('git','-C',REPO,'checkout','--detach',commit)
        print(json.dumps({'暂存完成':commit,'仓库目录':str(REPO),'正式服务已更新':False},ensure_ascii=False),flush=True)

if __name__=='__main__':
    try:sys.exit(main(REQUEST) or 0)
    except RuntimeError as exc:
        print(str(exc),file=sys.stderr,flush=True);sys.exit(1)
"""


def main():
    parser = argparse.ArgumentParser(description='同步 Git 到服务器 repos，首次 clone，后续 fetch；不部署。')
    parser.add_argument("--config", help="指定私有 TOML；默认从 CUO_CONFIG_ROOT 读取")
    parser.add_argument("--host", help="覆盖配置中的 SSH 目标")
    parser.add_argument("--ref", help="指定提交、标签或 origin/分支；默认远端默认分支最新版本")
    request = vars(parser.parse_args())
    config_path=request.pop("config")
    app_root=Path(__file__).resolve().parents[3]
    config_root=Path(os.environ.get("CUO_CONFIG_ROOT") or app_root/"var/config")
    if not config_root.is_absolute():config_root=app_root/config_root
    with Path(config_path or config_root/"ops/deploy/tool/sync_config.toml").open("rb") as stream:
        settings=tomllib.load(stream)
    if type(settings.get('ops_deploy_git_timeout_seconds')) is not int or settings['ops_deploy_git_timeout_seconds'] <= 0:
        parser.error('配置中需要正整数 ops_deploy_git_timeout_seconds，请同步新版 example')
    host = request.pop("host") or settings["ops_deploy_ssh_host"]
    if not host or not settings["ops_deploy_repository_url"]:parser.error("填写专用配置中的 SSH 目标和仓库地址")
    request["config"]=settings
    if host.startswith("-") or any(c.isspace() for c in host):
        parser.error("SSH 主机名格式错误")
    encoded = base64.b64encode(json.dumps(request).encode()).decode()
    source = "import base64,json\nREQUEST=json.loads(base64.b64decode('" + encoded + "'))\n" + REMOTE_SOURCE
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout="+str(settings["ops_deploy_ssh_connect_timeout_seconds"]), host,
                             "sudo -n python3 -"], input=source.encode("utf-8"))
    if result.returncode == 75:
        print('同步未开始：服务器部署锁被其他任务占用。')
    elif result.returncode:
        print("同步失败，请查看上方错误。此次未部署，也未执行数据库迁移。")
    else:
        print('同步完成。正式服务尚未更新；部署请运行 deploy.py。')
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
