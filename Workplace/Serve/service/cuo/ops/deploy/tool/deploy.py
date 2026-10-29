"""从本地通过 SSH 执行；应用源码仅从服务器 Git 仓库取得。"""
import argparse
import base64
import json
import subprocess

REMOTE_SOURCE = r"""
# Remote deployment worker.
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.request
from datetime import datetime, timezone

REPOSITORY = "https://github.com/CuTO3/CuO.git"
REPO = Path("/serve/repos/CuO")
SOURCE = REPO / "Workplace/Serve/service/cuo"
SERVICE = Path("/serve/service/cuo")
UNIT = "cuo-backend.service"
PYTHON = "/serve/software/python/environments/cuo/bin/python"


def run(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def output(*args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def emit(**values):
    print(json.dumps(values, ensure_ascii=False), flush=True)


def git(*args):
    return output("git", "-C", REPO, *args)


def ready():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/ready", timeout=2) as response:
            return json.load(response)
    except Exception:
        return {"ready": False, "onebot_connected": False}


def validate_checkout():
    if git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("Server repos checkout has local changes; preserve them before staging/deploying")
    if git("remote", "get-url", "origin").rstrip("/").removesuffix(".git") != REPOSITORY.removesuffix(".git"):
        raise RuntimeError("Unexpected Git origin")


def validate_deploy(commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("deploy requires the full lowercase 40-character commit SHA")
    validate_checkout()
    if git("rev-parse", "HEAD") != commit:
        raise RuntimeError("Staged HEAD does not match --commit")
    # Resolve every recursive-copy destination before any mutation.
    if SERVICE.resolve() != SERVICE or SOURCE.resolve() != SOURCE:
        raise RuntimeError("Unexpected symlink in source or service path")
    for name in ("src", "ops"):
        if (SERVICE / name).resolve() != SERVICE / name or not (SOURCE / name).is_dir():
            raise RuntimeError("Invalid source or destination layout")
        if any(p.is_symlink() for p in (SOURCE / name).rglob("*")):
            raise RuntimeError("Source symlinks require manual review")
    workdir = output("systemctl", "show", UNIT, "--value", "-p", "WorkingDirectory")
    if workdir != str(SERVICE / "src/backend"):
        raise RuntimeError("Service working directory differs from fixed deployment directory")
    if output("systemctl", "show", UNIT, "--value", "-p", "User") != "cuo":
        raise RuntimeError("Unexpected service user")
    old = tomllib.loads((SERVICE / "pyproject.toml").read_text())
    new = tomllib.loads((SOURCE / "pyproject.toml").read_text())
    if old["project"]["dependencies"] != new["project"]["dependencies"] or old["project"]["requires-python"] != new["project"]["requires-python"]:
        raise RuntimeError("Runtime requirements changed; prepare dependencies before deploying")
    for path in (SOURCE / "src/backend").rglob("*.py"):
        compile(path.read_text(encoding="utf-8-sig"), str(path), "exec")
    run("sudo", "-n", "-u", "cuo", PYTHON, "-m", "pip", "check")


def child(body):
    # Reproduce the unit environment without printing any values or credentials.
    loader = '''import os,shlex,subprocess,sys
from pathlib import Path
unit=subprocess.check_output(['systemctl','cat','cuo-backend.service'],text=True)
for line in unit.splitlines():
    if line.startswith('Environment='):
        for item in shlex.split(line[len('Environment='):]):
            key,value=item.split('=',1);os.environ[key]=value
root=Path('/serve/service/cuo')
sys.path[:0]=[str(root/'src/backend'),str(root)]
from Core.settings import Settings
s=Settings.load()
'''
    run("sudo", "-n", "-u", "cuo", PYTHON, "-c", loader + body, cwd=SERVICE)


def sync_code(source):
    for name in ("src", "ops"):
        run("rsync", "-a", "--delete", "--exclude=__pycache__/", "--exclude=*.pyc",
            str(source / name) + "/", str(SERVICE / name) + "/")
    for name in ("pyproject.toml", ".gitignore"):
        shutil.copy2(source / name, SERVICE / name)


def config_hashes():
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (SERVICE / "var/config").rglob("*") if p.is_file()}


def wait_ready():
    for _ in range(45):
        state = ready()
        if state.get("ready") and state.get("onebot_connected"):
            return state
        time.sleep(1)
    raise RuntimeError("Service or OneBot connection did not become ready")


def deploy(commit, migrate=False, dry_run=False):
    validate_deploy(commit)
    if dry_run:
        for name in ("src", "ops"):
            run("rsync", "-ain", "--delete", "--exclude=__pycache__/", "--exclude=*.pyc",
                str(SOURCE / name) + "/", str(SERVICE / name) + "/")
        emit(action="deploy", dry_run=True, commit=commit, migrate=migrate, service=str(SERVICE))
        return
    if not ready().get("ready"):
        raise RuntimeError("Service is not ready before deployment; inspect before changing it")
    before = config_hashes()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = SERVICE / "var/backups" / ("deploy-" + stamp)
    backup.mkdir(parents=True, mode=0o700)
    run("chown", "cuo:cuo", backup)
    code = backup / "code"
    code.mkdir()
    for name in ("src", "ops"):
        shutil.copytree(SERVICE / name, code / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("pyproject.toml", ".gitignore"):
        shutil.copy2(SERVICE / name, code / name)
    migration_attempted = False
    stopped = False
    try:
        emit(phase="stopping", backup=str(backup))
        run("systemctl", "stop", UNIT)
        stopped = True
        child('''from psycopg.conninfo import conninfo_to_dict
env=dict(os.environ)
keys={'dbname':'PGDATABASE','user':'PGUSER','password':'PGPASSWORD','host':'PGHOST','port':'PGPORT','sslmode':'PGSSLMODE','options':'PGOPTIONS','service':'PGSERVICE'}
for k,v in conninfo_to_dict(s.database_url).items():env[keys[k]]=v
path=Path(''' + repr(str(backup / "CuO.dump")) + ''')
subprocess.run(['pg_dump','--format=custom','--file',str(path)],env=env,check=True)
subprocess.run(['pg_restore','--list',str(path)],stdout=subprocess.DEVNULL,check=True)
''')
        emit(phase="backup_verified")
        sync_code(SOURCE)
        if migrate:
            migration_attempted = True
            emit(phase="migrating")
            child("import asyncio\nfrom ops.database.scripts.migrate import main\nasyncio.run(main())\n")
        child('''import asyncio
from Integration.postgresql import Database
from Workflow.main import verify_schema
async def verify():
    db=Database(s);await db.open()
    try:await verify_schema(db)
    finally:await db.close()
asyncio.run(verify())
from Function.divine.son_function.zhou_yi import load_hexagrams
load_hexagrams()
''')
        if before != config_hashes():
            raise RuntimeError("Production config changed during deployment")
        emit(phase="starting")
        run("systemctl", "start", UNIT)
        state = wait_ready()
        receipt = dict(commit=commit, service=str(SERVICE), backup=str(backup),
                       migrated=migrate, health=state, deployed_at=stamp)
        (backup / "deployment.json").write_text(json.dumps(receipt, indent=2) + "\n")
        temporary = SERVICE / "var/deployed-version.json.partial"
        temporary.write_text(json.dumps(receipt, indent=2) + "\n")
        temporary.replace(SERVICE / "var/deployed-version.json")
        emit(action="deploy", **receipt)
    except Exception:
        if stopped and not migration_attempted:
            run("systemctl", "stop", UNIT)
            sync_code(code)
            run("systemctl", "start", UNIT)
            emit(rollback="previous code restored", backup=str(backup), health=ready())
        elif stopped:
            run("systemctl", "stop", UNIT)
            emit(error="Migration attempted; service stopped. Inspect schema before restoring code or database.", backup=str(backup))
        raise


def main(request):
    with open("/run/lock/cuo-deploy.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        commit = request.get("commit") or git("rev-parse", "HEAD")
        emit(selected_commit=commit, service_directory=str(SERVICE))
        deploy(commit, request.get("migrate", False), request.get("dry_run", False))

if __name__ == "__main__":
    main(REQUEST)
"""


def main():
    parser = argparse.ArgumentParser(description='把服务器 repos 的暂存版本部署到固定 service 目录。')
    parser.add_argument("--host", default="cucl", help="SSH 别名，默认 cucl")
    parser.add_argument("--commit", help="可选：限定完整提交号；默认当前暂存版本")
    parser.add_argument("--migrate", action="store_true", help="同时执行数据库结构升级，默认不执行")
    parser.add_argument("--dry-run", action="store_true", help="仅核对并预览差异，不停服、不部署")
    request = vars(parser.parse_args())
    host = request.pop("host")
    if host.startswith("-") or any(c.isspace() for c in host):
        parser.error("SSH 主机名格式错误")
    encoded = base64.b64encode(json.dumps(request).encode()).decode()
    source = "import base64,json\nREQUEST=json.loads(base64.b64decode('" + encoded + "'))\n" + REMOTE_SOURCE
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
                             "sudo -n python3 -"], input=source.encode("utf-8"))
    if result.returncode:
        print("操作失败，请查看上方错误；不要直接重复执行数据库迁移。")
    else:
        print('操作完成。若使用 --dry-run，本次仅预览。')
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
