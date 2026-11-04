"""설치 없이 실행하는 서버 (파이썬 기본 라이브러리만 사용). FastAPI 서버와 API가 같다.

    python -m backend.serve_stdlib          # http://localhost:8000

발표장 노트북에 패키지를 설치할 수 없을 때나, 빠르게 확인할 때 쓴다.
"""
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config, db, services

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")


def _q(qs, key, cast=str, default=None):
    v = qs.get(key, [None])[0]
    return cast(v) if v not in (None, "") else default


GET = {
    "/api/config": lambda q: services.app_config(),
    "/api/now": lambda q: services.now_status(_q(q, "lat", float), _q(q, "lon", float), _q(q, "at")),
    "/api/rest/current": lambda q: services.rest_current(_q(q, "rider_id", int, 1), _q(q, "at")),
    "/api/history": lambda q: services.history(_q(q, "rider_id", int, 1), _q(q, "at")),
    "/api/shelters": lambda q: services.shelter_list(_q(q, "lat", float), _q(q, "lon", float), _q(q, "kind")),
    "/api/report": lambda q: services.report(_q(q, "lat", float), _q(q, "lon", float), _q(q, "at")),
}
POST = {
    "/api/rest/start": lambda b: services.rest_start(int(b.get("rider_id", 1)), float(b["lat"]), float(b["lon"]), b.get("place", "shelter"), b.get("at")),
    "/api/rest/stop": lambda b: services.rest_stop(int(b.get("rider_id", 1)), b.get("at")),
    "/api/demo/reset": lambda b: services.demo_reset(),
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj=None, raw=None, ctype="application/json; charset=utf-8"):
        data = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _api(self, table, arg):
        path = urlparse(self.path).path
        fn = table.get(path)
        if not fn:
            return self._send(404, {"detail": "없는 경로입니다."})
        try:
            self._send(200, fn(arg))
        except services.ServiceError as e:
            self._send(e.status, {"detail": str(e)})
        except (KeyError, TypeError, ValueError) as e:
            self._send(422, {"detail": f"요청 값이 잘못됐습니다: {e}"})

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith("/api/"):
            return self._api(GET, parse_qs(u.query))
        rel = u.path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(config.FRONTEND_DIR, rel))
        if not full.startswith(config.FRONTEND_DIR) or not os.path.isfile(full):
            full = os.path.join(config.FRONTEND_DIR, "index.html")
        with open(full, "rb") as f:
            self._send(200, raw=f.read(), ctype=mimetypes.guess_type(full)[0] or "application/octet-stream")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._send(422, {"detail": "JSON 형식이 아닙니다."})
        self._api(POST, body)

    def log_message(self, fmt, *args):
        pass


def main(port=int(os.getenv("PORT", "8000"))):
    db.init()
    print(f"쉼표 서버: http://localhost:{port}  (시연 모드: {'켜짐' if config.DEMO_MODE else '꺼짐'})")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
