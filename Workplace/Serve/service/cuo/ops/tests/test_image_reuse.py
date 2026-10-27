import asyncio,copy,json
from uuid import uuid4
import pytest
from test_media_admin import seed
from Integration.console.media import Annotation,revision,save_annotation
from Function.summary.son_function import image_processor as ip

async def duplicate(ctx,row,gid=None):
    fields={k:copy.deepcopy(row[k]) for k in ('sent_at','business_date','user_id','nickname','segments')}
    fields['message_id']=str(uuid4())
    fields['segments']=fields['segments'][:1]
    fields['segments'][0]['data']['url']='https://gchat.qpic.cn/'+str(uuid4())
    return (await ctx.db.write('messages',[fields],group_id=gid or ctx.gid))[0]

def fake_download(ctx,monkeypatch,digest):
    async def download(url,root):return ctx.settings.data_root/'groups'/ctx.gid/'media'/digest,digest
    monkeypatch.setattr(ip,'download',download)

async def test_review_replaces_same_hash_and_stale_file(ctx,monkeypatch):
    row,key,old=await seed(ctx);other=await duplicate(ctx,row)
    otherkey=ip.segment_key(other['segments'][0])
    machine={**old,'status':'ready','version':ip.VERSION,'description':'旧机器结果'}
    await ctx.db.write('messages',[{'id':other['id'],'processing':{'media_descriptions':{otherkey:machine}}}],group_id=ctx.gid,mode='update',key_fields=('id',))
    await save_annotation(ctx,ctx.gid,row['id'],key,Annotation(description='人工修正',expected_version=revision(old)))
    stored=(await ctx.db.read('messages',group_id=ctx.gid,filters={'id':other['id']}))[0]['processing']['media_descriptions'][otherkey]
    assert stored['description']=='人工修正' and stored['machine_result']['description']=='旧机器结果'
    cache=ctx.settings.data_root/'groups'/ctx.gid/'media'/(old['hash']+'-'+ip.VERSION+'.json')
    cache.write_text(json.dumps(machine),encoding='utf-8')  # simulate an old in-flight disk write
    new=await duplicate(ctx,row);fake_download(ctx,monkeypatch,old['hash'])
    async def forbidden(*args):pytest.fail('must reuse human annotation without model')
    ctx.model.describe_images=forbidden
    result=await ip.describe_image(new['segments'][0],ctx,ctx.gid,new)
    assert result['description']=='人工修正' and result['reuse_source']=='database'
    assert result['segment_key']==ip.segment_key(new['segments'][0])
    assert json.loads(cache.read_text())['description']=='人工修正'

async def test_missing_cache_uses_database(ctx,monkeypatch):
    row,key,old=await seed(ctx);fake_download(ctx,monkeypatch,old['hash']);calls=[]
    async def model(*args):calls.append(1);return '白色正方形'
    ctx.model.describe_images=model
    await ip.describe_image(row['segments'][0],ctx,ctx.gid,row)
    cache=ctx.settings.data_root/'groups'/ctx.gid/'media'/(old['hash']+'-'+ip.VERSION+'.json');cache.unlink()
    new=await duplicate(ctx,row)
    result=await ip.describe_image(new['segments'][0],ctx,ctx.gid,new)
    assert result['description']=='白色正方形' and result['reuse_source']=='database' and len(calls)==1

async def test_concurrent_same_hash_single_model_call(ctx,monkeypatch):
    row,key,old=await seed(ctx);new=await duplicate(ctx,row);fake_download(ctx,monkeypatch,old['hash']);calls=[]
    async def model(*args):calls.append(1);await asyncio.sleep(.03);return '白色正方形'
    ctx.model.describe_images=model
    results=await asyncio.gather(*(ip.describe_image(r['segments'][0],ctx,ctx.gid,r) for r in (row,new)))
    assert len(calls)==1 and all(r['status']=='ready' for r in results)

async def test_other_occurrence_review_wins_inflight_model(ctx,monkeypatch):
    row,key,old=await seed(ctx);new=await duplicate(ctx,row);fake_download(ctx,monkeypatch,old['hash'])
    started,release=asyncio.Event(),asyncio.Event()
    async def model(*args):started.set();await release.wait();return '过时机器描述'
    ctx.model.describe_images=model
    pending=asyncio.create_task(ip.describe_image(new['segments'][0],ctx,ctx.gid,new))
    await asyncio.wait_for(started.wait(),5)
    try:await save_annotation(ctx,ctx.gid,row['id'],key,Annotation(description='人工正确描述',expected_version=revision(old)))
    finally:release.set()
    result=await pending
    assert result['description']=='人工正确描述' and result['manually_reviewed']

async def test_hash_lookup_does_not_cross_groups(ctx,monkeypatch):
    row,key,old=await seed(ctx)
    await save_annotation(ctx,ctx.gid,row['id'],key,Annotation(description='仅属于本群',expected_version=revision(old)))
    new=await duplicate(ctx,row,ctx.other);fake_download(ctx,monkeypatch,old['hash']);calls=[]
    async def model(*args):calls.append(1);return '另一个群的描述'
    ctx.model.describe_images=model
    result=await ip.describe_image(new['segments'][0],ctx,ctx.other,new)
    assert result['description']=='另一个群的描述' and len(calls)==1

async def test_cancellation_releases_hash_lock(ctx,monkeypatch):
    row,key,old=await seed(ctx);fake_download(ctx,monkeypatch,old['hash']);started=asyncio.Event()
    async def model(*args):started.set();await asyncio.Event().wait()
    ctx.model.describe_images=model
    pending=asyncio.create_task(ip.describe_image(row['segments'][0],ctx,ctx.gid,row))
    await asyncio.wait_for(started.wait(),5);pending.cancel()
    with pytest.raises(asyncio.CancelledError):await pending
    async def available(*args):return '重试成功'
    ctx.model.describe_images=available
    assert (await asyncio.wait_for(ip.describe_image(row['segments'][0],ctx,ctx.gid,row),5))['status']=='ready'
