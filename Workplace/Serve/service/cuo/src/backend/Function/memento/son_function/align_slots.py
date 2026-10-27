import itertools
import regex
from collections import Counter


def similarity(a, b):
    if a == b:
        return 1.0
    ga = regex.findall(r'\X', a)
    gb = regex.findall(r'\X', b)
    la, lb = len(ga), len(gb)
    if la == 0 and lb == 0:
        return 1.0
    if la == 0 or lb == 0:
        return 0.0
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i]
        for j in range(1, lb + 1):
            cost = 0 if ga[i - 1] == gb[j - 1] else 1
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost))
        prev = curr
    return 1.0 - prev[lb] / max(la, lb)


def format_changes(changes):
    names = ["元谥", "亨谥", "利谥", "贞谥", "常谥", "平谥"]
    lines = []
    for ch in changes:
        slot = names[ch["slot"]]
        kind = ch["kind"]
        old = ch["old"] if ch["old"] is not None else "空"
        new = ch["new"] if ch["new"] is not None else "空"
        lines.append(f"{slot}: {kind} {old}→{new}")
    return "\n".join(lines)


def align_slots(old_slots, new_parts):
    if not isinstance(old_slots, list) or len(old_slots) != 6:
        raise ValueError("old_slots必须为长度6的列表")
    if not isinstance(new_parts, list) or not 1 <= len(new_parts) <= 6:
        raise ValueError("new_parts长度需在1到6之间")
    for i, v in enumerate(old_slots):
        if v is not None:
            if not isinstance(v, str):
                raise ValueError(f"槽位{i}必须是字符串或None")
            if v == "":
                raise ValueError(f"槽位{i}不允许空字符串")
    for i, v in enumerate(new_parts):
        if not isinstance(v, str):
            raise ValueError(f"new_parts[{i}]必须是字符串")
        if v == "":
            raise ValueError(f"new_parts[{i}]不允许空字符串")

    old_nonnull = [x for x in old_slots if x is not None]
    required_keep = sum((Counter(old_nonnull) & Counter(new_parts)).values())

    if all(v is None for v in old_slots):
        slots = [None] * 6
        for i, part in enumerate(new_parts):
            slots[i] = part
        changes = [
            {"slot": i, "kind": "insert", "old": None, "new": part}
            for i, part in enumerate(new_parts)
        ]
        return {"status": "aligned", "slots": slots, "changes": changes, "reason": ""}

    candidates = []
    combos = list(itertools.combinations(range(6), len(new_parts)))
    for combo in combos:
        slots = [None] * 6
        for idx, part in zip(combo, new_parts):
            slots[idx] = part
        keep = 0
        modify = 0
        cost = 0.0
        occupied = []
        for i in range(6):
            old = old_slots[i]
            new = slots[i]
            if old is not None and new is not None:
                occupied.append(i)
                if old == new:
                    keep += 1
                else:
                    sim = similarity(old, new)
                    if sim >= 0.60:
                        modify += 1
                        cost += 1 - sim
                    else:
                        cost += 1.30
            elif old is not None and new is None:
                cost += 0.65
            elif old is None and new is not None:
                cost += 0.65
        candidates.append((keep, cost, modify, combo, slots))

    candidates.sort(key=lambda x: (-x[0], x[1], x[2], x[3]))
    best = candidates[0]
    best_keep, best_cost, best_modify, best_combo, best_slots = best

    reason = ""
    if best_keep < required_keep:
        status = "needs_review"
        reason = f"可保留旧词数{best_keep}<应保留{required_keep}，可能存在换序或丢失"
    else:
        second = None
        for cand in candidates[1:]:
            if cand[0] == best_keep:
                second = cand
                break
        if second and second[1] - best_cost < 0.15:
            status = "needs_review"
            reason = f"次优候选({second[3]})代价差{second[1]-best_cost:.3f}<0.15"
        else:
            status = "aligned"

    changes = []
    for i in range(6):
        old = old_slots[i]
        new = best_slots[i]
        if old == new:
            continue
        if old is None and new is not None:
            changes.append({"slot": i, "kind": "insert", "old": None, "new": new})
        elif old is not None and new is None:
            changes.append({"slot": i, "kind": "delete", "old": old, "new": None})
        else:
            sim = similarity(old, new)
            if sim >= 0.60:
                changes.append({"slot": i, "kind": "modify", "old": old, "new": new})
            else:
                changes.append({"slot": i, "kind": "replace", "old": old, "new": new})

    result = {
        "status": status,
        "slots": best_slots,
        "changes": changes,
        "reason": reason,
    }
    if status == "needs_review":
        result["candidate_slots"] = [cand[4] for cand in candidates if cand[0] == best_keep][:2]
    return result
