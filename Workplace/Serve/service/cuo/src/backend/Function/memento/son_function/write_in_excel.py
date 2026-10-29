'''
本文件用途：Function/memento/son_function/write_in_excel.py 的后端实现。

配置字段：
cell                                 共享运行配置字段
title                                共享运行配置字段
'''

import hashlib
import json
import os
import tempfile
from copy import copy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from openpyxl import Workbook,load_workbook
HEADERS=["日期","元谥","亨谥","利谥","贞谥","常谥","平谥","备注"]
def create_workbook(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():return path
    wb=Workbook();wb.active.title="注释";wb.active.append(["修改时间","成员","变迁","修改记录"])
    _save(wb,path);return path
def _save(wb,path):
    fd,tmp=tempfile.mkstemp(dir=path.parent,suffix=".xlsx");os.close(fd)
    try:
        wb.save(tmp)
        check=load_workbook(tmp);check.close()
        with open(tmp,"r+b") as f:os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
        wb.close()
def _last(ws,cols):
    return next((r for r in range(ws.max_row,0,-1) if any(ws.cell(r,c).value not in (None,"") for c in range(1,cols+1))),1)
def _style(ws,source,target,cols):
    for c in range(1,cols+1):
        ws.cell(target,c)._style=copy(ws.cell(source,c)._style)
    ws.row_dimensions[target].height=ws.row_dimensions[source].height
def _text(cell,value):
    cell.value=value;cell.data_type="s";cell.number_format="@"
def write_event(workbook_path,sheet_name,event):
    path=Path(workbook_path)
    if not isinstance(sheet_name,str) or not sheet_name or len(sheet_name)>31 or any(c in sheet_name for c in "[]:*?/\\") or sheet_name in ("注释","_cuo_export"):
        raise ValueError("invalid member sheet")
    slots=event["new_slots"]
    if len(slots)!=6 or any(x is not None and not isinstance(x,str) for x in slots) or "".join(x or "" for x in slots)!=event["new_nickname"]:
        raise ValueError("invalid aligned slots")
    observed=datetime.fromisoformat(event["observed_at"]) if isinstance(event["observed_at"],str) else event["observed_at"]
    if observed.tzinfo is None:raise ValueError("aware observation required")
    observed=observed.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    create_workbook(path);wb=load_workbook(path)
    digest=hashlib.sha256(json.dumps([event["user_id"],event["new_nickname"],slots],ensure_ascii=False).encode()).hexdigest()
    try:
        if "注释" not in wb:raise ValueError("missing 注释 sheet")
        if "_cuo_export" not in wb:
            marker=wb.create_sheet("_cuo_export");marker.append(["event_id","user_id","member_row","log_row","hash"]);marker.sheet_state="hidden"
        marker=wb["_cuo_export"]
        for values in marker.iter_rows(min_row=2,values_only=True):
            if str(values[0])==str(event["event_id"]):
                if values[4]!=digest or str(values[1])!=str(event["user_id"]):raise ValueError("export hash conflict")
                return {"path":str(path),"event_id":str(event["event_id"]),"member_row":values[2],"log_row":values[3],"already_exported":True}
        if sheet_name not in wb:
            ws=wb.create_sheet(sheet_name);ws.append(HEADERS)
            template=next((s for s in wb if s.title not in (sheet_name,"注释","_cuo_export") and [str(s.cell(1,c).value or "").strip() for c in range(2,8)]==HEADERS[1:7]),None)
            if template:
                for key,dim in template.column_dimensions.items():ws.column_dimensions[key]=copy(dim)
                for c in range(1,9):ws.cell(1,c)._style=copy(template.cell(1,c)._style)
        ws=wb[sheet_name]
        if [str(ws.cell(1,c).value or "").strip() for c in range(2,8)]!=HEADERS[1:7]:
            raise ValueError("member sheet does not match six-slot template")
        r=_last(ws,8)+1;_style(ws,r-1,r,8)
        ws.cell(r,1,observed.date()).number_format="yyyy.m.d"
        for c,value in enumerate(slots,2):
            if value is not None:_text(ws.cell(r,c),value)
            else:ws.cell(r,c).value=None
        _text(ws.cell(r,8),event["remark"])
        log=wb["注释"];lr=_last(log,4)+1;_style(log,lr-1,lr,4)
        log.cell(lr,1,observed).number_format="yyyy-mm-dd hh:mm:ss"
        _text(log.cell(lr,2),event.get("display_name") or sheet_name)
        _text(log.cell(lr,3),("初创："+event["new_nickname"]) if event["old_nickname"] is None else event["old_nickname"]+" → "+event["new_nickname"])
        _text(log.cell(lr,4),event["remark"])
        marker.append([str(event["event_id"]),str(event["user_id"]),r,lr,digest])
        _save(wb,path)
        return {"path":str(path),"event_id":str(event["event_id"]),"member_row":r,"log_row":lr,"already_exported":False}
    finally:wb.close()
