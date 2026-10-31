from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from services.attendance_attribution import (
    OFFICE,
    WORKSHOP,
    assign_punches_to_dates,
    attribute_day,
    attribute_punches_to_work_date,
    expected_points_by_date,
    expected_points_for_day,
)
from services.oa_schedule import OaScheduleClient, OaScheduleDay, OaWorktime, _parse_ids


class _FakeOaClient:
    def __init__(self, *, worktimes, schedule):
        self._worktimes = worktimes
        self._schedule = schedule

    def _fetch_dicts(self, statement):
        if 'hrm_schedule_worktime' in statement:
            return self._worktimes
        return self._schedule


def _worktime(wid, name, start, end, hours=4):
    return {'worktime_id': wid, 'name': name, 'start_time': start, 'end_time': end, 'hours': hours}


def test_worktime_and_schedule_parsing():
    client = OaScheduleClient(_FakeOaClient(
        worktimes=[
            _worktime(25, '上午', '07:30', '11:30'),
            _worktime(26, '下午', '13:00', '17:00'),
            _worktime(58, '夜班', '19:30', '07:30'),
        ],
        schedule=[
            {'person_id': 13, 'schedule_date': '2026-09-01', 'worktime_ids': '26;25'},
            {'person_id': 13, 'schedule_date': '2026-09-02', 'worktime_ids': ''},
        ],
    ))

    worktimes = client.fetch_worktimes()
    assert worktimes[25].start_time == '07:30'
    assert worktimes[58].crosses_midnight is True
    assert worktimes[25].crosses_midnight is False

    days = client.fetch_schedule(date(2026, 9, 1), date(2026, 9, 30))
    assert days[0].worktime_ids == (26, 25)
    assert days[0].is_rest is False
    assert days[1].is_rest is True


def test_parse_ids_ignores_blanks():
    assert _parse_ids('26;25') == (26, 25)
    assert _parse_ids('') == ()
    assert _parse_ids(None) == ()


def test_office_uses_two_punches():
    worktimes = {
        1: OaWorktime(1, '上午', '07:30', '11:30', Decimal('4')),
        2: OaWorktime(2, '下午', '13:00', '17:00', Decimal('4')),
    }
    points, segments = expected_points_for_day(date(2026, 9, 1), [worktimes[1], worktimes[2]], OFFICE)
    assert points == [datetime(2026, 9, 1, 7, 30), datetime(2026, 9, 1, 17, 0)]
    assert len(segments) == 1

    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=13, employee_type=OFFICE,
        schedule=OaScheduleDay(13, date(2026, 9, 1), (1, 2)),
        worktime_map=worktimes,
        punches=[datetime(2026, 9, 1, 7, 32), datetime(2026, 9, 1, 17, 5)],
    )
    assert day.status == 'normal'
    assert day.check_in == datetime(2026, 9, 1, 7, 32)
    assert day.check_out == datetime(2026, 9, 1, 17, 5)
    # 排班 07:30~17:00, 午休 1.5h
    # clamp: in=max(07:32,07:30)=07:32, out=min(17:05,17:00)=17:00
    # 工时 = 17:00-07:32-90min = 478min → 按30分钟取整 → 450min = 7.50h
    assert day.work_hours == Decimal('7.50')


def test_office_early_punch_clamped_to_schedule():
    """提前打卡不算工时，从排班时间开始算。"""
    worktimes = {
        1: OaWorktime(1, '上午', '07:30', '11:30', Decimal('4')),
        2: OaWorktime(2, '下午', '13:00', '17:00', Decimal('4')),
    }
    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=13, employee_type=OFFICE,
        schedule=OaScheduleDay(13, date(2026, 9, 1), (1, 2)),
        worktime_map=worktimes,
        punches=[datetime(2026, 9, 1, 7, 21), datetime(2026, 9, 1, 17, 6)],
    )
    assert day.check_in == datetime(2026, 9, 1, 7, 21)
    assert day.check_out == datetime(2026, 9, 1, 17, 6)
    # clamp: in=07:30, out=17:00
    # 工时 = 17:00-07:30-90min = 480min → 取整 → 480min = 8.00h
    assert day.work_hours == Decimal('8.00')


def test_office_late_in_early_out():
    """迟到从实际时间算，早走到实际时间算。"""
    worktimes = {
        1: OaWorktime(1, '上午', '07:30', '11:30', Decimal('4')),
        2: OaWorktime(2, '下午', '13:00', '17:00', Decimal('4')),
    }
    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=13, employee_type=OFFICE,
        schedule=OaScheduleDay(13, date(2026, 9, 1), (1, 2)),
        worktime_map=worktimes,
        punches=[datetime(2026, 9, 1, 7, 36), datetime(2026, 9, 1, 16, 50)],
    )
    assert day.check_in == datetime(2026, 9, 1, 7, 36)
    assert day.check_out == datetime(2026, 9, 1, 16, 50)
    # clamp: in=07:36, out=16:50
    # 工时 = 16:50-07:36-90min = 454min → 取整 → 450min = 7.50h
    assert day.work_hours == Decimal('7.50')


def test_workshop_uses_four_punches_with_two_segments():
    worktimes = {
        1: OaWorktime(1, '上午', '07:30', '11:30', Decimal('4')),
        2: OaWorktime(2, '下午', '13:00', '17:00', Decimal('4')),
    }
    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=65, employee_type=WORKSHOP,
        schedule=OaScheduleDay(65, date(2026, 9, 1), (1, 2)),
        worktime_map=worktimes,
        punches=[
            datetime(2026, 9, 1, 7, 28),
            datetime(2026, 9, 1, 11, 31),
            datetime(2026, 9, 1, 12, 58),
            datetime(2026, 9, 1, 17, 2),
        ],
    )
    assert day.status == 'normal'
    assert len(day.segments) == 2
    assert day.segments[0].check_in == datetime(2026, 9, 1, 7, 28)
    assert day.segments[0].check_out == datetime(2026, 9, 1, 11, 31)
    assert day.segments[1].check_in == datetime(2026, 9, 1, 12, 58)
    assert day.segments[1].check_out == datetime(2026, 9, 1, 17, 2)
    # 每段独立 clamp：
    # 上午段: max(07:28,07:30)=07:30 → min(11:31,11:30)=11:30 = 240分钟
    # 下午段: max(12:58,13:00)=13:00 → min(17:02,17:00)=17:00 = 240分钟
    # 合计 = 480分钟 → 取整 → 480分钟 = 8.00h（午休自动排除）
    assert day.work_hours == Decimal('8.00')


def test_missing_punch_is_flagged():
    worktimes = {1: OaWorktime(1, '全天', '08:00', '17:00', Decimal('9'))}
    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=13, employee_type=OFFICE,
        schedule=OaScheduleDay(13, date(2026, 9, 1), (1,)),
        worktime_map=worktimes,
        punches=[datetime(2026, 9, 1, 8, 3)],
    )
    assert day.missing_points == 1
    assert day.status == 'missing_card'


def test_rest_day_without_schedule():
    day = attribute_day(
        work_date=date(2026, 9, 6), person_id=13, employee_type=OFFICE,
        schedule=None, worktime_map={}, punches=[datetime(2026, 9, 6, 9, 0)],
    )
    assert day.is_rest is True
    assert day.status == 'rest'


def test_no_punch_day_has_zero_hours_for_office():
    """无打卡不应把整段排班算成工时（旷工 = 0 小时）。"""
    worktimes = {
        1: OaWorktime(1, '上午', '07:30', '11:30', Decimal('4')),
        2: OaWorktime(2, '下午', '13:00', '17:00', Decimal('4')),
    }
    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=13, employee_type=OFFICE,
        schedule=OaScheduleDay(13, date(2026, 9, 1), (1, 2)),
        worktime_map=worktimes, punches=[],
    )
    assert day.status == 'absent'
    assert day.work_hours == Decimal('0.00')


def test_no_punch_day_has_zero_hours_for_workshop():
    """车间无打卡同样不计工时（含 12 小时班次）。"""
    worktimes = {58: OaWorktime(58, '白班', '08:00', '20:00', Decimal('12'))}
    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=65, employee_type=WORKSHOP,
        schedule=OaScheduleDay(65, date(2026, 9, 1), (58,)),
        worktime_map=worktimes, punches=[],
    )
    assert day.status == 'absent'
    assert day.work_hours == Decimal('0.00')


def test_office_rest_day_overtime_from_application():
    """休息日的后勤加班仍按申请单计入。"""
    day = attribute_day(
        work_date=date(2026, 9, 5), person_id=13, employee_type=OFFICE,
        schedule=None, worktime_map={}, punches=[],
        overtime_hours_override=Decimal('5.5'),
    )
    assert day.is_rest is True
    assert day.overtime_hours == Decimal('5.50')


def test_punch_fix_marks_start_and_end():
    """来自 OA 补卡单的打卡点被标记，用于前端「补」角标。"""
    worktimes = {
        1: OaWorktime(1, '上午', '07:30', '11:30', Decimal('4')),
        2: OaWorktime(2, '下午', '13:00', '17:00', Decimal('4')),
    }
    real = datetime(2026, 9, 1, 7, 30)
    fix_out = datetime(2026, 9, 1, 17, 0)
    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=13, employee_type=OFFICE,
        schedule=OaScheduleDay(13, date(2026, 9, 1), (1, 2)),
        worktime_map=worktimes,
        punches=[real, fix_out],
        fix_punches=[fix_out],
    )
    assert day.check_out_fixed is True
    assert day.check_in_fixed is False


def test_cross_day_worktime_attributes_to_shift_start_day():
    worktimes = {58: OaWorktime(58, '夜班', '19:30', '07:30', Decimal('12'))}
    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=200, employee_type=WORKSHOP,
        schedule=OaScheduleDay(200, date(2026, 9, 1), (58,)),
        worktime_map=worktimes,
        punches=[datetime(2026, 9, 1, 19, 35), datetime(2026, 9, 2, 7, 20)],
    )
    assert day.status == 'normal'
    assert day.check_in == datetime(2026, 9, 1, 19, 35)
    assert day.check_out == datetime(2026, 9, 2, 7, 20)
    # 夜班: clamp in=max(19:35,19:30)=19:35, out=min(07:20,07:30)=07:20
    # 工时 = 07:20次日 - 19:35当天 = 705min → 取整 → 690min = 11.50h
    assert day.work_hours == Decimal('11.50')


def test_workshop_overtime_from_late_punch_out():
    """车间加班按打卡算：晚于排班结束的部分（按半小时取整）。"""
    worktimes = {
        1: OaWorktime(1, '上午', '07:30', '11:30', Decimal('4')),
        2: OaWorktime(2, '下午', '13:00', '17:00', Decimal('4')),
    }
    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=65, employee_type=WORKSHOP,
        schedule=OaScheduleDay(65, date(2026, 9, 1), (1, 2)),
        worktime_map=worktimes,
        punches=[
            datetime(2026, 9, 1, 7, 30),
            datetime(2026, 9, 1, 11, 30),
            datetime(2026, 9, 1, 13, 0),
            datetime(2026, 9, 1, 18, 35),
        ],
    )
    assert day.work_hours == Decimal('8.00')
    # 加班 = 18:35 - 17:00 = 95分钟 → 按30分钟取整 → 90分钟 = 1.50h
    assert day.overtime_hours == Decimal('1.50')


def test_workshop_overtime_counts_punch_beyond_match_window():
    """下班后很久的加班卡（超出匹配窗口，如 21:00）也计入车间加班。"""
    worktimes = {
        1: OaWorktime(1, '上午', '07:30', '11:00', Decimal('4')),
        2: OaWorktime(2, '下午', '11:30', '17:00', Decimal('4')),
    }
    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=65, employee_type=WORKSHOP,
        schedule=OaScheduleDay(65, date(2026, 9, 1), (1, 2)),
        worktime_map=worktimes,
        punches=[
            datetime(2026, 9, 1, 7, 16),
            datetime(2026, 9, 1, 11, 0),
            datetime(2026, 9, 1, 11, 17),
            datetime(2026, 9, 1, 17, 0),
            datetime(2026, 9, 1, 17, 16),
            datetime(2026, 9, 1, 21, 0),
        ],
    )
    # 加班 = 当天最后一次 21:00 - 排班结束 17:00 = 4h（半小时取整不变）
    assert day.overtime_hours == Decimal('4.00')


def test_office_has_no_punch_based_overtime():
    """后勤加班不按打卡算（等加班单），晚走不计加班。"""
    worktimes = {
        1: OaWorktime(1, '上午', '07:30', '11:30', Decimal('4')),
        2: OaWorktime(2, '下午', '13:00', '17:00', Decimal('4')),
    }
    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=13, employee_type=OFFICE,
        schedule=OaScheduleDay(13, date(2026, 9, 1), (1, 2)),
        worktime_map=worktimes,
        punches=[datetime(2026, 9, 1, 7, 30), datetime(2026, 9, 1, 20, 0)],
    )
    assert day.work_hours == Decimal('8.00')
    assert day.overtime_hours == Decimal('0.00')


def test_workshop_no_overtime_when_on_time():
    worktimes = {
        1: OaWorktime(1, '上午', '07:30', '11:30', Decimal('4')),
        2: OaWorktime(2, '下午', '13:00', '17:00', Decimal('4')),
    }
    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=65, employee_type=WORKSHOP,
        schedule=OaScheduleDay(65, date(2026, 9, 1), (1, 2)),
        worktime_map=worktimes,
        punches=[
            datetime(2026, 9, 1, 7, 28),
            datetime(2026, 9, 1, 11, 31),
            datetime(2026, 9, 1, 12, 58),
            datetime(2026, 9, 1, 17, 2),
        ],
    )
    assert day.work_hours == Decimal('8.00')
    assert day.overtime_hours == Decimal('0.00')


def test_assign_punches_to_dates_returns_cross_day_out_punch():
    worktimes = {58: OaWorktime(58, '夜班', '19:30', '07:30', Decimal('12'))}
    schedule = [OaScheduleDay(200, date(2026, 9, 1), (58,))]
    points = expected_points_by_date(schedule, worktimes, WORKSHOP)
    buckets = assign_punches_to_dates(
        [datetime(2026, 9, 1, 19, 35), datetime(2026, 9, 2, 7, 20)], points,
    )
    assert buckets[date(2026, 9, 1)] == [
        datetime(2026, 9, 1, 19, 35), datetime(2026, 9, 2, 7, 20),
    ]


def test_punches_before_cutoff_go_to_previous_scheduled_day():
    scheduled = {date(2026, 9, 1)}
    buckets = attribute_punches_to_work_date(
        [datetime(2026, 9, 1, 19, 35), datetime(2026, 9, 2, 2, 0), datetime(2026, 9, 2, 8, 0)],
        scheduled_dates=scheduled,
    )
    assert buckets[date(2026, 9, 1)] == [datetime(2026, 9, 1, 19, 35), datetime(2026, 9, 2, 2, 0)]
    assert buckets[date(2026, 9, 2)] == [datetime(2026, 9, 2, 8, 0)]
