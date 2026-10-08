"""打卡归属与日考勤计算。

业务规则（业务方确认）：
- 排班来自 OA（不落库），按班次定义上下班时间
- 后勤人员：每天 2 次卡（上班 / 下班）
- 车间人员：每天 4 次卡（上午上下班 + 下午上下班）
- 跨天班次：下班时间在次日，考勤日按「班次开始的那一天」（归前一天）
- 月度考勤时长 = 各时段实际打卡区间之和（暂不扣减迟到早退）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from services.oa_schedule import OaScheduleDay, OaWorktime, _minutes

OFFICE = '后勤'
WORKSHOP = '车间'

# 打卡与应打卡时间点的最大允许偏差（分钟）；超出则不归属该卡
DEFAULT_MATCH_WINDOW_MINUTES = 180


@dataclass
class SegmentPunch:
    start_expected: datetime | None
    end_expected: datetime | None
    check_in: datetime | None = None
    check_out: datetime | None = None

    @property
    def work_minutes(self) -> int:
        if self.check_in is None or self.check_out is None:
            return 0
        return max(0, int((self.check_out - self.check_in).total_seconds() // 60))


@dataclass
class DailyAttribution:
    work_date: date
    person_id: int
    worktime_ids: tuple[int, ...]
    is_rest: bool
    expected_points: list[datetime] = field(default_factory=list)
    segments: list[SegmentPunch] = field(default_factory=list)
    check_in: datetime | None = None
    check_out: datetime | None = None
    check_in_fixed: bool = False
    check_out_fixed: bool = False
    actual_punches: int = 0
    missing_points: int = 0
    excused_points: int = 0
    work_hours: Decimal = Decimal('0.00')
    overtime_hours: Decimal = Decimal('0.00')
    leave_hours: Decimal = Decimal('0.00')
    cover_hours: Decimal = Decimal('0.00')
    event_labels: list[str] = field(default_factory=list)
    punch_times: list[datetime] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.is_rest:
            return 'rest'
        if self.missing_points and self.actual_punches == 0:
            return 'absent'
        if self.missing_points:
            return 'missing_card'
        if self.excused_points and self.work_hours <= 0:
            return 'leave'
        return 'normal'


def _subtract_intervals(
    base: tuple[datetime, datetime],
    cuts: list[tuple[datetime, datetime]],
) -> int:
    """从 base 时间段里扣除 cuts（可重叠），返回剩余分钟数。"""
    remaining = [(base[0], base[1])]
    for cut_start, cut_end in cuts:
        if cut_end <= cut_start:
            continue
        next_remaining = []
        for seg_start, seg_end in remaining:
            if cut_end <= seg_start or cut_start >= seg_end:
                next_remaining.append((seg_start, seg_end))
                continue
            if cut_start > seg_start:
                next_remaining.append((seg_start, cut_start))
            if cut_end < seg_end:
                next_remaining.append((cut_end, seg_end))
        remaining = next_remaining
    total = 0
    for seg_start, seg_end in remaining:
        total += max(0, int((seg_end - seg_start).total_seconds() // 60))
    return total


def _clamp_start(actual: datetime | None, scheduled: datetime | None) -> datetime | None:
    if actual is None:
        return None
    if scheduled is None:
        return actual
    return max(actual, scheduled)


def _clamp_end(actual: datetime | None, scheduled: datetime | None) -> datetime | None:
    if actual is None:
        return None
    if scheduled is None:
        return actual
    return min(actual, scheduled)


def _union_minutes(windows: list[tuple[datetime, datetime]]) -> int:
    items = sorted((start, end) for start, end in windows if end > start)
    total = 0
    current_start = None
    current_end = None
    for start, end in items:
        if current_start is None:
            current_start, current_end = start, end
        elif start <= current_end:
            current_end = max(current_end, end)
        else:
            total += int((current_end - current_start).total_seconds() // 60)
            current_start, current_end = start, end
    if current_start is not None:
        total += int((current_end - current_start).total_seconds() // 60)
    return total


def _intersect_windows(
    first: list[tuple[datetime, datetime]],
    second: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    result = []
    for start_a, end_a in first:
        for start_b, end_b in second:
            start = max(start_a, start_b)
            end = min(end_a, end_b)
            if end > start:
                result.append((start, end))
    return result


def _to_hours(minutes: int) -> Decimal:
    minutes = _round_down_half_hour(minutes)
    return (Decimal(minutes) / Decimal(60)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _is_excused(point: datetime, windows: list[tuple[datetime, datetime]]) -> bool:
    for start, end in windows:
        if start <= point <= end:
            return True
    return False


def _point_datetime(work_date: date, hhmm: str, *, next_day: bool = False) -> datetime | None:
    minutes = _minutes(hhmm)
    if minutes is None:
        return None
    base = datetime.combine(work_date, time(0, 0)) + timedelta(minutes=minutes)
    if next_day:
        base += timedelta(days=1)
    return base


def expected_points_for_day(
    work_date: date,
    worktimes: list[OaWorktime],
    employee_type: str,
) -> tuple[list[datetime], list[tuple[datetime | None, datetime | None]]]:
    """返回应打卡时间点与时段。

    - 后勤：整个工作日记 2 个点（第一个时段上班、最后一个时段下班）
    - 车间：每个时段记 2 个点（该时段上下班）
    """
    ordered = sorted(worktimes, key=lambda wt: (_minutes(wt.start_time) or 0))
    segments = []
    for wt in ordered:
        start = _point_datetime(work_date, wt.start_time)
        end = _point_datetime(work_date, wt.end_time, next_day=wt.crosses_midnight)
        if start is None or end is None:
            continue
        segments.append((start, end))

    if not segments:
        return [], []

    if employee_type == OFFICE:
        points = [segments[0][0], segments[-1][1]]
        merged = [(segments[0][0], segments[-1][1])]
        return points, merged

    # 车间：每个时段上下班各一次
    points = [point for segment in segments for point in segment]
    return points, segments


def _round_down_half_hour(minutes: int) -> int:
    """按半小时往前取整：451分钟 → 450，470分钟 → 450，480分钟 → 480。"""
    return (minutes // 30) * 30


def _assign_punch(
    point: datetime,
    punches: list[datetime],
    used: set[int],
    window_minutes: int,
) -> datetime | None:
    best_index = None
    best_delta = None
    for index, punch in enumerate(punches):
        if index in used:
            continue
        delta = abs((punch - point).total_seconds())
        if delta > window_minutes * 60:
            continue
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_index = index
    if best_index is None:
        return None
    used.add(best_index)
    return punches[best_index]


def attribute_day(
    *,
    work_date: date,
    person_id: int,
    employee_type: str,
    schedule: OaScheduleDay | None,
    worktime_map: dict[int, OaWorktime],
    punches: list[datetime],
    window_minutes: int = DEFAULT_MATCH_WINDOW_MINUTES,
    deduct_windows: list[tuple[datetime, datetime]] | None = None,
    cover_windows: list[tuple[datetime, datetime]] | None = None,
    overtime_hours_override: Decimal | None = None,
    event_labels: list[str] | None = None,
    fix_punches: list[datetime] | None = None,
) -> DailyAttribution:
    """计算某人某天的打卡归属。punches 为已按时间升序的打卡时间。

    deduct_windows：请假/调休时段（扣工时、免缺卡）。
    cover_windows：外出/出差时段（当前仅免缺卡并标记，不扣工时）。
    overtime_hours_override：后勤加班单时长（覆盖打卡加班）。
    fix_punches：来自 OA 补卡单的补卡时间点（用于标记上下班是否为补卡）。
    """
    worktime_ids = schedule.worktime_ids if schedule else ()
    worktimes = [worktime_map[wid] for wid in worktime_ids if wid in worktime_map]

    result = DailyAttribution(
        work_date=work_date,
        person_id=person_id,
        worktime_ids=worktime_ids,
        is_rest=not worktimes,
        actual_punches=len(punches),
        event_labels=list(event_labels or []),
    )
    # 后勤加班以申请单时长为准，休息日也照算（车间仍按打卡）
    if employee_type == OFFICE and overtime_hours_override:
        result.overtime_hours = Decimal(overtime_hours_override).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
    ordered_punches = sorted(punches)
    result.punch_times = ordered_punches
    if not worktimes:
        return result

    deduct = list(deduct_windows or [])
    cover = list(cover_windows or [])
    # 只有请假/调休会被免缺卡并扣工时；外出/出差当前仅标记（业务待定）。
    excuse_windows = deduct

    points, segments = expected_points_for_day(work_date, worktimes, employee_type)
    result.expected_points = points
    ordered_punches = sorted(punches)

    used: set[int] = set()
    assigned: list[datetime | None] = []
    missing = 0
    excused = 0
    for point in points:
        matched = _assign_punch(point, ordered_punches, used, window_minutes)
        assigned.append(matched)
        if matched is not None:
            continue
        if _is_excused(point, excuse_windows):
            excused += 1
        else:
            missing += 1
    result.missing_points = missing
    result.excused_points = excused

    if employee_type == OFFICE:
        # 后勤只有 2 个应打卡点（首段上班、末段下班），但实际打卡可能因请假/早退
        # 只有一次或落在段中间；这里按「排班窗口内最早/最晚卡」作为实际上下班。
        sched_start = segments[0][0] if segments else None
        sched_end = segments[-1][1] if segments else None
        window = timedelta(minutes=window_minutes)
        day_punches = ordered_punches
        if sched_start is not None and sched_end is not None:
            day_punches = [
                punch for punch in ordered_punches
                if (sched_start - window) <= punch <= (sched_end + window)
            ]
        actual_in = min(day_punches) if day_punches else None
        actual_out = max(day_punches) if day_punches else None
        result.segments = [SegmentPunch(
            start_expected=sched_start,
            end_expected=sched_end,
            check_in=actual_in,
            check_out=actual_out,
        )]
        result.check_in = actual_in
        result.check_out = actual_out
    else:
        built = []
        cursor = 0
        for start, end in segments:
            built.append(SegmentPunch(
                start_expected=start,
                end_expected=end,
                check_in=assigned[cursor] if cursor < len(assigned) else None,
                check_out=assigned[cursor + 1] if cursor + 1 < len(assigned) else None,
            ))
            cursor += 2
        result.segments = built
        # 实际打卡时间（展示用）
        valid_in = [seg.check_in for seg in result.segments if seg.check_in]
        valid_out = [seg.check_out for seg in result.segments if seg.check_out]
        result.check_in = min(valid_in) if valid_in else None
        result.check_out = max(valid_out) if valid_out else None

    fix_set = set(fix_punches or [])
    if fix_set:
        result.check_in_fixed = result.check_in in fix_set
        result.check_out_fixed = result.check_out in fix_set

    # 工时计算口径（业务确认）：
    #   上班取大值 max(实际打卡, 排班开始) → 早到不算工时，迟到从实际时间算
    #   下班取小值 min(实际打卡, 排班结束) → 晚走不算工时（加班另接加班单），早走算到实际时间
    #   扣掉班次间的休息空档（如午休 11:30~13:00）与请假/调休时段
    scheduled_segments: list[tuple[datetime, datetime]] = []
    for wt in sorted(worktimes, key=lambda w: (_minutes(w.start_time) or 0)):
        seg_start = _point_datetime(work_date, wt.start_time)
        seg_end = _point_datetime(work_date, wt.end_time, next_day=wt.crosses_midnight)
        if seg_start and seg_end:
            scheduled_segments.append((seg_start, seg_end))

    if employee_type == OFFICE:
        sched_start = scheduled_segments[0][0] if scheduled_segments else None
        sched_end = scheduled_segments[-1][1] if scheduled_segments else None

        rest_gaps: list[tuple[datetime, datetime]] = []
        for i in range(len(scheduled_segments) - 1):
            gap_start = scheduled_segments[i][1]
            gap_end = scheduled_segments[i + 1][0]
            if gap_end > gap_start:
                rest_gaps.append((gap_start, gap_end))

        # 必须有实际上下班两次卡才计工时；缺卡不计（避免把「无打卡」当成满勤）。
        if result.check_in and result.check_out:
            effective_in = _clamp_start(result.check_in, sched_start)
            effective_out = _clamp_end(result.check_out, sched_end)
            if effective_in and effective_out and effective_out > effective_in:
                total_minutes = _subtract_intervals(
                    (effective_in, effective_out), rest_gaps + deduct,
                )
            else:
                total_minutes = 0
        else:
            total_minutes = 0
    else:
        # 车间：每段独立计算，同样用 clamp 规则
        total_minutes = 0
        for seg in result.segments:
            seg_eff_in = _clamp_start(seg.check_in, seg.start_expected)
            seg_eff_out = _clamp_end(seg.check_out, seg.end_expected)
            if seg_eff_in and seg_eff_out and seg_eff_out > seg_eff_in:
                total_minutes += _subtract_intervals((seg_eff_in, seg_eff_out), deduct)

    # 按半小时往前取整
    total_minutes = _round_down_half_hour(total_minutes)
    result.work_hours = (Decimal(total_minutes) / Decimal(60)).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )

    # 请假/调休、外出/出差与排班的交叠时长（展示与汇总核对用）
    if deduct:
        result.leave_hours = _to_hours(_union_minutes(_intersect_windows(deduct, scheduled_segments)))
    if cover:
        result.cover_hours = _to_hours(_union_minutes(_intersect_windows(cover, scheduled_segments)))

    # 加班计算：
    #   后勤 —— 以加班申请单时长为准（业务确认）
    #   车间 —— 实际（当天最后一次）打卡晚于排班结束的部分，按半小时取整。
    #          注意不能用段内匹配的 check_out：下班后很久的加班卡（如 21:00）
    #          超出匹配窗口不会归到任何段，会被漏算。
    if employee_type == OFFICE:
        if overtime_hours_override:
            result.overtime_hours = Decimal(overtime_hours_override).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
    elif employee_type == WORKSHOP and ordered_punches:
        scheduled_ends = [
            seg.end_expected for seg in result.segments if seg.end_expected
        ]
        if scheduled_ends:
            sched_end_time = max(scheduled_ends)
            last_punch = ordered_punches[-1]
            if last_punch > sched_end_time:
                ot_minutes = int((last_punch - sched_end_time).total_seconds() // 60)
                ot_minutes = _round_down_half_hour(ot_minutes)
                if ot_minutes > 0:
                    result.overtime_hours = (Decimal(ot_minutes) / Decimal(60)).quantize(
                        Decimal('0.01'), rounding=ROUND_HALF_UP
                    )

    return result


def attribute_person_month(
    *,
    employee_type: str,
    person_id: int,
    month_start: date,
    month_end: date,
    schedule_days: list[OaScheduleDay],
    worktime_map: dict[int, OaWorktime],
    punches_by_date: dict[date, list[datetime]],
    window_minutes: int = DEFAULT_MATCH_WINDOW_MINUTES,
    day_contexts: dict[date, object] | None = None,
    fix_punches: list[datetime] | None = None,
) -> list[DailyAttribution]:
    """按天计算某人一个月的打卡归属。

    punches_by_date 的键是**考勤日**（跨天打卡已归到班次开始日）。
    day_contexts 可提供每天的单据信息（deduct_windows / cover_windows /
    overtime_hours / labels 属性）。
    """
    schedule_by_date = {
        day.schedule_date: day for day in schedule_days if day.person_id == person_id
    }
    contexts = day_contexts or {}
    results = []
    cursor = month_start
    while cursor <= month_end:
        context = contexts.get(cursor)
        results.append(attribute_day(
            work_date=cursor,
            person_id=person_id,
            employee_type=employee_type,
            schedule=schedule_by_date.get(cursor),
            worktime_map=worktime_map,
            punches=punches_by_date.get(cursor, []),
            window_minutes=window_minutes,
            deduct_windows=getattr(context, 'deduct_windows', None) if context else None,
            cover_windows=getattr(context, 'cover_windows', None) if context else None,
            overtime_hours_override=getattr(context, 'overtime_hours', None) if context else None,
            event_labels=getattr(context, 'labels', None) if context else None,
            fix_punches=fix_punches,
        ))
        cursor += timedelta(days=1)
    return results


def attribute_punches_to_work_date(
    punches: list[datetime],
    *,
    cross_day_cutoff_hour: int = 6,
    scheduled_dates: set[date],
) -> dict[date, list[datetime]]:
    """把原始打卡按「考勤日」分桶：凌晨打卡归前一天（若前一天有排班）。

    注意：此为简单分界法，跨天班次（下班时间 > cutoff）可能漏归；
    生成日考勤明细时请用 `assign_punches_to_dates`（按应打卡点就近归属）。
    """
    buckets: dict[date, list[datetime]] = {}
    for punch in punches:
        work_date = punch.date()
        if punch.hour < cross_day_cutoff_hour:
            previous = work_date - timedelta(days=1)
            if previous in scheduled_dates:
                work_date = previous
        buckets.setdefault(work_date, []).append(punch)
    for values in buckets.values():
        values.sort()
    return buckets


def expected_points_by_date(
    schedule_days: list[OaScheduleDay],
    worktime_map: dict[int, OaWorktime],
    employee_type: str,
) -> dict[date, list[datetime]]:
    """按考勤日列出应打卡时间点（含跨天班次落在次日的下班点）。"""
    result: dict[date, list[datetime]] = {}
    for day in schedule_days:
        worktimes = [worktime_map[wid] for wid in day.worktime_ids if wid in worktime_map]
        if not worktimes:
            continue
        points, _ = expected_points_for_day(day.schedule_date, worktimes, employee_type)
        if points:
            result[day.schedule_date] = points
    return result


def assign_punches_to_dates(
    punches: list[datetime],
    points_by_date: dict[date, list[datetime]],
    *,
    window_minutes: int = DEFAULT_MATCH_WINDOW_MINUTES,
    extra_dates: set[date] | None = None,
) -> dict[date, list[datetime]]:
    """按应打卡点就近归属打卡：每个点最多匹配一个卡。

    跨天班次的次日下班点会归到「班次开始日」，避免按自然日漏卡。
    未能匹配任何点的打卡，按自然日放入（若该日出现在 extra_dates 中）。
    """
    ordered_points: list[tuple[date, datetime]] = []
    for work_date in sorted(points_by_date):
        for point in points_by_date[work_date]:
            ordered_points.append((work_date, point))

    available = sorted(punches)
    used: set[int] = set()
    buckets: dict[date, list[datetime]] = {}

    for work_date, point in ordered_points:
        best_index = None
        best_delta = None
        for index, punch in enumerate(available):
            if index in used:
                continue
            delta = abs((punch - point).total_seconds())
            if delta > window_minutes * 60:
                continue
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_index = index
        if best_index is None:
            continue
        used.add(best_index)
        buckets.setdefault(work_date, []).append(available[best_index])

    extra = extra_dates or set()
    for index, punch in enumerate(available):
        if index in used:
            continue
        if punch.date() in extra:
            buckets.setdefault(punch.date(), []).append(punch)

    for values in buckets.values():
        values.sort()
    return buckets
