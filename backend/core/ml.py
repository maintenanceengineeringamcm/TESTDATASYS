"""XGBoost DGA fault classifier.

Trained on three published DGA datasets and applied **only to power transformers
that have dissolved-gas data** - the model learns from five hydrocarbon gases and
has no meaning for a breaker or a surge arrester.

The 19-feature vector and the hyperparameters follow `DGA_AI_DUVAL_LOGIC.md`
section 2 exactly. Two things the merged data needed that the spec did not
anticipate are handled here and reported in the model card:

*   **Duplicate rows.** 674 of 3,147 merged rows are exact duplicates. Left in,
    the same row lands in both the training and the test split, and hold-out
    accuracy measures memorisation rather than generalisation. They are dropped
    before the split.
*   **A label granularity clash.** Two sources carry the coarse class
    "Low/Middle-temperature overheating" (22 rows) while all three also carry the
    finer "Low-temperature" (248) and "Middle-temperature" (202). The classes are
    therefore not disjoint. See :data:`COARSE_LABEL_STRATEGY`.

The rest of the system - IEEE limits, Rogers ratios, Duval triangles and
pentagons - works whether or not this model is available.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path
from typing import Any

from config import BASE_DIR, Config

log = logging.getLogger(__name__)

# The single most important contract here: training and inference must build
# this vector identically, in this order.
FEATURE_COLS = [
    "H2", "CH4", "C2H6", "C2H4", "C2H2",
    "R1_C2H2_C2H4", "R2_CH4_H2", "R3_C2H4_C2H6", "R4_C2H2_CH4", "R5_C2H6_C2H2",
    "pct_CH4", "pct_C2H4", "pct_C2H2",
    "TDCG",
    "log_H2", "log_CH4", "log_C2H6", "log_C2H4", "log_C2H2",
]

EPS = 1e-6

GAS_COLS = ["H2", "CH4", "C2H6", "C2H4", "C2H2"]

TRAINING_FILES = ["DGA-dataset-1.csv", "equipment_p_fault_data.xlsx", "dataset_2_en.csv"]

# Duval codes in the spreadsheet source -> the shared label vocabulary.
FAULT_MAP = {
    "D1": "Spark discharge",
    "D2": "Arc discharge",
    "T1/T2": "Low/Middle-temperature overheating",
    "T3": "High-temperature overheating",
}

COARSE_LABEL = "Low/Middle-temperature overheating"
FINE_LABELS = ["Low-temperature overheating", "Middle-temperature overheating"]

# How to resolve the overlap between the coarse class and its two constituents:
#
#   "drop"  - discard the 22 coarse rows, keeping seven disjoint classes and the
#             Low vs Middle distinction. That distinction is Duval T1 (<300 C)
#             against T2 (300-700 C), where T2 implies paper carbonisation, so it
#             is worth more than 0.7% of the rows it costs.
#   "merge" - fold Low- and Middle- into the coarse class instead: six classes,
#             no row discarded, but the T1/T2 distinction is lost.
COARSE_LABEL_STRATEGY = Config.ML_COARSE_LABEL_STRATEGY

# Where the classifier applies. Anything else gets an explicit refusal rather
# than a meaningless number.
SUPPORTED_ASSET_TYPES = {"TR"}

_state: dict[str, Any] = {
    "model": None, "encoder": None, "trained": False,
    "error": None, "metrics": None,
}
_lock = threading.Lock()


def model_dir() -> Path:
    return Config.ML_MODEL_DIR


def build_feature_vector(h2: float, ch4: float, c2h6: float, c2h4: float,
                         c2h2: float) -> list[float]:
    """The 19 features, in FEATURE_COLS order. Every division is eps-guarded."""
    h2, ch4, c2h6, c2h4, c2h2 = (float(x or 0.0) for x in (h2, ch4, c2h6, c2h4, c2h2))
    tri = ch4 + c2h4 + c2h2 + EPS
    return [
        h2, ch4, c2h6, c2h4, c2h2,
        c2h2 / (c2h4 + EPS), ch4 / (h2 + EPS), c2h4 / (c2h6 + EPS),
        c2h2 / (ch4 + EPS), c2h6 / (c2h2 + EPS),
        ch4 / tri * 100, c2h4 / tri * 100, c2h2 / tri * 100,
        h2 + ch4 + c2h6 + c2h4 + c2h2,
        math.log1p(h2), math.log1p(ch4), math.log1p(c2h6),
        math.log1p(c2h4), math.log1p(c2h2),
    ]


def _deps() -> tuple[bool, str]:
    try:
        import numpy, pandas, sklearn, xgboost, joblib   # noqa: F401
        return True, ""
    except ImportError as exc:
        return False, (f"ML dependencies missing ({exc.name}). "
                       "Install with: pip install -r requirements-ml.txt")


def data_dirs() -> list[Path]:
    """Where training files may live: the configured folder, then the repo root."""
    return [Config.ML_DATA_DIR, BASE_DIR.parent]


def find_training_files() -> dict[str, Path | None]:
    found: dict[str, Path | None] = {}
    for name in TRAINING_FILES:
        found[name] = next((d / name for d in data_dirs() if (d / name).exists()), None)
    return found


def load_training_frame():
    """Merge the three sources into one labelled frame, and report what happened."""
    import pandas as pd

    files = find_training_files()
    missing = [n for n, p in files.items() if p is None]
    if len(missing) == len(TRAINING_FILES):
        return None, {"error": "No training files found in "
                               + " or ".join(str(d) for d in data_dirs())}

    report: dict[str, Any] = {"sources": [], "missing": missing}
    frames = []

    for name, path in files.items():
        if path is None:
            continue
        df = pd.read_excel(path) if path.suffix.lower() in {".xlsx", ".xls"} \
            else pd.read_csv(path)

        # The spreadsheet source labels with Duval codes rather than fault names.
        if "Type" not in df.columns and "Fault Type" in df.columns:
            df["Type"] = df["Fault Type"].map(FAULT_MAP)

        if not set(GAS_COLS + ["Type"]).issubset(df.columns):
            report["sources"].append({"file": name, "rows": 0,
                                      "skipped": "missing expected columns"})
            continue

        subset = df[GAS_COLS + ["Type"]].copy()
        subset["_source"] = name
        frames.append(subset)
        report["sources"].append({"file": name, "path": str(path), "rows": int(len(subset))})

    if not frames:
        return None, {**report, "error": "No source carried the expected columns."}

    merged = pd.concat(frames, ignore_index=True)
    merged = merged.dropna(subset=["Type"])
    # Gases arrive as text in places and carry a few blanks; the spec's rule is
    # to coerce to numeric and treat missing as zero.
    merged[GAS_COLS] = merged[GAS_COLS].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    merged["Type"] = merged["Type"].astype(str).str.strip()
    report["mergedRows"] = int(len(merged))
    report["labelsBeforeHarmonisation"] = merged["Type"].value_counts().to_dict()

    # --- resolve the coarse/fine label overlap ---------------------------
    has_coarse = (merged["Type"] == COARSE_LABEL).sum()
    has_fine = merged["Type"].isin(FINE_LABELS).sum()
    report["coarseLabelStrategy"] = COARSE_LABEL_STRATEGY
    if has_coarse and has_fine:
        if COARSE_LABEL_STRATEGY == "merge":
            merged.loc[merged["Type"].isin(FINE_LABELS), "Type"] = COARSE_LABEL
            report["coarseLabelAction"] = (
                f"Folded {int(has_fine)} Low-/Middle-temperature rows into "
                f"'{COARSE_LABEL}' so the classes are disjoint.")
        else:
            merged = merged[merged["Type"] != COARSE_LABEL]
            report["coarseLabelAction"] = (
                f"Dropped {int(has_coarse)} '{COARSE_LABEL}' rows, which overlap the "
                f"finer Low- and Middle-temperature classes, keeping those distinct.")
    else:
        report["coarseLabelAction"] = "No overlap present."

    # --- drop exact duplicates -------------------------------------------
    before = len(merged)
    merged = merged.drop_duplicates(subset=GAS_COLS + ["Type"]).reset_index(drop=True)
    report["duplicatesDropped"] = int(before - len(merged))

    report["trainingRows"] = int(len(merged))
    report["classes"] = merged["Type"].value_counts().to_dict()
    return merged, report


def train(force: bool = False) -> dict[str, Any]:
    """Train once, persist the weights, and cache in memory."""
    with _lock:
        if _state["trained"] and not force:
            return status()

        ok, message = _deps()
        if not ok:
            _state.update(trained=False, error=message)
            return status()

        try:
            import numpy as np
            import joblib
            from sklearn.model_selection import (StratifiedKFold, cross_val_score,
                                                 train_test_split)
            from sklearn.metrics import classification_report, confusion_matrix
            from sklearn.preprocessing import LabelEncoder
            from xgboost import XGBClassifier

            df, report = load_training_frame()
            if df is None:
                _state.update(trained=False, error=report.get("error"))
                return status()

            feats = np.array([
                build_feature_vector(r.H2, r.CH4, r.C2H6, r.C2H4, r.C2H2)
                for r in df.itertuples()
            ])
            encoder = LabelEncoder()
            y = encoder.fit_transform(df["Type"].astype(str))

            # stratify is required - the classes are imbalanced.
            x_tr, x_te, y_tr, y_te = train_test_split(
                feats, y, test_size=0.20, random_state=42, stratify=y)

            model = XGBClassifier(
                n_estimators=300, max_depth=5, learning_rate=0.08,
                subsample=0.8, colsample_bytree=0.8,
                eval_metric="mlogloss", random_state=42,
            )
            model.fit(x_tr, y_tr)

            cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
            cv_scores = cross_val_score(model, feats, y, cv=cv, scoring="accuracy")
            test_acc = float(model.score(x_te, y_te))
            predictions = model.predict(x_te)
            classes = [str(c) for c in encoder.classes_]

            importance = sorted(
                zip(FEATURE_COLS, (float(v) for v in model.feature_importances_)),
                key=lambda kv: -kv[1],
            )

            out = model_dir()
            out.mkdir(parents=True, exist_ok=True)
            joblib.dump(model, out / "dga_fault_model.pkl")
            joblib.dump(encoder, out / "dga_label_encoder.pkl")

            metrics = {
                "samples": int(len(df)),
                "trainSamples": int(len(x_tr)),
                "testSamples": int(len(x_te)),
                "classes": classes,
                "classCounts": report.get("classes", {}),
                "testAccuracy": round(test_acc * 100, 2),
                "cvMean": round(float(cv_scores.mean()) * 100, 2),
                "cvStd": round(float(cv_scores.std()) * 100, 2),
                "featureImportance": [{"feature": f, "gain": round(v, 4)}
                                      for f, v in importance],
                "report": classification_report(
                    y_te, predictions, target_names=classes, zero_division=0),
                "confusionMatrix": confusion_matrix(y_te, predictions).tolist(),
                "data": report,
                "modelDir": str(out),
                "trainedAt": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
            }
            # A model card next to the weights, so a saved model can always be
            # traced back to the data and decisions that produced it.
            (out / "model_card.json").write_text(json.dumps(metrics, indent=2),
                                                 encoding="utf-8")

            _state.update(model=model, encoder=encoder, trained=True, error=None,
                          metrics=metrics)
            log.info("model trained: %d samples, %d classes, hold-out %.1f%%, CV %.1f%%",
                     metrics["samples"], len(classes), metrics["testAccuracy"],
                     metrics["cvMean"])
        except Exception as exc:                       # pragma: no cover
            log.exception("model training failed")
            _state.update(trained=False, error=f"Training failed: {exc}")
        return status()


def load_saved() -> bool:
    """Load previously trained weights from disk, if present."""
    ok, _ = _deps()
    if not ok:
        return False
    out = model_dir()
    model_path = out / "dga_fault_model.pkl"
    encoder_path = out / "dga_label_encoder.pkl"
    if not (model_path.exists() and encoder_path.exists()):
        return False
    try:
        import joblib

        with _lock:
            _state["model"] = joblib.load(model_path)
            _state["encoder"] = joblib.load(encoder_path)
            card = out / "model_card.json"
            if card.exists():
                _state["metrics"] = json.loads(card.read_text(encoding="utf-8"))
            _state["trained"] = True
            _state["error"] = None
        log.info("loaded saved model from %s", out)
        return True
    except Exception as exc:                           # pragma: no cover
        log.warning("could not load saved model: %s", exc)
        return False


def ensure_ready() -> dict[str, Any]:
    """Load saved weights, training them if none exist yet."""
    if _state["trained"]:
        return status()
    if load_saved():
        return status()
    return train()


def status() -> dict[str, Any]:
    ok, dep_msg = _deps()
    files = {n: (str(p) if p else None) for n, p in find_training_files().items()} \
        if ok else {n: None for n in TRAINING_FILES}
    return {
        "available": bool(_state["trained"]),
        "dependenciesInstalled": ok,
        "error": _state["error"] or (None if ok else dep_msg),
        "metrics": _state["metrics"],
        "dataDirs": [str(d) for d in data_dirs()],
        "trainingFiles": files,
        "modelDir": str(model_dir()),
        "supportedAssetTypes": sorted(SUPPORTED_ASSET_TYPES),
    }


def confidence_flag(confidence: float) -> dict[str, str]:
    if confidence >= 85:
        return {"level": "high", "color": "#0E9F6E", "text": "Trust the prediction"}
    if confidence >= 65:
        return {"level": "medium", "color": "#B7791F",
                "text": "Corroborate with Duval / Rogers"}
    return {"level": "low", "color": "#D64545", "text": "Engineer review required"}


def predict(h2: float, ch4: float, c2h6: float, c2h4: float, c2h2: float,
            asset_type: str | None = None) -> dict[str, Any]:
    """Classify one gas sample.

    `asset_type` gates the model to power transformers. The training data is
    transformer oil DGA, so a prediction for a breaker or arrester would be
    meaningless - it is refused rather than shown.
    """
    if asset_type is not None and asset_type not in SUPPORTED_ASSET_TYPES:
        return {"available": False, "applicable": False,
                "fault": "Not applicable", "confidence": 0.0, "probabilities": {},
                "reason": (f"The classifier is trained on transformer oil DGA and does "
                           f"not apply to asset type '{asset_type}'.")}

    if not _state["trained"]:
        return {"available": False, "applicable": True,
                "fault": "N/A (model not loaded)", "confidence": 0.0,
                "probabilities": {}, "reason": _state["error"] or "Model not trained."}

    total = sum(float(x or 0.0) for x in (h2, ch4, c2h6, c2h4, c2h2))
    if total <= 0:
        return {"available": False, "applicable": True,
                "fault": "No gas detected", "confidence": 0.0, "probabilities": {},
                "reason": "All five modelled gases are zero - nothing to classify."}

    try:
        import numpy as np

        model, encoder = _state["model"], _state["encoder"]
        vector = np.array([build_feature_vector(h2, ch4, c2h6, c2h4, c2h2)])
        proba = model.predict_proba(vector)[0]
        idx = int(proba.argmax())
        label = str(encoder.inverse_transform([idx])[0])
        confidence = float(proba.max() * 100)
        return {
            "available": True,
            "applicable": True,
            "fault": label,
            "confidence": round(confidence, 1),
            "flag": confidence_flag(confidence),
            "probabilities": {str(c): round(float(p) * 100, 1)
                              for c, p in zip(encoder.classes_, proba)},
        }
    except Exception as exc:                           # pragma: no cover
        return {"available": False, "applicable": True,
                "fault": "N/A (prediction failed)", "confidence": 0.0,
                "probabilities": {}, "reason": str(exc)}


def agrees_with_duval(ai_fault: str, duval_zone: str | None) -> bool:
    """Cross-map the ML label vocabulary onto Duval zone codes.

    Never silently pick a winner when they disagree - surfacing the
    disagreement is the diagnostic value.
    """
    if not duval_zone:
        return False
    short = duval_zone.split("-")[0].strip()
    return (
        ("High-temperature" in ai_fault and short == "T3")
        or ("Middle-temperature" in ai_fault and short == "T2")
        or ("Low-temperature" in ai_fault and short == "T1")
        or ("Low/Middle-temperature" in ai_fault and short in ("T1", "T2"))
        or ("Spark" in ai_fault and short == "D1")
        or ("Arc" in ai_fault and short == "D2")
        or ("Partial discharge" in ai_fault and short == "PD")
        or ("Normal" in ai_fault and short in ("S", "PD"))
        or (ai_fault == short)
    )
