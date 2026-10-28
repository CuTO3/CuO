import itertools,json
from datetime import datetime,date
from pathlib import Path
import pytest
from Core.clock import business_date,summary_bounds,BEIJING
from Function.divine.son_function.zhou_yi import from_lines,load_hexagrams
from Function.divine.son_function.dictum import select_dictum
from Function.divine.son_function.tarot import map_tarot
from Function.divine.divine import luck_weights,draw_luck
from Function.divine.son_function.merge_message import render
from Function.memento.son_function.nickname_segmenter import split_nickname
from Function.memento.son_function.align_slots import align_slots
from Function.summary.son_function.AI_sum import validate,SummaryError
from Integration.napcat.text import split_text
def test_day_boundary():
    assert business_date(datetime(2026,10,26,3,59,tzinfo=BEIJING))==date(2026,10,25)
    assert business_date(datetime(2026,10,26,4,tzinfo=BEIJING))==date(2026,10,26)
    with pytest.raises(ValueError):business_date(datetime(2026,10,26))
def test_all_4096_divinations():
    table=load_hexagrams()
    for values in itertools.product((6,7,8,9),repeat=6):
        z=from_lines(list(values),table);q=select_dictum(z);t=map_tarot(z,0)
        assert q["primary"]["text_original"] and q["primary"]["source_url"]
        assert len(z["moving_lines"])==sum(v in (6,9) for v in values)
        assert (z["base_bits"]!=z["changed_bits"])==z["has_change"]
        assert t["orientation"]=="正位"
def test_independent_quotes():
    z=from_lines([9,7,7,7,7,9]);q=select_dictum(z)
    assert q["primary"]["line_position"]==6
    assert "亢龙有悔" in q["primary"]["text_original"].replace("，","")
    z=from_lines([6]*6);q=select_dictum(z)
    assert q["primary"]["source_label"]=="用六" and len(q["auxiliary"])==1
    z=from_lines([9,9,7,7,9,9]);q=select_dictum(z)
    assert q["primary"]["line_position"]==3 and q["primary"]["hexagram_number"]==z["changed"]["number"]
def test_luck_distribution():
    w=luck_weights();p=[v/sum(w) for v in w]
    assert p==list(reversed(p))
    assert p[7]==p[8]==p[9]==p[11]==p[12]==p[13]
    assert p[10]==p[5] and abs(p[0]-.000571379208)<1e-10
    assert draw_luck(type("R",(),{"random":lambda self:0})())==-10
    assert draw_luck(type("R",(),{"random":lambda self:.99999999999})())==10
def test_render():
    z=from_lines([7]*6);q=select_dictum(z);t=map_tarot(z,0)
    text=render(z,t,{"keyword":"今日小事","advice":"吃饭"},0,-20)
    assert " | " in text.splitlines()[0] and "→" not in text.splitlines()[0]
    assert "\n解卦\n" in text and "· 正位" in text and "卦运 0 · 福缘 -20" in text
    assert "无动爻" not in text and "今日应事" not in text
    z=from_lines([7,9,7,7,7,7])
    changed=render(z,t,{"keyword":"x","advice":"y"},1,1)
    assert "→" in changed.splitlines()[0] and " | " in changed.splitlines()[0]
    assert "九二 · 有变卦" not in changed and "\n应事 · x\n" in changed
def test_graphemes():
    emoji="👨‍👩‍👧‍👦"
    parts=split_nickname("最爱ABC"+emoji+"马铃薯",[None]*6)
    assert "".join(parts)=="最爱ABC"+emoji+"马铃薯"
    assert emoji in parts
def test_alignment_gap():
    r=align_slots(["甲","乙","丙",None,None,None],["甲","丙"])
    assert r["slots"]==["甲",None,"丙",None,None,None]
def test_evidence_validation():
    rows=[{"ref":"m00001","text":"今晚吃火锅"}]
    good={"events":[{"title":"晚饭","body":"聊到火锅","refs":["m00001"],"quotes":[{"ref":"m00001","text":"吃火锅"}]}]}
    assert len(validate(good,rows))==1
    good["events"][0]["quotes"][0]["text"]="吃面"
    with pytest.raises(SummaryError):validate(good,rows)
def test_split_long():
    chunks=split_text("鲸"*5000,1500)
    assert len(chunks)>1 and all(len(c)<=1500 for c in chunks)
