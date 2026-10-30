import importlib.util
import sys
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock
import subprocess
import pytest


@pytest.fixture
def worker(monkeypatch, tmp_path):
    path=Path(__file__).resolve().parents[1]/'deploy/tool/sync.py'
    spec=importlib.util.spec_from_file_location('sync_tool_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    locking=SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=Mock())
    monkeypatch.setitem(sys.modules,'fcntl',locking)
    namespace={'__name__':'worker_test','REQUEST':{'config':{
        'ops_deploy_repository_directory':str(tmp_path/'repo'),
        'ops_deploy_repository_url':'https://example.invalid/repo.git',
        'ops_deploy_lock_file':str(tmp_path/'deploy.lock'),
        'ops_deploy_git_timeout_seconds':1,
    }}}
    exec(module.REMOTE_SOURCE,namespace)
    return namespace,locking


def test_busy_lock_does_not_run_git(worker,capsys):
    ns,locking=worker;locking.flock.side_effect=BlockingIOError()
    ns['run']=Mock(side_effect=AssertionError('Git must not run'))
    assert ns['main']({})==75
    assert '不要删除锁文件' in capsys.readouterr().err
    ns['run'].assert_not_called()


def test_git_timeout_terminates_group_and_reaps_child(worker,monkeypatch):
    ns,_=worker
    process=Mock(pid=123,returncode=-15)
    process.communicate.side_effect=[subprocess.TimeoutExpired(['git'],1),('',None)]
    monkeypatch.setattr(ns['subprocess'],'Popen',Mock(return_value=process))
    kill=Mock();monkeypatch.setattr(ns['os'],'killpg',kill,raising=False)
    with pytest.raises(RuntimeError,match='Git 命令超时'):ns['execute'](['git','fetch'])
    kill.assert_called_once_with(123,ns['signal'].SIGTERM)
    assert process.communicate.call_count==2


def test_git_failure_is_not_reported_as_success(worker,monkeypatch):
    ns,_=worker;process=Mock(returncode=1)
    process.communicate.return_value=('',None)
    monkeypatch.setattr(ns['subprocess'],'Popen',Mock(return_value=process))
    with pytest.raises(RuntimeError,match='Git 命令失败'):ns['execute'](['git','fetch'])
