"""Train the DGA fault classifier and save its weights.

    py train_model.py                    # train and persist
    py train_model.py --strategy merge   # fold Low-/Middle- into the coarse class
    py train_model.py --report           # show the saved model card, train nothing

Weights land in `backend/ml_models/` as `dga_fault_model.pkl` plus the label
encoder and a `model_card.json` recording the data, decisions and scores behind
them. The API loads those on startup.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import Config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the DGA fault classifier.")
    parser.add_argument("--strategy", choices=["drop", "merge"], default=None,
                        help="How to resolve the overlapping coarse label.")
    parser.add_argument("--report", action="store_true",
                        help="Print the saved model card and exit.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")

    if args.strategy:
        Config.ML_COARSE_LABEL_STRATEGY = args.strategy

    # Imported after the strategy is set - the module reads it at import time.
    from core import ml  # noqa: E402
    ml.COARSE_LABEL_STRATEGY = Config.ML_COARSE_LABEL_STRATEGY

    if args.report:
        card = Path(ml.model_dir()) / "model_card.json"
        if not card.exists():
            print(f"No model card at {card}. Train first.")
            return 1
        print(card.read_text(encoding="utf-8"))
        return 0

    ok, message = ml._deps()
    if not ok:
        print(f"ERROR: {message}")
        return 1

    print("=" * 68)
    print("  DGA fault classifier - training")
    print("=" * 68)

    files = ml.find_training_files()
    for name, path in files.items():
        print(f"  {'found  ' if path else 'MISSING'} {name}"
              + (f"  ({path})" if path else ""))
    if all(p is None for p in files.values()):
        print("\nNo training data. Place the CSV/XLSX files in the project root.")
        return 1

    result = ml.train(force=True)
    if not result["available"]:
        print(f"\nTraining failed: {result['error']}")
        return 1

    m = result["metrics"]
    data = m["data"]

    print(f"\n--- data ---")
    for s in data["sources"]:
        print(f"  {s['file']:<32} {s.get('rows', 0):>5} rows"
              + (f"  [{s['skipped']}]" if s.get("skipped") else ""))
    print(f"  merged                           {data['mergedRows']:>5} rows")
    print(f"  duplicates dropped               {data['duplicatesDropped']:>5}")
    print(f"  label strategy: {data['coarseLabelStrategy']}")
    print(f"    {data['coarseLabelAction']}")
    print(f"  training rows                    {data['trainingRows']:>5}")

    print(f"\n--- classes ({len(m['classes'])}) ---")
    for label, n in sorted(data["classes"].items(), key=lambda kv: -kv[1]):
        print(f"  {label:<40} {n:>5}")

    print(f"\n--- performance ---")
    print(f"  hold-out accuracy   {m['testAccuracy']:.2f}%  ({m['testSamples']} samples)")
    print(f"  5-fold CV           {m['cvMean']:.2f}% +/- {m['cvStd']:.2f}%")
    print(f"\n{m['report']}")

    print(f"--- top features ---")
    for f in m["featureImportance"][:8]:
        bar = "#" * int(f["gain"] * 120)
        print(f"  {f['feature']:<16} {f['gain']:.4f} {bar}")

    print(f"\nWeights saved to {m['modelDir']}")
    print("  dga_fault_model.pkl, dga_label_encoder.pkl, model_card.json")
    print("\nRestart the API (or POST /api/ml/train) to serve the new model.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
