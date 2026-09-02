import json
import random
from datetime import UTC, datetime

from ground_truth.calibrate.curves import ConfidencePoint, fit_curve, threshold_for_precision
from ground_truth.calibrate.export import EXPORT_SCHEMA_VERSION, export_curves, load_export

FITTED_AT = datetime(2026, 10, 1, tzinfo=UTC)
TARGETS = [0.90, 0.95]


def points(n, seed):
    rng = random.Random(seed)
    return [
        ConfidencePoint(f"i{i}", score, rng.random() < score)
        for i in range(n)
        for score in [rng.uniform(0.5, 1.0)]
    ]


def curve(field_type="money"):
    return fit_curve(points(200, 1), points(200, 2), field_type, "isotonic")


def written(tmp_path):
    path = tmp_path / "calibration.json"
    export_curves([curve("money"), curve("percent")], path,
                  rubric_version="v1", fitted_at=FITTED_AT, targets=TARGETS)
    return path


def test_export_carries_the_schema_version(tmp_path):
    assert load_export(written(tmp_path))["schema_version"] == EXPORT_SCHEMA_VERSION


def test_every_required_key_is_present(tmp_path):
    entry = load_export(written(tmp_path))["curves"][0]
    assert set(entry) == {
        "field_type", "method", "curve_points", "n", "fitted_at",
        "rubric_version", "source_split", "threshold_recommendations",
    }


def test_source_split_states_the_design(tmp_path):
    assert load_export(written(tmp_path))["curves"][0]["source_split"] == "public-fit/private-validate"


def test_exported_thresholds_match_the_curve(tmp_path):
    body = load_export(written(tmp_path))
    for entry, source in zip(body["curves"], [curve("money"), curve("percent")], strict=True):
        for rec in entry["threshold_recommendations"]:
            assert rec["threshold"] == threshold_for_precision(source, rec["target_precision"])


def test_every_requested_target_appears(tmp_path):
    entry = load_export(written(tmp_path))["curves"][0]
    assert {r["target_precision"] for r in entry["threshold_recommendations"]} == set(TARGETS)


def test_export_is_byte_stable_for_a_fixed_input(tmp_path):
    path = written(tmp_path)
    first = path.read_text(encoding="utf-8")
    export_curves([curve("money"), curve("percent")], path,
                  rubric_version="v1", fitted_at=FITTED_AT, targets=TARGETS)
    assert path.read_text(encoding="utf-8") == first
    json.loads(first)


def test_n_is_the_validation_sample(tmp_path):
    assert load_export(written(tmp_path))["curves"][0]["n"] == 200, (
        "the published n is the held-out sample the curve was validated on"
    )
