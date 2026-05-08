"""
account_detail_router.py - Routes for account detail reports.
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
from pydantic import BaseModel
from datetime import date
import re
import json

from app.db.engine import get_db
from app.modules.reports.account_detail_report import AccountDetailReportService

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


class AccountDetailRequest(BaseModel):
    """Request body for account detail report."""
    account_ids: str  # Comma-separated account numbers


def serialize_for_json(obj):
    """Recursively convert all date objects to ISO format strings and numbers to float."""
    if isinstance(obj, date):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize_for_json(item) for item in obj]
    elif isinstance(obj, (int, float)):
        return float(obj) if isinstance(obj, int) and not isinstance(obj, bool) else obj
    else:
        return obj


@router.get("/account-detail", response_class=HTMLResponse)
async def account_detail_page(request: Request, db: Session = Depends(get_db)):
    """Main account detail report page."""
    return templates.TemplateResponse(
        "reports/account_detail_report.html",
        {"request": request},
    )


@router.post("/account-detail/calculate.json")
async def calculate_account_detail(data: AccountDetailRequest, db: Session = Depends(get_db)):
    """Calculate account detail report."""
    try:
        # Parse account IDs: comma-separated, each 10 digits
        account_ids_str = data.account_ids.strip()
        account_ids = [a.strip() for a in account_ids_str.split(',') if a.strip()]
        
        # Validate: each should be 10 digits
        for account_id in account_ids:
            if not re.match(r'^\d{10}$', account_id):
                return JSONResponse(
                    {"error": f"Invalid account format: {account_id}. Use 10 digits."},
                    status_code=400,
                )
        
        if len(account_ids) == 0:
            return JSONResponse(
                {"error": "Please enter at least one account number"},
                status_code=400,
            )
        
        if len(account_ids) > 10:
            return JSONResponse(
                {"error": "Maximum 10 accounts allowed"},
                status_code=400,
            )
        
        service = AccountDetailReportService()
        result = service.get_account_details(account_ids)
        
        # Recursively convert all dates and make JSON-serializable
        result = serialize_for_json(result)
        
        return JSONResponse(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            {"error": str(e)},
            status_code=400,
        )
