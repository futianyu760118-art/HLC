"""Canonical helpers for employee course and hour progress.

The original progress tables predate the SaaS unique-key boundary.  A short
period of concurrent video reports can therefore leave more than one row for
the same employee/course (or employee/course/hour).  Read paths must treat
those rows as one logical record, while the write path updates the strongest
existing row instead of selecting an arbitrary ``first()`` row.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from typing import Iterable

from sqlalchemy import text

from models import CourseHour, UserCourseProgress, UserHourProgress, db


_MIN_TIME = datetime.min


def _time(value):
    return value if isinstance(value, datetime) else _MIN_TIME


def _bounded_int(value, minimum=0, maximum=None) -> int:
    try:
        result = int(value or 0)
    except (TypeError, ValueError):
        result = 0
    result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _course_row_rank(row):
    """Prefer a completed/high-progress row, then the newest stable row."""
    return (
        bool(getattr(row, 'is_finished', False)),
        _bounded_int(getattr(row, 'progress', 0), maximum=100),
        _bounded_int(getattr(row, 'finished_count', 0)),
        getattr(row, 'finished_at', None) is not None,
        _time(getattr(row, 'finished_at', None)),
        _time(getattr(row, 'updated_at', None)),
        _time(getattr(row, 'created_at', None)),
        str(getattr(row, 'id', '') or ''),
    )


def _hour_row_rank(row):
    return (
        bool(getattr(row, 'is_finished', False)),
        _bounded_int(getattr(row, 'watched_duration', 0)),
        _bounded_int(getattr(row, 'total_duration', 0)),
        getattr(row, 'finished_at', None) is not None,
        _time(getattr(row, 'finished_at', None)),
        _time(getattr(row, 'updated_at', None)),
        _time(getattr(row, 'created_at', None)),
        str(getattr(row, 'id', '') or ''),
    )


def merge_hour_progress_rows(rows: Iterable[UserHourProgress]) -> dict | None:
    """Merge duplicate rows for one logical ``hour_id``.

    ``watchedDuration`` is monotonic, and completion is sticky.  The returned
    ``_row`` is the best existing ORM row for callers that need to update it;
    no historical row is deleted here.
    """
    rows = list(rows)
    if not rows:
        return None
    source = max(rows, key=_hour_row_rank)
    finished_at_values = [row.finished_at for row in rows if row.finished_at]
    updated_values = [row.updated_at for row in rows if row.updated_at]
    total_duration = max(
        (_bounded_int(getattr(row, 'total_duration', 0)) for row in rows),
        default=0,
    )
    watched_duration = max(
        (_bounded_int(getattr(row, 'watched_duration', 0)) for row in rows),
        default=0,
    )
    return {
        'hourId': source.hour_id,
        'courseId': source.course_id,
        'totalDuration': total_duration,
        'watchedDuration': watched_duration,
        'isFinished': any(bool(row.is_finished) for row in rows),
        'finishedAt': min(finished_at_values) if finished_at_values else None,
        'updatedAt': max(updated_values) if updated_values else None,
        '_row': source,
    }


def merge_hour_progress_groups(rows: Iterable[UserHourProgress]) -> dict[str, dict]:
    """Return one merged snapshot per hour id."""
    groups = defaultdict(list)
    for row in rows:
        groups[row.hour_id].append(row)
    return {
        hour_id: merged
        for hour_id, grouped in groups.items()
        if (merged := merge_hour_progress_rows(grouped)) is not None
    }


def merge_course_progress_rows(
    rows: Iterable[UserCourseProgress],
    *,
    total_hours: int | None = None,
    finished_count: int | None = None,
) -> dict | None:
    """Merge duplicate rows for one logical ``course_id``.

    Stored values are retained for legacy/imported records that do not have
    corresponding hour rows.  When hour-derived values are available they are
    combined using distinct hour identities, never raw duplicate-row counts.
    """
    rows = list(rows)
    if not rows:
        return None
    source = max(rows, key=_course_row_rank)
    row_hour_count = max(
        (_bounded_int(getattr(row, 'hour_count', 0)) for row in rows),
        default=0,
    )
    row_finished_count = max(
        (_bounded_int(getattr(row, 'finished_count', 0)) for row in rows),
        default=0,
    )
    row_progress = max(
        (_bounded_int(getattr(row, 'progress', 0), maximum=100) for row in rows),
        default=0,
    )
    actual_hours = _bounded_int(total_hours) if total_hours is not None else 0
    # Once the current course has a real hour roster, that roster is the
    # authoritative denominator.  Imported course rows can carry stale counts
    # from an older version (for example ``4/4`` after the course was reduced
    # to one hour); never expose those counts beyond the current roster.
    effective_hours = actual_hours or row_hour_count
    derived_finished = _bounded_int(finished_count) if finished_count is not None else 0
    if actual_hours:
        effective_finished = min(
            actual_hours,
            max(derived_finished, min(row_finished_count, actual_hours)),
        )
    else:
        effective_finished = row_finished_count
    derived_progress = (
        int(derived_finished / actual_hours * 100)
        if actual_hours else 0
    )
    is_finished = any(bool(row.is_finished) for row in rows)
    if row_progress >= 100:
        is_finished = True
    if actual_hours and max(row_finished_count, derived_finished) >= actual_hours:
        is_finished = True
    progress = max(row_progress, derived_progress)
    if is_finished:
        progress = 100
        if actual_hours:
            effective_finished = actual_hours
        elif effective_hours:
            effective_finished = max(effective_finished, effective_hours)
    finished_at_values = [row.finished_at for row in rows if row.finished_at]
    updated_values = [row.updated_at for row in rows if row.updated_at]
    created_values = [row.created_at for row in rows if row.created_at]
    return {
        'courseId': source.course_id,
        'hourCount': effective_hours,
        'finishedCount': effective_finished,
        'progress': min(100, max(0, progress)),
        'isFinished': is_finished,
        # Keep the first known completion moment; duplicate rows must not move
        # the displayed completion date just because a stale row was inserted.
        'finishedAt': min(finished_at_values) if finished_at_values else None,
        'updatedAt': max(updated_values) if updated_values else None,
        'createdAt': min(created_values) if created_values else None,
        '_row': source,
    }


def current_course_hour_ids(course_ids: Iterable[str]) -> dict[str, set[str]]:
    """Load the current hour roster for each course in one query."""
    course_ids = [course_id for course_id in set(course_ids) if course_id]
    if not course_ids:
        return {}
    rosters = defaultdict(set)
    for course_id, hour_id in db.session.query(
        CourseHour.course_id, CourseHour.id,
    ).filter(CourseHour.course_id.in_(course_ids)).all():
        rosters[course_id].add(hour_id)
    return dict(rosters)


def employee_course_progress_map(
    employee_id: str,
    course_ids: Iterable[str] | None = None,
) -> dict[str, dict]:
    """Load and merge all course progress for an employee."""
    requested = {course_id for course_id in (course_ids or []) if course_id}
    if course_ids is not None and not requested:
        return {}
    cp_query = UserCourseProgress.query.filter_by(employee_id=employee_id)
    hp_query = UserHourProgress.query.filter_by(employee_id=employee_id)
    if requested:
        cp_query = cp_query.filter(UserCourseProgress.course_id.in_(requested))
        hp_query = hp_query.filter(UserHourProgress.course_id.in_(requested))
    course_rows = cp_query.all()
    hour_rows = hp_query.all()
    course_groups = defaultdict(list)
    for row in course_rows:
        course_groups[row.course_id].append(row)
    hour_groups = defaultdict(list)
    for row in hour_rows:
        hour_groups[(row.course_id, row.hour_id)].append(row)
    hour_snapshots = defaultdict(dict)
    for (course_id, hour_id), grouped in hour_groups.items():
        merged = merge_hour_progress_rows(grouped)
        if merged:
            hour_snapshots[course_id][hour_id] = merged

    all_course_ids = set(course_groups) | set(hour_snapshots)
    if requested:
        all_course_ids &= requested
    hour_rosters = current_course_hour_ids(all_course_ids)
    result = {}
    for course_id in all_course_ids:
        # A deleted or replaced hour can retain an old progress row.  Once a
        # course has a current hour roster, only that roster is allowed to
        # contribute to the completion count or watched-time summary.
        current_hour_ids = hour_rosters.get(course_id, set())
        all_hour_progress = hour_snapshots.get(course_id, {})
        current_hour_progress = (
            {
                hour_id: snapshot
                for hour_id, snapshot in all_hour_progress.items()
                if hour_id in current_hour_ids
            }
            if current_hour_ids else all_hour_progress
        )
        actual_total = len(current_hour_ids)
        derived_finished = sum(
            1 for hour in current_hour_progress.values()
            if hour['isFinished']
        )
        merged = merge_course_progress_rows(
            course_groups.get(course_id, []),
            total_hours=actual_total,
            finished_count=derived_finished,
        )
        if merged is None:
            # A progress row can be missing when a first report is interrupted;
            # synthesize a read-only snapshot from the hour rows.
            merged = {
                'courseId': course_id,
                'hourCount': actual_total,
                'finishedCount': derived_finished,
                'progress': int(derived_finished / actual_total * 100) if actual_total else 0,
                'isFinished': bool(actual_total and derived_finished >= actual_total),
                'finishedAt': None,
                'updatedAt': max(
                    (row['updatedAt'] for row in current_hour_progress.values()
                     if row['updatedAt']),
                    default=None,
                ),
                'createdAt': None,
                '_row': None,
            }
        merged['hourProgress'] = current_hour_progress
        result[course_id] = merged
    return result


def employee_hour_progress_map(employee_id: str, course_id: str) -> dict[str, dict]:
    rows = UserHourProgress.query.filter_by(
        employee_id=employee_id, course_id=course_id,
    ).all()
    return merge_hour_progress_groups(rows)


class CourseProgressLockTimeout(RuntimeError):
    """The database advisory lock could not be acquired in time."""


@contextmanager
def course_progress_lock(employee_id: str, course_id: str, timeout_seconds: int = 10):
    """Serialize reports for one employee/course on MySQL.

    Existing deployments cannot add a unique index while historical duplicate
    rows remain.  A MySQL advisory lock closes the race immediately without
    deleting those rows; SQLite test/dev databases simply use the surrounding
    transaction because SQLite has no equivalent named lock.
    """
    if not str(db.engine.name).startswith('mysql'):
        yield
        return
    # MySQL limits advisory-lock names to 64 bytes; keep the fixed prefix
    # plus digest comfortably below that boundary.
    digest = hashlib.sha256(
        f'{employee_id}:{course_id}'.encode('utf-8')
    ).hexdigest()[:40]
    lock_name = f'hpt_course_progress_{digest}'
    # The progress write commits through ``db.session`` while the lock is
    # held.  Session.commit() closes its SQLAlchemy Connection, whereas a
    # MySQL named lock is tied to the physical connection.  Keep the lock on
    # a dedicated connection so the final course-progress commit cannot make
    # RELEASE_LOCK operate on a closed connection or leak the named lock into
    # the pool.
    connection = db.engine.connect()
    try:
        acquired = connection.execute(
            text('SELECT GET_LOCK(:lock_name, :timeout_seconds)'),
            {'lock_name': lock_name, 'timeout_seconds': int(timeout_seconds)},
        ).scalar()
        if acquired != 1:
            raise CourseProgressLockTimeout('course progress is busy')
        try:
            yield
        finally:
            released = connection.execute(
                text('SELECT RELEASE_LOCK(:lock_name)'),
                {'lock_name': lock_name},
            ).scalar()
            if released != 1:
                connection.invalidate()
                raise RuntimeError('course progress lock release failed')
    finally:
        connection.close()
