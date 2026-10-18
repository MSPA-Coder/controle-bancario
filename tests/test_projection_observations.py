"""Measure the actual projection/middleware against the disposable PostgreSQL."""

import logging
import re
from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.domain.settings import APP_SETTING_LAST_PROJECTION_RUN
from core.services import update_recurring_projection_settings, upsert_app_setting
from transactions.middleware import ProjecaoRecorrenteMensalMiddleware


@pytest.mark.django_db
def test_resolved_projection_adds_zero_queries_to_subsequent_requests(caplog):
    update_recurring_projection_settings(horizon_months=6, run_day=1)
    upsert_app_setting(APP_SETTING_LAST_PROJECTION_RUN, "")
    instance = ProjecaoRecorrenteMensalMiddleware(lambda _request: "ok")
    request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True))
    caplog.set_level(logging.INFO, logger="transactions.recurring_projection")

    with CaptureQueriesContext(connection) as initial:
        assert instance(request) == "ok"
    assert len(initial) > 0
    assert re.search(r"duration_ms=\d+\.\d", caplog.text)
    caplog.clear()
    with CaptureQueriesContext(connection) as resolved:
        for _ in range(100):
            assert instance(request) == "ok"
    assert len(resolved) == 0
    assert caplog.text == ""
    print(f"projection_queries_initial={len(initial)}; resolved_100_requests={len(resolved)}")
