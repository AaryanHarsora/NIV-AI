"""Niv AI — FastAPI entry point."""
from __future__ import annotations
import json
import logging
import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from backend.routers.analysis import router as analysis_router
from backend.routers.reports import router as reports_router
from backend.routers.health import router as health_router
from backend.routers.tools import router as tools_router
from backend.routers.documents import router as documents_router
from backend.routers.whatsapp import router as whatsapp_router
from backend.utils.rate_limit import limiter
from backend.firebase import firestore as fs

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
logger = logging.getLogger("niv-ai")

app = FastAPI(title="Niv AI", description="Decision Intelligence for Home Buying", version="4.0.0")

# Rate limiting
app.state.limiter = limiter


async def _custom_rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    retry_after = int(getattr(exc, "retry_after", 60) or 60)
    return JSONResponse(
        status_code=429,
        content={
            "detail": (
                "Rate limit exceeded. Maximum 5 analyses per 10 minutes per IP. "
                "Please wait before trying again."
            ),
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )


app.add_exception_handler(RateLimitExceeded, _custom_rate_limit_handler)

frontend_url = os.getenv("FRONTEND_URL", "*")
app.add_middleware(CORSMiddleware,
                   allow_origins=[frontend_url] if frontend_url != "*" else ["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(analysis_router)
app.include_router(reports_router)
app.include_router(health_router)
app.include_router(tools_router)
app.include_router(documents_router)
app.include_router(whatsapp_router)

frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
_index_html_path = os.path.join(frontend_dir, "index.html")

if os.path.isdir(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_frontend():
        return FileResponse(os.path.join(frontend_dir, "landing.html"))

    @app.get("/landing.html", include_in_schema=False)
    async def serve_landing():
        return FileResponse(os.path.join(frontend_dir, "landing.html"))

    @app.get("/style.css", include_in_schema=False)
    async def serve_style():
        return FileResponse(os.path.join(frontend_dir, "style.css"))

    @app.get("/calc", include_in_schema=False)
    async def serve_calc():
        return FileResponse(os.path.join(frontend_dir, "index.html"))

    @app.get("/app.js", include_in_schema=False)
    async def serve_app_js():
        """Serve app.js for the frontend."""
        return FileResponse(os.path.join(frontend_dir, "app.js"), media_type="application/javascript")
        """Serve a saved report by embedding the report data into the index.html page."""
        report = await fs.get_report(report_id)
        if not report:
            return JSONResponse(status_code=404, content={"detail": "Report not found"})

        try:
            with open(_index_html_path, "r", encoding="utf-8") as f:
                html = f.read()
        except OSError:
            return JSONResponse(status_code=500, content={"detail": "Frontend unavailable"})

        report_json = json.dumps(report.get("report", report), ensure_ascii=False)
        created_at = report.get("created_at", "")
        injection = (
            f'<script>'
            f'window.__NIV_PRELOADED_REPORT__ = {report_json};'
            f'window.__NIV_SHARED_MODE__ = true;'
            f'window.__NIV_REPORT_ID__ = "{report_id}";'
            f'window.__NIV_REPORT_CREATED__ = "{created_at}";'
            f'</script>'
        )
        # Inject before </head> so globals are available when app.js runs
        html = html.replace("</head>", f"{injection}\n</head>", 1)
        return HTMLResponse(content=html)
else:
    @app.get("/", include_in_schema=False)
    async def root():
        return {"message": "Niv AI API running", "docs": "/docs"}

logger.info("Niv AI v4.0 started — 10 new features active")
