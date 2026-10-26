"""Rebuildable caches. PostgreSQL remains authoritative; files never decide settlement."""
import asyncio
import json
import os
import tempfile
from datetime import date,datetime,timedelta
from pathlib import Path
from Infrastructure.clock import business_date,now
from Infrastructure.results import jsonable
def atomic_write(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix=".cuo-",suffix=".tmp")
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            f.write(text);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
def dump(value):return json.dumps(jsonable(value),ensure_ascii=False,sort_keys=True)
class CacheManager:
    def __init__(self,settings,db):
        self.settings=settings;self.db=db;self.ready=set();self.dates={}
    def paths(self,gid,day):
        self.db.check_group(gid)
        if isinstance(day,str):day=date.fromisoformat(day)
        if type(day) is not date:raise ValueError("invalid date")
        root=self.settings.backend_root
        suffix=Path(gid)/day.isoformat()
        return {'messages':root/'Function/summary/cache'/suffix/'messages.jsonl',
                'divined_users':root/'Function/divine/cache'/suffix/'divined_users.json',
                'keywords':root/'Function/divine/cache'/suffix/'keywords.json',
                'manifest':root/'database/cache'/suffix/'manifest.json'}
    def known_dates(self,gid):return self.dates.get(gid,set())
    async def _refresh(self,gid,day):
        paths=self.paths(gid,day);self.ready.discard((gid,day))
        await asyncio.to_thread(atomic_write,paths["manifest"],dump({"state":"dirty"}))
        messages=await self.db.read("messages",group_id=gid,filters={"business_date":day},order_by=(("sent_at","asc"),("id","asc")))
        divined=await self.db.read("divinations",group_id=gid,filters={"business_date":day,"status":"settled"})
        logs=await self.db.read("log",group_id=gid,filters={"request_type":"initialize_day","business_date":day,"business_status":"completed"},order_by=(("created_at","desc"),))
        kw=next((r["result"]["keywords"] for r in logs if "keywords" in r["result"] and not r["result"].get("source_dirty")),{"business_date":str(day),"source_status":"missing","items":[]})
        for name,value in (("messages",messages),("divined_users",{r["user_id"]:str(r["id"]) for r in divined}),("keywords",kw)):
            text='\n'.join(dump(r) for r in value)+'\n' if name=='messages' else dump(value)
            await asyncio.to_thread(atomic_write,paths[name],text)
        await asyncio.to_thread(atomic_write,paths["manifest"],dump({"state":"ready","business_date":str(day),"count":len(messages)}))
        self.ready.add((gid,day));self.dates.setdefault(gid,set()).add(day)
    async def refresh_day(self,gid,day):
        if isinstance(day,str):day=date.fromisoformat(day)
        async with self.db.group_lock(gid):await self._refresh(gid,day)
    async def _after_commit(self,gid,affected):
        for day in affected:
            try:await self._refresh(gid,day)
            except Exception:self.ready.discard((gid,day))
    async def startup(self):
        today=business_date(now())
        for gid in self.db.groups:
            for day in (today-timedelta(days=1),today):await self.refresh_day(gid,day)
    async def set_current(self,gid,day,task_id):
        if (gid,day) not in self.ready:raise RuntimeError("cache not ready")
        await asyncio.to_thread(atomic_write,self.paths(gid,day)["manifest"].parent.parent/"current.json",dump({"business_date":str(day),"task_id":str(task_id)}))
    async def read_messages(self,gid,day):
        if isinstance(day,str):day=date.fromisoformat(day)
        async with self.db.group_lock(gid):
            try:
                if (gid,day) not in self.ready:await self._refresh(gid,day)
                rows=[json.loads(line) for line in self.paths(gid,day)['messages'].read_text(encoding='utf-8').splitlines() if line]
                if len({r['id'] for r in rows})!=len(rows):raise ValueError('duplicate cache row')
                for r in rows:
                    r['business_date']=date.fromisoformat(r['business_date'])
                    r['sent_at']=datetime.fromisoformat(r['sent_at']);r['received_at']=datetime.fromisoformat(r['received_at'])
                return rows
            except (OSError,ValueError,KeyError,TypeError):self.ready.discard((gid,day))
        return await self.db.read('messages',group_id=gid,filters={'business_date':day},order_by=(('sent_at','asc'),('id','asc')))
    async def read_keywords(self,gid,day):
        rows=await self.db.read("log",group_id=gid,filters={"request_type":"initialize_day","business_date":day,"business_status":"completed"},order_by=(("created_at","desc"),))
        return next((r["result"]["keywords"] for r in rows if not r["result"].get("source_dirty") and "keywords" in r["result"]),{"source_status":"missing","items":[]})
    async def prune(self,gid,day):
        self.db.check_group(gid)
        if isinstance(day,str):day=date.fromisoformat(day)
        async with self.db.group_lock(gid):
            pending=await self.db.read('log',group_id=gid,filters={'status':{'in':['pending','running','failed','needs_review']}})
            protected={r['business_date'] for r in pending}
            protected.update(date.fromisoformat(r['params']['target_date']) for r in pending if r['params'].get('target_date'))
            for old in list(self.known_dates(gid)):
                if old>=day-timedelta(days=1) or old in protected:continue
                # A successful read proves the authoritative source is available even for an empty day.
                await self.db.read('messages',group_id=gid,filters={'business_date':old},limit=1)
                for path in self.paths(gid,old).values():
                    resolved=path.resolve()
                    if not resolved.is_relative_to(self.settings.backend_root.resolve()) or path.is_symlink():raise ValueError('cache path escaped workspace')
                    path.unlink(missing_ok=True)
                    try:path.parent.rmdir()
                    except OSError:pass
                self.ready.discard((gid,old));self.dates[gid].discard(old)
