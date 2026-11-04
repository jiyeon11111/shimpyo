"""설치 없이 쓰는 서버(serve_stdlib)가 라이더 앱과 지자체 화면을 둘 다 내주는지."""
import json
import os
import tempfile
import threading
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

import pytest


@pytest.fixture()
def base(monkeypatch):
    from backend import config, db, serve_stdlib
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    monkeypatch.setattr(config, "DB_PATH", tmp)
    monkeypatch.setattr(config, "DEMO_MODE", True)
    db.init()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), serve_stdlib.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()
    os.remove(tmp)


def _get(url):
    with urlopen(url) as r:
        return r.read().decode()


def test_rider_app_has_no_region_tab(base):
    html = _get(base + "/")
    assert 'data-v="report"' not in html and 'href="admin.html"' in html


def test_admin_page_and_report(base):
    assert "admin.js" in _get(base + "/admin.html")
    r = json.loads(_get(base + "/api/report?lat=37.5552&lon=126.9222&at=15:00"))
    assert len(r["grid"]) == 49 and r["virtual"] is True and r["missed_hours"] >= 0
