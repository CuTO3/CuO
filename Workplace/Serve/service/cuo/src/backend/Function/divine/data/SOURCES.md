# 周易原文来源
原文为公版古籍《周易》，来自维基文库各卦页面的原始维基文本。每条数据保留 source_url、原始响应的 SHA-256 和 text_version；不包含现代译文。64 卦 Unicode 字符遵循 U+4DC0 至 U+4DFF 的文王卦序。
- https://zh.wikisource.org/wiki/周易
- https://www.unicode.org/charts/PDF/U4DC0.pdf
卦序、名称与上下卦元数据参考 https://github.com/muyen/decoding-iching 的 data/zhouyi-64gua/zhouyi_64gua.json；其爻辞未采用。
hexagrams.json 的卦名、上下卦名、卦辞、爻辞及用九/用六文本已使用 OpenCC t2s 转为简体，保留易学用字“乾”，避免误转为“干”；text_version 为 wikisource-2026-10-26-hans-v1。source_sha256 仍指向来源原始响应，并非转换后的 JSON 文件。text_display 使用此简体文本。导入不等于逐字人工校勘；版本升级需要保留既有占卜结果中的引文。

固定解卦资料：hexagrams.json 新增 interpretation、reading_title、theme 为本项目编写的游戏用卦义，不属于维基文库原文。readings.json 为覆盖 4096 种变化的固定资料初版，editorial_status=initial_rule_composed，以主断辞选择规则、爻位、固定卦义和游戏吉凶规则编排，非逐条人工校勘的学术注释。每条 primary、auxiliary 保留原文来源。
