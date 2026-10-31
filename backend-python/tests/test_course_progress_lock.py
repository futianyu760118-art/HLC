"""Regression coverage for the MySQL course-progress advisory lock."""

from __future__ import annotations

import services.course_progress as course_progress


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _LockConnection:
    def __init__(self):
        self.calls = []
        self.closed = False
        self.invalidated = False

    def execute(self, statement, params):
        sql = str(statement)
        self.calls.append((sql, params))
        if 'GET_LOCK' in sql:
            return _ScalarResult(1)
        if 'RELEASE_LOCK' in sql:
            return _ScalarResult(1)
        raise AssertionError(f'unexpected SQL: {sql}')

    def close(self):
        self.closed = True

    def invalidate(self):
        self.invalidated = True


class _LockEngine:
    name = 'mysql'

    def __init__(self, connection):
        self.connection = connection
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1
        return self.connection


class _LockDb:
    def __init__(self, engine):
        self.engine = engine
        # Deliberately no ``session.connection``: the advisory lock must not
        # borrow the ORM transaction connection because Session.commit closes it.
        self.session = object()


def test_course_progress_lock_uses_dedicated_connection(monkeypatch):
    connection = _LockConnection()
    engine = _LockEngine(connection)
    monkeypatch.setattr(course_progress, 'db', _LockDb(engine))

    with course_progress.course_progress_lock('employee-1', 'course-1'):
        pass

    assert engine.connect_calls == 1
    assert connection.closed is True
    lock_names = [params['lock_name'] for _sql, params in connection.calls]
    assert len(set(lock_names)) == 1
    assert len(lock_names[0]) <= 64
    assert 'GET_LOCK' in connection.calls[0][0]
    assert 'RELEASE_LOCK' in connection.calls[1][0]
