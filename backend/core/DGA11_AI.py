# ============================================================
#  DGA11_AI.py  —  AI-Enhanced DGA Analysis Tool (Dashboard Edition)
#  Standard: IEEE C57.104-2019
#  ML Model : XGBoost trained on new data set
#
#  Architecture:
#    - Model trains ONCE at startup.
#    - main() loops: input form -> run_analysis() -> dashboard.
#    - The dashboard embeds live figures (no PNG reloads), and lets you
#      start a NEW analysis without restarting / retraining.
#    - Save figures, save Word report, or print the text report from the dash.
# ============================================================

import sys
sys.stdout.reconfigure(encoding='utf-8')

import io
import os
import json
import datetime
import warnings
import contextlib
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")                       # render off-screen; we embed into Tk
import matplotlib.patches as mpatches
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

warnings.filterwarnings('ignore')

SCRIPT_DIR = Path(__file__).parent
BAR_PNG   = str(SCRIPT_DIR / 'dga_bar_chart.png')
DUVAL_PNG = str(SCRIPT_DIR / 'duval_triangle.png')
PENTAGON1_PNG = str(SCRIPT_DIR / 'duval_pentagon_1.png')
PENTAGON2_PNG = str(SCRIPT_DIR / 'duval_pentagon_2.png')
TREND_PNG = str(SCRIPT_DIR / 'dga_trend.png')

print('✅ All libraries loaded successfully!')

# ============================================================
#  STEP 1 — Train AI Model (runs once at startup)
# ============================================================
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import classification_report
from xgboost import XGBClassifier
import joblib

def engineer_features(df):
    """
    Engineer diagnostic features from raw gas concentrations.
    Input columns required: H2, CH4, C2H6, C2H4, C2H2
    Returns DataFrame with original + engineered features.
    """
    eps = 1e-6
    d = df.copy()

    # Rogers Ratios
    d['R1_C2H2_C2H4'] = d['C2H2'] / (d['C2H4'] + eps)
    d['R2_CH4_H2']    = d['CH4']  / (d['H2']   + eps)
    d['R3_C2H4_C2H6'] = d['C2H4'] / (d['C2H6'] + eps)
    d['R4_C2H2_CH4']  = d['C2H2'] / (d['CH4']  + eps)
    d['R5_C2H6_C2H2'] = d['C2H6'] / (d['C2H2'] + eps)

    # Duval % components
    tri = d['CH4'] + d['C2H4'] + d['C2H2'] + eps
    d['pct_CH4']  = d['CH4']  / tri * 100
    d['pct_C2H4'] = d['C2H4'] / tri * 100
    d['pct_C2H2'] = d['C2H2'] / tri * 100

    # TDCG (without CO since dataset lacks it)
    d['TDCG'] = d['H2'] + d['CH4'] + d['C2H6'] + d['C2H4'] + d['C2H2']

    # Log-transform raw gases
    for g in ['H2', 'CH4', 'C2H6', 'C2H4', 'C2H2']:
        d[f'log_{g}'] = np.log1p(d[g])

    return d

def train_model(dataset_path='new data set.xlsx'):
    """Train XGBoost fault classifier. Returns (model, le, feature_cols, acc, report)."""
    print('\n' + '='*60)
    print('  TRAINING AI MODEL — NEW DATASET')
    print('='*60)

    if dataset_path.endswith('.csv'):
        df = pd.read_csv(dataset_path)
    else:
        df = pd.read_excel(dataset_path)

    df = df[['H2', 'CH4', 'C2H6', 'C2H4', 'C2H2', 'Type']]
    df = df.dropna(subset=['Type'])

    print(f'  Dataset loaded: {df.shape[0]} samples, {df.shape[1]} columns')

    df_feat = engineer_features(df)

    feature_cols = [
        'H2', 'CH4', 'C2H6', 'C2H4', 'C2H2',
        'R1_C2H2_C2H4', 'R2_CH4_H2', 'R3_C2H4_C2H6',
        'R4_C2H2_CH4', 'R5_C2H6_C2H2',
        'pct_CH4', 'pct_C2H4', 'pct_C2H2',
        'TDCG',
        'log_H2', 'log_CH4', 'log_C2H6', 'log_C2H4', 'log_C2H2',
    ]

    X = df_feat[feature_cols].values
    le = LabelEncoder()
    y = le.fit_transform(df['Type'])

    print(f'  Classes: {list(le.classes_)}')

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )

    model = XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.08,
        subsample=0.8, colsample_bytree=0.8,
        use_label_encoder=False, eval_metric='mlogloss', random_state=42
    )
    model.fit(X_train, y_train)

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(model, X, y, cv=cv, scoring='accuracy')
    test_acc = model.score(X_test, y_test)

    y_pred = model.predict(X_test)
    report = classification_report(y_test, y_pred, target_names=le.classes_)

    print(f'  Test Accuracy     : {test_acc*100:.1f}%')
    print(f'  CV Accuracy (5-fold): {cv_scores.mean()*100:.1f}% ± {cv_scores.std()*100:.1f}%')

    joblib.dump(model, 'dga_fault_model.pkl')
    joblib.dump(le,    'dga_label_encoder.pkl')
    print('  ✅ Model saved: dga_fault_model.pkl  |  dga_label_encoder.pkl')

    return model, le, feature_cols, test_acc, report

# ── Run training ──────────────────────────────────────────────
DATASET_PATH = 'new data set.xlsx'
if not os.path.exists(DATASET_PATH):
    DATASET_PATH = '/mnt/user-data/uploads/new data set.xlsx'

_model, _le, _feature_cols, _train_acc, _train_report = train_model(DATASET_PATH)
_AI_AVAILABLE = True

# ============================================================
#  STEP 2 — AI Prediction Function
# ============================================================
def ai_predict(H2, CH4, C2H6, C2H4, C2H2):
    """AI fault prediction using trained XGBoost model.
    Returns (fault_label, confidence_%, probability_dict)."""
    if not _AI_AVAILABLE:
        return 'N/A (model not loaded)', 0.0, {}

    eps = 1e-6
    R1 = C2H2  / (C2H4  + eps)
    R2 = CH4   / (H2    + eps)
    R3 = C2H4  / (C2H6  + eps)
    R4 = C2H2  / (CH4   + eps)
    R5 = C2H6  / (C2H2  + eps)

    tri = CH4 + C2H4 + C2H2 + eps
    pct_CH4  = CH4  / tri * 100
    pct_C2H4 = C2H4 / tri * 100
    pct_C2H2 = C2H2 / tri * 100

    TDCG = H2 + CH4 + C2H6 + C2H4 + C2H2

    feat = np.array([[
        H2, CH4, C2H6, C2H4, C2H2,
        R1, R2, R3, R4, R5,
        pct_CH4, pct_C2H4, pct_C2H2,
        TDCG,
        np.log1p(H2), np.log1p(CH4), np.log1p(C2H6),
        np.log1p(C2H4), np.log1p(C2H2),
    ]])

    pred  = _model.predict(feat)[0]
    proba = _model.predict_proba(feat)[0]
    label = _le.inverse_transform([pred])[0]
    conf  = proba.max() * 100
    prob_dict = dict(zip(_le.classes_, (proba * 100).round(1)))
    return label, conf, prob_dict

# ============================================================
#  GUI toolkit
# ============================================================
import customtkinter as ctk
from tkinter import messagebox, filedialog

# ============================================================
#  Database Source (SQL Server) — load DGA samples by Asset Number
#  Mirrors the TrendAnalysisTool: CEB_TRANSMISSION.dbo.CEB_DGA_DATA
# ============================================================
try:
    import pyodbc
    _PYODBC_AVAILABLE = True
except ImportError:
    _PYODBC_AVAILABLE = False

_DB_CONFIG_PATH = SCRIPT_DIR / "config.json"

# DB column  →  app gas name
DB_GAS_COLUMNS = {
    "H2ppm": "H2",   "CH4ppm": "CH4", "COppm": "CO",   "CO2ppm": "CO2",
    "C2H4ppm": "C2H4", "C2H6ppm": "C2H6", "C2H2ppm": "C2H2",
    "O2ppm": "O2",   "N2ppm": "N2",
}

def load_db_config():
    if _DB_CONFIG_PATH.exists():
        try:
            return json.loads(_DB_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"server": "", "database": "CEB_TRANSMISSION", "auth": "windows",
            "username": "", "password": ""}

def save_db_config(cfg):
    try:
        _DB_CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass

def _find_odbc_driver():
    preferred = [
        "ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server", "SQL Server Native Client 11.0", "SQL Server",
    ]
    installed = pyodbc.drivers()
    for d in preferred:
        if d in installed:
            return d
    for d in installed:
        if "SQL Server" in d:
            return d
    return "ODBC Driver 17 for SQL Server"

def _build_conn_str(cfg):
    driver = _find_odbc_driver()
    base = (f"DRIVER={{{driver}}};SERVER={cfg['server']};"
            f"DATABASE={cfg['database']};TrustServerCertificate=yes;")
    if cfg.get("auth") == "windows":
        return base + "Trusted_Connection=yes;"
    return base + f"UID={cfg.get('username','')};PWD={cfg.get('password','')};"

def fetch_asset_dga_rows(cfg, asset):
    """All DGA samples for one AssetNumber, newest first.
    Columns: Date + H2, CH4, CO, CO2, C2H4, C2H6, C2H2, O2, N2."""
    cols_sql = ", ".join(DB_GAS_COLUMNS.keys())
    sql = f"""
        SELECT DateSampled, {cols_sql}
        FROM [{cfg['database']}].[dbo].[CEB_DGA_DATA]
        WHERE LTRIM(RTRIM(AssetNumber)) = ?
        ORDER BY DateSampled DESC
    """
    conn = pyodbc.connect(_build_conn_str(cfg), timeout=30)
    cur = conn.cursor()
    cur.execute(sql, [asset.strip()])
    columns = [c[0] for c in cur.description]
    rows = cur.fetchall()
    conn.close()
    df = pd.DataFrame.from_records(rows, columns=columns)
    if not df.empty:
        df["DateSampled"] = pd.to_datetime(df["DateSampled"])
        df = df.rename(columns=DB_GAS_COLUMNS)
        for g in DB_GAS_COLUMNS.values():
            df[g] = pd.to_numeric(df[g], errors="coerce").fillna(0.0)
        df = df.rename(columns={"DateSampled": "Date"})
        df = df.dropna(subset=["Date"]).sort_values("Date", ascending=False).reset_index(drop=True)
    return df

# ============================================================
#  IEEE C57.104-2019 Norm Tables
# ============================================================
# Indices: [Sealed: 1-9y, 10-30y, >30y, Unk | Free: 1-9y, 10-30y, >30y, Unk]
TABLE1 = {  # 90th percentile (DGA Status 1 limits)
    'H2'   : [10,   40,    40,    40,     80,    100,   100,   100],
    'CH4'  : [25,   50,    90,    50,     90,    150,   200,   150],
    'C2H6' : [10,   60,    150,   60,     90,    175,   250,   175],
    'C2H4' : [20,   50,    90,    50,     50,    95,    175,   100],
    'C2H2' : [1,    2,     2,     2,      1,     2,     4,     2],
    'CO'   : [500,  700,   900,   700,    900,   1100,  1100,  1100],
    'CO2'  : [3500, 5500,  7000,  5500,   9000,  14000, 14000, 12500],
}
TABLE2 = {  # 95th percentile (DGA Status 2/3 boundary)
    'H2'   : [40,   80,    80,    80,     100,   150,   150,   150],
    'CH4'  : [45,   90,    145,   90,     110,   240,   310,   240],
    'C2H6' : [30,   115,   245,   115,    150,   280,   400,   280],
    'C2H4' : [25,   60,    115,   60,     80,    155,   280,   165],
    'C2H2' : [2,    2,     4,     2,      2,     4,     7,     4],
    'CO'   : [600,  900,   1100,  900,    1100,  1400,  1400,  1400],
    'CO2'  : [5000, 8000,  10000, 8000,   12500, 18500, 18500, 16500],
}
TABLE3 = {  # Delta limits: [Sealed, Free-Breathing]
    'H2'   : [25, 40],  'CH4'  : [10, 30], 'C2H6' : [7, 25], 'C2H4' : [20, 20],
    'C2H2' : [0, 0],    'CO'   : [175, 250], 'CO2'  : [1750, 2500],
}
TABLE4 = {  # Rate norms ppm/year: [S_4-9M, S_10-24M, F_4-9M, F_10-24M]
    'H2'   : [25, 10, 50, 20], 'CH4'  : [4, 3, 15, 10], 'C2H6' : [3, 2, 15, 9],
    'C2H4' : [7, 5, 10, 7],    'C2H2' : [0, 0, 0, 0],
    'CO'   : [100, 80, 200, 100], 'CO2'  : [1000, 800, 1750, 1000],
}

STATUS_EMOJI = {1: '🟢', 2: '🟡', 3: '🔴'}
STATUS_LABEL = {1: 'NORMAL', 2: 'INVESTIGATE', 3: 'URGENT ATTENTION'}
STATUS_COLORS = {1: "#00CC66", 2: "#FFD700", 3: "#FF4500"}

# ============================================================
#  Pure diagnostic helpers
# ============================================================
def calculate_regression_rate(gas_name, current_val, current_date_str,
                              prev_val=None, prev_date_str=None, history_df=None):
    """Slope via linear regression for 3 to 6 samples (IEEE 4-24 months)."""
    try:
        data_points = []
        try:
            d_curr = datetime.datetime.strptime(current_date_str, "%Y-%m-%d")
        except Exception:
            return 0.0, "Invalid Date"
        data_points.append((d_curr, current_val))

        if prev_val is not None and prev_date_str:
            try:
                d_prev = datetime.datetime.strptime(prev_date_str, "%Y-%m-%d")
                if d_prev < d_curr:
                    data_points.append((d_prev, prev_val))
            except Exception:
                pass

        if history_df is not None and gas_name in history_df.columns:
            h_df = history_df.sort_values(by='Date', ascending=False)
            for _, row in h_df.iterrows():
                d_hist = row['Date']
                if (d_curr - d_hist).days > 731:
                    continue
                if len(data_points) >= 6:
                    break
                if not any(abs((d_hist - dp[0]).days) < 1 for dp in data_points):
                    data_points.append((d_hist, row[gas_name]))

        if len(data_points) < 3:
            return 0.0, len(data_points), 0.0

        earliest = min(d for d, v in data_points)
        x = np.array([(d - earliest).days for d, v in data_points])
        y = np.array([v for d, v in data_points])

        m, c = np.polyfit(x, y, 1)
        rate_yr = m * 365.25

        latest = max(d for d, v in data_points)
        total_months = (latest - earliest).days / 30.44
        return round(rate_yr, 1), len(data_points), total_months
    except Exception:
        return 0.0, 0, 0.0

def rogers_ratios(H2, CH4, C2H6, C2H4, C2H2):
    R1 = C2H2 / C2H4 if C2H4 > 0 else 0
    R2 = CH4  / H2   if H2   > 0 else 0
    R3 = C2H4 / C2H6 if C2H6 > 0 else 0

    if R1 < 0.1 and 0.1 <= R2 <= 1.0 and R3 < 1.0:
        return 'Case 0: Unit Normal', R1, R2, R3
    elif R1 < 0.1 and R2 < 0.1 and R3 < 1.0:
        return 'Case 1: Low-Energy Density Arcing — Partial Discharge (PD)', R1, R2, R3
    elif 0.1 <= R1 <= 3.0 and 0.1 <= R2 <= 1.0 and R3 > 3.0:
        return 'Case 2: High-Energy Arcing — Discharge (D2)', R1, R2, R3
    elif R1 < 0.1 and R2 > 1.0 and 1.0 <= R3 <= 3.0:
        return 'Case 3: Low-Temperature Thermal Fault', R1, R2, R3
    elif R1 < 0.1 and R2 > 1.0 and R3 > 3.0:
        return 'Case 4: High-Temperature Thermal Fault', R1, R2, R3
    else:
        return 'Cannot identify fault using Rogers ratios method', R1, R2, R3

def duval_triangle_1(CH4, C2H4, C2H2):
    total = CH4 + C2H4 + C2H2
    if total == 0:
        return 'INDETERMINATE (all gases zero)', 0, 0, 0

    pCH4  = CH4  / total * 100
    pC2H4 = C2H4 / total * 100
    pC2H2 = C2H2 / total * 100

    if pCH4 >= 98:
        zone = 'PD — Partial discharges of corona type'
    elif pC2H2 >= 29 and pC2H4 >= 23:
        zone = 'D2 — Discharges of high energy'
    elif pC2H2 >= 13 and pC2H4 < 23:
        zone = 'D1 — Discharges of low energy or partial discharges of sparking type'
    elif pC2H2 >= 4 and pC2H2 < 13:
        zone = 'DT — Mix of Thermal + Electrical Fault'
    elif pC2H4 >= 50 and pC2H2 < 15:
        zone = 'T3 — Thermal fault, t > 700 °C'
    elif 20 <= pC2H4 < 50 and pC2H2 < 4:
        zone = 'T2 — Thermal fault, 300 °C < t < 700 °C'
    elif pCH4 < 98 and pC2H4 < 20 and pC2H2 < 4:
        zone = 'T1 — Thermal fault, t < 300 °C'
    else:
        zone = 'DT — Mixed Zone (Thermal + Electrical)'

    return zone, round(pCH4, 1), round(pC2H4, 1), round(pC2H2, 1)


def duval_triangle_4(H2, CH4, C2H6):
    total = H2 + CH4 + C2H6
    if total == 0: return 'INDETERMINATE', 0, 0, 0
    h = H2 / total * 100
    m = CH4 / total * 100
    e = C2H6 / total * 100
    z = 'Unknown'
    if m >= 2 and m < 15 and e < 1: z = 'PD'
    elif h >= 9 and e >= 30 and e < 46: z = 'S'
    elif h >= 15 and e >= 24 and e < 30: z = 'S'
    elif m < 36 and e >= 1 and e < 24: z = 'S'
    elif m >= 15 and m < 36 and e < 1: z = 'S'
    elif m < 2 and e < 1: z = 'S'
    elif h < 9 and e >= 30: z = 'O'
    elif m >= 36 and e >= 24: z = 'C'
    elif h < 15 and e >= 24 and e < 30: z = 'C'
    elif h >= 9 and e >= 46: z = 'ND'
    return z, round(h, 1), round(m, 1), round(e, 1)

def duval_triangle_5(CH4, C2H4, C2H6):
    total = CH4 + C2H4 + C2H6
    if total == 0: return 'INDETERMINATE', 0, 0, 0
    m = CH4 / total * 100
    et = C2H4 / total * 100
    ea = C2H6 / total * 100
    z = 'Unknown'
    if et < 1 and ea >= 2 and ea < 14: z = 'PD'
    elif et >= 1 and et < 10 and ea >= 2 and ea < 14: z = 'O'
    elif et < 1 and ea < 2: z = 'O'
    elif et < 10 and ea >= 54: z = 'O'
    elif et < 10 and ea >= 14 and ea < 54: z = 'S'
    elif et >= 10 and et < 35 and ea < 12: z = 'T2'
    elif et >= 35 and ea < 12: z = 'T3'
    elif et >= 50 and ea >= 12 and ea < 14: z = 'T3'
    elif et >= 70 and ea >= 14: z = 'T3'
    elif et >= 35 and ea >= 30: z = 'T3'
    elif et >= 10 and et < 50 and ea >= 12 and ea < 14: z = 'C'
    elif et >= 10 and et < 70 and ea >= 14 and ea < 30: z = 'C'
    elif et >= 10 and et < 35 and ea >= 30: z = 'ND'
    return z, round(m, 1), round(et, 1), round(ea, 1)

def duval_pentagon_centroid(H2, C2H6, CH4, C2H4, C2H2):
    """Compute the Duval Pentagon centroid per IEEE C57.104-2019 / Duval 2014.

    Gas axis angles (standard Cartesian, CCW from positive X-axis):
      H2   → 90°   (top)
      C2H6 → 162°  (upper-left)
      CH4  → 234°  (lower-left)
      C2H4 → 306°  (lower-right)
      C2H2 → 18°   (upper-right)

    Each gas is plotted at radius = percentage × 0.40, so 100 % maps to r = 40,
    matching the outer pentagon whose vertex H2 is at (0, 40).
    The centroid of the resulting irregular polygon is computed via the
    standard shoelace / polygon-centroid formula.
    """
    import math
    total = H2 + C2H6 + CH4 + C2H4 + C2H2
    if total == 0:
        return 0.0, 0.0

    # Relative percentages
    pct = [
        H2   / total * 100,   # axis 0: H2   at 90°
        C2H6 / total * 100,   # axis 1: C2H6 at 162°
        CH4  / total * 100,   # axis 2: CH4  at 234°
        C2H4 / total * 100,   # axis 3: C2H4 at 306°
        C2H2 / total * 100,   # axis 4: C2H2 at 18°
    ]
    angles_deg = [90, 162, 234, 306, 18]

    # DO NOT SCALE BY 0.4! The Duval Pentagon calculates the centroid of the 
    # polygon formed by the 0-100% values. The mathematical limit of this 
    # centroid is 33.33 units from the origin, which naturally fits inside 
    # the defined standard zones that have an outer radius of 40.
    SCALE = 1.0

    pts = [
        (pct[i] * SCALE * math.cos(math.radians(angles_deg[i])),
         pct[i] * SCALE * math.sin(math.radians(angles_deg[i])))
        for i in range(5)
    ]

    # Shoelace / polygon centroid formula
    n = len(pts)
    area = 0.0
    cx   = 0.0
    cy   = 0.0
    for i in range(n):
        x_i,   y_i   = pts[i]
        x_ip1, y_ip1 = pts[(i + 1) % n]
        factor = (x_i * y_ip1 - x_ip1 * y_i)
        area += factor
        cx   += (x_i   + x_ip1) * factor
        cy   += (y_i   + y_ip1) * factor

    area *= 0.5
    if abs(area) < 1e-9:
        # Degenerate polygon – fall back to arithmetic mean of vertices
        cx = sum(p[0] for p in pts) / n
        cy = sum(p[1] for p in pts) / n
    else:
        cx = cx / (6.0 * area)
        cy = cy / (6.0 * area)

    return cx, cy


def _nearest_zone(cx, cy, zones):
    """Return the zone name whose polygon boundary is closest to (cx, cy).

    Uses minimum distance from the point to each polygon edge segment,
    which is more accurate than nearest vertex distance.
    """
    import math

    def _seg_dist_sq(px, py, ax, ay, bx, by):
        """Squared distance from point (px,py) to segment (ax,ay)-(bx,by)."""
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return (px - ax) ** 2 + (py - ay) ** 2
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        nx, ny = ax + t * dx, ay + t * dy
        return (px - nx) ** 2 + (py - ny) ** 2

    best_dist_sq = float('inf')
    best_zone    = 'Unknown'
    for name, poly in zones.items():
        n = len(poly)
        for i in range(n):
            ax, ay = poly[i]
            bx, by = poly[(i + 1) % n]
            d2 = _seg_dist_sq(cx, cy, ax, ay, bx, by)
            if d2 < best_dist_sq:
                best_dist_sq = d2
                best_zone    = name
    return best_zone


# ── IEEE C57.104-2019 / Duval 2014 zone boundary polygons ────────────────────
#
# Pentagon 1 zones  (x, y) in the same coordinate system as the centroid:
#   Positive Y = up  (H2 apex at (0, 40))
#   Positive X = right (C2H2 / C2H4 side)
#
# Source: Duval & Lamarre, IEEE Elec. Insul. Mag. 2014 + IEEE C57.104-2019 Annex D
# ---------------------------------------------------------------------------
_PENT1_ZONES = {
    'PD': [(  0.0,  33.0), ( -1.0,  33.0), ( -1.0,  24.5), (  0.0,  24.5)],
    'D1': [(  0.0,  40.0), ( 38.0,  12.0), ( 32.0,  -6.1), (  4.0,  16.0),
           (  0.0,   1.5)],
    'D2': [(  4.0,  16.0), ( 32.0,  -6.1), ( 24.3, -30.0), (  0.0,  -3.0),
           (  0.0,   1.5)],
    # T3: Use (1.0, -32.4) to perfectly share the boundary with T2 and eliminate gaps.
    'T3': [(  0.0,  -3.0), ( 24.3, -30.0), ( 23.5, -32.4), (  1.0, -32.4),
           ( -6.0,  -4.0)],
    'T2': [( -6.0,  -4.0), (  1.0, -32.4), (-22.5, -32.4)],
    'T1': [( -6.0,  -4.0), (-22.5, -32.4), (-23.5, -32.4), (-35.0,   3.0),
           (  0.0,   1.5), (  0.0,  -3.0)],
    'S':  [(  0.0,   1.5), (-35.0,   3.1), (-38.0,  12.4), (  0.0,  40.0),
           (  0.0,  33.0), ( -1.0,  33.0), ( -1.0,  24.5), (  0.0,  24.5)],
}

# Pentagon 2 zones — Source: same references as above
_PENT2_ZONES = {
    'PD':   [(  0.0,  33.0), ( -1.0,  33.0), ( -1.0,  24.5), (  0.0,  24.5)],
    'D1':   [(  0.0,  40.0), ( 38.0,  12.0), ( 32.0,  -6.1), (  4.0,  16.0),
             (  0.0,   1.5)],
    'D2':   [(  4.0,  16.0), ( 32.0,  -6.1), ( 24.3, -30.0), (  0.0,  -3.0),
             (  0.0,   1.5)],
    'S':    [(  0.0,   1.5), (-35.0,   3.1), (-38.0,  12.4), (  0.0,  40.0),
             (  0.0,  33.0), ( -1.0,  33.0), ( -1.0,  24.5), (  0.0,  24.5)],
    'T3-H': [(  0.0,  -3.0), ( 24.3, -30.0), ( 23.5, -32.4), (  2.5, -32.4),
             ( -3.5,  -3.0)],
    'C':    [( -3.5,  -3.0), (  2.5, -32.4), (-21.5, -32.4), (-11.0,  -8.0)],
    'O':    [( -3.5,  -3.0), (-11.0,  -8.0), (-21.5, -32.4), (-23.5, -32.4),
             (-35.0,   3.1), (  0.0,   1.5), (  0.0,  -3.0)],
}


def duval_pentagon_1(H2, C2H6, CH4, C2H4, C2H2):
    """Classify using Duval Pentagon 1 (IEEE C57.104-2019).
    Returns (zone_name, cx, cy)."""
    from matplotlib.path import Path
    cx, cy = duval_pentagon_centroid(H2, C2H6, CH4, C2H4, C2H2)

    # Primary: point-in-polygon test (small positive radius handles edge cases)
    for name, poly in _PENT1_ZONES.items():
        if Path(poly).contains_point((cx, cy), radius=0.5):
            return name, cx, cy

    # Fallback: nearest polygon edge
    return _nearest_zone(cx, cy, _PENT1_ZONES), cx, cy


def duval_pentagon_2(H2, C2H6, CH4, C2H4, C2H2):
    """Classify using Duval Pentagon 2 (IEEE C57.104-2019).
    Returns (zone_name, cx, cy)."""
    from matplotlib.path import Path
    cx, cy = duval_pentagon_centroid(H2, C2H6, CH4, C2H4, C2H2)

    # Primary: point-in-polygon test
    for name, poly in _PENT2_ZONES.items():
        if Path(poly).contains_point((cx, cy), radius=0.5):
            return name, cx, cy

    # Fallback: nearest polygon edge
    return _nearest_zone(cx, cy, _PENT2_ZONES), cx, cy

def build_duval_bg(ax, eval_func, labels):
    import numpy as np
    pts = []
    colors = []
    zone_colors = {'PD':'#AED6F1', 'T1':'#A9DFBF', 'T2':'#F9E79F', 'T3':'#F0B27A', 'D1':'#D2B4DE', 'D2':'#F1948A', 'DT':'#CCD1D1', 'S':'#D5DBDB', 'O':'#FAD7A1', 'C':'#E6B0AA', 'ND':'#FFFFFF', 'Unknown':'#FFFFFF'}
    for a in range(0, 101, 1):
        for b in range(0, 101 - a, 1):
            c = 100 - a - b
            # mapping: a=bottom-left, b=bottom-right, c=top
            # T4: a=C2H6, b=CH4, c=H2  => eval_func(H2, CH4, C2H6) = eval_func(c, b, a)
            # T5: a=C2H6, b=C2H4, c=CH4 => eval_func(CH4, C2H4, C2H6) = eval_func(c, b, a)
            zone, _, _, _ = eval_func(c, b, a)
            px, py = ternary_to_cartesian(a, b, c)
            pts.append([px, py])
            colors.append(zone_colors.get(zone, '#FFFFFF'))
    pts = np.array(pts)
    ax.scatter(pts[:,0], pts[:,1], c=colors, s=30, alpha=0.3, edgecolors='none', marker='h')
    
    triangle = mpatches.Polygon([[0, 0], [1, 0], [0.5, 3**0.5/2]], closed=True, fill=False, edgecolor='black', linewidth=2)
    ax.add_patch(triangle)
    ax.text(-0.07, 0.0, labels[0], fontsize=12, ha='center', color='#1A5276', fontweight='bold')
    ax.text( 1.05, 0.0, labels[1], fontsize=12, ha='center', color='#1A5276', fontweight='bold')
    ax.text( 0.5,  3**0.5/2 + 0.05, labels[2], fontsize=12, ha='center', color='#1A5276', fontweight='bold')
    ax.set_xlim(-0.1, 1.15); ax.set_ylim(-0.1, 1.0); ax.set_aspect('equal'); ax.axis('off')

def build_duval_4_figure(res):
    fig = Figure(figsize=(8, 7), dpi=100)
    ax = fig.add_subplot(111)
    if res["use_t4"]:
        build_duval_bg(ax, duval_triangle_4, ['% C2H6', '% CH4', '% H2'])
        px, py = ternary_to_cartesian(res['t4_e'], res['t4_m'], res['t4_h'])
        ax.plot(px, py, 'k*', markersize=20, zorder=10)
        ax.annotate(f" {res['transformer_id']}\n H2={res['t4_h']}%\n CH4={res['t4_m']}%\n C2H6={res['t4_e']}%", (px, py), fontsize=9, bbox=dict(boxstyle='round,pad=0.4', facecolor='white', alpha=0.8), xytext=(px+0.05, py+0.05))
        ax.set_title(f"Duval Triangle 4 — {res['transformer_id']}\nZone: {res['fault_t4_desc']}", fontsize=12, fontweight='bold', pad=15)
    else:
        ax.text(0.5, 0.5, 'Triangle 4 Not Applicable\n(Requires PD, T1, or T2 in Triangle 1)', ha='center', va='center', fontsize=14, color='gray')
        ax.axis('off')
    fig.tight_layout()
    return fig

def build_duval_5_figure(res):
    fig = Figure(figsize=(8, 7), dpi=100)
    ax = fig.add_subplot(111)
    if res["use_t5"]:
        build_duval_bg(ax, duval_triangle_5, ['% C2H6', '% C2H4', '% CH4'])
        px, py = ternary_to_cartesian(res['t5_ea'], res['t5_et'], res['t5_m'])
        ax.plot(px, py, 'k*', markersize=20, zorder=10)
        ax.annotate(f" {res['transformer_id']}\n CH4={res['t5_m']}%\n C2H4={res['t5_et']}%\n C2H6={res['t5_ea']}%", (px, py), fontsize=9, bbox=dict(boxstyle='round,pad=0.4', facecolor='white', alpha=0.8), xytext=(px+0.05, py+0.05))
        ax.set_title(f"Duval Triangle 5 — {res['transformer_id']}\nZone: {res['fault_t5_desc']}", fontsize=12, fontweight='bold', pad=15)
    else:
        ax.text(0.5, 0.5, 'Triangle 5 Not Applicable\n(Requires T2 or T3 in Triangle 1)', ha='center', va='center', fontsize=14, color='gray')
        ax.axis('off')
    fig.tight_layout()
    return fig

def ternary_to_cartesian(a, b, c):
    total = a + b + c
    if total == 0:
        return 0.5, 0.5
    a, b, c = a/total, b/total, c/total
    return b + c * 0.5, c * (3**0.5) / 2

ZONE_POLYS = {
    'PD':  [(98,2,0),(98,0,2),(100,0,0)],
    'T1':  [(0,0,4),(78,18,4),(98,2,0),(98,0,0),(0,0,0)],
    'T2':  [(0,20,4),(78,18,4),(50,46,4),(0,50,0),(0,20,0)],
    'T3':  [(0,50,0),(50,46,4),(15,85,0),(0,100,0)],
    'D1':  [(0,0,100),(0,23,77),(23,0,77)],
    'D2':  [(0,23,77),(0,71,29),(29,42,29),(71,0,29),(23,0,77)],
    'DT':  [(0,0,4),(23,0,77),(0,23,77),(0,20,4)],
}
ZONE_COLORS = {
    'PD': '#AED6F1', 'T1': '#A9DFBF', 'T2': '#F9E79F', 'T3': '#F0B27A',
    'D1': '#D2B4DE', 'D2': '#F1948A', 'DT': '#CCD1D1', 'S': '#D5DBDB',
    'O': '#FAD7A1', 'C': '#E6B0AA', 'T3-H': '#E59866', 'ND': '#FFFFFF',
    'Unknown': '#FFFFFF'
}

# ============================================================
#  Input state (set by the input form, read by run_analysis)
# ============================================================
transformer_id  = "TR-001"
sample_date     = "2025-01-15"
transformer_age = 10
H2 = CH4 = C2H6 = C2H4 = C2H2 = CO = CO2 = O2 = N2 = 0.0
has_previous    = False
prev_sample_date = "2024-01-15"
prev_H2 = prev_CH4 = prev_C2H6 = prev_C2H4 = prev_C2H2 = prev_CO = prev_CO2 = 0.0
total_samples   = 2
df_history_data = None   # full historical dataframe (Date + gas columns)

# ============================================================
#  STEP 3 — Input Form  (returns True if user submitted)
# ============================================================
def get_input_data(master):
    global df_history_data
    df_history_data = None      # reset stale history on each new analysis

    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")

    state = {"submitted": False}

    win = ctk.CTkToplevel(master)
    win.title("Enter DGA Data (IEEE C57.104-2019) Pro Version")
    win.geometry("1300x840")
    win.lift()
    win.after(100, win.focus_force)

    # Title
    title_frame = ctk.CTkFrame(win, fg_color="transparent")
    title_frame.pack(side="top", fill="x", pady=(20, 10))
    ctk.CTkLabel(title_frame, text="⚡ DGA Analyzer Pro",
                 font=ctk.CTkFont(family="Segoe UI", size=32, weight="bold"),
                 text_color="#00D2FF").pack()
    ctk.CTkLabel(title_frame, text="Advanced AI-Enhanced IEEE C57.104-2019 Diagnostics",
                 font=ctk.CTkFont(family="Segoe UI", size=14), text_color="gray").pack()

    # Submit button (bottom)
    submit_frame = ctk.CTkFrame(win, fg_color="transparent")
    submit_frame.pack(side="bottom", fill="x", padx=40, pady=20)

    main_frame = ctk.CTkScrollableFrame(win, fg_color="transparent")
    main_frame.pack(side="top", fill="both", expand=True, padx=20, pady=5)

    entries = {}

    def on_submit():
        global transformer_id, sample_date, transformer_age
        global H2, CH4, C2H6, C2H4, C2H2, CO, CO2, O2, N2
        global has_previous, prev_sample_date
        global prev_H2, prev_CH4, prev_C2H6, prev_C2H4, prev_C2H2, prev_CO, prev_CO2
        global total_samples
        try:
            transformer_id  = entries['Transformer ID'].get().strip() or "TR-001"
            sample_date     = entries['Sample Date'].get().strip()
            transformer_age = int(entries['Transformer Age (yrs)'].get() or 0)

            H2   = float(entries['H2'].get()   or 0)
            CH4  = float(entries['CH4'].get()  or 0)
            C2H6 = float(entries['C2H6'].get() or 0)
            C2H4 = float(entries['C2H4'].get() or 0)
            C2H2 = float(entries['C2H2'].get() or 0)
            CO   = float(entries['CO'].get()   or 0)
            CO2  = float(entries['CO2'].get()  or 0)
            O2   = float(entries['O2'].get()   or 0)
            N2   = float(entries['N2'].get()   or 0)

            has_previous = prev_var.get() == "yes"
            if has_previous:
                total_samples    = int(entries['Total Samples in Series'].get() or 2)
                prev_sample_date = entries['Prev Sample Date'].get().strip()
                prev_H2   = float(entries['Prev H2'].get()   or 0)
                prev_CH4  = float(entries['Prev CH4'].get()  or 0)
                prev_C2H6 = float(entries['Prev C2H6'].get() or 0)
                prev_C2H4 = float(entries['Prev C2H4'].get() or 0)
                prev_C2H2 = float(entries['Prev C2H2'].get() or 0)
                prev_CO   = float(entries['Prev CO'].get()   or 0)
                prev_CO2  = float(entries['Prev CO2'].get()  or 0)

            state["submitted"] = True
            win.destroy()
        except ValueError:
            messagebox.showerror("Error", "Please enter valid numbers for all gas concentrations and age.")

    btn_submit = ctk.CTkButton(submit_frame, text="⚡ Run DGA AI Analysis / Analyzer",
                               fg_color="#FF4500", hover_color="#CD3700",
                               height=55, font=ctk.CTkFont(size=20, weight="bold"),
                               corner_radius=12, command=on_submit)
    btn_submit.pack(fill="x")

    # Three-column layout: inputs | historical | loaded samples
    left_col = ctk.CTkFrame(main_frame, fg_color="transparent")
    left_col.grid(row=0, column=0, sticky="nw", padx=10, pady=10)
    right_col = ctk.CTkFrame(main_frame, fg_color="transparent")
    right_col.grid(row=0, column=1, sticky="nw", padx=10, pady=10)
    samples_col = ctk.CTkFrame(main_frame, fg_color="transparent")
    samples_col.grid(row=0, column=2, sticky="nsew", padx=10, pady=10)

    def create_card(parent, title, icon):
        card = ctk.CTkFrame(parent, corner_radius=15, border_width=1, border_color="#333333", fg_color="#1E1E1E")
        card.pack(fill="x", pady=10, ipady=10)
        ctk.CTkLabel(card, text=f"{icon} {title}", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color="#00D2FF").pack(anchor="w", padx=20, pady=(15, 10))
        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="x", padx=20, pady=5)
        return content

    def add_field(frame, label, default, row, col=0):
        ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=14)).grid(
            row=row, column=col*2, sticky="w", pady=8, padx=(0, 10))
        ent = ctk.CTkEntry(frame, width=150, height=35, border_width=1, corner_radius=8)
        ent.insert(0, str(default))
        ent.grid(row=row, column=col*2+1, pady=8, padx=(0, 10), sticky="w")
        entries[label] = ent
        return row + 1

    # ── Database loading (Asset Number → samples → pick current sample) ────────
    def apply_selected_sample(df_rows, idx):
        global df_history_data
        sel_row  = df_rows.iloc[idx]
        sel_date = sel_row['Date']

        entries['Sample Date'].delete(0, 'end')
        entries['Sample Date'].insert(0, sel_date.strftime('%Y-%m-%d'))
        for g in ['H2', 'CH4', 'CO', 'CO2', 'C2H4', 'C2H6', 'C2H2', 'O2', 'N2']:
            entries[g].delete(0, 'end')
            entries[g].insert(0, f"{sel_row[g]:g}")

        older = (df_rows[df_rows['Date'] < sel_date]
                 .sort_values('Date', ascending=False).reset_index(drop=True))

        if not older.empty:
            chk.select()
            prev_var.set("yes")
            df_history_data = older.copy()
            prev_row = older.iloc[0]
            entries['Total Samples in Series'].delete(0, 'end')
            entries['Total Samples in Series'].insert(0, str(len(older) + 1))
            entries['Prev Sample Date'].delete(0, 'end')
            entries['Prev Sample Date'].insert(0, prev_row['Date'].strftime('%Y-%m-%d'))
            for g in ['H2', 'CH4', 'CO', 'CO2', 'C2H4', 'C2H6', 'C2H2']:
                entries[f'Prev {g}'].delete(0, 'end')
                entries[f'Prev {g}'].insert(0, f"{prev_row[g]:g}")
        else:
            chk.deselect()
            prev_var.set("no")
            df_history_data = None

        samples_status.configure(
            text=f"✔ Current sample: {sel_date.strftime('%Y-%m-%d')}   |   "
                 f"{len(older)} older sample(s) loaded as history."
        )

    def populate_samples_panel(df_rows, asset):
        """Render the loaded samples INLINE in the right-hand panel (no popup)."""
        gas_order = ['H2', 'CH4', 'C2H6', 'C2H4', 'C2H2', 'CO', 'CO2', 'O2', 'N2']
        for w in samples_scroll.winfo_children():
            w.destroy()
        samples_title.configure(text=f"📋 Available Samples — {asset}  ({len(df_rows)})")
        samples_status.configure(text="Click ✅ Select on the sample you want to analyse.")

        for i in range(len(df_rows)):
            r = df_rows.iloc[i]
            rowf = ctk.CTkFrame(samples_scroll, fg_color="#161616", corner_radius=8,
                                border_width=1, border_color="#2A2A2A")
            rowf.pack(fill="x", pady=4, padx=2)

            top = ctk.CTkFrame(rowf, fg_color="transparent")
            top.pack(fill="x", padx=10, pady=(7, 2))
            ctk.CTkLabel(top, text=f"🗓 {r['Date'].strftime('%Y-%m-%d')}",
                         font=ctk.CTkFont(size=14, weight="bold"),
                         text_color="#00D2FF").pack(side="left")
            ctk.CTkButton(top, text="✅ Select", width=84, height=28,
                          fg_color="#28a745", hover_color="#218838",
                          font=ctk.CTkFont(size=12, weight="bold"),
                          command=lambda idx=i: apply_selected_sample(df_rows, idx)).pack(side="right")

            gas_txt = "   ".join(f"{g}: {r[g]:g}" for g in gas_order)
            ctk.CTkLabel(rowf, text=gas_txt, font=ctk.CTkFont(size=11),
                         text_color="#CCCCCC", wraplength=400,
                         justify="left").pack(anchor="w", padx=10, pady=(0, 7))

    def load_from_database():
        if not _PYODBC_AVAILABLE:
            messagebox.showerror("Missing Dependency",
                                 "pyodbc is not installed.\nRun:  pip install pyodbc")
            return
        asset = entries['Transformer ID'].get().strip()
        if not asset:
            messagebox.showwarning("Asset Number Required",
                                   "Enter the Asset Number in the 'Transformer ID' field first.")
            return
        cfg = {
            "server":   db_server_entry.get().strip(),
            "database": db_name_entry.get().strip() or "CEB_TRANSMISSION",
            "auth":     "windows",
            "username": "", "password": "",
        }
        if not cfg["server"]:
            messagebox.showwarning("Server Required", "Enter the SQL Server / IP.")
            return
        save_db_config(cfg)
        try:
            df_rows = fetch_asset_dga_rows(cfg, asset)
        except Exception as e:
            messagebox.showerror("Database Error", f"Could not load data:\n{e}")
            return
        if df_rows.empty:
            messagebox.showinfo("No Data", f"No DGA samples found for asset:\n{asset}")
            samples_title.configure(text="📋 Available Samples")
            for w in samples_scroll.winfo_children():
                w.destroy()
            samples_status.configure(text=f"No samples found for {asset}.")
            return
        populate_samples_panel(df_rows, asset)

    # Left Column
    info_card = create_card(left_col, "Transformer Info", "📋")
    add_field(info_card, 'Transformer ID', transformer_id, 0)
    add_field(info_card, 'Sample Date', sample_date, 1)
    add_field(info_card, 'Transformer Age (yrs)', transformer_age, 2)

    # Database source card
    _db_cfg = load_db_config()
    db_card = create_card(left_col, "Load from Database", "🗄️")
    ctk.CTkLabel(db_card, text="Server / IP", font=ctk.CTkFont(size=14)).grid(
        row=0, column=0, sticky="w", pady=8, padx=(0, 10))
    db_server_entry = ctk.CTkEntry(db_card, width=180, height=35, border_width=1, corner_radius=8)
    db_server_entry.insert(0, _db_cfg.get("server", ""))
    db_server_entry.grid(row=0, column=1, pady=8, sticky="w")
    ctk.CTkLabel(db_card, text="Database", font=ctk.CTkFont(size=14)).grid(
        row=1, column=0, sticky="w", pady=8, padx=(0, 10))
    db_name_entry = ctk.CTkEntry(db_card, width=180, height=35, border_width=1, corner_radius=8)
    db_name_entry.insert(0, _db_cfg.get("database", "CEB_TRANSMISSION"))
    db_name_entry.grid(row=1, column=1, pady=8, sticky="w")
    ctk.CTkButton(db_card, text="🔍 Load Samples for this Transformer ID",
                  fg_color="#8E44AD", hover_color="#6C3483",
                  font=ctk.CTkFont(weight="bold", size=14), height=40, corner_radius=8,
                  command=load_from_database).grid(
        row=2, column=0, columnspan=2, pady=(12, 4), sticky="ew")

    gas_card = create_card(left_col, "Current Gas (ppm)", "🧪")
    row_idx = 0
    for label in ['H2','CH4','CO','CO2','C2H4','C2H6','C2H2','O2','N2']:
        add_field(gas_card, label, '', row_idx, col=0)
        row_idx += 1

    # Right Column
    hist_card = create_card(right_col, "Historical Data", "📊")

    prev_var = ctk.StringVar(value="no")
    chk = ctk.CTkCheckBox(hist_card, text="Include Previous Sample Data", variable=prev_var,
                          onvalue="yes", offvalue="no",
                          font=ctk.CTkFont(size=14, weight="bold"), text_color="#00FF7F",
                          border_color="#00FF7F", hover_color="#00CC66")
    chk.grid(row=0, column=0, columnspan=2, pady=(10, 15), sticky="w")

    def load_history_file():
        filepath = filedialog.askopenfilename(
            title="Select Historical Data File",
            filetypes=(("Excel files", "*.xlsx *.xls"), ("CSV files", "*.csv"), ("All files", "*.*"))
        )
        if not filepath:
            return
        try:
            global df_history_data
            if filepath.endswith('.csv'):
                df_hist = pd.read_csv(filepath)
            else:
                df_hist = pd.read_excel(filepath)
            cols = {str(c).upper().strip(): c for c in df_hist.columns}

            date_col = next((cols[c] for c in ['DATE', 'SAMPLE DATE', 'TIME', 'SAMPLEDATE', 'TEST DATE'] if c in cols), None)
            if not date_col:
                date_col = next((orig for upper, orig in cols.items() if 'DATE' in upper or 'TIME' in upper), None)

            if date_col:
                df_hist[date_col] = pd.to_datetime(df_hist[date_col], errors='coerce')
                df_hist = df_hist.dropna(subset=[date_col])
                df_hist = df_hist.sort_values(by=date_col, ascending=False).reset_index(drop=True)

                df_history_data = df_hist.copy()
                df_history_data.rename(columns={date_col: 'Date'}, inplace=True)
                for g in ['H2', 'CH4', 'C2H6', 'C2H4', 'C2H2', 'CO', 'CO2']:
                    g_col = cols.get(g)
                    if not g_col:
                        g_col = next((orig for upper, orig in cols.items() if g in upper.split() or g + '_' in upper or g + '(' in upper or upper.startswith(g)), None)
                    if g_col:
                        df_history_data.rename(columns={g_col: g}, inplace=True)

                latest_date = df_hist[date_col].iloc[0].strftime('%Y-%m-%d')
            else:
                latest_date = "2024-01-15"

            chk.select()
            prev_var.set("yes")

            entries['Total Samples in Series'].delete(0, 'end')
            entries['Total Samples in Series'].insert(0, str(len(df_hist) + 1))
            entries['Prev Sample Date'].delete(0, 'end')
            entries['Prev Sample Date'].insert(0, latest_date)

            for g in ['H2', 'CH4', 'C2H6', 'C2H4', 'C2H2', 'CO', 'CO2']:
                g_col = cols.get(g)
                if not g_col:
                    g_col = next((orig for upper, orig in cols.items() if g in upper.split() or g + '_' in upper or g + '(' in upper or upper.startswith(g)), None)
                val = df_hist[g_col].iloc[0] if g_col else 0.0
                entries[f'Prev {g}'].delete(0, 'end')
                entries[f'Prev {g}'].insert(0, str(val))

            messagebox.showinfo("Success", f"Loaded {len(df_hist)} previous samples from file.\nLatest past sample date: {latest_date}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not parse file.\nDetails: {e}")

    ctk.CTkButton(hist_card, text="📁 Load History from Excel/CSV", fg_color="#20B2AA", hover_color="#008B8B",
                  font=ctk.CTkFont(weight="bold", size=14), height=40, corner_radius=8,
                  command=load_history_file).grid(row=1, column=0, columnspan=2, pady=(0, 20), sticky="ew")

    row_h = 2
    add_field(hist_card, 'Total Samples in Series', 2, row_h)
    add_field(hist_card, 'Prev Sample Date', prev_sample_date, row_h+1)
    row_h += 2
    for label in ['Prev H2','Prev CH4','Prev CO','Prev CO2','Prev C2H4','Prev C2H6','Prev C2H2']:
        add_field(hist_card, label, '', row_h)
        row_h += 1

    # Samples Column — inline panel that lists DB samples for the entered asset
    samples_card = ctk.CTkFrame(samples_col, corner_radius=15, border_width=1,
                                border_color="#333333", fg_color="#1E1E1E")
    samples_card.pack(fill="both", expand=True, pady=10)
    samples_title = ctk.CTkLabel(samples_card, text="📋 Available Samples",
                                 font=ctk.CTkFont(size=18, weight="bold"), text_color="#00D2FF")
    samples_title.pack(anchor="w", padx=20, pady=(15, 4))
    ctk.CTkLabel(samples_card,
                 text="Enter the Asset Number under Transformer Info, click "
                      "🔍 Load Samples, then pick the sample to analyse here.",
                 font=ctk.CTkFont(size=12), text_color="gray",
                 wraplength=410, justify="left").pack(anchor="w", padx=20, pady=(0, 8))
    samples_scroll = ctk.CTkScrollableFrame(samples_card, fg_color="transparent",
                                            height=540, width=430)
    samples_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 6))
    samples_status = ctk.CTkLabel(samples_card, text="", font=ctk.CTkFont(size=12, weight="bold"),
                                  text_color="#00FF7F", wraplength=410, justify="left")
    samples_status.pack(anchor="w", padx=20, pady=(0, 14))

    win.wait_window()
    return state["submitted"]

# ============================================================
#  STEP 4 — Analysis  (reads input globals, returns a result dict)
# ============================================================
def run_analysis():
    res = {}

    o2_n2_ratio = O2 / N2 if N2 > 0 else 0
    if o2_n2_ratio <= 0.2:
        if transformer_age == 0:    col, col_label = 3, 'Sealed, Unknown Age'
        elif transformer_age <= 9:  col, col_label = 0, 'Sealed, 1-9yr'
        elif transformer_age <= 30: col, col_label = 1, 'Sealed, 10-30yr'
        else:                       col, col_label = 2, 'Sealed, >30yr'
    else:
        if transformer_age == 0:    col, col_label = 7, 'Free-Breathing, Unknown Age'
        elif transformer_age <= 9:  col, col_label = 4, 'Free-Breathing, 1-9yr'
        elif transformer_age <= 30: col, col_label = 5, 'Free-Breathing, 10-30yr'
        else:                       col, col_label = 6, 'Free-Breathing, >30yr'

    gases      = {'H2':H2,'CH4':CH4,'C2H6':C2H6,'C2H4':C2H4,'C2H2':C2H2,'CO':CO,'CO2':CO2}
    prev_gases = {'H2':prev_H2,'CH4':prev_CH4,'C2H6':prev_C2H6,'C2H4':prev_C2H4,
                  'C2H2':prev_C2H2,'CO':prev_CO,'CO2':prev_CO2}

    results = []
    any_above_t2 = any_above_t1 = False

    for gas, val in gases.items():
        t1 = TABLE1[gas][col]
        t2 = TABLE2[gas][col]
        t3 = TABLE3[gas][0 if o2_n2_ratio <= 0.2 else 1]

        above_t1 = val > t1
        above_t2 = val > t2

        delta = val - prev_gases.get(gas, val) if has_previous else 0
        above_t3 = (delta > t3) if gas != 'C2H2' else (delta > 0)

        p_val = prev_gases.get(gas) if has_previous else None
        rate_val, n_pts, total_mo = calculate_regression_rate(
            gas, val, sample_date, p_val, prev_sample_date, df_history_data)

        t4 = "-"
        above_t4 = False
        if has_previous:
            r_col = -1
            if 3 <= n_pts <= 6 and 4 <= total_mo <= 24:
                if total_mo <= 9:
                    r_col = 0 if o2_n2_ratio <= 0.2 else 2
                else:
                    r_col = 1 if o2_n2_ratio <= 0.2 else 3
            if r_col != -1:
                t4 = TABLE4[gas][r_col]
                above_t4 = (rate_val > t4) if gas != 'C2H2' else (rate_val > 0)
            else:
                rate_val = "-"

        if above_t2:
            status_level = '🔴 ABOVE T2'
            any_above_t2 = any_above_t1 = True
        elif above_t1:
            status_level = '🟡 ABOVE T1'
            any_above_t1 = True
        else:
            status_level = '🟢 Normal'

        results.append({
            'Gas': gas, 'Value (ppm)': val,
            'Table 1 Limit': t1, 'Table 2 Limit': t2,
            'Delta vs Prev': round(delta, 2) if has_previous else 'N/A',
            'Table 3 Limit': t3,
            'Delta Flag': '⚠️ YES' if above_t3 and has_previous else '-',
            'Rate (ppm/yr)': rate_val if has_previous else '-',
            'Table 4 Limit': t4,
            'Rate Flag': '⚠️ YES' if above_t4 and has_previous else '-',
            'Level Status': status_level
        })

    delta_flags = [r['Delta Flag'] == '⚠️ YES' for r in results]
    rate_flags  = [r['Rate Flag']  == '⚠️ YES' for r in results]

    if any_above_t2 or any(rate_flags):
        dga_status  = 3
        status_desc = '🔴 DGA STATUS 3 — Probably Suspicious'
        action = ('High gas levels or elevated rate detected. Place transformer under INCREASED SURVEILLANCE.\n'
                  'Consider online monitoring. Consult transformer expert. Additional testing recommended.')
    elif any_above_t1 or any(delta_flags):
        dga_status  = 2
        status_desc = '🟡 DGA STATUS 2 — Possibly Suspicious'
        action = ('Intermediate gas level, delta change, or elevated rate detected.\n'
                  'Resample within 1 month for confirmation. Investigate possible causes.')
    else:
        dga_status  = 1
        status_desc = '🟢 DGA STATUS 1 — Probably Normal'
        action = 'All gas levels acceptable. Continue routine DGA sampling per company policy.'

    fault_rogers, R1, R2, R3 = rogers_ratios(H2, CH4, C2H6, C2H4, C2H2)
    fault_duval, pCH4, pC2H4, pC2H2 = duval_triangle_1(CH4, C2H4, C2H2)
    ai_fault, ai_conf, ai_proba = ai_predict(H2, CH4, C2H6, C2H4, C2H2)

    fault_t4, t4_h, t4_m, t4_e = duval_triangle_4(H2, CH4, C2H6)
    fault_t5, t5_m, t5_et, t5_ea = duval_triangle_5(CH4, C2H4, C2H6)

    fault_pent1, pent1_cx, pent1_cy = duval_pentagon_1(H2, C2H6, CH4, C2H4, C2H2)
    fault_pent2, pent2_cx, pent2_cy = duval_pentagon_2(H2, C2H6, CH4, C2H4, C2H2)

    t4_t5_desc_dict = {
        'S': 'Stray gassing at temperatures < 200 °C',
        'O': 'Overheating < 250 °C without carbonization of paper',
        'C': 'Possible paper carbonization',
        'T3-H': 'Thermal fault T3 in mineral oil only',
        'R': 'Catalytic reaction',
        'PD': 'Partial discharges of corona type',
        'T2': 'Thermal fault, 300 °C < t < 700 °C',
        'T3': 'Thermal fault, t > 700 °C',
        'ND': 'Not Determined',
        'Unknown': 'Unknown Zone'
    }

    pent1_desc_dict = {
        'PD': 'Partial discharges of corona type',
        'D1': 'Discharges of low energy',
        'D2': 'Discharges of high energy',
        'T1': 'Thermal fault, t < 300 °C',
        'T2': 'Thermal fault, 300 °C < t < 700 °C',
        'T3': 'Thermal fault, t > 700 °C',
        'S':  'Stray gassing of mineral oil',
        'Unknown': 'Unknown Zone'
    }

    pent2_desc_dict = {
        'PD': 'Partial discharges of corona type',
        'D1': 'Discharges of low energy',
        'D2': 'Discharges of high energy',
        'S':  'Stray gassing of mineral oil',
        'T3-H': 'Thermal fault T3 in mineral oil only',
        'C':  'Possible carbonization of paper',
        'O':  'Overheating < 250 °C without carbonization of paper',
        'Unknown': 'Unknown Zone'
    }

    fault_pent1_desc = f"{fault_pent1} — {pent1_desc_dict.get(fault_pent1, '')}"
    fault_pent2_desc = f"{fault_pent2} — {pent2_desc_dict.get(fault_pent2, '')}"
    
    # In Triangle 5, T3 is usually 'T3-H' for mineral oil only according to the note.
    # The image says T3-H: Thermal fault T3 in mineral oil only. 
    # But since my code returns 'T3', I'll map 'T3' to the full string.
    
    fault_t4_desc = f"{fault_t4} — {t4_t5_desc_dict.get(fault_t4, '')}"
    fault_t5_desc = f"{fault_t5} — {t4_t5_desc_dict.get(fault_t5, '')}"

    
    # IEEE C57.104 D.4 application rules
    d1_zone = fault_duval.split('—')[0].strip()
    use_t4 = d1_zone in ['PD', 'T1', 'T2']
    use_t5 = d1_zone in ['T2', 'T3']


    conf_icon = '🟢' if ai_conf >= 85 else ('🟡' if ai_conf >= 65 else '🔴')

    # ── Build the text report (captured to a buffer) ─────────────────────────
    def key_gas_method(H2, CH4, C2H6, C2H4, C2H2, CO):
        combustible = {'H2':H2,'CH4':CH4,'C2H6':C2H6,'C2H4':C2H4,'C2H2':C2H2,'CO':CO}
        dominant = max(combustible, key=combustible.get)
        meanings = {
            'H2'   : 'Hydrogen   — Indicates corona Partial Discharge (PD) or catalytic reaction',
            'CH4'  : 'Methane    — Indicates low temperature thermal fault in oil (T1)',
            'C2H6' : 'Ethane     — Indicates low-to-medium temperature thermal fault in oil',
            'C2H4' : 'Ethylene   — Indicates high temperature thermal fault in oil (T2/T3)',
            'C2H2' : 'Acetylene  — Indicates arcing at very high temperature (D2 / >1000°C)',
            'CO'   : 'CO         — Indicates cellulose (paper insulation) thermal degradation'
        }
        total = sum(combustible.values()) or 1
        pcts  = {g: round(v/total*100, 1) for g, v in combustible.items()}
        print('\nCombustible Gas Breakdown:')
        for g, v in combustible.items():
            bar = '█' * int(pcts[g] // 2)
            print(f'  {g:5s}: {v:8.1f} ppm  ({pcts[g]:5.1f}%)  {bar}')
        print(f'\n  Dominant gas: {dominant}')
        print(f'  Interpretation: {meanings[dominant]}')
        co_co2 = CO / CO2 if CO2 > 0 else 0
        print(f'\n  CO/CO2 ratio = {co_co2:.3f}')
        if co_co2 > 0.1:
            print('  ⚠️  CO/CO2 > 0.1 — Paper/cellulose insulation may be involved!')
        else:
            print('  ✅ CO/CO2 <= 0.1 — No strong indication of paper involvement.')

    def generate_expert_analysis():
        print('-'*65)
        print('  🧠 EXPERT AI SYNTHESIS REPORT')
        print('-'*65)
        combustibles = {'H2':H2, 'CH4':CH4, 'C2H6':C2H6, 'C2H4':C2H4, 'C2H2':C2H2}
        dominant_gas = max(combustibles, key=combustibles.get) if any(combustibles.values()) else 'None'

        duval_short = fault_duval.split("—")[0].strip()
        is_match = False
        if 'High-temperature' in ai_fault and duval_short == 'T3':
            is_match = True
        elif 'Low/Middle-temperature' in ai_fault and duval_short in ['T1', 'T2']:
            is_match = True
        elif 'Spark' in ai_fault and duval_short == 'D1':
            is_match = True
        elif 'Arc' in ai_fault and duval_short == 'D2':
            is_match = True
        elif 'PD' in ai_fault and duval_short == 'PD':
            is_match = True
        elif ai_fault == duval_short:
            is_match = True

        if is_match:
            print(f'  Fault Type: {ai_fault} (Supported by Duval Zone {duval_short})')
        else:
            print(f'  Fault Type: {ai_fault} (AI Prediction) | Duval Zone: {duval_short}')

        print(f'  Evidence: The gas profile is dominated by {dominant_gas} ({combustibles.get(dominant_gas, 0)} ppm).')

        if 'Thermal' in ai_fault or 'T' in fault_duval:
            if dominant_gas in ['C2H4', 'C2H2']:
                print('            This signature strongly indicates a high-temperature thermal event (>700°C).')
            else:
                print('            This signature is classic for low-temperature overheating of oil (e.g., localized hot spots or stray flux).')
        elif 'Discharge' in ai_fault or 'D' in fault_duval or 'PD' in fault_duval:
            if C2H2 > 5:
                print('            The presence of Acetylene (C2H2) strongly indicates high-energy arcing.')
            else:
                print('            This signature suggests low-energy partial discharges (corona) or sparking.')

        co_co2_ratio = CO2 / CO if CO > 0 else 0
        print(f'  Paper Involvement: The CO2/CO ratio is {co_co2_ratio:.2f}.')
        if co_co2_ratio < 3 and CO > 500:
            print('                     ⚠️ Ratio < 3 with high CO suggests severe cellulose degradation or arcing in paper!')
        elif co_co2_ratio > 10:
            print('                     Ratio > 10 usually suggests normal aging or low-intensity overheating without major paper involvement.')
        else:
            print('                     Ratio is within limits (3-10), indicating mild or no abnormal cellulose degradation.')

        if has_previous:
            delta_dom = combustibles.get(dominant_gas, 0) - prev_gases.get(dominant_gas, 0)
            if delta_dom > 15:
                print(f'  Trend Inflection: The primary fault gas ({dominant_gas}) is actively rising (Delta: +{delta_dom:.1f}), indicating an active fault.')
            elif delta_dom < -5:
                print(f'  Trend Inflection: The primary gas is decreasing (Delta: {delta_dom:.1f}), suggesting a stagnant or resolved fault event.')
            else:
                print(f'  Trend Inflection: Recent samples show stabilization in {dominant_gas}, appearing more like a cumulative "stagnant" fault rather than an active event.')

        duval_short2 = fault_duval.split('—')[0].strip().split()[0] if '—' in fault_duval else fault_duval.split()[0]
        if ai_fault.upper() in fault_duval.upper() or duval_short2.upper() == ai_fault.upper():
            print('  Alignment: Perfect agreement between IEEE C57.104 ratios, Duval Triangle, and XGBoost AI Model.')
        else:
            print('  Alignment: ⚠️ Discrepancy detected between AI Model and Duval Triangle. Engineer review highly recommended.')

        print('  Caveats:')
        if C2H2 > 0 and H2 < 10 and C2H4 < 10:
            print('    - Data Integrity: High C2H2 values without matching H2/C2H4 are highly suspect and may be lab artifacts or data entry errors.')
        if O2 > 10000:
            print('    - Free-Breathing: High O2 indicates a free-breathing transformer. Gas limits are naturally higher.')
        elif O2 < 2000 and N2 > 10000:
            print('    - Sealed System: Low O2 suggests a nitrogen-blanketed or sealed system. Saturated hydrocarbons can accumulate significantly over time without reflecting an emergency.')

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print(f'✅ Transformer: {transformer_id}  |  Sample Date: {sample_date}')
        print(f'   H2={H2}, CH4={CH4}, C2H6={C2H6}, C2H4={C2H4}, C2H2={C2H2}')
        print(f'   CO={CO}, CO2={CO2}, O2={O2}, N2={N2}')
        print(f'O2/N2 ratio = {o2_n2_ratio:.3f}  ({"Sealed/Low" if o2_n2_ratio <= 0.2 else "Open/High"})')
        print(f'Table column used: {col_label}\n')

        print('=' * 65)
        print('       DGA ANALYSIS REPORT — IEEE C57.104-2019')
        print('=' * 65)
        print(f'  Transformer ID : {transformer_id}')
        print(f'  Sample Date    : {sample_date}')
        print(f'  Transformer Age: {transformer_age} years')
        print(f'  O2/N2 Ratio    : {o2_n2_ratio:.3f}  (Norm column: {col_label})')
        print('-' * 65)
        print('  GAS CONCENTRATIONS (µL/L / ppm):')
        print(f'  {"Gas":<8} {"Value":>8}  {"T1 Limit":>10}  {"T2 Limit":>10}  Status')
        print('  ' + '-' * 55)
        for r in results:
            print(f'  {r["Gas"]:<8} {r["Value (ppm)"]:>8.1f}  {r["Table 1 Limit"]:>10}'
                  f'  {r["Table 2 Limit"]:>10}  {r["Level Status"]}')

        if has_previous:
            print('-' * 65)
            print('  RATE & DELTA ANALYSIS (Table 3 & 4):')
            print(f'  {"Gas":<8} {"Delta":>8}  {"T3 Lmt":>8} {"Flag":>6} | {"Rate/yr":>9}  {"T4 Lmt":>8} {"Flag":>6}')
            print('  ' + '-' * 63)
            for r in results:
                t3_str = str(r["Table 3 Limit"]) if r["Gas"] != 'C2H2' else ">0"
                t4_str = str(r["Table 4 Limit"]) if r["Gas"] != 'C2H2' else ">0"
                print(f'  {r["Gas"]:<8} {str(r["Delta vs Prev"]):>8}  {t3_str:>8} {r["Delta Flag"]:>6} | '
                      f'{str(r["Rate (ppm/yr)"]):>9}  {t4_str:>8} {r["Rate Flag"]:>6}')

        print('-' * 65)
        print(f'  OVERALL DGA STATUS: {STATUS_EMOJI[dga_status]} STATUS {dga_status} — {STATUS_LABEL[dga_status]}')
        print('-' * 65)

        print('\n' + '-' * 65)
        print('  DETAILED BREAKDOWNS')
        print('-' * 65)
        print('Rogers Ratios:')
        print(f'  R1 = C2H2/C2H4 = {R1:.4f}')
        print(f'  R2 = CH4/H2    = {R2:.4f}')
        print(f'  R3 = C2H4/C2H6 = {R3:.4f}')
        print(f'Rogers Ratios Diagnosis: {fault_rogers}\n')

        print(f'Duval Triangle 1:  CH4={pCH4}%  C2H4={pC2H4}%  C2H2={pC2H2}%')
        print(f'Duval Fault Zone : ➡️  {fault_duval}')

        if use_t4:
            print(f'Duval Triangle 4:  H2={t4_h}%  CH4={t4_m}%  C2H6={t4_e}%')
            print(f'Duval 4 Zone     : ➡️  {fault_t4_desc}')
            if fault_t4 == 'C': print('  ⚠️ Zone C indicates a possibility of carbonization of paper. Investigate carbon oxides/furans.')
        if use_t5:
            print(f'Duval Triangle 5:  CH4={t5_m}%  C2H4={t5_et}%  C2H6={t5_ea}%')
            print(f'Duval 5 Zone     : ➡️  {fault_t5_desc}')
            if fault_t5 == 'C': print('  ⚠️ Zone C indicates a possibility of carbonization of paper. Investigate carbon oxides/furans.')


        print(f'\nDuval Pentagon 1: (Cx={pent1_cx:.2f}, Cy={pent1_cy:.2f})')
        print(f'Duval Pentagon 1 Zone : ➡️  {fault_pent1_desc}')
        print(f'Duval Pentagon 2: (Cx={pent2_cx:.2f}, Cy={pent2_cy:.2f})')
        print(f'Duval Pentagon 2 Zone : ➡️  {fault_pent2_desc}')

        key_gas_method(H2, CH4, C2H6, C2H4, C2H2, CO)

        print('  FAULT IDENTIFICATION:')
        print(f'  Rogers Ratios : {fault_rogers}')
        print(f'  Duval Tri. 1  : {fault_duval}')
        print('-' * 65)
        print('  AI MODEL DIAGNOSIS  (XGBoost — trained on new data set):')
        print(f'  Predicted Fault : {ai_fault}')
        print(f'  Confidence      : {conf_icon} {ai_conf:.1f}%')
        print(f'  Model Test Acc  : {_train_acc*100:.1f}%')
        if ai_proba:
            print('  Class Probabilities:')
            for cls, prob in sorted(ai_proba.items(), key=lambda x: -x[1]):
                bar = '█' * int(prob // 5)
                print(f'    {cls:<42s}: {prob:5.1f}%  {bar}')

        generate_expert_analysis()

        print('-' * 65)
        print('  RECOMMENDED ACTION:')
        for line in action.split('\n'):
            print(f'  {line}')
        print('=' * 65)
        print()
        print('⚠️  DISCLAIMER: DGA analysis should always be performed by a')
        print('   qualified engineer. This tool is for guidance only per')
        print('   IEEE C57.104-2019. Never act on DGA alone without expert review.')

    report_text = buf.getvalue()

    res.update({
        'transformer_id': transformer_id, 'sample_date': sample_date,
        'transformer_age': transformer_age, 'o2_n2_ratio': o2_n2_ratio,
        'col': col, 'col_label': col_label,
        'gases': gases, 'prev_gases': prev_gases, 'results': results,
        'dga_status': dga_status, 'status_desc': status_desc, 'action': action,
        'fault_rogers': fault_rogers, 'R1': R1, 'R2': R2, 'R3': R3,
        'fault_duval': fault_duval, 'pCH4': pCH4, 'pC2H4': pC2H4, 'pC2H2': pC2H2,

        'fault_t4': fault_t4, 'fault_t4_desc': fault_t4_desc, 't4_h': t4_h, 't4_m': t4_m, 't4_e': t4_e, 'use_t4': use_t4,
        'fault_t5': fault_t5, 'fault_t5_desc': fault_t5_desc, 't5_m': t5_m, 't5_et': t5_et, 't5_ea': t5_ea, 'use_t5': use_t5,

        'fault_pent1': fault_pent1, 'fault_pent1_desc': fault_pent1_desc, 'pent1_cx': pent1_cx, 'pent1_cy': pent1_cy,
        'fault_pent2': fault_pent2, 'fault_pent2_desc': fault_pent2_desc, 'pent2_cx': pent2_cx, 'pent2_cy': pent2_cy,

        'ai_fault': ai_fault, 'ai_conf': ai_conf, 'ai_proba': ai_proba,
        'has_previous': has_previous, 'report_text': report_text,
    })

    # ── Figures ──────────────────────────────────────────────────────────────
    res['fig_bar']   = build_bar_figure(res)
    res['fig_duval'] = build_duval_figure(res)
    res['fig_duval_4'] = build_duval_4_figure(res)
    res['fig_duval_5'] = build_duval_5_figure(res)
    res['fig_pentagon_1'] = build_pentagon_1_figure(res)
    res['fig_pentagon_2'] = build_pentagon_2_figure(res)
    res['fig_trend'] = build_trend_figure(res)

    # Save PNGs for Word export / external use
    try:
        res['fig_bar'].savefig(BAR_PNG, dpi=150, bbox_inches='tight')
        res['fig_duval'].savefig(DUVAL_PNG, dpi=150, bbox_inches='tight')
        res['fig_pentagon_1'].savefig(PENTAGON1_PNG, dpi=150, bbox_inches='tight')
        res['fig_pentagon_2'].savefig(PENTAGON2_PNG, dpi=150, bbox_inches='tight')
        if res['fig_trend'] is not None:
            res['fig_trend'].savefig(TREND_PNG, dpi=150, bbox_inches='tight')
        elif os.path.exists(TREND_PNG):
            os.remove(TREND_PNG)
    except Exception:
        pass

    return res

# ============================================================
#  STEP 5 — Figure builders (return Matplotlib Figure objects)
# ============================================================
def build_bar_figure(res):
    gases = res['gases']; col = res['col']
    gas_names = list(gases.keys())
    gas_vals  = list(gases.values())
    t1_limits = [TABLE1[g][col] for g in gas_names]
    t2_limits = [TABLE2[g][col] for g in gas_names]

    x = np.arange(len(gas_names))
    width = 0.25

    fig = Figure(figsize=(11, 5.2), dpi=100)
    ax = fig.add_subplot(111)
    bars = ax.bar(x - width, gas_vals,  width, label='Measured Value', color='steelblue', zorder=3)
    ax.bar(x,         t1_limits, width, label='Table 1 (90th%)', color='goldenrod', alpha=0.7, zorder=3)
    ax.bar(x + width, t2_limits, width, label='Table 2 (95th%)', color='tomato',    alpha=0.7, zorder=3)

    for i, (val, t1, t2) in enumerate(zip(gas_vals, t1_limits, t2_limits)):
        if val > t2:
            bars[i].set_color('red'); bars[i].set_edgecolor('darkred'); bars[i].set_linewidth(2)
        elif val > t1:
            bars[i].set_color('orange'); bars[i].set_edgecolor('darkorange'); bars[i].set_linewidth(2)

    ax.set_xlabel('Dissolved Gas', fontsize=12)
    ax.set_ylabel('Concentration (µL/L) — log scale', fontsize=11)
    ax.set_yscale('log')
    ax.set_title(
        f'DGA Results — {res["transformer_id"]} | {res["sample_date"]}\n'
        f'DGA Status: {res["dga_status"]} | Duval: {res["fault_duval"]}\n'
        f'AI Diagnosis: {res["ai_fault"]} ({res["ai_conf"]:.1f}% confidence)',
        fontsize=12, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(gas_names, fontsize=11)
    ax.legend(fontsize=10)
    ax.grid(axis='y', alpha=0.4, zorder=0)

    for bar in bars:
        h = bar.get_height()
        if h > 0:
            ax.text(bar.get_x() + bar.get_width()/2, h * 1.05, f'{h:.0f}',
                    ha='center', va='bottom', fontsize=8, fontweight='bold')

    fig.tight_layout()
    return fig

def build_duval_figure(res):
    pCH4, pC2H4, pC2H2 = res['pCH4'], res['pC2H4'], res['pC2H2']
    fig = Figure(figsize=(8, 7), dpi=100)
    ax = fig.add_subplot(111)

    triangle = mpatches.Polygon([[0, 0], [1, 0], [0.5, 3**0.5/2]], closed=True,
                                fill=False, edgecolor='black', linewidth=2)
    ax.add_patch(triangle)

    for zone, pts in ZONE_POLYS.items():
        cart = [ternary_to_cartesian(a, b, c) for a, b, c in pts]
        poly = mpatches.Polygon(cart, closed=True, facecolor=ZONE_COLORS[zone],
                                edgecolor='gray', linewidth=0.8, alpha=0.85)
        ax.add_patch(poly)
        cx = np.mean([p[0] for p in cart])
        cy = np.mean([p[1] for p in cart])
        ax.text(cx, cy, zone, ha='center', va='center', fontsize=13,
                fontweight='bold', color='#2C3E50')

    ax.text(-0.07, 0.0, '% CH4',  fontsize=12, ha='center', color='#1A5276', fontweight='bold')
    ax.text( 1.05, 0.0, '% C2H4', fontsize=12, ha='center', color='#1A5276', fontweight='bold')
    ax.text( 0.5,  3**0.5/2 + 0.05, '% C2H2', fontsize=12, ha='center', color='#1A5276', fontweight='bold')

    px, py = ternary_to_cartesian(pCH4, pC2H4, pC2H2)
    ax.plot(px, py, 'k*', markersize=20, zorder=10)
    ax.annotate(f' {res["transformer_id"]}\n CH4={pCH4}%\n C2H4={pC2H4}%\n C2H2={pC2H2}%',
                (px, py), fontsize=9,
                bbox=dict(boxstyle='round,pad=0.4', facecolor='white', alpha=0.8),
                xytext=(px+0.05, py+0.05))

    ax.set_xlim(-0.1, 1.15)
    ax.set_ylim(-0.1, 1.0)
    ax.set_aspect('equal')
    ax.axis('off')
    ax.set_title(
        f'Duval Triangle 1 — {res["transformer_id"]}\n'
        f'Duval: {res["fault_duval"]}\n'
        f'AI Model: {res["ai_fault"]} ({res["ai_conf"]:.1f}% confidence)',
        fontsize=12, fontweight='bold', pad=15)

    legend_items = [mpatches.Patch(color=ZONE_COLORS[z], label=z) for z in ZONE_POLYS]
    ax.legend(handles=legend_items, loc='lower right', fontsize=10, title='Fault Zones')

    fig.tight_layout()
    return fig

def _draw_pentagon_background(ax, zones, zone_colors, title, res_key_zone, res_key_desc, res_cx, res_cy, tid, res):
    """Shared helper to draw a Duval Pentagon figure (1 or 2)."""
    import math
    R = 40  # outer pentagon radius

    # Axis angles: H2=90°, C2H6=162°, CH4=234°, C2H4=306°, C2H2=18°
    angles = [math.radians(a) for a in [90, 162, 234, 306, 18]]
    gas_labels = ['H₂', 'C₂H₆', 'CH₄', 'C₂H₄', 'C₂H₂']

    # Outer pentagon vertices
    outer = [(R * math.cos(a), R * math.sin(a)) for a in angles]
    outer_closed = outer + [outer[0]]

    # Draw coloured zone patches
    for zname, poly in zones.items():
        color = zone_colors.get(zname, '#FFFFFF')
        patch = mpatches.Polygon(poly, closed=True, facecolor=color,
                                 edgecolor='#555555', linewidth=0.8, alpha=0.75)
        ax.add_patch(patch)
        # Label at centroid of zone polygon
        cx_z = sum(p[0] for p in poly) / len(poly)
        cy_z = sum(p[1] for p in poly) / len(poly)
        ax.text(cx_z, cy_z, zname, ha='center', va='center', fontsize=11,
                fontweight='bold', color='#2C3E50',
                bbox=dict(boxstyle='round,pad=0.15', facecolor='white', alpha=0.5))

    # Outer pentagon border
    outer_patch = mpatches.Polygon(outer, closed=True, fill=False,
                                   edgecolor='black', linewidth=2.5)
    ax.add_patch(outer_patch)

    # Radial axes from origin to vertices
    for i, (ox, oy) in enumerate(outer):
        ax.plot([0, ox], [0, oy], color='#888888', linewidth=0.8, linestyle='--', zorder=1)

    # Gas axis labels outside the pentagon
    label_r = R + 6
    for i, a in enumerate(angles):
        lx, ly = label_r * math.cos(a), label_r * math.sin(a)
        ax.text(lx, ly, gas_labels[i], ha='center', va='center',
                fontsize=12, fontweight='bold', color='#1A5276')

    # Plot the centroid
    cx = res[res_cx]
    cy = res[res_cy]
    ax.plot(cx, cy, 'k*', markersize=22, zorder=10)
    ax.annotate(f" {tid}\n Cx={cx:.2f}\n Cy={cy:.2f}",
                (cx, cy), fontsize=9,
                bbox=dict(boxstyle='round,pad=0.4', facecolor='white', alpha=0.85),
                xytext=(cx + 4, cy + 4), zorder=11)

    ax.set_xlim(-R - 14, R + 14)
    ax.set_ylim(-R - 14, R + 14)
    ax.set_aspect('equal')
    ax.axis('off')
    ax.set_title(f"{title} — {tid}\n"
                 f"Zone: {res[res_key_desc]}",
                 fontsize=12, fontweight='bold', pad=15)

    # Legend
    legend_items = [mpatches.Patch(color=zone_colors.get(z, '#FFF'), label=z) for z in zones]
    ax.legend(handles=legend_items, loc='lower right', fontsize=9, title='Fault Zones')


def build_pentagon_1_figure(res):
    """Build the Duval Pentagon 1 figure (IEEE C57.104-2019 zone boundaries)."""
    zone_colors = {
        'PD': '#AED6F1', 'D1': '#D2B4DE', 'D2': '#F1948A',
        'T3': '#F0B27A', 'T2': '#F9E79F', 'T1': '#A9DFBF', 'S': '#D5DBDB'
    }
    fig = Figure(figsize=(8, 7.5), dpi=100)
    ax = fig.add_subplot(111)
    _draw_pentagon_background(ax, _PENT1_ZONES, zone_colors,
                              'Duval Pentagon 1', 'fault_pent1', 'fault_pent1_desc',
                              'pent1_cx', 'pent1_cy',
                              res['transformer_id'], res)
    fig.tight_layout()
    return fig


def build_pentagon_2_figure(res):
    """Build the Duval Pentagon 2 figure (IEEE C57.104-2019 zone boundaries)."""
    zone_colors = {
        'PD': '#AED6F1', 'D1': '#D2B4DE', 'D2': '#F1948A',
        'S': '#D5DBDB', 'T3-H': '#E59866', 'C': '#E6B0AA', 'O': '#FAD7A1'
    }
    fig = Figure(figsize=(8, 7.5), dpi=100)
    ax = fig.add_subplot(111)
    _draw_pentagon_background(ax, _PENT2_ZONES, zone_colors,
                              'Duval Pentagon 2', 'fault_pent2', 'fault_pent2_desc',
                              'pent2_cx', 'pent2_cy',
                              res['transformer_id'], res)
    fig.tight_layout()
    return fig


def build_trend_figure(res):
    """Multi-point trend using the full history series when available."""
    if not res['has_previous']:
        return None

    col = res['col']
    plot_gases = ['H2', 'CH4', 'C2H6', 'C2H4', 'C2H2', 'CO']

    rows = []
    if df_history_data is not None and not df_history_data.empty:
        for _, r in df_history_data.iterrows():
            row = {'Date': r['Date']}
            for g in plot_gases:
                row[g] = r[g] if g in df_history_data.columns else np.nan
            rows.append(row)
    else:
        try:
            d_prev = datetime.datetime.strptime(prev_sample_date, "%Y-%m-%d")
        except Exception:
            d_prev = None
        rows.append({'Date': d_prev, 'H2': prev_H2, 'CH4': prev_CH4, 'C2H6': prev_C2H6,
                     'C2H4': prev_C2H4, 'C2H2': prev_C2H2, 'CO': prev_CO})

    try:
        d_curr = datetime.datetime.strptime(sample_date, "%Y-%m-%d")
    except Exception:
        d_curr = None
    rows.append({'Date': d_curr, 'H2': H2, 'CH4': CH4, 'C2H6': C2H6,
                 'C2H4': C2H4, 'C2H2': C2H2, 'CO': CO})

    trend_df = pd.DataFrame(rows).dropna(subset=['Date'])
    trend_df['Date'] = pd.to_datetime(trend_df['Date'])
    trend_df = trend_df.sort_values('Date').reset_index(drop=True)

    fig = Figure(figsize=(12, 6.4), dpi=100)
    axes = fig.subplots(2, 3).flatten()

    for i, gas in enumerate(plot_gases):
        ax = axes[i]
        ax.plot(trend_df['Date'], trend_df[gas], 'o-', color='steelblue',
                linewidth=2, markersize=7)
        ax.axhline(TABLE1[gas][col], color='gold', linestyle='--', linewidth=1.5,
                   label=f'T1={TABLE1[gas][col]}')
        ax.axhline(TABLE2[gas][col], color='red', linestyle='--', linewidth=1.5,
                   label=f'T2={TABLE2[gas][col]}')
        ax.set_title(gas, fontweight='bold', fontsize=12)
        ax.set_xlabel('Sample Date')
        ax.set_ylabel('ppm')
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        ax.tick_params(axis='x', labelrotation=30, labelsize=8)

    fig.suptitle(f'DGA Trend Analysis — {res["transformer_id"]} '
                 f'({len(trend_df)} samples)', fontsize=14, fontweight='bold')
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    return fig

# ============================================================
#  STEP 6 — Dashboard  (returns "new" or "quit")
# ============================================================
def show_dashboard(master, res):
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")

    decision = {"action": "quit"}
    tid = res['transformer_id']

    win = ctk.CTkToplevel(master)
    win.title(f"DGA Report Dashboard — {tid}")
    win.geometry("1240x900")
    win.lift()
    win.after(100, win.focus_force)

    # Header
    header = ctk.CTkFrame(win, fg_color="#1E1E1E", corner_radius=0)
    header.pack(fill="x", ipady=10)
    ctk.CTkLabel(header, text=f"⚡ DGA Analysis Report — {tid}",
                 font=ctk.CTkFont(size=26, weight="bold"), text_color="#00D2FF").pack(pady=(15, 5))
    ctk.CTkLabel(header, text=f"Sample Date: {res['sample_date']} | Transformer Age: {res['transformer_age']} years",
                 font=ctk.CTkFont(size=14), text_color="#AAAAAA").pack()

    # ── Footer actions ───────────────────────────────────────────────────────
    footer = ctk.CTkFrame(win, fg_color="transparent")
    footer.pack(side="bottom", fill="x", pady=(8, 14))
    footer_center = ctk.CTkFrame(footer, fg_color="transparent")
    footer_center.pack(expand=True)

    def save_figures():
        folder = filedialog.askdirectory(title="Choose a folder to save the figures")
        if not folder:
            return
        base = f"{tid}_{res['sample_date']}".replace('/', '_').replace(':', '_')
        saved = []
        try:
            p = os.path.join(folder, f"{base}_gas_bar.png")
            res['fig_bar'].savefig(p, dpi=200, bbox_inches='tight'); saved.append(p)
            p = os.path.join(folder, f"{base}_duval.png")
            res['fig_duval'].savefig(p, dpi=200, bbox_inches='tight'); saved.append(p)

            p = os.path.join(folder, f"{base}_duval_4.png")
            res['fig_duval_4'].savefig(p, dpi=200, bbox_inches='tight'); saved.append(p)
            p = os.path.join(folder, f"{base}_duval_5.png")
            res['fig_duval_5'].savefig(p, dpi=200, bbox_inches='tight'); saved.append(p)

            p = os.path.join(folder, f"{base}_pentagon_1.png")
            res['fig_pentagon_1'].savefig(p, dpi=200, bbox_inches='tight'); saved.append(p)
            p = os.path.join(folder, f"{base}_pentagon_2.png")
            res['fig_pentagon_2'].savefig(p, dpi=200, bbox_inches='tight'); saved.append(p)

            if res['fig_trend'] is not None:
                p = os.path.join(folder, f"{base}_trend.png")
                res['fig_trend'].savefig(p, dpi=200, bbox_inches='tight'); saved.append(p)
            messagebox.showinfo("Figures Saved", "Saved:\n" + "\n".join(saved))
        except Exception as e:
            messagebox.showerror("Error", f"Could not save figures:\n{e}")

    def save_to_word():
        try:
            from docx import Document
            from docx.shared import Inches
        except ImportError:
            messagebox.showerror("Dependency Error",
                                 "Please install python-docx to save as Word.\nRun: pip install python-docx")
            return
        file_path = filedialog.asksaveasfilename(
            defaultextension=".docx", filetypes=[("Word Document", "*.docx")],
            title="Save Report as Word",
            initialfile=f"DGA_Report_{tid}_{res['sample_date']}.docx".replace('/', '_'))
        if not file_path:
            return
        try:
            doc = Document()
            doc.add_heading(f'DGA Analysis Report - {tid}', 0)
            doc.add_paragraph(res['report_text'])
            doc.add_heading('Visual Dashboards', level=1)
            if os.path.exists(BAR_PNG):
                doc.add_picture(BAR_PNG, width=Inches(6.5))
            if os.path.exists(DUVAL_PNG):
                doc.add_picture(DUVAL_PNG, width=Inches(5.0))
            if os.path.exists(PENTAGON1_PNG):
                doc.add_picture(PENTAGON1_PNG, width=Inches(5.0))
            if os.path.exists(PENTAGON2_PNG):
                doc.add_picture(PENTAGON2_PNG, width=Inches(5.0))
            if res['has_previous'] and os.path.exists(TREND_PNG):
                doc.add_picture(TREND_PNG, width=Inches(6.5))
            doc.save(file_path)
            messagebox.showinfo("Success", f"Report saved successfully as\n{file_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save Word document:\n{str(e)}")

    def print_report():
        """Send the text report to the default printer (Windows)."""
        try:
            import tempfile
            tmp = os.path.join(tempfile.gettempdir(),
                               f"DGA_Report_{tid}_{res['sample_date']}.txt".replace('/', '_'))
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write(res['report_text'])
            try:
                os.startfile(tmp, "print")          # Windows: print via associated app
                messagebox.showinfo("Printing", "Report sent to the default printer.")
            except AttributeError:
                messagebox.showinfo("Print", f"Saved a printable text file:\n{tmp}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not print:\n{e}")

    def new_analysis():
        decision["action"] = "new"
        win.destroy()

    def exit_app():
        decision["action"] = "quit"
        win.destroy()

    ctk.CTkButton(footer_center, text="🔄 New Analysis", fg_color="#0078D4", hover_color="#005A9E",
                  font=ctk.CTkFont(weight="bold", size=15), width=180, height=44, corner_radius=10,
                  command=new_analysis).pack(side="left", padx=10)
    ctk.CTkButton(footer_center, text="🖼️ Save Figures", fg_color="#6f42c1", hover_color="#59359a",
                  font=ctk.CTkFont(weight="bold", size=15), width=170, height=44, corner_radius=10,
                  command=save_figures).pack(side="left", padx=10)
    ctk.CTkButton(footer_center, text="💾 Save as Word", fg_color="#28a745", hover_color="#218838",
                  font=ctk.CTkFont(weight="bold", size=15), width=170, height=44, corner_radius=10,
                  command=save_to_word).pack(side="left", padx=10)
    ctk.CTkButton(footer_center, text="🖨️ Print Report", fg_color="#fd7e14", hover_color="#d96a0b",
                  font=ctk.CTkFont(weight="bold", size=15), width=170, height=44, corner_radius=10,
                  command=print_report).pack(side="left", padx=10)
    ctk.CTkButton(footer_center, text="❌ Exit", fg_color="#dc3545", hover_color="#c82333",
                  font=ctk.CTkFont(weight="bold", size=15), width=120, height=44, corner_radius=10,
                  command=exit_app).pack(side="left", padx=10)

    # ── Tabs ─────────────────────────────────────────────────────────────────
    tabview = ctk.CTkTabview(win, corner_radius=15)
    tabview.pack(padx=20, pady=12, fill="both", expand=True)
    tab_dash = tabview.add("📊 Visual Dashboard")
    tab_text = tabview.add("📄 Detailed Report Text")

    # TAB 1: Dashboard ────────────────────────────────────────────────────────
    dash_scroll = ctk.CTkScrollableFrame(tab_dash, fg_color="transparent")
    dash_scroll.pack(fill="both", expand=True)

    bg_color = STATUS_COLORS.get(res['dga_status'], "#AAAAAA")
    banner = ctk.CTkFrame(dash_scroll, fg_color=bg_color, corner_radius=15)
    banner.pack(fill="x", pady=10, padx=10, ipady=15)
    ctk.CTkLabel(banner, text=f"OVERALL DGA STATUS: {STATUS_LABEL[res['dga_status']]}",
                 font=ctk.CTkFont(size=24, weight="bold"), text_color="#111111").pack()

    top_cards = ctk.CTkFrame(dash_scroll, fg_color="transparent")
    top_cards.pack(fill="x", pady=10, padx=10)
    top_cards.columnconfigure(0, weight=1)
    top_cards.columnconfigure(1, weight=1)

    ai_card = ctk.CTkFrame(top_cards, corner_radius=15, fg_color="#1E1E1E", border_width=1, border_color="#333")
    ai_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    ctk.CTkLabel(ai_card, text="🧠 AI Diagnosis", font=ctk.CTkFont(size=18, weight="bold"), text_color="#00D2FF").pack(pady=(15, 5))
    ctk.CTkLabel(ai_card, text=f"{res['ai_fault']}", font=ctk.CTkFont(size=20, weight="bold"), text_color="white", wraplength=450).pack(pady=10)
    conf = res['ai_conf']
    conf_color = "#00CC66" if conf >= 85 else ("#FFD700" if conf >= 65 else "#FF4500")
    ctk.CTkLabel(ai_card, text=f"Confidence: {conf:.1f}%", font=ctk.CTkFont(size=16), text_color=conf_color).pack(pady=5)
    prog = ctk.CTkProgressBar(ai_card, width=300, height=12, progress_color=conf_color)
    prog.pack(pady=10); prog.set(conf / 100)

    duval_card = ctk.CTkFrame(top_cards, corner_radius=15, fg_color="#1E1E1E", border_width=1, border_color="#333")
    duval_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
    ctk.CTkLabel(duval_card, text="📐 Classical Diagnostics", font=ctk.CTkFont(size=18, weight="bold"), text_color="#FF00FF").pack(pady=(15, 5))
    ctk.CTkLabel(duval_card, text=f"Duval Triangle 1: {res['fault_duval']}", font=ctk.CTkFont(size=16), text_color="white", wraplength=450).pack(pady=5)
    if res['use_t4']:
        ctk.CTkLabel(duval_card, text=f"Duval Triangle 4: {res['fault_t4_desc']}", font=ctk.CTkFont(size=14), text_color="#E0E0E0", wraplength=450).pack(pady=3)
    if res['use_t5']:
        ctk.CTkLabel(duval_card, text=f"Duval Triangle 5: {res['fault_t5_desc']}", font=ctk.CTkFont(size=14), text_color="#E0E0E0", wraplength=450).pack(pady=3)
    ctk.CTkLabel(duval_card, text=f"Rogers Ratio: {res['fault_rogers']}", font=ctk.CTkFont(size=15), text_color="white", wraplength=450).pack(pady=5)
    ctk.CTkLabel(duval_card, text=f"Pentagon 1: {res['fault_pent1_desc']}", font=ctk.CTkFont(size=14), text_color="#E0E0E0", wraplength=450).pack(pady=3)
    ctk.CTkLabel(duval_card, text=f"Pentagon 2: {res['fault_pent2_desc']}", font=ctk.CTkFont(size=14), text_color="#E0E0E0", wraplength=450).pack(pady=3)
    ctk.CTkLabel(duval_card, text=f"Action: {res['action']}", font=ctk.CTkFont(size=14, slant="italic"), text_color="#AAAAAA", wraplength=450).pack(pady=15, padx=10)

    # Gas results table
    table_card = ctk.CTkFrame(dash_scroll, corner_radius=15, fg_color="#1A1A1A", border_width=1, border_color="#333")
    table_card.pack(fill="x", pady=10, padx=10)
    ctk.CTkLabel(table_card, text="🧪 Gas Concentrations vs IEEE Limits",
                 font=ctk.CTkFont(size=16, weight="bold"), text_color="#00D2FF").pack(anchor="w", padx=15, pady=(12, 8))
    grid = ctk.CTkFrame(table_card, fg_color="transparent")
    grid.pack(fill="x", padx=15, pady=(0, 12))
    headers = ['Gas', 'Value (ppm)', 'T1 Limit', 'T2 Limit', 'Delta', 'Rate/yr', 'Status']
    for j, h in enumerate(headers):
        ctk.CTkLabel(grid, text=h, font=ctk.CTkFont(size=13, weight="bold"), text_color="#FFD700",
                     width=120, anchor="w").grid(row=0, column=j, padx=4, pady=4, sticky="w")
    for i, r in enumerate(res['results'], start=1):
        row_vals = [r['Gas'], f"{r['Value (ppm)']:.1f}", str(r['Table 1 Limit']),
                    str(r['Table 2 Limit']), str(r['Delta vs Prev']),
                    str(r['Rate (ppm/yr)']), r['Level Status']]
        txt_color = "#FF6B6B" if 'T2' in r['Level Status'] else ("#FFD700" if 'T1' in r['Level Status'] else "#E0E0E0")
        for j, v in enumerate(row_vals):
            ctk.CTkLabel(grid, text=v, font=ctk.CTkFont(size=12), text_color=txt_color,
                         width=120, anchor="w").grid(row=i, column=j, padx=4, pady=2, sticky="w")

    # Embedded figures
    def embed_figure(parent, fig, title):
        wrap = ctk.CTkFrame(parent, corner_radius=15, fg_color="#1A1A1A", border_width=1, border_color="#333")
        wrap.pack(fill="both", expand=True, pady=10, padx=10)
        ctk.CTkLabel(wrap, text=title, font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="#00D2FF").pack(anchor="w", padx=15, pady=(12, 4))
        canvas = FigureCanvasTkAgg(fig, master=wrap)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

    charts_row = ctk.CTkFrame(dash_scroll, fg_color="transparent")
    charts_row.pack(fill="x", pady=4, padx=4)
    embed_figure(charts_row, res['fig_bar'], "📊 Gas Values vs Table 1 & 2")
    embed_figure(charts_row, res['fig_duval'], "📐 Duval Triangle 1")

    embed_figure(charts_row, res['fig_duval_4'], "📐 Duval Triangle 4 (Low Temp)")
    embed_figure(charts_row, res['fig_duval_5'], "📐 Duval Triangle 5 (High Temp)")

    embed_figure(charts_row, res['fig_pentagon_1'], "⬠ Duval Pentagon 1")
    embed_figure(charts_row, res['fig_pentagon_2'], "⬠ Duval Pentagon 2")

    if res['fig_trend'] is not None:
        embed_figure(charts_row, res['fig_trend'], "📈 Trend Analysis")

    # TAB 2: Text report ──────────────────────────────────────────────────────
    text_area = ctk.CTkTextbox(tab_text, wrap="word", font=ctk.CTkFont(family="Consolas", size=14),
                               fg_color="#111111", text_color="#E0E0E0")
    text_area.pack(fill="both", expand=True, padx=10, pady=10)
    text_area.tag_config("header", foreground="#00D2FF")
    text_area.tag_config("alert", foreground="#FF4500")
    text_area.tag_config("warning", foreground="#FFD700")
    text_area.tag_config("rogers", foreground="#FF69B4")
    text_area.tag_config("ai", foreground="#00FF7F")
    text_area.tag_config("expert", foreground="#FFD700")
    text_area.tag_config("co2", foreground="#00FFFF")
    text_area.tag_config("normal", foreground="#E0E0E0")

    current_tag = "normal"
    for line in res['report_text'].split('\n'):
        line_text = line + '\n'
        if "DGA ANALYSIS REPORT" in line or "DETAILED BREAKDOWNS" in line or "FAULT IDENTIFICATION:" in line:
            text_area.insert("end", line_text, "header"); current_tag = "header"; continue
        elif "Rogers Ratios" in line:
            current_tag = "rogers"
        elif "AI MODEL DIAGNOSIS" in line:
            current_tag = "ai"
        elif "EXPERT AI SYNTHESIS" in line:
            current_tag = "expert"
        elif "CO/CO2 ratio" in line or "CO/CO2 >" in line or "CO/CO2 <=" in line:
            current_tag = "co2"
        elif "OVERALL DGA STATUS" in line:
            current_tag = "header"

        line_tag = current_tag
        if "ABOVE T2" in line or "🔴" in line or "⚠️" in line:
            line_tag = "alert"
        elif "ABOVE T1" in line or "🟡" in line:
            line_tag = "warning"
        elif "===================" in line or "-------------------" in line:
            line_tag = "header"
        text_area.insert("end", line_text, line_tag)

    text_area.configure(state="disabled")

    win.protocol("WM_DELETE_WINDOW", exit_app)
    win.wait_window()
    return decision["action"]

# ============================================================
#  MAIN LOOP — input → analysis → dashboard → (new / quit)
# ============================================================
def main():
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")

    app = ctk.CTk()
    app.withdraw()   # hidden master window

    while True:
        submitted = get_input_data(app)
        if not submitted:
            break
        try:
            res = run_analysis()
        except Exception as e:
            messagebox.showerror("Analysis Error",
                                 f"An error occurred during DGA analysis:\n{e}\n\n"
                                 "Please check your input dates and values.")
            continue
        action = show_dashboard(app, res)
        if action != "new":
            break

    app.destroy()

if __name__ == "__main__":
    main()
