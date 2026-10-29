import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from Core.clock import BEIJING
from Workflow import _analyzer_ as analyzer


def context(tmp_path):
    return SimpleNamespace(settings=SimpleNamespace(config_root=tmp_path, groups={'100': {}}),
                           db=SimpleNamespace(write=AsyncMock(), read=AsyncMock(return_value=[])), corpus_conflict=False)


@pytest.mark.parametrize('semantic', [
    {'opt':'conversation','params':{}},
    {'opt':'error','params':{'code':'unsupported_intent'}},
    {'opt':'summary','params':{'date_expressions':['明天']}},
])
async def test_nonfunction_results_are_not_stored(tmp_path,monkeypatch,semantic):
    monkeypatch.setattr(analyzer,'MODEL',SimpleNamespace(complete=AsyncMock(return_value=json.dumps(semantic)),model_name='synthetic'))
    ctx=context(tmp_path)
    await analyzer.run('请求内容包含明天',datetime(2026,10,29,12,tzinfo=BEIJING),context=ctx)
    path=tmp_path/'intention.json'
    assert not path.exists() or json.loads(path.read_text(encoding='utf-8'))['entries']==[]


async def test_function_intent_reused_and_relative_date_resolved_again(tmp_path,monkeypatch):
    model=SimpleNamespace(complete=AsyncMock(return_value=json.dumps({'opt':'summary','params':{'date_expressions':['昨天']}})),model_name='synthetic')
    monkeypatch.setattr(analyzer,'MODEL',model)
    ctx=context(tmp_path)
    first=await analyzer.run('请整理昨天的群聊',datetime(2026,10,29,12,tzinfo=BEIJING),context=ctx)
    second=await analyzer.run('请整理昨天的群聊',datetime(2026,10,30,12,tzinfo=BEIJING),context=ctx)
    assert first['params']['target_date']=='2026-10-28'
    assert second['params']['target_date']=='2026-10-29'
    assert model.complete.await_count==1
    assert json.loads((tmp_path/'intention.json').read_text(encoding='utf-8'))['entries'][0]['hit_count']==2


async def test_sync_prunes_old_chat_records_and_persists_revision(tmp_path):
    corpus={'schema_version':1,'revision':4,'entries':[{'opt':'conversation','raw_text':'合成聊天'},{'opt':'divine'}],'examples':[]}
    path=tmp_path/'intention.json';path.write_text(json.dumps(corpus),encoding='utf-8')
    ctx=context(tmp_path)
    ctx.db.read.return_value=[{'result':{'corpus':corpus}}]
    await analyzer.synchronize(ctx)
    result=json.loads(path.read_text(encoding='utf-8'))
    assert result['entries']==[{'opt':'divine'}]
    assert result['revision']==5
    assert not ctx.corpus_conflict
    assert ctx.db.write.await_count==1
