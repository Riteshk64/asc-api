import pandas as pd
import re

def normalize_id(val):
    """
    Cleans IDs so '8', '8.0', ' 8 ' all match.
    """
    if pd.isna(val):
        return None
    s = str(val).strip()
    if s.endswith('.0'):
        s = s[:-2]
    return s

def time_to_decimal(time_str):
    """
    Converts '08:30' -> 8.5
    """
    if not isinstance(time_str, str) or ':' not in time_str:
        return 0.0
    try:
        parts = time_str.split(':')
        h, m = int(parts[0]), int(parts[1])
        return h + (m / 60.0)
    except:
        return 0.0

def load_attendance_sheet(file_storage):
    """
    Smart loader: Looks for 'Sheet2', otherwise uses the largest sheet.
    """
    xls = pd.ExcelFile(file_storage)
    
    # Priority: Specific Sheet Names
    for sheet in xls.sheet_names:
        if "sheet" in sheet.lower() and "2" in sheet:
            return pd.read_excel(file_storage, sheet_name=sheet, header=None)
            
    # Fallback: Sheet with most rows
    best_sheet = xls.sheet_names[0]
    max_rows = 0
    for sheet in xls.sheet_names:
        df = pd.read_excel(file_storage, sheet_name=sheet, header=None)
        if len(df) > max_rows:
            max_rows = len(df)
            best_sheet = sheet
            
    return pd.read_excel(file_storage, sheet_name=best_sheet, header=None)

def extract_raw_attendance(file_storage):
    df = load_attendance_sheet(file_storage)
    
    # 1. Find the header row containing "Days"
    day_cols = {}
    day_row_idx = None
    for idx, row in df.iterrows():
        if str(row[0]).strip() == "Days":
            day_row_idx = idx
            break
            
    if day_row_idx is None: 
        return []

    # 2. Map Day Numbers (1-31) to Column Indexes
    day_row = df.iloc[day_row_idx]
    for i, val in enumerate(day_row):
        if pd.notna(val) and i > 1:
            match = re.search(r'(\d+)', str(val))
            if match: 
                day_cols[int(match.group(1))] = i

    extracted_data = []
    current_code = None
    current_name = None

    # 3. Iterate rows to find "Emp. Code" and "Total"
    for idx, row in df.iterrows():
        label = str(row[0]).strip()
        
        if label == 'Emp. Code:':
            current_code = str(row[3]).strip()
            # Try to grab name if available
            current_name = str(row[13]).strip() if len(row) > 13 else "Unknown"
            
        elif label == 'Total' and current_code:
            record = {
                "id": normalize_id(current_code),
                "name": current_name, 
                "days": {}
            }
            # Sum hours for days 1 to 31
            for day in range(1, 32):
                col_idx = day_cols.get(day)
                val = 0.0
                if col_idx is not None:
                    raw = str(row[col_idx]).strip()
                    val = time_to_decimal(raw)
                record["days"][day] = val
            
            extracted_data.append(record)
            current_code = None

    return extracted_data

def calculate_payroll(raw_data, reference_map):
    report = []
    
    for entry in raw_data:
        emp_id = entry['id']
        ref = reference_map.get(emp_id)
        
        # SKIP if not in Master File
        if not ref:
            continue

        salary = float(ref.get('salary', 0))
        daily_req = float(ref.get('hours', 0))
        ot_mult = float(ref.get('ot_mult', 1.5))

        # Skip if Daily Hours is 0/Missing (Cannot calculate rate)
        if daily_req <= 0:
            continue

        # --- THE REQUESTED MATH ---
        
        # 1. Monthly Threshold (e.g., 9 * 30 = 270)
        monthly_required_hours = daily_req * 30
        
        # 2. Hourly Rate
        # (Monthly Salary / 30 days) / Daily Hours
        hourly_rate = (salary / 30) / daily_req
            
        # 3. Total Worked Hours (Sum of duration)
        total_worked_hours = sum(entry['days'].values())

        # 4. Overtime Calculation
        if total_worked_hours > monthly_required_hours:
            ot_hours = total_worked_hours - monthly_required_hours
            regular_hours = monthly_required_hours # Capped at threshold
        else:
            ot_hours = 0
            regular_hours = total_worked_hours

        # 5. Final Pay
        base_pay = regular_hours * hourly_rate
        overtime_pay = ot_hours * hourly_rate * ot_mult
        total_pay = base_pay + overtime_pay

        report.append({
            "id": emp_id,
            "name": entry['name'],
            "salary": salary,
            "req_hours": monthly_required_hours,
            "worked_hours": round(total_worked_hours, 2),
            "ot_hours": round(ot_hours, 2),
            "hourly_rate": round(hourly_rate, 2),
            "final_pay": round(total_pay, 2)
        })
        
    return pd.DataFrame(report)