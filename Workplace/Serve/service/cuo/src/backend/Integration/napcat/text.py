# Drafted by DS-Flash, reviewed and tested in this workspace.
def split_text(text: str, limit: int = 1500, reserve: int = 20) -> list[str]:
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit <= 0
        or not isinstance(reserve, int)
        or isinstance(reserve, bool)
        or reserve < 0
        or reserve >= limit
    ):
        raise ValueError("invalid limit or reserve")

    if len(text) <= limit:
        return [text]

    window = limit - reserve
    chunks: list[str] = []
    pos = 0
    total = len(text)

    while pos < total:
        sub = text[pos:pos + window]
        cut = sub.rfind("\n\n")
        if cut != -1:
            cut += 2
        else:
            cut = sub.rfind("\n")
            if cut != -1:
                cut += 1
            else:
                cut = len(sub)

        if cut <= 0:
            raise ValueError("split made no progress")

        chunks.append(text[pos:pos + cut])
        pos += cut

    n = len(chunks)
    result: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        prefixed = f"({i}/{n})\n{chunk}"
        if len(prefixed) > limit:
            raise ValueError("prefixed chunk exceeds limit")
        result.append(prefixed)

    return result
