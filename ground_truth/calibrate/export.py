"""Static JSON export of calibration curves -- the file Ledger Sense reads.

Ledger Sense never calls into this codebase; it reads this file as a published
artifact. There is no runtime coupling in either direction, so a release in
either project can never block the other. Byte stability across reruns on
identical input matters because Phase 3's reproducibility test regenerates
this file from published raw results and asserts it comes out byte-identical
-- hence `sort_keys=True` and a fixed `indent`, and every value under our
control (never a dict with insertion-order-dependent construction).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ground_truth.calibrate.curves import CalibrationCurve, threshold_for_precision

EXPORT_SCHEMA_VERSION = "1.0.0"


def export_curves(
    curves: list[CalibrationCurve],
    path: Path,
    *,
    rubric_version: str,
    fitted_at: datetime,
    targets: list[float],
) -> None:
    body = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "curves": [
            {
                "field_type": curve.field_type,
                "method": curve.method,
                "curve_points": curve.points,
                # n_validate, not n_fit: the published sample size is the held-out
                # sample the curve was validated on, not the one it was fit to.
                "n": curve.n_validate,
                "fitted_at": fitted_at.isoformat(),
                "rubric_version": rubric_version,
                "source_split": "public-fit/private-validate",
                "threshold_recommendations": [
                    {
                        "target_precision": target,
                        "threshold": threshold_for_precision(curve, target),
                    }
                    for target in targets
                ],
            }
            for curve in curves
        ],
    }
    path.write_text(json.dumps(body, sort_keys=True, indent=2), encoding="utf-8")


def load_export(path: Path) -> dict[str, object]:
    result: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return result
