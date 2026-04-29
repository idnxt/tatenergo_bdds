"""
provider_report.py - Provider-based billing report service.
"""
from datetime import date
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from app.db.engine import raw_conn


class ProviderReportService:
    """Service for provider billing reports."""

    def __init__(self, db: Session = None):
        self.db = db

    def get_periods(self) -> List[Dict[str, Any]]:
        """Get all loaded periods from import_log."""
        with raw_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    id,
                    period_from,
                    period_to,
                    row_count,
                    loaded_at
                FROM import_log
                ORDER BY period_from ASC
            """)
            rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "period_from": r[1],
                    "period_to": r[2],
                    "row_count": r[3],
                    "loaded_at": r[4],
                }
                for r in rows
            ]

    def get_providers(self) -> List[Dict[str, Any]]:
        """Get all providers."""
        with raw_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, name
                FROM providers
                ORDER BY name ASC
            """)
            rows = cur.fetchall()
            return [
                {"id": r[0], "name": r[1]}
                for r in rows
            ]

    def calculate_report(
        self,
        provider_ids: Optional[List[int]],
        period_from: date,
        period_to: date,
    ) -> Dict[str, Any]:
        """
        Calculate report for selected providers and period range.
        
        Args:
            provider_ids: List of provider IDs or None for "All providers"
            period_from: Start period (from import_log.period_from)
            period_to: End period (from import_log.period_to)
        
        Returns:
            Dictionary with chart_data, stats_table, top_20 (if single provider)
        """
        with raw_conn() as conn:
            cur = conn.cursor()

            # Get all periods in range
            cur.execute("""
                SELECT period_from, period_to
                FROM import_log
                WHERE period_from >= %s AND period_to <= %s
                ORDER BY period_from ASC
            """, (period_from, period_to))
            periods = cur.fetchall()

            if not periods:
                return {
                    "error": "No data for selected period range",
                    "period_str": f"{period_from.strftime('%d.%m.%Y')} — {period_to.strftime('%d.%m.%Y')}",
                    "chart_data": [],
                    "stats_table": [],
                    "top_20": None,
                }

            period_str = f"{period_from.strftime('%d.%m.%Y')} — {period_to.strftime('%d.%m.%Y')}"

            # Calculate monthly sums
            if provider_ids is None or len(provider_ids) == 0:
                # All providers: use filesum from import_log
                chart_data = self._calc_all_providers_monthly(cur, periods)
            else:
                # Multiple providers: sum all selected providers
                chart_data = self._calc_multi_providers_monthly(cur, periods, provider_ids)

            # Build stats table with account counts and averages
            stats_table = self._build_stats_table(cur, chart_data, periods, provider_ids)

            # Top 20 accounts (only for single provider)
            top_20 = None
            if provider_ids and len(provider_ids) == 1 and periods:
                top_20 = self._calc_top_20_accounts(
                    cur, provider_ids[0], periods[-1][0], periods[-1][1], periods
                )

            return {
                "period_str": period_str,
                "chart_data": chart_data,
                "stats_table": stats_table,
                "top_20": top_20,
            }

    def _calc_all_providers_monthly(self, cur, periods: List[tuple]) -> List[Dict]:
        """Calculate monthly sums for all providers (from filesum)."""
        data = []
        for period_from, period_to in periods:
            cur.execute("""
                SELECT
                    period_from,
                    period_to,
                    COALESCE(filesum, 0) AS sum
                FROM import_log
                WHERE period_from = %s AND period_to = %s
            """, (period_from, period_to))
            row = cur.fetchone()
            if row:
                data.append({
                    "period_from": row[0],
                    "period_to": row[1],
                    "month_str": f"{row[0].strftime('%b %Y')}",
                    "sum": float(row[2]) if row[2] else 0.0,
                })
        return data

    def _calc_multi_providers_monthly(
        self, cur, periods: List[tuple], provider_ids: List[int]
    ) -> List[Dict]:
        """Calculate monthly sums for multiple selected providers."""
        data = []
        placeholders = ','.join(['%s'] * len(provider_ids))
        
        for period_from, period_to in periods:
            cur.execute(f"""
                SELECT
                    c.period_from,
                    c.period_to,
                    COALESCE(SUM(cp.amount), 0) AS sum
                FROM charges c
                LEFT JOIN charge_providers cp ON cp.charge_id = c.id
                WHERE c.period_from = %s
                  AND c.period_to = %s
                  AND cp.provider_id IN ({placeholders})
                GROUP BY c.period_from, c.period_to
            """, [period_from, period_to] + provider_ids)
            row = cur.fetchone()
            if row:
                data.append({
                    "period_from": row[0],
                    "period_to": row[1],
                    "month_str": f"{row[0].strftime('%b %Y')}",
                    "sum": float(row[2]) if row[2] else 0.0,
                })
        return data

    def _build_stats_table(
        self, cur, chart_data: List[Dict], periods: List[tuple], provider_ids: Optional[List[int]]
    ) -> List[Dict]:
        """Build stats table with monthly sums, account counts, and YoY % changes."""
        if not chart_data:
            return []

        table = []
        for i, point in enumerate(chart_data):
            period_from = point["period_from"]
            period_to = point["period_to"]
            
            # Count unique accounts (LS) for this period
            account_count = self._count_accounts_in_period(
                cur, period_from, period_to, provider_ids
            )
            
            # Calculate average per account
            avg_per_account = point["sum"] / account_count if account_count > 0 else 0.0
            
            row = {
                "month": point["month_str"],
                "sum": point["sum"],
                "account_count": account_count,
                "avg_per_account": avg_per_account,
                "pct_mom": None,
                "pct_yoy": None,
            }

            if i > 0:
                prev_sum = chart_data[i - 1]["sum"]
                if prev_sum > 0:
                    pct = ((point["sum"] - prev_sum) / prev_sum) * 100
                    row["pct_mom"] = pct

            if i >= 12:
                prev_year_sum = chart_data[i - 12]["sum"]
                if prev_year_sum > 0:
                    pct = ((point["sum"] - prev_year_sum) / prev_year_sum) * 100
                    row["pct_yoy"] = pct

            table.append(row)

        return table

    def _count_accounts_in_period(
        self, cur, period_from: date, period_to: date, provider_ids: Optional[List[int]]
    ) -> int:
        """Count unique accounts (LS) in a period for given providers."""
        if provider_ids is None or len(provider_ids) == 0:
            # All providers: count all accounts
            cur.execute("""
                SELECT COUNT(DISTINCT c.account_id)
                FROM charges c
                WHERE c.period_from = %s AND c.period_to = %s
            """, (period_from, period_to))
        else:
            # Specific providers: count accounts with those providers
            placeholders = ','.join(['%s'] * len(provider_ids))
            cur.execute(f"""
                SELECT COUNT(DISTINCT c.account_id)
                FROM charges c
                JOIN charge_providers cp ON cp.charge_id = c.id
                WHERE c.period_from = %s
                  AND c.period_to = %s
                  AND cp.provider_id IN ({placeholders})
            """, [period_from, period_to] + provider_ids)
        
        result = cur.fetchone()
        return result[0] if result and result[0] else 0

    def _calc_top_20_accounts(
        self,
        cur,
        provider_id: int,
        last_period_from: date,
        last_period_to: date,
        all_periods: List[tuple],
    ) -> List[Dict]:
        """
        Calculate top 20 accounts by sum in last period.
        """
        cur.execute("""
            SELECT
                c.account_id,
                SUM(cp.amount) AS sum_last
            FROM charges c
            JOIN charge_providers cp ON cp.charge_id = c.id
            WHERE c.period_from = %s
              AND c.period_to = %s
              AND cp.provider_id = %s
            GROUP BY c.account_id
            ORDER BY sum_last DESC
            LIMIT 20
        """, (last_period_from, last_period_to, provider_id))

        top_accounts = [r[0] for r in cur.fetchall()]
        if not top_accounts:
            return None

        top_20 = []
        for account_id in top_accounts:
            row = {"account_id": account_id}

            for period_from, period_to in reversed(all_periods):
                cur.execute("""
                    SELECT COALESCE(SUM(cp.amount), 0)
                    FROM charges c
                    JOIN charge_providers cp ON cp.charge_id = c.id
                    WHERE c.account_id = %s
                      AND c.period_from = %s
                      AND c.period_to = %s
                      AND cp.provider_id = %s
                """, (account_id, period_from, period_to, provider_id))
                result = cur.fetchone()
                sum_val = float(result[0]) if result and result[0] else 0.0

                period_key = f"{period_from.strftime('%b %y')}"
                row[period_key] = sum_val

            top_20.append(row)

        return top_20 if top_20 else None
