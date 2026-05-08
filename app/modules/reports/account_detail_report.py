"""
account_detail_report.py - Account (LS) detail report service.
"""
from datetime import date
from typing import List, Dict, Any, Optional
from app.db.engine import raw_conn


class AccountDetailReportService:
    """Service for detailed account reports."""

    def get_account_details(
        self,
        account_ids: List[str],
    ) -> Dict[str, Any]:
        """Get detailed report for selected accounts."""
        with raw_conn() as conn:
            cur = conn.cursor()
            
            cur.execute("""
                SELECT period_from, period_to
                FROM import_log
                ORDER BY period_from ASC
            """)
            periods = cur.fetchall()
            
            if not periods:
                return {
                    "error": "No data loaded",
                    "accounts": []
                }
            
            period_from = periods[0][0]
            period_to = periods[-1][1]
            period_str = f"{period_from.strftime('%d.%m.%Y')} — {period_to.strftime('%d.%m.%Y')}"
            
            accounts_data = []
            
            for account_id in account_ids:
                cur.execute("""
                    SELECT COUNT(*) FROM charges WHERE account_id = %s
                """, (account_id,))
                
                if cur.fetchone()[0] == 0:
                    accounts_data.append({
                        "account_id": account_id,
                        "error": "Account not found"
                    })
                    continue
                
                billing_data = self._get_billing_by_period_provider(cur, account_id, periods)
                meters_data = self._get_all_meters_unified(cur, account_id, periods)
                
                accounts_data.append({
                    "account_id": account_id,
                    "period_str": period_str,
                    "billing": billing_data,
                    "meters": meters_data,
                })
            
            return {
                "error": None,
                "accounts": accounts_data
            }

    def _get_billing_by_period_provider(
        self, cur, account_id: str, periods: List[tuple]
    ) -> List[Dict[str, Any]]:
        """Get billing by period and provider with % changes and yearly totals."""
        
        cur.execute("""
            SELECT DISTINCT p.id, p.name
            FROM providers p
            JOIN charge_providers cp ON cp.provider_id = p.id
            JOIN charges c ON c.id = cp.charge_id
            WHERE c.account_id = %s
            ORDER BY p.name
        """, (account_id,))
        providers = cur.fetchall()
        provider_list = [(r[0], r[1]) for r in providers]
        
        billing = []
        prev_total = None
        yearly_totals = {}
        
        for period_from, period_to in periods:
            row = {
                "period": f"{period_from.strftime('%m.%Y')}",
                "period_from": period_from,
                "period_to": period_to,
                "total": 0.0,
                "total_pct": None,
                "providers": {},
                "is_year_total": False
            }
            
            for provider_id, provider_name in provider_list:
                cur.execute("""
                    SELECT COALESCE(SUM(cp.amount), 0)
                    FROM charges c
                    JOIN charge_providers cp ON cp.charge_id = c.id
                    WHERE c.account_id = %s
                      AND c.period_from = %s
                      AND c.period_to = %s
                      AND cp.provider_id = %s
                """, (account_id, period_from, period_to, provider_id))
                
                amount = float(cur.fetchone()[0] or 0)
                row["providers"][provider_name] = {
                    "amount": amount,
                    "pct": None
                }
                row["total"] += amount
            
            # Calculate % changes for total
            if prev_total and prev_total > 0:
                row["total_pct"] = ((row["total"] - prev_total) / prev_total) * 100
            
            # Calculate % changes for each provider
            if billing:
                for provider_name in row["providers"]:
                    prev_amount = billing[-1]["providers"].get(provider_name, {}).get("amount", 0)
                    curr_amount = row["providers"][provider_name]["amount"]
                    if prev_amount and prev_amount > 0:
                        row["providers"][provider_name]["pct"] = (
                            (curr_amount - prev_amount) / prev_amount
                        ) * 100
            
            prev_total = row["total"]
            
            # Accumulate yearly totals
            year = period_from.year
            if year not in yearly_totals:
                yearly_totals[year] = {}
            if 'total' not in yearly_totals[year]:
                yearly_totals[year]['total'] = 0.0
            
            yearly_totals[year]['total'] += row["total"]
            
            for provider_name in row["providers"]:
                if provider_name not in yearly_totals[year]:
                    yearly_totals[year][provider_name] = 0.0
                yearly_totals[year][provider_name] += row["providers"][provider_name]["amount"]
            
            billing.append(row)
        
        # Insert yearly totals
        final_billing = []
        prev_year = None
        prev_year_total = None
        
        for row in billing:
            if prev_year and row["period_from"].year != prev_year:
                year_row = {
                    "period": f"ИТОГ {prev_year}",
                    "period_from": None,
                    "period_to": None,
                    "total": yearly_totals[prev_year]['total'],
                    "total_pct": None,
                    "providers": {},
                    "is_year_total": True
                }
                
                if prev_year_total and prev_year_total > 0:
                    year_row["total_pct"] = ((year_row["total"] - prev_year_total) / prev_year_total) * 100
                
                for provider_id, provider_name in provider_list:
                    prev_year_amount = yearly_totals.get(prev_year - 1, {}).get(provider_name, 0.0)
                    curr_year_amount = yearly_totals[prev_year].get(provider_name, 0.0)
                    pct = None
                    if prev_year_amount and prev_year_amount > 0:
                        pct = ((curr_year_amount - prev_year_amount) / prev_year_amount) * 100
                    
                    year_row["providers"][provider_name] = {
                        "amount": curr_year_amount,
                        "pct": pct
                    }
                
                final_billing.append(year_row)
                prev_year_total = year_row["total"]
            
            final_billing.append(row)
            prev_year = row["period_from"].year
        
        # Add final yearly total
        if prev_year and prev_year in yearly_totals:
            year_row = {
                "period": f"ИТОГ {prev_year}",
                "period_from": None,
                "period_to": None,
                "total": yearly_totals[prev_year]['total'],
                "total_pct": None,
                "providers": {},
                "is_year_total": True
            }
            
            if prev_year_total and prev_year_total > 0:
                year_row["total_pct"] = ((year_row["total"] - prev_year_total) / prev_year_total) * 100
            
            for provider_id, provider_name in provider_list:
                prev_year_amount = yearly_totals.get(prev_year - 1, {}).get(provider_name, 0.0)
                curr_year_amount = yearly_totals[prev_year].get(provider_name, 0.0)
                pct = None
                if prev_year_amount and prev_year_amount > 0:
                    pct = ((curr_year_amount - prev_year_amount) / prev_year_amount) * 100
                
                year_row["providers"][provider_name] = {
                    "amount": curr_year_amount,
                    "pct": pct
                }
            
            final_billing.append(year_row)
        
        return final_billing

    def _get_all_meters_unified(
        self, cur, account_id: str, periods: List[tuple]
    ) -> Dict[str, Any]:
        """Get all meter readings with electricity tariff calculation."""
        
        # Get all distinct meters for this account
        cur.execute("""
            SELECT DISTINCT mr.meter_type_name, mr.meter_number
            FROM meter_readings mr
            JOIN charges c ON c.id = mr.charge_id
            WHERE c.account_id = %s
            ORDER BY mr.meter_type_name, mr.meter_number
        """, (account_id,))
        
        meters = cur.fetchall()
        
        if not meters:
            return {
                "electricity_meters": [],
                "other_meters": [],
                "readings": []
            }
        
        # Group meters - electricity starts with "Электроснабжение"
        electricity_meters = []
        other_meters = []
        
        for meter_type, meter_number in meters:
            if meter_type.startswith('Электроснабжение'):
                electricity_meters.append({"type": meter_type, "number": meter_number})
            else:
                other_meters.append({"type": meter_type, "number": meter_number})
        
        # Get electricity provider ID
        cur.execute("""
            SELECT id FROM providers WHERE name ILIKE '%ТАТЭНЕРГОСБЫТ%' LIMIT 1
        """)
        elec_provider_row = cur.fetchone()
        elec_provider_id = elec_provider_row[0] if elec_provider_row else None
        
        # Get readings for all periods
        readings_data = {}
        
        for period_from, period_to in periods:
            period_key = period_from.strftime('%m.%Y')
            readings_data[period_key] = {
                "period_from": period_from,
                "period_to": period_to,
                "readings": {},
                "elec_amount": 0.0
            }
            
            # Get readings for all meters
            for meter_type, meter_number in meters:
                cur.execute("""
                    SELECT mr.reading
                    FROM meter_readings mr
                    JOIN charges c ON c.id = mr.charge_id
                    WHERE c.account_id = %s
                      AND c.period_from = %s
                      AND c.period_to = %s
                      AND mr.meter_number = %s
                      AND mr.meter_type_name = %s
                    LIMIT 1
                """, (account_id, period_from, period_to, meter_number, meter_type))
                
                result = cur.fetchone()
                reading = float(result[0]) if result and result[0] is not None else None
                
                meter_key = f"{meter_type}||{meter_number}"
                readings_data[period_key]["readings"][meter_key] = reading
            
            # Get electricity amount for this period
            if elec_provider_id:
                cur.execute("""
                    SELECT COALESCE(SUM(cp.amount), 0)
                    FROM charges c
                    JOIN charge_providers cp ON cp.charge_id = c.id
                    WHERE c.account_id = %s
                      AND c.period_from = %s
                      AND c.period_to = %s
                      AND cp.provider_id = %s
                """, (account_id, period_from, period_to, elec_provider_id))
                
                amount_row = cur.fetchone()
                readings_data[period_key]["elec_amount"] = float(amount_row[0]) if amount_row and amount_row[0] else 0.0
        
        # Build result rows with calculations
        result = []
        prev_readings = {}  # {meter_key: reading}
        prev_elec_tariff = None
        
        # Initialize prev_readings from first period
        if periods:
            first_period_key = periods[0][0].strftime('%m.%Y')
            first_period_data = readings_data[first_period_key]
            for meter_key, reading in first_period_data["readings"].items():
                if reading is not None:
                    prev_readings[meter_key] = reading
        
        for period_idx, (period_from, period_to) in enumerate(periods):
            period_key = period_from.strftime('%m.%Y')
            period_data = readings_data[period_key]
            
            row = {
                "period": period_key,
                "period_from": period_from,
                "period_to": period_to,
                "meters": {},
                "elec_total_reading": None,
                "elec_total_diff": None,
                "elec_tariff": None,
                "elec_tariff_pct": None,
            }
            
            # Process all meters and calculate diffs
            elec_total_diff = 0.0
            elec_total_reading = 0.0
            has_electricity = False
            
            for meter in electricity_meters + other_meters:
                meter_key = f"{meter['type']}||{meter['number']}"
                reading = period_data["readings"].get(meter_key)
                
                if reading is not None:
                    diff = None
                    # Calculate diff only if not first period and we have previous reading
                    if period_idx > 0 and meter_key in prev_readings and prev_readings[meter_key] is not None:
                        diff = reading - prev_readings[meter_key]
                    
                    row["meters"][meter_key] = {
                        "reading": reading,
                        "diff": diff
                    }
                    
                    # Process electricity meters
                    is_electricity = meter['type'].startswith('Электроснабжение')
                    if is_electricity:
                        has_electricity = True
                        elec_total_reading += reading
                        if diff is not None:
                            elec_total_diff += diff
                    
                    # Save for next period
                    prev_readings[meter_key] = reading
            
            # Set elec_total_reading if we have electricity meters
            if has_electricity:
                row["elec_total_reading"] = elec_total_reading
                # Set elec_total_diff even if 0 (for display)
                if elec_total_diff != 0 or (period_idx > 0):
                    row["elec_total_diff"] = elec_total_diff if elec_total_diff != 0 else None
            
            # Тариф считается в JavaScript на клиенте (ТАТЭНЕРГОСБЫТ / elec_total_diff)
            # Python просто готовит данные
            
            result.append(row)
        
        return {
            "electricity_meters": electricity_meters,
            "other_meters": other_meters,
            "readings": result,
            "billing_by_period": readings_data  # {period_key: {elec_amount, ...}}
        }
