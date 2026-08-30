from __future__ import annotations

import hashlib
import random
from decimal import Decimal
from enum import StrEnum
from typing import cast

from ground_truth.golden.schema import FieldType, Item, ItemField, Source, Split

NON_AFFILIATION = (
    "This document is not affiliated with, endorsed by, approved by or sponsored by the AIA. "
    "References describe column semantics only."
)
_LEGAL_SUFFIXES = ("Inc.", "LLC", "Ltd.", "Pty Ltd", "GmbH")
_TRADES = ("Sitework", "Concrete", "Masonry", "Structural Steel", "Roofing", "Glazing")

# audit M1: the document's wording, which must never contain the JSON key it answers.
# `test_document_does_not_use_the_json_key_names` enforces this. Underscores do most of
# the work; the entries that needed real thought are the retainage family, because
# "retainage" is both a bare JSON key and the obvious English word -- hence "AMOUNT
# RETAINED" throughout, which is also what a real certificate for payment says.
_WORDING = {
    "work_completed": "TOTAL COMPLETED & STORED TO DATE",
    "stored_materials": "MATERIALS PRESENTLY STORED",
    "retainage": "LESS AMOUNT RETAINED",
    "total_earned_less_retainage": "TOTAL EARNED LESS AMOUNT RETAINED",
    "contract_sum": "CONTRACT SUM TO DATE",
    "balance_to_finish": "BALANCE TO FINISH, PLUS AMOUNT RETAINED",
    "line_count": "ITEMS ON THIS SHEET",
    "period_to": "PERIOD ENDING",
    "application_no": "APPLICATION NO.",
    "contractor": "CERTIFIED BY",
    "status": "CERTIFICATION",
}


class ErrorClass(StrEnum):
    TRANSPOSED_DIGITS = "transposed_digits"
    OFF_BY_ONE_CENT = "off_by_one_cent"
    MISSING_FIELD = "missing_field"
    RETAINAGE_MISMATCH = "retainage_mismatch"
    STORED_MATERIALS_DOUBLE_COUNT = "stored_materials_double_count"
    DATE_LOCALE_AMBIGUOUS = "date_locale_ambiguous"


def _money(rng: random.Random, low: int, high: int) -> Decimal:
    return (Decimal(rng.randint(low * 100, high * 100)) / Decimal(100)).quantize(Decimal("0.01"))


def _transpose_digits(value: str) -> str:
    """Swap the rightmost adjacent pair of unequal digits. Deterministic; draws no rng."""
    chars = list(value)
    digits = [i for i, c in enumerate(chars) if c.isdigit()]
    for a, b in zip(reversed(digits[:-1]), reversed(digits[1:]), strict=True):
        if chars[a] != chars[b]:
            chars[a], chars[b] = chars[b], chars[a]
            return "".join(chars)
    return value  # every digit identical; the corruption test is the guard


def _build_fields(
    rng: random.Random, injected: ErrorClass | None
) -> tuple[list[ItemField], dict[str, object]]:
    """Injection MUST NOT draw from `rng`. The clean and dirty streams are compared
    position-by-position in `test_every_injected_error_class_actually_corrupts_the_item`,
    and one extra draw silently desynchronises them (audit M2)."""
    n_lines = rng.randint(3, 8)
    line_values = [_money(rng, 5_000, 90_000) for _ in range(n_lines)]
    descriptions = [f"{rng.choice(_TRADES)} works, phase {n}" for n in range(1, n_lines + 1)]
    work_completed = sum(line_values, Decimal("0.00"))
    retainage_rate = Decimal("10.00")  # percentage points, as a certificate for payment prints it
    retainage = (work_completed * retainage_rate / Decimal(100)).quantize(Decimal("0.01"))
    stored = _money(rng, 0, 5_000)
    previous_certificates = _money(rng, 1_000, 40_000)  # distractor: never a labelled field
    project_no = f"{rng.randint(1000, 9999)}-{rng.choice(('A', 'B', 'C', 'D', 'E'))}"  # distractor

    if injected is ErrorClass.RETAINAGE_MISMATCH:
        retainage += Decimal("500.00")
    if injected is ErrorClass.STORED_MATERIALS_DOUBLE_COUNT:
        work_completed += stored
    earned_less_retainage = work_completed + stored - retainage
    if injected is ErrorClass.OFF_BY_ONE_CENT:
        # Exactly on the tolerance boundary: the document is internally inconsistent by one
        # cent, and a correct extraction still reproduces it. This is the boundary probe.
        earned_less_retainage += Decimal("0.01")
    contract_sum = work_completed + stored + _money(rng, 10_000, 50_000)
    balance = contract_sum - earned_less_retainage
    contract_sum_text = str(contract_sum)
    if injected is ErrorClass.TRANSPOSED_DIGITS:
        contract_sum_text = _transpose_digits(contract_sum_text)
    date_value = "2026-09-01" if injected is not ErrorClass.DATE_LOCALE_AMBIGUOUS else "01/09/2026"
    application_no = f"APP-{rng.randint(1, 999):06d}"
    if injected is ErrorClass.MISSING_FIELD:
        application_no = ""  # dropped from the document; an empty label means "absent"

    def f(name: str, ftype: FieldType, value: str, tol: Decimal | None = None) -> ItemField:
        return ItemField(field_name=name, field_type=ftype, expected_value=value, tolerance=tol)

    cents = Decimal("0.01")
    fields = [
        f(f"line_{n}", FieldType.MONEY, str(v), cents) for n, v in enumerate(line_values, start=1)
    ]
    fields += [
        f("work_completed", FieldType.MONEY, str(work_completed), cents),
        f("stored_materials", FieldType.MONEY, str(stored), cents),
        f("retainage", FieldType.MONEY, str(retainage), cents),
        f("total_earned_less_retainage", FieldType.MONEY, str(earned_less_retainage), cents),
        f("contract_sum", FieldType.MONEY, contract_sum_text, cents),
        f("balance_to_finish", FieldType.MONEY, str(balance), cents),
        f("retainage_rate", FieldType.PERCENT, str(retainage_rate), Decimal("0.01")),
        f("period_to", FieldType.DATE, date_value),
        f("application_no", FieldType.IDENTIFIER, application_no),
        f(
            "contractor",
            FieldType.PARTY_NAME,
            f"{rng.choice(_TRADES)} Partners {rng.choice(_LEGAL_SUFFIXES)}",
        ),
        f("status", FieldType.ENUM_CATEGORY, rng.choice(("approved", "pending", "rejected"))),
        f("line_count", FieldType.COUNT, str(n_lines)),
        f("line_1_description", FieldType.LINE_ITEM_DESCRIPTION, descriptions[0]),
    ]
    # Layout metadata, carried so render_document can lay out rows and distractors without
    # re-drawing from rng. Never a label; write_manifest must not emit it.
    layout: dict[str, object] = {
        "descriptions": descriptions,
        "previous_certificates": str(previous_certificates),
        "project_no": project_no,
    }
    return fields, layout


def generate(
    count: int,
    seed: int | str,
    rubric_version: str,
    *,
    salt: str = "dev-salt-do-not-use-in-production",
    inject: bool = True,
) -> list[Item]:
    """`inject=False` replays the identical rng stream with every corruption skipped, which
    is what makes "does this error class actually corrupt anything?" a testable question.

    audit B4: `content_hash` is salted. `generate.py` is published (spec §13.1), so without a
    salt the message space is fully enumerable from the seed alone -- the manifest's commitment
    strength would be exactly the seed's entropy. `build.py` (Task 9) passes the real
    `GT_HASH_SALT`; the default here is a fixed placeholder so every existing test call site
    is unaffected and no test pins a literal hash value.
    """
    rng = random.Random(seed)
    errors = list(ErrorClass)
    items: list[Item] = []
    for n in range(count):
        injected = errors[(n // 2) % len(errors)] if n % 2 == 0 else None
        fields, layout = _build_fields(rng, injected if inject else None)
        payload = "|".join(f"{f.field_name}={f.expected_value}" for f in fields)
        content_hash = hashlib.sha256(f"{salt}:{seed}:{n}:{payload}".encode()).hexdigest()
        # audit H1: item_id must NOT be a prefix of the published content_hash, or publishing
        # the hash publishes the id and test_private_item_ids_never_appear_in_published_output
        # can never pass. Preimage resistance keeps the two namespaces apart.
        item_id = hashlib.sha256(b"item-id:" + content_hash.encode()).hexdigest()[:16]
        items.append(
            Item(
                item_id=item_id,
                split=Split.PUBLIC,  # build.py generates the two splits separately; see Task 9
                rubric_version=rubric_version,
                source=Source.SYNTHETIC,
                content_hash=content_hash,
                fields=fields,
                layout=layout,
                injected_error=injected.value if (injected and inject) else None,
            )
        )
    return items


def _amount(value: str) -> str:
    return f"{Decimal(value):,.2f}" if value else ""


def render_document(item: Item) -> str:
    """A continuation sheet and a summary block, in the document's own wording.

    audit M1: the previous version emitted `f"{field_name:<32}{expected_value}"` using the
    exact keys the prompt asks for, which made the entire benchmark a string-copy task with
    no external validity at all. Every number a model must find is now where a real form
    would put it, beside numbers it must ignore.
    """
    by_name = {f.field_name: f for f in item.fields}

    def v(name: str) -> str:
        return by_name[name].expected_value

    rule, thin = "=" * 78, "-" * 78
    out = [
        rule,
        f"  PROGRESS BILLING SUMMARY{'':<28}Project No. {item.layout['project_no']}",
        f"  {_WORDING['application_no']} {v('application_no') or '(not issued)':<24}"
        f"{_WORDING['period_to']}  {v('period_to')}",
        thin,
        "  ITEM  DESCRIPTION OF WORK                                    AMOUNT THIS PERIOD",
        thin,
    ]
    rows = [
        f
        for f in item.fields
        if f.field_name.startswith("line_") and f.field_name.removeprefix("line_").isdigit()
    ]
    for n, (field, description) in enumerate(
        zip(rows, cast(list[str], item.layout["descriptions"]), strict=True), start=1
    ):
        out.append(f"  {n:>4}  {description:<52}{_amount(field.expected_value):>18}")
    out += [
        thin,
        f"  {_WORDING['line_count']:<58}{v('line_count'):>18}",
        rule,
        f"  {_WORDING['contract_sum']:<58}{_amount(v('contract_sum')):>18}",
        f"  {_WORDING['work_completed']:<58}{_amount(v('work_completed')):>18}",
        f"  {_WORDING['stored_materials']:<58}{_amount(v('stored_materials')):>18}",
        f"  {_WORDING['retainage'] + '  ' + v('retainage_rate') + ' % OF COMPLETED WORK':<58}"
        f"{_amount(v('retainage')):>18}",
        f"  {_WORDING['total_earned_less_retainage']:<58}"
        f"{_amount(v('total_earned_less_retainage')):>18}",
        f"  LESS PREVIOUS CERTIFICATES FOR PAYMENT{'':<20}"
        f"{_amount(str(item.layout['previous_certificates'])):>18}",
        f"  {_WORDING['balance_to_finish']:<58}{_amount(v('balance_to_finish')):>18}",
        rule,
        f"  {_WORDING['contractor']}: {v('contractor')}",
        f"  {_WORDING['status']}: {v('status')}",
        "",
        NON_AFFILIATION,
    ]
    return "\n".join(out)
