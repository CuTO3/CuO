def render(zhou,tarot,dictum,ai,luck_delta,fortune_after):
    base=zhou["base"];changed=zhou["changed"]
    first=f'{base["symbol"]} {base["name"]}'
    if zhou["has_change"]:first+=f' → {changed["symbol"]} {changed["name"]}'
    names=[]
    for pos in sorted(zhou["moving_lines"]):
        stem="九" if zhou["line_values"][pos-1] in (7,9) else "六"
        names.append("初"+stem if pos==1 else "上"+stem if pos==6 else stem+"一二三四五六"[pos-1])
    second="、".join(names)+" · 有变卦" if names else "无动爻 · 无变卦"
    delta=f"{luck_delta:+d}" if luck_delta else "0"
    return (f'{first}\n{second}\n塔罗｜{tarot["name"]} · {tarot["orientation"]}\n\n'
            f'「{dictum["primary"]["text_display"]}」\n\n今日应事 · {ai["keyword"]}\n{ai["advice"]}\n\n'
            f'卦运 {delta} · 福缘 {fortune_after}')
