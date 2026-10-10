from types import SimpleNamespace

from job_agent import worker


class PausedSession:
    def __init__(self):
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, model, row_id):
        assert row_id == 1
        return SimpleNamespace(enabled=False)

    def flush(self):
        return None

    def commit(self):
        self.committed = True


def test_scheduled_discovery_stops_before_recording_run_if_paused(monkeypatch):
    session = PausedSession()
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)

    worker.scheduled_discovery()

    assert session.committed is True
