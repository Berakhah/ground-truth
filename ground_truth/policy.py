"""Which sensitivity of payload a given slot is allowed to receive.

`00-SHARED-FOUNDATION.md`: CLIENT_CONFIDENTIAL routes only to a fully local path, or to a
provider explicitly marked `trains_on_data: false` **and** `commercial_use: true` with a paid
key supplied by the client -- "the gateway refuses to send it anywhere else, and the refusal
is a test". The key half is bok-core's to enforce at dispatch; the manifest half is ours, and
this is it. REDACTED and below are deliberately unrestricted: the 2026-09-03 decision keeps
training providers in the slot list and feeds them the redacted corpus variant, so gating
REDACTED here would quietly reverse that.

The check reads `models.yaml`, which is only as good as the audit behind it. Two things the
OpenRouter research (2026-09-03, `docs/providers-desk-research.md`) says about filling it in:
`trains_on_data` is a property of the model x provider *endpoint*, not the platform -- a `:free`
variant can train where the same provider's paid endpoints do not -- and the request-level
`{"provider": {"data_collection": "deny"}}` opt-out cannot be set from this repo, because
`call_fn` is bok-core's router and its signature is contract-fixed. That flag and the
account-level free-model opt-out are operator prerequisites recorded in the desk research, not
code here. This gate is the last line, not the only one.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ground_truth._bok_shim import Sensitivity, SensitivityViolation
from ground_truth.providers import SlotSpec


def assert_slot_may_see(
    slot: str,
    sensitivity: Sensitivity,
    specs: Mapping[str, SlotSpec],
    models_yaml: Path,
) -> None:
    """Raise `SensitivityViolation` before dispatch if `slot` may not receive `sensitivity`.

    Fails closed on an undeclared slot: no manifest row means no recorded data policy, and an
    unchecked policy is not a cleared one.
    """
    if sensitivity is not Sensitivity.CLIENT_CONFIDENTIAL:
        return
    spec = specs.get(slot)
    if spec is None:
        raise SensitivityViolation(
            f"slot {slot!r} carries {sensitivity.value} but is not declared in {models_yaml}; "
            "an undeclared slot has no recorded data policy to clear it"
        )
    if spec.trains_on_data or not spec.commercial_use:
        raise SensitivityViolation(
            f"slot {slot!r} ({spec.provider} / {spec.model_ref}) may not receive "
            f"{sensitivity.value}: {models_yaml} declares "
            f"trains_on_data={spec.trains_on_data} commercial_use={spec.commercial_use}, "
            f"retrieved {spec.retrieved_at.isoformat()}"
        )
