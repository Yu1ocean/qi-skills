import pandas as pd
import numpy as np
import os
import argparse
import json

# =============================================================================
# v6 Charting Logic (Integrated from v6-panoramic-chart-generator)
# =============================================================================

class PiecewiseMap:
    def __init__(self, x_breaks, y_breaks):
        self.x_breaks = x_breaks
        self.y_breaks = y_breaks

    def map(self, x):
        xb, yb = self.x_breaks, self.y_breaks
        if x <= xb[0]: return yb[0]
        for i in range(len(xb) - 1):
            x0, x1 = xb[i], xb[i + 1]
            y0, y1 = yb[i], yb[i + 1]
            if x <= x1:
                if x1 == x0: return y1
                return y0 + (x - x0) * (y1 - y0) / (x1 - x0)
        x0, x1 = xb[-2], xb[-1]
        y0, y1 = yb[-2], yb[-1]
        slope = (y1 - y0) / (x1 - x0) if x1 != x0 else 1.0
        return y1 + (x - x1) * slope

    def map_series(self, xs):
        return np.array([self.map(float(v)) for v in xs], dtype=float)

def get_v6_share_map():
    # v6 share breaks to prevent compression of small percentages (T3-T5)
    x = [0.0, 0.005, 0.02, 0.08, 0.20, 0.40, 1.0]
    y = [0.0, 0.25, 0.45, 0.60, 0.75, 0.88, 1.0]
    return PiecewiseMap(x, y)

# =============================================================================
# Core Analysis Logic
# =============================================================================

def process_merchant_tiers(input_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Load Data (Assume xlsx or csv)
    if input_path.endswith('.xlsx'):
        df = pd.read_excel(input_path, sheet_name=0) # Read the first sheet or specific sheet
        # Handle cases where the first row is a note (like in the reference sheet)
        if df.columns[0].startswith('💡'):
            df = pd.read_excel(input_path, sheet_name=0, skiprows=1)
    else:
        df = pd.read_csv(input_path)

    # 2. Field Mapping & Cleaning (Align to V2.0 Standard)
    mapping = {
        'p_date': 'Date',
        'global_seller_id': 'Seller_ID',
        'global_seller_name': 'Seller_Name',
        '运营国家': 'Country',
        '一级类目': 'Category',
        'gmv_tier_1d': 'Tier',
        '日均GMV/K': 'Daily_Avg_GMV_K'
    }
    
    # Try to find mapping if original names differ
    for old, new in mapping.items():
        if old in df.columns:
            df = df.rename(columns={old: new})
    
    # Ensure Tier is T1-T5
    if 'Tier' in df.columns:
        df['Tier'] = df['Tier'].astype(str).str.extract(r'(T\d)').fillna('T1')
    
    # Filter for last 6 months (if Date column exists)
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'])
        latest_date = df['Date'].max()
        six_months_ago = latest_date - pd.DateOffset(months=6)
        df_6m = df[df['Date'] > six_months_ago].copy()
    else:
        df_6m = df.copy()

    # --- Sheet 1: Raw data ---
    raw_data_path = os.path.join(output_dir, "Sheet1_Raw_data.csv")
    # V3 Update: Truncated output for Lark Sheet (Sampling top 10,000)
    if 'Daily_Avg_GMV_K' in df.columns:
        df_truncated = df.sort_values(by='Daily_Avg_GMV_K', ascending=False).head(10000)
    else:
        df_truncated = df.head(10000)
    df_truncated.to_csv(raw_data_path, index=False)

    # --- Sheet 2: 商家结构矩阵 ---
    # Group by Country, Category, Tier
    matrix_groups = ['Country', 'Category']
    avail_groups = [g for g in matrix_groups if g in df.columns]
    
    if avail_groups:
        pivot_count = df.pivot_table(index=avail_groups, columns='Tier', values='Seller_ID', aggfunc='nunique', fill_value=0)
        pivot_gmv = df.pivot_table(index=avail_groups, columns='Tier', values='Daily_Avg_GMV_K', aggfunc='sum', fill_value=0)
        
        # Calculate percentages
        total_count = pivot_count.sum(axis=1)
        total_gmv = pivot_gmv.sum(axis=1)
        
        matrix_df = pd.DataFrame(index=pivot_count.index)
        for t in sorted(df['Tier'].unique()):
            matrix_df[f'{t} Count'] = pivot_count[t]
            matrix_df[f'{t} GMV'] = pivot_gmv[t]
            matrix_df[f'{t} Count %'] = (pivot_count[t] / total_count).apply(lambda x: f"{x:.2%}")
            matrix_df[f'{t} GMV %'] = (pivot_gmv[t] / total_gmv).apply(lambda x: f"{x:.2%}")
            
        matrix_path = os.path.join(output_dir, "Sheet2_商家结构矩阵.csv")
        matrix_df.reset_index().to_csv(matrix_path, index=False)
    
    # --- Sheet 3: 近6个月增长表 ---
    if 'Date' in df_6m.columns:
        df_6m['Month'] = df_6m['Date'].dt.to_period('M')
        growth_df = df_6m.groupby(['Month', 'Tier'])['Daily_Avg_GMV_K'].sum().unstack(fill_value=0)
        growth_df['Total_GMV'] = growth_df.sum(axis=1)
        growth_df['MoM %'] = growth_df['Total_GMV'].pct_change().apply(lambda x: f"{x:.2%}" if not pd.isna(x) else "-")
        
        growth_path = os.path.join(output_dir, "Sheet3_近6个月增长表.csv")
        growth_df.reset_index().to_csv(growth_path, index=False)

    # --- Integrated v6 Charting Data Prep ---
    # Prepare v6 panoramic data
    if 'Tier' in df.columns and 'Daily_Avg_GMV_K' in df.columns:
        share_map = get_v6_share_map()
        # Example: National level structure
        nat_struct = df.groupby('Tier')['Daily_Avg_GMV_K'].sum()
        nat_count = df.groupby('Tier')['Seller_ID'].nunique()
        
        v6_meta = {
            "national_stats": {
                "counts": nat_count.to_dict(),
                "gmv": nat_struct.to_dict(),
                "mapped_share": {t: float(share_map.map(v/nat_struct.sum())) for t, v in nat_struct.items()}
            }
        }
        with open(os.path.join(output_dir, "v6_chart_meta.json"), "w") as f:
            json.dump(v6_meta, f, indent=4)

    return {
        "raw": raw_data_path,
        "matrix": matrix_path if avail_groups else None,
        "growth": growth_path if 'Date' in df_6m.columns else None,
        "v6_meta": os.path.join(output_dir, "v6_chart_meta.json")
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output_dir", default="analysis_output")
    args = parser.parse_args()
    
    results = process_merchant_tiers(args.input, args.output_dir)
    print(json.dumps(results, indent=2))
