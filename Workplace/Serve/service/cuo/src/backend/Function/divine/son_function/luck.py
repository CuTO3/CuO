'''
本文件用途：根据断辞计算福缘方向与范围。

配置字段：
无独立外部配置。
'''

import re

VERSION = "dictum-v3"


def assess_dictum(dictum):
    text = dictum["primary"]["text_display"].translate(str.maketrans({"厲": "厉", "無": "无", "終": "终", "貞": "贞", "禍": "祸"}))
    protected = "无咎" in text
    # Immunity to blame does not cancel an adverse outcome. Negated warnings
    # and descriptions such as 凶事 must not be read as adverse predictions.
    for phrase in ("无大悔", "无悔", "无吝", "无凶", "无咎"):
        text = text.replace(phrase, "")
    text = text.replace("无不利", "利").replace("凶事", "事")
    negative = [w for w in ("无攸利", "无所利", "不利", "不吉", "不亨") if w in text]
    for phrase in negative:
        text = text.replace(phrase, "")
    positive = [w for w in ("悔亡", "有福", "有喜", "祉", "有尚", "血去惕出", "去逖出", "既平", "得黄金", "中行") if w in text]
    text = text.replace("悔亡", "")
    positive += [w for w in ("亨", "利") if w in text]
    negative += [w for w in ("厉", "吝", "悔", "遇毒", "有愠", "折其右肱", "灭顶", "濡其首", "不节", "赍涕洟") if w in text]
    good, bad = "吉" in text, "凶" in text
    endings = re.findall(r"(?:终|后)(吉|凶)", text)
    if endings:
        direction = 1 if endings[-1] == "吉" else -1
        level = "转吉" if direction > 0 else "转凶"
        bounds = (1, 3) if direction > 0 else (4, 10)
    elif good and bad:
        direction, level, bounds = 0, "吉凶参半", (0, 0)
    elif good:
        direction = 1
        level, bounds = ("小吉", (1, 3)) if negative else (("大吉", (4, 10)) if "元吉" in text or "大吉" in text else ("吉", (2, 6)))
    elif bad:
        direction, level, bounds = -1, "凶", (4, 10)
    else:
        score = len(positive) - len(negative)
        direction = (score > 0) - (score < 0)
        level = "小吉" if direction > 0 else "小凶" if direction < 0 else "平"
        bounds = (1, 3) if direction else (0, 0)
    if good: positive.append("吉")
    if bad: negative.append("凶")
    return {"direction": direction, "level": level, "magnitude_min": bounds[0], "magnitude_max": bounds[1], "positive": positive, "negative": negative, "no_blame": protected, "rule_version": VERSION}
