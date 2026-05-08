"""
region_meter_analysis_service.py - Service for region meter analysis report.
"""
from datetime import date
from typing import List, Dict, Any, Optional
from app.db.engine import raw_conn
from collections import defaultdict


class RegionMeterAnalysisService:
    """Service for analyzing meter readings anomalies by region."""

    def __init__(self, db=None):
        self.db = db

    def get_regions(self) -> List[Dict[str, Any]]:
        """Get all regions."""
        with raw_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT code, name
                FROM regions
                ORDER BY name ASC
            """)
            rows = cur.fetchall()
            return [
                {"code": r[0], "name": r[1]}
                for r in rows
            ]

    def calculate_analysis(self, region_code: str, anomaly_threshold: float) -> Dict[str, Any]:
        """
        Calculate meter anomalies for region.
        anomaly_threshold: 0.4 to 1.0
        """
        with raw_conn() as conn:
            cur = conn.cursor()
            
            # Get all accounts in region with >=5 periods
            cur.execute("""
                SELECT DISTINCT c.account_id
                FROM charges c
                JOIN import_log il ON il.id = c.import_id
                WHERE c.region = %s
                GROUP BY c.account_id
                HAVING COUNT(DISTINCT il.period_from) >= 5
                ORDER BY c.account_id
            """, (region_code,))
            
            accounts = [r[0] for r in cur.fetchall()]
            
            if not accounts:
                return {
                    "error": f"No accounts with >=5 periods in region {region_code}",
                    "results": []
                }
            
            results = []
            
            for account_id in accounts:
                # Create new cursor for each account to avoid conflicts
                sub_cur = conn.cursor()
                anomalies = self._analyze_account_meters(sub_cur, account_id, anomaly_threshold)
                sub_cur.close()
                for anomaly in anomalies:
                    results.append({
                        "account_id": account_id,
                        "meter_type": anomaly["meter_type"],
                        "meter_number": anomaly["meter_number"],
                        "periods": anomaly["periods"],
                        "anomalies_count": len(anomaly["periods"])
                    })
            
            # Sort by anomaly period count descending, take top 100
            results.sort(key=lambda x: x["anomalies_count"], reverse=True)
            top_results = results[:100]
            
            return {
                "region_code": region_code,
                "anomaly_threshold": int(anomaly_threshold * 100),
                "total_accounts": len(accounts),
                "results": top_results
            }

    def _analyze_account_meters(self, cur, account_id: str, anomaly_threshold: float) -> List[Dict[str, Any]]:
        """Analyze meters for one account. Return list of anomalies."""
        # Get all meters except "Отопление"
        cur.execute("""
            SELECT DISTINCT mr.meter_type_name, mr.meter_number
            FROM meter_readings mr
            JOIN charges c ON c.id = mr.charge_id
            WHERE c.account_id = %s
              AND mr.meter_type_name NOT ILIKE '%%отопление%%'
            ORDER BY mr.meter_type_name, mr.meter_number
        """, (account_id,))
        
        meters = cur.fetchall()
        
        # IMPORTANT: Convert to list to avoid cursor state issues
        meters_list = list(meters)
        
        electric_group = False
        anomalies = []
        
        for meter_type, meter_number in meters_list:
            if meter_type.lower().startswith('электроснабжение'):
                electric_group = True
                continue
            meter_anomalies = self._check_meter_anomalies(cur, account_id, meter_type, meter_number, anomaly_threshold)
            if meter_anomalies:
                anomalies.extend(meter_anomalies)

        if electric_group:
            electric_anomalies = self._check_electric_anomalies(cur, account_id, anomaly_threshold)
            if electric_anomalies:
                anomalies.extend(electric_anomalies)
        
        # Check if anomalies are isolated (1-2 meters affected)
        if len(anomalies) > 0:
            affected_meters = set()
            for anomaly in anomalies:
                affected_meters.add((anomaly["meter_type"], anomaly.get("meter_number", "")))
            
            if len(affected_meters) <= 2:
                return anomalies
        
        return []

    def _check_meter_anomalies(self, cur, account_id: str, meter_type: str, meter_number: str, anomaly_threshold: float) -> List[Dict[str, Any]]:
        """Check for anomalies in meter readings."""
        # Get readings ordered by period
        cur.execute("""
            SELECT il.period_from, mr.reading
            FROM meter_readings mr
            JOIN charges c ON c.id = mr.charge_id
            JOIN import_log il ON il.id = c.import_id
            WHERE c.account_id = %s
              AND mr.meter_type_name = %s
              AND mr.meter_number = %s
              AND mr.reading IS NOT NULL
            ORDER BY il.period_from ASC
        """, (account_id, meter_type, meter_number))
        
        readings = list(cur.fetchall())  # Convert to list immediately
        return self._analyze_meter_series(readings, meter_type, meter_number, anomaly_threshold)

    def _check_electric_anomalies(self, cur, account_id: str, anomaly_threshold: float) -> List[Dict[str, Any]]:
        """Check for anomalies across all Электроснабжение meters combined."""
        cur.execute("""
            SELECT il.period_from, SUM(mr.reading)
            FROM meter_readings mr
            JOIN charges c ON c.id = mr.charge_id
            JOIN import_log il ON il.id = c.import_id
            WHERE c.account_id = %s
              AND mr.meter_type_name ILIKE 'Электроснабжение%%'
              AND mr.reading IS NOT NULL
            GROUP BY il.period_from
            ORDER BY il.period_from ASC
        """, (account_id,))
        readings = list(cur.fetchall())

        return self._analyze_meter_series(readings, 'Электроснабжение', '', anomaly_threshold)

    def _analyze_meter_series(self, readings, meter_type: str, meter_number: str, anomaly_threshold: float) -> List[Dict[str, Any]]:
        if len(readings) < 5:  # Need at least 5 periods
            return []
        
        # Calculate differences (ignore decreases)
        periods = []
        diffs = []
        
        for i in range(1, len(readings)):
            prev_reading = readings[i-1][1]
            curr_reading = readings[i][1]
            if prev_reading is None or curr_reading is None:
                continue
            # Convert Decimal to float if needed
            prev_reading = float(prev_reading)
            curr_reading = float(curr_reading)
            diff = curr_reading - prev_reading
            if diff > 0:  # Only positive increases
                periods.append(readings[i][0])
                diffs.append(diff)
        
        if len(diffs) < 4:  # Need at least 4 diffs for analysis
            return []
        
        # Calculate average increase
        avg_increase = float(sum(diffs) / len(diffs))
        
        if avg_increase == 0:
            return []
        
        # Check for anomaly streaks
        anomalies = []
        
        i = 0
        while i < len(diffs):
            # Find streak where diff < anomaly_threshold * avg_increase
            if diffs[i] >= anomaly_threshold * avg_increase:
                i += 1
                continue
            
            streak_start = i
            streak_end = i
            
            while streak_end < len(diffs) and diffs[streak_end] < anomaly_threshold * avg_increase:
                streak_end += 1
            
            streak_length = streak_end - streak_start
            
            if streak_length > 3:  # More than 3 periods
                # Check compensation: look for recovery in next periods
                compensation_found = False
                check_start = streak_end
                check_end = min(streak_end + 3, len(diffs))  # Check next 3 periods safely
                
                for j in range(check_start, check_end):
                    if j < len(diffs) and diffs[j] >= 0.6 * avg_increase and diffs[j] <= 1.2 * avg_increase:
                        compensation_found = True
                        break
                
                if not compensation_found:
                    # Anomaly found
                    anomaly_periods = periods[streak_start:streak_end]
                    anomalies.append({
                        "meter_type": meter_type,
                        "meter_number": meter_number,
                        "periods": [p.strftime('%m.%Y') for p in anomaly_periods],
                        "avg_increase": float(avg_increase),
                        "streak_length": streak_length
                    })
            
            i = streak_end
        
        return anomalies