'''
本文件用途：Function/memento/son_function/nickname_segmenter.py 的后端实现。

配置字段：
memento_nickname_protected_words                     私有昵称分词保护词
memento_nickname_character_limit                     昵称字符上限
'''

from Core.configuration import load, resource

CONFIG = load("nickname")

import re
from pathlib import Path
import jieba
import regex
PROTECTED=tuple(CONFIG["memento_nickname_protected_words"])
TOKENIZER=jieba.Tokenizer()
for word in PROTECTED:TOKENIZER.add_word(word,100000)
def split_nickname(nickname,old_slots):
    if not isinstance(nickname,str) or not nickname.strip() or len(nickname)>CONFIG["memento_nickname_character_limit"]:
        raise ValueError("invalid nickname")
    if not isinstance(old_slots,list) or len(old_slots)!=6 or any(x is not None and (not isinstance(x,str) or not x) for x in old_slots):
        raise ValueError("six slots required")
    # Resolve overlapping protected spans once, longest first, old before dictionary.
    candidates=[]
    for priority,words in enumerate(([x for x in old_slots if x],PROTECTED)):
        for order,word in enumerate(words):
            for match in re.finditer(re.escape(word),nickname):
                candidates.append((-len(regex.findall(r"\X",word)),priority,order,match.start(),match.end()))
    chosen=[]
    for _,priority,order,a,b in sorted(candidates):
        if not any(a<end and b>start for start,end in chosen):chosen.append((a,b))
    # Never split a grapheme or an ASCII identifier.
    spans=set(chosen)
    for match in regex.finditer(r"最爱[A-Za-z0-9]+|[A-Za-z0-9]+|\X",nickname):
        a,b=match.span();token=match.group()
        if len(token)==1 and (ord(token)<128 or regex.fullmatch(r"\p{Han}",token)):continue
        if not any(a<e and b>s for s,e in spans):spans.add((a,b))
    parts=[];cursor=0
    def free(text):
        tokens=list(TOKENIZER.cut(text,HMM=False))
        # Restore tokenizer boundaries that bisect a grapheme cluster.
        boundaries=set();pos=0
        for g in regex.findall(r"\X",text):pos+=len(g);boundaries.add(pos)
        out=[];buf="";pos=0
        for token in tokens:
            buf+=token;pos+=len(token)
            if pos in boundaries:out.append(buf);buf=""
        if buf:out.append(buf)
        return out
    for a,b in sorted(spans):
        parts.extend(free(nickname[cursor:a]));parts.append(nickname[a:b]);cursor=b
    parts.extend(free(nickname[cursor:]))
    old=set(x for x in old_slots if x)
    while len(parts)>6:
        pairs=[(len(regex.findall(r"\X",parts[i]+parts[i+1])),i) for i in range(len(parts)-1)
               if parts[i] not in old and parts[i+1] not in old]
        if not pairs:raise ValueError("nickname_alignment_required")
        _,i=min(pairs);parts[i:i+2]=[parts[i]+parts[i+1]]
    if "".join(parts)!=nickname:raise ValueError("nickname reconstruction failed")
    return parts
