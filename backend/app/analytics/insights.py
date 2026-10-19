from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def parse_timestamp(value: str | datetime, tz: ZoneInfo) -> datetime:
    """Parse an ISO 8601 string or datetime and normalize to the target timezone."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=tz)
        return value.astimezone(tz)

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def get_period_window(
    period: Literal["week", "last_week", "all"] | str,
    reference_time: datetime,
    user_tz: ZoneInfo,
) -> tuple[datetime | None, datetime | None]:
    """Calculate the ISO 8601 period window based on K-8.

    K-8:
    - User's registered IANA timezone is the sole authority.
    - Week starts Monday 00:00:00.000000 and ends Sunday 23:59:59.999999.
    """
    ref_dt = (
        reference_time.astimezone(user_tz)
        if reference_time.tzinfo
        else reference_time.replace(tzinfo=user_tz)
    )
    ref_date = ref_dt.date()
    weekday_idx = ref_date.weekday()  # Monday = 0, Sunday = 6
    this_monday = ref_date - timedelta(days=weekday_idx)
    this_sunday = this_monday + timedelta(days=6)

    if period == "week":
        start_dt = datetime.combine(this_monday, time.min, tzinfo=user_tz)
        end_dt = datetime.combine(this_sunday, time.max, tzinfo=user_tz)
        return start_dt, end_dt
    elif period == "last_week":
        last_monday = this_monday - timedelta(days=7)
        last_sunday = this_sunday - timedelta(days=7)
        start_dt = datetime.combine(last_monday, time.min, tzinfo=user_tz)
        end_dt = datetime.combine(last_sunday, time.max, tzinfo=user_tz)
        return start_dt, end_dt
    elif period == "all":
        return None, None
    else:
        raise ValueError(f"Unsupported period: {period}")


def calculate_insights(
    plans: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    period: Literal["week", "last_week", "all"] | str,
    reference_time: datetime,
    user_timezone: str = "Europe/Istanbul",
    is_demo: bool = False,
) -> dict[str, Any]:
    """Pure, deterministic GAP analysis adherence engine.

    Calculates all metrics required by docs/api-contract.md:
    - planned, done, postponed, skipped, unreported
    - adherence_pct
    - avg_start_delay_min
    - by_weekday
    - by_hour
    - by_category
    - postponed_targets
    - trend_vs_prev, narrative, is_demo, data_label

    Constraints:
    - Pure Python: no FastAPI or database dependencies.
    - Deterministic: no system clock access; relies strictly on reference_time.
    - Invariant: planned == done + postponed + skipped + unreported.
    """
    if reference_time is None:
        raise ValueError("reference_time must be explicitly provided.")

    try:
        user_tz = ZoneInfo(user_timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Invalid timezone: {user_timezone}") from exc

    ref_dt = parse_timestamp(reference_time, user_tz)
    window_start, window_end = get_period_window(period, ref_dt, user_tz)

    # 1. Filter and sort evaluated plans deterministically by planned_start ascending, then id ascending
    evaluated_plans: list[dict[str, Any]] = []
    for plan in plans:
        start_dt = parse_timestamp(plan["planned_start"], user_tz)
        if window_start is not None and start_dt < window_start:
            continue
        if window_end is not None and start_dt > window_end:
            continue
        # Exclude plans scheduled strictly after reference_time (future plans)
        if start_dt > ref_dt:
            continue
        evaluated_plans.append(plan)

    evaluated_plans.sort(
        key=lambda p: (
            parse_timestamp(p["planned_start"], user_tz),
            str(p.get("id", "")),
        )
    )

    # 2. Map outcomes by plan_id
    # Indexing order in DB: (plan_id, user_id, reported_at DESC, id DESC)
    plan_outcomes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for outcome in outcomes:
        pid = str(outcome.get("plan_id", ""))
        plan_outcomes[pid].append(outcome)

    latest_outcomes: dict[str, dict[str, Any]] = {}
    for pid, p_outs in plan_outcomes.items():
        sorted_outs = sorted(
            p_outs,
            key=lambda o: (
                parse_timestamp(o.get("reported_at"), user_tz)
                if o.get("reported_at")
                else datetime.min.replace(tzinfo=user_tz),
                str(o.get("id", "")),
            ),
            reverse=True,
        )
        if sorted_outs:
            latest_outcomes[pid] = sorted_outs[0]

    # 3. Calculate adherence and categorical distributions
    planned = len(evaluated_plans)
    done_count = 0
    postponed_count = 0
    skipped_count = 0
    unreported_count = 0
    delays_min: list[float] = []

    by_weekday_map: dict[str, dict[str, int]] = defaultdict(
        lambda: {"planned": 0, "done": 0, "postponed": 0}
    )
    by_hour_map: dict[str, dict[str, int]] = defaultdict(
        lambda: {"planned": 0, "done": 0}
    )
    by_category_map: dict[str, dict[str, int]] = defaultdict(
        lambda: {"planned": 0, "done": 0}
    )

    for plan in evaluated_plans:
        pid = str(plan.get("id", ""))
        start_dt = parse_timestamp(plan["planned_start"], user_tz)
        weekday = WEEKDAYS[start_dt.weekday()]
        hour_str = f"{start_dt.hour:02d}"
        category = str(plan.get("category", "other"))

        by_weekday_map[weekday]["planned"] += 1
        by_hour_map[hour_str]["planned"] += 1
        by_category_map[category]["planned"] += 1

        latest = latest_outcomes.get(pid)
        if latest is None:
            unreported_count += 1
        else:
            status = latest.get("status")
            if status == "done":
                done_count += 1
                by_weekday_map[weekday]["done"] += 1
                by_hour_map[hour_str]["done"] += 1
                by_category_map[category]["done"] += 1

                actual_start_raw = latest.get("actual_start")
                if actual_start_raw is not None:
                    actual_start_dt = parse_timestamp(actual_start_raw, user_tz)
                    delay = (actual_start_dt - start_dt).total_seconds() / 60.0
                    delays_min.append(delay)
            elif status == "postponed":
                postponed_count += 1
                by_weekday_map[weekday]["postponed"] += 1
            elif status == "skipped":
                skipped_count += 1
            else:
                unreported_count += 1

    # Invariant verification: planned == done + postponed + skipped + unreported
    assert planned == (
        done_count + postponed_count + skipped_count + unreported_count
    ), "Invariant violation: planned != done + postponed + skipped + unreported"

    # 4. Adherence percentage
    reported_total = done_count + postponed_count + skipped_count
    if reported_total == 0:
        adherence_pct = None
    else:
        adherence_pct = round((done_count / reported_total) * 100.0, 1)

    # 5. Average start delay in minutes
    if not delays_min:
        avg_start_delay_min = None
    else:
        avg_start_delay_min = round(sum(delays_min) / len(delays_min))

    # 6. Structured groupings (only include keys where planned > 0)
    # by_weekday: ordered Monday..Sunday
    by_weekday: dict[str, dict[str, int]] = {}
    for d in WEEKDAYS:
        if d in by_weekday_map and by_weekday_map[d]["planned"] > 0:
            by_weekday[d] = dict(by_weekday_map[d])

    # by_hour: ordered numerically (e.g. "07", "08", "14")
    by_hour: dict[str, dict[str, int]] = {}
    for h in sorted(by_hour_map.keys()):
        if by_hour_map[h]["planned"] > 0:
            by_hour[h] = dict(by_hour_map[h])

    # by_category: ordered by appearance in evaluated plans
    by_category: dict[str, dict[str, int]] = {}
    for c in by_category_map.keys():
        if by_category_map[c]["planned"] > 0:
            by_category[c] = dict(by_category_map[c])

    # 7. Postponed targets pattern analysis
    # Contract: "tüm 'postponed' olayları örüntü analizine dahil edilir."
    # Analyze all outcomes passed for the user that have status == 'postponed' and postponed_to is not None
    postponed_target_counts: dict[tuple[str, int], int] = defaultdict(int)
    for outcome in outcomes:
        if outcome.get("status") == "postponed":
            pto_raw = outcome.get("postponed_to")
            if pto_raw:
                pto_dt = parse_timestamp(pto_raw, user_tz)
                p_weekday = WEEKDAYS[pto_dt.weekday()]
                p_hour = pto_dt.hour
                postponed_target_counts[(p_weekday, p_hour)] += 1

    postponed_targets: list[dict[str, Any]] = []
    # Deterministik sıralama: önce hafta günü (Pzt..Paz), sonra hedef saat
    for (pw, ph) in sorted(
        postponed_target_counts.keys(),
        key=lambda item: (WEEKDAYS.index(item[0]), item[1]),
    ):
        postponed_targets.append({
            "weekday": pw,
            "hour": ph,
            "count": postponed_target_counts[(pw, ph)],
        })

    return {
        "period": period,
        "planned": planned,
        "done": done_count,
        "postponed": postponed_count,
        "skipped": skipped_count,
        "unreported": unreported_count,
        "adherence_pct": adherence_pct,
        "avg_start_delay_min": avg_start_delay_min,
        "by_weekday": by_weekday,
        "by_hour": by_hour,
        "by_category": by_category,
        "postponed_targets": postponed_targets,
        "trend_vs_prev": None,
        "narrative": None,
        "is_demo": is_demo,
        "data_label": "demo" if is_demo else "real",
    }
