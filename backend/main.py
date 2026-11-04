"""FastAPI 서버. 실행: 프로젝트 폴더에서

    pip install -r requirements.txt
    uvicorn backend.main:app --reload --port 8000

브라우저로 http://localhost:8000 을 열면 앱이 뜬다. API 문서는 http://localhost:8000/docs
로직은 전부 services.py에 있고, 여기서는 요청을 넘겨주기만 한다.
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, services

app = FastAPI(title="쉼표 API", version="0.1.0")
db.init()


def _call(fn, *a, **k):
    try:
        return fn(*a, **k)
    except services.ServiceError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


class RestStartIn(BaseModel):
    rider_id: int = 1
    lat: float
    lon: float
    place: str = "shelter"      # shelter | street
    at: str | None = None       # 시연 모드 시각 (HH:MM)


class RestStopIn(BaseModel):
    rider_id: int = 1
    at: str | None = None


@app.get("/api/config")
def get_config():
    return services.app_config()


@app.get("/api/now")
def get_now(lat: float = Query(...), lon: float = Query(...), at: str | None = None):
    return _call(services.now_status, lat, lon, at)


@app.post("/api/rest/start")
def post_rest_start(body: RestStartIn):
    return _call(services.rest_start, body.rider_id, body.lat, body.lon, body.place, body.at)


@app.get("/api/rest/current")
def get_rest_current(rider_id: int = 1, at: str | None = None):
    return _call(services.rest_current, rider_id, at)


@app.post("/api/rest/stop")
def post_rest_stop(body: RestStopIn):
    return _call(services.rest_stop, body.rider_id, body.at)


@app.get("/api/history")
def get_history(rider_id: int = 1, at: str | None = None):
    return _call(services.history, rider_id, at)


@app.get("/api/shelters")
def get_shelters(lat: float, lon: float, kind: str | None = None):
    return _call(services.shelter_list, lat, lon, kind)


@app.get("/api/report")
def get_report(lat: float, lon: float, at: str | None = None):
    return _call(services.report, lat, lon, at)


@app.post("/api/demo/reset")
def post_demo_reset():
    return _call(services.demo_reset)


app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
