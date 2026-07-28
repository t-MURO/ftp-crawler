from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.config import get_settings
from app.database import SessionLocal, get_db
from app.models import CrawlLog, ScanDirectory, ScanRun, utcnow
from app.schemas import ScanCreate, SearchParams, SettingsUpdate
from app.services.crawler import create_scan, write_crawl_log
from app.services.dashboard import dashboard_stats, scan_to_dict
from app.services.search import get_file_detail, search_files
from app.services.security import (
    get_csrf_token,
    new_csrf_token,
    require_authenticated,
    require_csrf,
    seed_admin_user,
    verify_login,
)
from app.services.settings import effective_settings, public_crawler_config, save_overrides

settings = get_settings()
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.log_directory.mkdir(parents=True, exist_ok=True)
    settings.config_directory.mkdir(parents=True, exist_ok=True)
    try:
        with SessionLocal() as db:
            seed_admin_user(db)
    except OperationalError:
        pass
    yield


app = FastAPI(
    title="Port Browser API",
    description="Search and manage a persistent FTP/FTPS metadata index.",
    version=__version__,
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="port_browser_session",
    same_site="strict",
    https_only=settings.secure_cookies,
    max_age=60 * 60 * 12,
)
if settings.allowed_hosts_list != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts_list)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self'; script-src 'self'; connect-src 'self'; "
        "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


@app.get("/healthz", tags=["system"])
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "healthy", "version": __version__}
    except Exception:
        return JSONResponse({"status": "unhealthy"}, status_code=503)


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request):
    if not settings.auth_enabled:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"csrf_token": get_csrf_token(request), "error": None},
    )


@app.post("/login", response_class=HTMLResponse, include_in_schema=False)
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    expected = request.session.get("csrf_token")
    if not expected or csrf_token != expected or not verify_login(db, username, password):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"csrf_token": new_csrf_token(request), "error": "Invalid sign-in details."},
            status_code=400,
        )
    request.session.clear()
    request.session["username"] = username
    new_csrf_token(request)
    return RedirectResponse("/", status_code=303)


@app.post("/logout", include_in_schema=False)
def logout(request: Request, csrf_token: str = Form(...)):
    if csrf_token != request.session.get("csrf_token"):
        raise HTTPException(403, "Invalid CSRF token")
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(request: Request, db: Session = Depends(get_db)):
    if settings.auth_enabled and not request.session.get("username"):
        return RedirectResponse("/login", status_code=303)
    current = effective_settings(db)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "csrf_token": get_csrf_token(request),
            "app_name": settings.app_name,
            "ftp_host": current["ftp_host"] or "FTP server",
            "auth_enabled": settings.auth_enabled,
            "username": request.session.get("username"),
            "default_results_per_page": current["default_results_per_page"],
        },
    )


@app.get("/api/search", tags=["files"])
def api_search(
    request: Request,
    q: str = Query(default="", max_length=500),
    extension: str | None = Query(default=None, max_length=64),
    min_size: int | None = Query(default=None, ge=0),
    max_size: int | None = Query(default=None, ge=0),
    modified_from: str | None = None,
    modified_to: str | None = None,
    directory: str | None = Query(default=None, max_length=4096),
    file_status: str = Query(default="available", alias="status"),
    sort: str = "filename",
    order: str = "asc",
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=10, le=1000),
    db: Session = Depends(get_db),
    _user: str = Depends(require_authenticated),
):
    params = SearchParams.model_validate(
        {
            "q": q,
            "extension": extension or None,
            "min_size": min_size,
            "max_size": max_size,
            "modified_from": modified_from or None,
            "modified_to": modified_to or None,
            "directory": directory or None,
            "status": file_status,
            "sort": sort,
            "order": order,
            "page": page,
            "per_page": per_page,
        }
    )
    return search_files(db, params)


@app.get("/api/files/{file_id}", tags=["files"])
def api_file_detail(
    file_id: int,
    db: Session = Depends(get_db),
    _user: str = Depends(require_authenticated),
):
    item = get_file_detail(db, file_id)
    if item is None:
        raise HTTPException(404, "File not found")
    return item


@app.get("/api/dashboard", tags=["dashboard"])
def api_dashboard(
    db: Session = Depends(get_db),
    _user: str = Depends(require_authenticated),
):
    return dashboard_stats(db)


@app.get("/api/scans/status", tags=["crawler"])
def api_scan_status(
    db: Session = Depends(get_db),
    _user: str = Depends(require_authenticated),
):
    scan = db.scalar(select(ScanRun).order_by(ScanRun.queued_at.desc()))
    return {"scan": scan_to_dict(scan)}


@app.post("/api/scans", status_code=status.HTTP_202_ACCEPTED, tags=["crawler"])
def api_start_scan(
    payload: ScanCreate,
    request: Request,
    db: Session = Depends(get_db),
    _user: str = Depends(require_authenticated),
):
    require_csrf(request)
    try:
        scan = create_scan(db, payload.mode)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"scan": scan_to_dict(scan)}


@app.post("/api/scans/stop", tags=["crawler"])
def api_stop_scan(
    request: Request,
    db: Session = Depends(get_db),
    _user: str = Depends(require_authenticated),
):
    require_csrf(request)
    scan = db.scalar(
        select(ScanRun)
        .where(ScanRun.status.in_(["queued", "running", "stopping"]))
        .order_by(ScanRun.queued_at.desc())
    )
    if scan is None:
        raise HTTPException(409, "No scan is running or queued")
    if scan.status == "queued":
        scan.status = "stopped"
        scan.finished_at = utcnow()
    else:
        scan.stop_requested = True
        scan.status = "stopping"
    write_crawl_log(db, scan.id, "INFO", "Safe stop requested.", commit=False)
    db.commit()
    return {"scan": scan_to_dict(scan)}


@app.post("/api/scans/resume", tags=["crawler"])
def api_resume_scan(
    request: Request,
    db: Session = Depends(get_db),
    _user: str = Depends(require_authenticated),
):
    require_csrf(request)
    active = db.scalar(
        select(ScanRun).where(ScanRun.status.in_(["queued", "running", "stopping"]))
    )
    if active:
        raise HTTPException(409, "A scan is already queued or running")
    scan = db.scalar(
        select(ScanRun)
        .where(ScanRun.status.in_(["stopped", "failed"]))
        .order_by(ScanRun.queued_at.desc())
    )
    if scan is None:
        raise HTTPException(409, "There is no stopped or failed scan to resume")
    db.execute(
        update(ScanDirectory)
        .where(ScanDirectory.scan_id == scan.id, ScanDirectory.status == "in_progress")
        .values(status="pending", updated_at=utcnow())
    )
    scan.status = "queued"
    scan.stop_requested = False
    scan.finished_at = None
    scan.error_message = None
    scan.queued_at = utcnow()
    write_crawl_log(db, scan.id, "INFO", "Scan resume requested.", commit=False)
    db.commit()
    return {"scan": scan_to_dict(scan)}


@app.get("/api/logs", tags=["crawler"])
def api_logs(
    after_id: int | None = Query(default=None, ge=0),
    level: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: str = Depends(require_authenticated),
):
    query = select(CrawlLog)
    if after_id is not None:
        query = query.where(CrawlLog.id > after_id).order_by(CrawlLog.id.asc())
    else:
        query = query.order_by(CrawlLog.id.desc())
    if level:
        query = query.where(CrawlLog.level == level.upper())
    logs = db.scalars(query.limit(limit)).all()
    return {
        "items": [
            {
                "id": log.id,
                "scan_id": log.scan_id,
                "created_at": log.created_at.isoformat(),
                "level": log.level,
                "message": log.message,
                "directory": log.directory,
            }
            for log in logs
        ]
    }


@app.get("/api/settings", tags=["settings"])
def api_settings(
    db: Session = Depends(get_db),
    _user: str = Depends(require_authenticated),
):
    return {
        **effective_settings(db),
        **public_crawler_config(db),
    }


@app.put("/api/settings", tags=["settings"])
def api_update_settings(
    payload: SettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _user: str = Depends(require_authenticated),
):
    require_csrf(request)
    values = payload.model_dump(exclude_unset=True, exclude_none=True)
    return save_overrides(db, values)
