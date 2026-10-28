from .readings import select_reading

def render(zhou, tarot, ai, luck_delta, fortune_after):
    reading = zhou.get("reading") or select_reading(zhou)
    base = zhou["base"]
    heading = f'{base["symbol"]} {base["name"]}'
    if zhou["has_change"]:
        changed = zhou["changed"]
        heading += f' → {changed["symbol"]} {changed["name"]}'
    delta = f"{luck_delta:+d}" if luck_delta else "0"
    return (
        f'{heading} | {reading["title"]}\n\n'
        f'塔罗｜{tarot["name"]} · {tarot["orientation"]}\n\n'
        f'「{reading["primary"]["text_display"]}」\n\n'
        f'解卦\n{reading["interpretation"]}\n\n'
        f'应事 · {ai["keyword"]}\n{ai["advice"]}\n\n'
        f'卦运 {delta} · 福缘 {fortune_after}\n\n'
        f'{reading["closing"]}'
    )

'''
{zhou.base.symbol/本卦符号} {zhou.base.name/本卦名称} → {zhou.changed.symbol/变卦符号} {zhou.changed.name/变卦名称} | {ai.title/卦题}

塔罗｜{tarot.name/塔罗牌名} · {tarot.orientation/正逆位}
{action.segments中type=image的消息段/塔罗牌图片}

「{dictum.primary.text_display/主断辞}」

解卦
{ai.interpretation/解卦内容}

应事 · {ai.keyword/应事主题}
{ai.advice/应事内容}

卦运 {luck_delta/本次卦运增减，正数带+号} · 福缘 {fortune_after/结算后福缘}

{ai.closing/收尾签语}
'''
