"""
站点关键词分级：仅 Ahrefs 六类搜索意图 + 价值分公式（见 docs/keyword-grading-scheme.md）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PRIMARY_INTENT_SPECS: tuple[tuple[str, str], ...] = (
    ("交易类", "is_transactional"),
    ("商业/比价类", "is_commercial"),
    ("导航/找品牌", "is_navigational"),
    ("品牌词", "is_branded"),
    ("本地类", "is_local"),
    ("信息类", "is_informational"),
)

INTENT_COEFFICIENTS: dict[str, float] = {
    "交易类": 1.5,
    "商业/比价类": 1.5,
    "导航/找品牌": 1.0,
    "品牌词": 1.0,
    "本地类": 1.1,
    "信息类": 1.0,
}

INTENT_PRIORITY_CEILING: dict[str, str | None] = {
    "交易类": None,
    "商业/比价类": None,
    "导航/找品牌": "P2",
    "品牌词": "P2",
    "本地类": "P2",
    "信息类": "P2",
}

PRIORITY_RANK: tuple[str, ...] = ("P0", "P1", "P2", "P3", "未分级")
DEFAULT_CPC = 0.5


def normalize_ahrefs_cpc(cpc: float | int | None) -> float | None:
    """Ahrefs API 的 cpc 为 USD 美分，需 ÷100 得到美元。"""
    if cpc is None:
        return None
    return float(cpc) / 100.0


def resolve_primary_intent(item: dict[str, Any]) -> str | None:
    for label, field in PRIMARY_INTENT_SPECS:
        if item.get(field):
            return label
    return None


def intent_coefficient(intent: str | None) -> float:
    if not intent:
        return 1.0
    return INTENT_COEFFICIENTS.get(intent, 1.0)


def score_keyword(
    *,
    volume: float | int | None,
    kd: float | int | None,
    cpc: float | int | None,
    intent: str | None,
) -> float | None:
    if volume is None or kd is None:
        return None
    vol = float(volume)
    difficulty = float(kd)
    normalized = normalize_ahrefs_cpc(cpc)
    cost = DEFAULT_CPC if normalized is None else normalized
    coeff = intent_coefficient(intent)
    raw = ((vol / 1000 * 60) + (cost * 80)) * coeff / (difficulty + 20) * 100
    return round(raw, 2)


def base_priority_from_score(score: float | None) -> str:
    if score is None:
        return "未分级"
    if score >= 70:
        return "P0"
    if score >= 50:
        return "P1"
    if score >= 30:
        return "P2"
    if score >= 15:
        return "P3"
    return "未分级"


def _priority_index(label: str) -> int:
    try:
        return PRIORITY_RANK.index(label)
    except ValueError:
        return len(PRIORITY_RANK) - 1


def _min_priority(a: str, b: str) -> str:
    """取更严（更低投入）的优先级：P0 最高，未分级最低。"""
    return a if _priority_index(a) >= _priority_index(b) else b


def _max_priority(a: str, b: str) -> str:
    return a if _priority_index(a) <= _priority_index(b) else b


def demote_priority(priority: str, steps: int = 1) -> str:
    idx = min(_priority_index(priority) + steps, len(PRIORITY_RANK) - 1)
    return PRIORITY_RANK[idx]


def apply_intent_ceiling(priority: str, intent: str | None) -> str:
    ceiling = INTENT_PRIORITY_CEILING.get(intent or "")
    if ceiling is None:
        return priority
    return _min_priority(priority, ceiling)


def apply_rank_kd_vol_adjustments(
    priority: str,
    *,
    score: float | None,
    rank: float | int | None,
    kd: float | int | None,
    volume: float | int | None,
) -> str:
    if score is None:
        return "未分级"

    result = priority
    rank_val = float(rank) if rank is not None else None

    if rank_val is not None and rank_val <= 10 and score >= 50 and result == "P0":
        result = "P1"
    if rank_val is not None and rank_val > 30 and score >= 70:
        result = "P0"

    not_top30 = rank_val is None or rank_val > 30
    if kd is not None and float(kd) > 60 and not_top30:
        result = demote_priority(result, 1)

    if volume is not None and float(volume) < 20:
        result = _min_priority(result, "P3")

    return result


@dataclass(frozen=True)
class KeywordGradeDetail:
    keyword: str
    volume: float | int | None
    kd: float | int | None
    cpc_cents: float | int | None
    cpc_usd: float | None
    rank: float | int | None
    intent: str | None
    intent_coef: float
    value_score: float | None
    base_priority: str
    after_intent_cap: str
    final_priority: str
    adjustments: tuple[str, ...]
    write_priority: bool


def _apply_rank_kd_vol_with_notes(
    priority: str,
    *,
    score: float | None,
    rank: float | int | None,
    kd: float | int | None,
    volume: float | int | None,
) -> tuple[str, list[str]]:
    if score is None:
        return "未分级", []

    result = priority
    notes: list[str] = []
    rank_val = float(rank) if rank is not None else None

    if rank_val is not None and rank_val <= 10 and score >= 50 and result == "P0":
        result = "P1"
        notes.append(f"排名≤10且分≥50: {priority}→P1")
    if rank_val is not None and rank_val > 30 and score >= 70:
        if result != "P0":
            notes.append(f"排名>30且分≥70: →P0")
        result = "P0"

    not_top30 = rank_val is None or rank_val > 30
    if kd is not None and float(kd) > 60 and not_top30:
        prev = result
        result = demote_priority(result, 1)
        notes.append(f"KD>60未进Top30: {prev}→{result}")

    if volume is not None and float(volume) < 20:
        prev = result
        result = _min_priority(result, "P3")
        if prev != result:
            notes.append(f"Vol<20: 最高P3 ({prev}→{result})")

    return result, notes


def grade_keyword(
    *,
    keyword: str,
    item: dict[str, Any],
    volume: float | int | None,
    kd: float | int | None,
    cpc: float | int | None,
    rank: float | int | None,
    write_priority: bool,
) -> KeywordGradeDetail:
    intent = resolve_primary_intent(item)
    coef = intent_coefficient(intent)
    cpc_usd = normalize_ahrefs_cpc(cpc)
    value_score = score_keyword(volume=volume, kd=kd, cpc=cpc, intent=intent)
    adjustments: list[str] = []

    if volume is None or kd is None:
        return KeywordGradeDetail(
            keyword=keyword,
            volume=volume,
            kd=kd,
            cpc_cents=cpc,
            cpc_usd=cpc_usd,
            rank=rank,
            intent=intent,
            intent_coef=coef,
            value_score=value_score,
            base_priority="未分级",
            after_intent_cap="未分级",
            final_priority="未分级",
            adjustments=("缺Vol或KD",),
            write_priority=write_priority,
        )

    base = base_priority_from_score(value_score)
    capped = apply_intent_ceiling(base, intent)
    if capped != base:
        ceiling = INTENT_PRIORITY_CEILING.get(intent or "")
        adjustments.append(f"意图上限{ceiling}: {base}→{capped}")

    final, rank_notes = _apply_rank_kd_vol_with_notes(
        capped,
        score=value_score,
        rank=rank,
        kd=kd,
        volume=volume,
    )
    adjustments.extend(rank_notes)

    return KeywordGradeDetail(
        keyword=keyword,
        volume=volume,
        kd=kd,
        cpc_cents=cpc,
        cpc_usd=cpc_usd,
        rank=rank,
        intent=intent,
        intent_coef=coef,
        value_score=value_score,
        base_priority=base,
        after_intent_cap=capped,
        final_priority=final,
        adjustments=tuple(adjustments),
        write_priority=write_priority,
    )


def assign_priority(
    *,
    volume: float | int | None,
    kd: float | int | None,
    cpc: float | int | None,
    rank: float | int | None,
    item: dict[str, Any],
) -> tuple[str | None, float | None, str | None]:
    """返回 (主意图, 价值分, 建议优先级)。"""
    detail = grade_keyword(
        keyword="",
        item=item,
        volume=volume,
        kd=kd,
        cpc=cpc,
        rank=rank,
        write_priority=True,
    )
    return detail.intent, detail.value_score, detail.final_priority


def format_grading_summary_lines(
    site_key: str,
    data_date: str,
    details: list[KeywordGradeDetail],
    *,
    created: int,
    updated: int,
    priority_skipped_manual: int,
) -> list[str]:
    lines = [
        f"站点关键词分级 ({site_key}) 锚点日={data_date}",
        f"  写入: 新建={created} 更新={updated} API词数={len(details)}",
        f"  自动写优先级={sum(1 for d in details if d.write_priority)} "
        f"保留人工优先级={priority_skipped_manual}",
    ]
    if not details:
        return lines

    intent_counts: dict[str, int] = {}
    final_counts: dict[str, int] = {}
    base_counts: dict[str, int] = {}
    adjusted = 0
    no_intent = 0
    for d in details:
        label = d.intent or "(无Intent)"
        intent_counts[label] = intent_counts.get(label, 0) + 1
        if d.intent is None:
            no_intent += 1
        final_counts[d.final_priority] = final_counts.get(d.final_priority, 0) + 1
        base_counts[d.base_priority] = base_counts.get(d.base_priority, 0) + 1
        if d.adjustments:
            adjusted += 1

    lines.append(f"  搜索意图分布: {dict(sorted(intent_counts.items()))}")
    lines.append(f"  分值档优先级(未微调): {dict(sorted(base_counts.items()))}")
    lines.append(f"  最终建议优先级: {dict(sorted(final_counts.items()))}")
    lines.append(f"  经规则微调词数: {adjusted}  无Intent词数: {no_intent}")

    ranked = sorted(
        [d for d in details if d.value_score is not None],
        key=lambda d: d.value_score or 0,
        reverse=True,
    )
    lines.append("  Top10 价值分 (keyword | vol | kd | cpc$ | rank | intent | 分 | 分值档→最终 | 微调):")
    for d in ranked[:10]:
        adj = ";".join(d.adjustments) if d.adjustments else "-"
        cpc_s = f"{d.cpc_usd:.2f}" if d.cpc_usd is not None else "-"
        lines.append(
            f"    {d.keyword[:48]} | vol={d.volume} kd={d.kd} cpc=${cpc_s} "
            f"rank={d.rank} {d.intent}({d.intent_coef}) score={d.value_score} "
            f"{d.base_priority}→{d.final_priority} | {adj}"
        )

    changed = [d for d in details if d.final_priority != d.base_priority or d.adjustments]
    if changed:
        lines.append(f"  分值档≠最终或有意图上限/微调 ({min(len(changed), 15)} 条示例):")
        for d in changed[:15]:
            adj = ";".join(d.adjustments) if d.adjustments else "-"
            lines.append(
                f"    {d.keyword[:40]} | {d.base_priority}→cap {d.after_intent_cap}→{d.final_priority} | {adj}"
            )

    return lines


def grading_detail_csv_row(d: KeywordGradeDetail) -> dict[str, Any]:
    return {
        "keyword": d.keyword,
        "volume": d.volume,
        "kd": d.kd,
        "cpc_cents": d.cpc_cents,
        "cpc_usd": d.cpc_usd,
        "rank": d.rank,
        "intent": d.intent,
        "intent_coef": d.intent_coef,
        "value_score": d.value_score,
        "base_priority": d.base_priority,
        "after_intent_cap": d.after_intent_cap,
        "final_priority": d.final_priority,
        "adjustments": ";".join(d.adjustments),
        "write_priority": d.write_priority,
    }


def priority_label_from_row_value(
    raw: str,
    priority_keys: dict[str, str],
) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw in priority_keys:
        return raw
    for label, key in priority_keys.items():
        if raw == key:
            return label
    return None


def should_auto_write_priority(
    raw_priority: str,
    *,
    priority_keys: dict[str, str],
) -> bool:
    """仅「未分级」或空值时自动写入优先级。"""
    label = priority_label_from_row_value(raw_priority, priority_keys)
    if label is None:
        return not raw_priority.strip()
    return label == "未分级"
