"""
reports/service.py — запросы для отчётов.
Каждый отчёт = один метод. Возвращает dict для Jinja2-шаблона.
"""
from decimal import Decimal
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.db import models


class ReportService:

    def __init__(self, db: Session):
        self.db = db

    def get_periods(self) -> list[models.ImportLog]:
        return (
            self.db.query(models.ImportLog)
            .order_by(models.ImportLog.period_from.desc())
            .all()
        )

    def get_summary(self, import_id: int) -> dict | None:
        """
        Сводка по периоду:
        - заголовок (период, файл, кол-во строк)
        - итого начислений
        - по регионам (таблица + данные для графика)
        - топ-10 поставщиков
        - счётчики по типам приборов
        - аномальные тарифы
        """
        imp = self.db.query(models.ImportLog).get(import_id)
        if not imp:
            return None

        # Итого начислений
        total = (
            self.db.query(func.sum(models.Charge.total_amount))
            .filter(models.Charge.import_id == import_id)
            .scalar() or Decimal(0)
        )

        # По регионам
        by_region = (
            self.db.query(
                models.Charge.region,
                func.count(models.Charge.id).label("accounts"),
                func.sum(models.Charge.total_amount).label("amount"),
            )
            .filter(models.Charge.import_id == import_id)
            .group_by(models.Charge.region)
            .order_by(func.sum(models.Charge.total_amount).desc())
            .all()
        )

        # Топ поставщиков
        top_providers = (
            self.db.query(
                models.Provider.name,
                func.sum(models.ChargeProvider.amount).label("amount"),
                func.count(models.ChargeProvider.charge_id).label("accounts"),
            )
            .join(models.Provider, models.Provider.id == models.ChargeProvider.provider_id)
            .join(models.Charge,   models.Charge.id   == models.ChargeProvider.charge_id)
            .filter(models.Charge.import_id == import_id)
            .group_by(models.Provider.name)
            .order_by(func.sum(models.ChargeProvider.amount).desc())
            .limit(10)
            .all()
        )

        # Счётчики по типам приборов
        meter_stats = (
            self.db.query(
                models.MeterReading.meter_type_name,
                func.count(models.MeterReading.id).label("count"),
            )
            .join(models.Charge, models.Charge.id == models.MeterReading.charge_id)
            .filter(models.Charge.import_id == import_id)
            .group_by(models.MeterReading.meter_type_name)
            .order_by(func.count(models.MeterReading.id).desc())
            .all()
        )

        # Аномалии (пока — записи с is_anomaly=True)
        anomalies = (
            self.db.query(
                models.TariffCalc,
                models.Charge.account_id,
                models.Charge.region,
            )
            .join(models.Charge, models.Charge.id == models.TariffCalc.charge_id)
            .filter(
                models.Charge.import_id == import_id,
                models.TariffCalc.is_anomaly == True,
            )
            .limit(500)
            .all()
        )

        # Данные для Chart.js (регионы)
        chart_labels  = [r.region for r in by_region[:20]]
        chart_amounts = [float(r.amount or 0) for r in by_region[:20]]

        return {
            "imp":           imp,
            "total":         total,
            "by_region":     by_region,
            "top_providers": top_providers,
            "meter_stats":   meter_stats,
            "anomalies":     anomalies,
            "chart_labels":  chart_labels,
            "chart_amounts": chart_amounts,
        }