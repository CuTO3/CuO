import asyncio,json
from contextlib import asynccontextmanager
from types import SimpleNamespace
import pytest
from Function.summary.son_function import AI_sum

@pytest.mark.asyncio
async def test_large_day_keeps_all_batches_and_individual_deadlines(monkeypatch):
    records=[{'ref':f'm{i:05}', 'text':'甲'*6500} for i in range(18)]
    seen=[];deadlines=[];active=0
    @asynccontextmanager
    async def deadline(seconds):
        nonlocal active
        deadlines.append(seconds);active+=1
        try:yield
        finally:active-=1
    async def complete(**kw):
        assert active==1
        batch=json.loads(kw['messages'][-1]['content'])['records']
        seen.extend(batch)
        return json.dumps({'events':[{'title':'讨论','body':'群友交流。','refs':[batch[0]['ref']],'quotes':[]}]})
    monkeypatch.setattr(AI_sum.asyncio,'timeout',deadline)
    result=await AI_sum.generate(records,{},SimpleNamespace(model=SimpleNamespace(complete=complete)))
    assert seen==records
    assert len(result)==18
    assert deadlines==[120]*18

@pytest.mark.asyncio
async def test_large_day_does_not_relax_evidence_validation():
    calls=0
    async def complete(**kw):
        nonlocal calls
        calls+=1
        return json.dumps({'events':[{'title':'讨论','body':'群友交流。','refs':['missing'],'quotes':[]}]})
    with pytest.raises(AI_sum.SummaryError,match='evidence validation failed'):
        await AI_sum.generate([{'ref':f'm{i:05}','text':'甲'*6500} for i in range(18)],{},SimpleNamespace(model=SimpleNamespace(complete=complete)))
    assert calls==2

@pytest.mark.asyncio
async def test_empty_input_does_not_call_model():
    assert await AI_sum.generate([],{},SimpleNamespace(model=None))==[]
