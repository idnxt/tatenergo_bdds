"""
provider_router.py - Routes for provider billing reports.
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
from datetime import date
from pydantic import BaseModel
import json

from app.db.engine import get_db
from app.modules.reports.provider_report import ProviderReportService

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


class ReportRequest(BaseModel):
    """Request body for report calculation."""
    provider_ids: list[int] | None = None  # List of provider IDs or None for all
    period_from: str  # ISO date
    period_to: str    # ISO date


def serialize_report_data(data: dict) -> dict:
    """Convert all dates and decimals to JSON-serializable format."""
    if "chart_data" in data:
        for point in data["chart_data"]:
            point["period_from"] = point["period_from"].isoformat()
            point["period_to"] = point["period_to"].isoformat()
    
    if "stats_table" in data:
        for row in data["stats_table"]:
            if row.get("pct_mom") is not None:
                row["pct_mom"] = float(row["pct_mom"])
            if row.get("pct_yoy") is not None:
                row["pct_yoy"] = float(row["pct_yoy"])
    
    if "top_20" in data and data["top_20"]:
        for row in data["top_20"]:
            for key in list(row.keys()):
                if key != "account_id" and isinstance(row[key], (int, float)):
                    row[key] = float(row[key])
    
    return data


@router.get("/provider", response_class=HTMLResponse)
async def provider_report_page(request: Request, db: Session = Depends(get_db)):
    """Main provider report page."""
    service = ProviderReportService(db)
    
    periods = service.get_periods()
    providers = service.get_providers()
    
    period_from = periods[0]["period_from"] if periods else None
    period_to = periods[-1]["period_to"] if periods else None
    
    return templates.TemplateResponse(
        "reports/provider_report.html",
        {
            "request": request,
            "periods": periods,
            "providers": providers,
            "period_from": period_from,
            "period_to": period_to,
        },
    )


@router.get("/provider/periods.json")
async def get_periods(db: Session = Depends(get_db)):
    """Get all available periods."""
    service = ProviderReportService(db)
    periods = service.get_periods()
    for p in periods:
        p["period_from"] = p["period_from"].isoformat()
        p["period_to"] = p["period_to"].isoformat()
    return JSONResponse(periods)


@router.get("/provider/providers.json")
async def get_providers(db: Session = Depends(get_db)):
    """Get all providers."""
    service = ProviderReportService(db)
    providers = service.get_providers()
    return JSONResponse(providers)


@router.post("/provider/calculate.json")
async def calculate_report(data: ReportRequest, db: Session = Depends(get_db)):
    """Calculate report for selected providers and period."""
    try:
        period_from = date.fromisoformat(data.period_from)
        period_to = date.fromisoformat(data.period_to)
        
        service = ProviderReportService(db)
        result = service.calculate_report(data.provider_ids, period_from, period_to)
        
        result = serialize_report_data(result)
        
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse(
            {"error": str(e)},
            status_code=400,
        )
