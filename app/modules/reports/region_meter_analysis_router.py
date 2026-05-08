"""
region_meter_analysis_router.py - Routes for region meter analysis report.
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
from pydantic import BaseModel
from datetime import date

from app.db.engine import get_db
from app.modules.reports.region_meter_analysis_service import RegionMeterAnalysisService

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


class AnalysisRequest(BaseModel):
    """Request body for analysis calculation."""
    region_code: str
    anomaly_threshold: int = 50  # 40-100, step 10


@router.get("/region-meter-analysis", response_class=HTMLResponse)
async def region_meter_analysis_page(request: Request, db: Session = Depends(get_db)):
    """Main region meter analysis page."""
    service = RegionMeterAnalysisService(db)
    
    regions = service.get_regions()
    
    return templates.TemplateResponse(
        "reports/region_meter_analysis.html",
        {
            "request": request,
            "regions": regions,
        },
    )


@router.post("/region-meter-analysis/calculate.json")
async def calculate_analysis(data: AnalysisRequest, db: Session = Depends(get_db)):
    """Calculate meter analysis for selected region."""
    try:
        service = RegionMeterAnalysisService(db)
        result = service.calculate_analysis(data.region_code, data.anomaly_threshold / 100.0)
        
        return JSONResponse(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            {"error": str(e)},
            status_code=400,
        )