import time

from flask import Flask, current_app

from services import study_reminder


def test_scheduler_runs_daily_check_inside_app_context(monkeypatch):
    study_reminder.stop_reminder_scheduler()
    observed = []

    def fake_daily_check():
        observed.append(current_app.name)
        study_reminder.stop_reminder_scheduler()
        return 0

    monkeypatch.setattr(study_reminder, 'run_daily_check', fake_daily_check)
    app = Flask('study-reminder-context-test')

    try:
        study_reminder.start_reminder_scheduler(app)
        for _ in range(40):
            if observed:
                break
            time.sleep(0.05)
        assert observed == ['study-reminder-context-test']
    finally:
        study_reminder.stop_reminder_scheduler()
