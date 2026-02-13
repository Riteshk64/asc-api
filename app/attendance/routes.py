import io
import base64
import pandas as pd
from flask import request, jsonify
from app.auth.jwt_middleware import jwt_required
from app.common.decorators import admin_only
from .processor import extract_raw_attendance, calculate_payroll, normalize_id
from . import attendance

def get_col_name(df, candidates):
    """
    Helper to find a column name in the dataframe that matches one of the candidates.
    Case-insensitive.
    """
    cols = [str(c).lower().strip() for c in df.columns]
    for cand in candidates:
        if cand in cols:
            # Return the actual column name from the dataframe
            return df.columns[cols.index(cand)]
    return None

@attendance.route('/calculate-payroll', methods=['POST'])
@jwt_required
@admin_only
def calculate_payroll_route():
    if 'attendance_file' not in request.files or 'master_file' not in request.files:
        return jsonify({"error": "Missing files. Please upload both Attendance and Master files."}), 400
        
    try:
        att_file = request.files['attendance_file']
        master_file = request.files['master_file']
        
        # 1. Parse Master File
        master_df = pd.read_excel(master_file)
        
        # Identify Columns intelligently
        id_col = get_col_name(master_df, ['id', 'emp_id', 'emp id', 'code', 'emp code'])
        salary_col = get_col_name(master_df, ['salary', 'monthly_salary', 'monthly salary', 'basic', 'stipend', 'amount'])
        hours_col = get_col_name(master_df, ['hours', 'daily_hours', 'daily hours', 'req_hours', 'shift hours'])
        ot_col = get_col_name(master_df, ['ot_mult', 'overtime_multiplier', 'ot rate'])
        
        if not id_col:
            return jsonify({"error": "Could not find an 'ID' column in the Master file."}), 400
            
        ref_map = {}
        for _, row in master_df.iterrows():
            raw_id = row[id_col]
            if pd.isna(raw_id): continue
            
            clean_id = normalize_id(raw_id)
            
            # Extract values using the detected column names
            # Default Salary to 0, Hours to 9 (since you mentioned 9*30=270 mostly)
            salary_val = row[salary_col] if salary_col else 0
            hours_val = row[hours_col] if hours_col else 0 
            ot_val = row[ot_col] if ot_col else 1.5

            ref_map[clean_id] = {
                'salary': salary_val,
                'hours': hours_val,
                'ot_mult': ot_val
            }
            
        # 2. Process Attendance
        raw_data = extract_raw_attendance(att_file)
        
        # 3. Calculate Logic
        result_df = calculate_payroll(raw_data, ref_map)
        
        if result_df.empty:
             return jsonify({"error": "No matching employees found. Check if IDs in Master file match Attendance file."}), 400

        # 4. Prepare Response
        ui_data = result_df.to_dict(orient='records')
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            result_df.to_excel(writer, index=False, sheet_name='Payroll')
        output.seek(0)
        b64_data = base64.b64encode(output.read()).decode('utf-8')
        
        return jsonify({
            "results": ui_data,
            "excel_file": b64_data
        })

    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500