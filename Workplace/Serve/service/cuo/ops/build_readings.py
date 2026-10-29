"""Build the checked-in 4096-case catalog from fixed editorial materials.

Run from the project root: PYTHONPATH=src/backend python -m ops.build_readings
This creates an initial rule-composed edition, not 4096 independently vetted essays.
Runtime uses the saved catalog; editing its entries does not require calling AI.
"""
import itertools
import json

from Function.divine.son_function.dictum import select_dictum
from Function.divine.son_function.luck import assess_dictum
from Function.divine.son_function.readings import VERSION, reading_key
from Core.configuration import load, resource
CONFIG = load("ops_build_readings_config")
from Function.divine.son_function.zhou_yi import from_lines, load_hexagrams

GUIDANCE = {
    "转吉": ("先难后吉", "前段须经整顿，后势尚有转机，宜耐心处置，不可半途而废。", "先解其结，后承其吉。"),
    "转凶": ("顺中防险", "后势有不利之兆，宜收敛行动，预留退路，勿恃初时之顺。", "顺时知戒，未雨绸缪。"),
    "大吉": ("吉势可承", "吉意较明，宜持正有所作为，不因顺遂而失于轻率。", "得时而进，持正而行。"),
    "吉": ("守正得吉", "行事有利，宜把握可行之机，以诚信与节度承接其利。", "顺势有为，进退有节。"),
    "小吉": ("小有所获", "可于小处求进，宜先成眼前之事，渐积其功。", "积小成善，渐有所获。"),
    "小凶": ("谨行避失", "事有警示，宜先查疏漏、减其负担，暂缓冒进。", "谨慎其行，先安其本。"),
    "凶": ("见险宜守", "不利之象较明，宜止险守成，先整顿问题，再图后进。", "知险而止，守正待时。"),
    "吉凶参半": ("审势取舍", "利害条件并存，宜辨明所处情势，不可一概以吉凶论之。", "审其所处，择善而行。"),
    "平": ("守常待时", "未见明确吉凶，宜依常理行事；无咎重在免于过失，不等于诸事皆吉。", "守常有度，从容待时。"),
}
POSITION = {1: "初处其事，宜慎始立本。", 2: "处内得中，宜以诚实稳其根基。", 3: "居内外之交，进退尤须审慎。", 4: "初临外境，宜辨明职责与所依。", 5: "居任事之位，宜兼顾大局与众人。", 6: "事至其极，宜防过度，审其终局。", 7: "六爻皆变，宜通观全局，不执一端。"}


def build():
    table = load_hexagrams()
    by_number = {h["number"]: h for h in table}
    records = {}
    for values in itertools.product((6, 7, 8, 9), repeat=6):
        z = from_lines(list(values), table)
        q = select_dictum(z)
        a = assess_dictum(q)
        title, guidance, closing = GUIDANCE[a["level"]]
        primary = q["primary"]
        h = by_number[primary["hexagram_number"]]
        position = primary["line_position"]
        interpretation = z["base"]["interpretation"]
        if z["has_change"]:
            interpretation += f'本次以{primary["source_label"]}为主断。'
            if h["number"] != z["base"]["number"]:
                interpretation += h["interpretation"]
            if position:
                interpretation += POSITION[position]
            if z["changed"]["number"] != h["number"]:
                interpretation += f'后势转入{z["changed"]["short_name"]}，{z["changed"]["interpretation"]}'
        interpretation += guidance
        if h["number"] == 11 and position == 3:
            a.update(direction=1, level="小吉", magnitude_min=1, magnitude_max=3)
            title, closing = "顺中有变，临事有度", "顺势而不恃势，进取亦知分寸。"
            interpretation = "平陂往复，盛衰有常。泰至九三，通达之势渐有转折；宜居安思变，持正知节，艰难之中仍可免于过失。"
            if z["changed"]["number"] == 19:
                interpretation += "变卦为临，临事尤须审势，进退皆当留有余地。"
        a["rule_version"] = VERSION
        records[reading_key(z)] = {
            "key": reading_key(z), "base_number": z["base"]["number"],
            "moving_lines": z["moving_lines"], "changed_number": z["changed"]["number"],
            "title": title, "primary": primary, "auxiliary": q["auxiliary"],
            "interpretation": interpretation, "fortune": a,
            "theme": h["theme"], "closing": closing,
            "fallback_advice": f'今日可留意“{h["theme"]}”相关的小事。先辨明眼前条件，再决定进退。',
            "editorial_status": "initial_rule_composed", "version": VERSION,
        }
    assert len(records) == 4096
    document = {"version": VERSION, "editorial_status": "initial_rule_composed", "readings": records}
    resource(CONFIG["ops_readings_output_file"]).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(records)} fixed readings")


if __name__ == "__main__":
    build()
