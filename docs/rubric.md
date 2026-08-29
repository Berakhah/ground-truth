---
rubric_version: v1
status: frozen-before-labelling
grading_scope: pay-application and invoice field extraction, per FieldType in ground_truth/golden/schema.py
---

# Ground Truth Grading Rubric

This rubric defines, per `FieldType`, exactly what counts as a correct extraction: the grader used, any numeric tolerance, the normalisation pipeline applied to both the expected and extracted values before comparison, explicit acceptable-variant equivalences, and the adjudication rule for disputed or ambiguous cases.

It is authored and cryptographically timestamped (`docs/rubric.md.ots`, via OpenTimestamps) before any item in the golden set is labelled, so scores cannot be reverse-engineered into the rubric after the fact. Blind re-labelling of a 20% sample after a two-week gap, and a second labeller from the Ledger Sense design partner on a subset, are measured against this same frozen rubric; disagreement rates are reported honestly, not smoothed over. Changing a grading rule after labelling has started requires a new rubric version, never a silent edit of `v1`.

## MONEY
- grader: numeric_tolerance
- tolerance: 0.01
- normalisation: strip_currency_symbol; strip_thousands_separator; parenthesised_negative_to_minus
- acceptable_variants: -
- adjudication: A value within tolerance of the expected Decimal is correct regardless of formatting; a value outside tolerance is incorrect with no exception. A currency-symbol mismatch (extracted amount tagged with the wrong currency) is not resolved by this grader and is escalated to a human adjudicator. Borderline tolerance cases surfaced during blind re-labelling are recorded as adjudication decisions, not silently re-scored.

## PERCENT
- grader: numeric_tolerance
- tolerance: 0.001
- normalisation: strip_percent_symbol; percent_to_decimal
- acceptable_variants: -
- adjudication: 12.5% and 0.125 are the same value after normalisation and are graded identically; a value outside the 0.001 tolerance is incorrect. A whole number with an ambiguous implied denominator (e.g. "5" meaning 5% vs 500%) is escalated to a human adjudicator rather than guessed from context.

## DATE
- grader: normalised
- tolerance: -
- normalisation: parse_to_iso_8601; strip_ordinal_suffix; expand_two_digit_year_using_document_context
- acceptable_variants: 2024-01-05=January 5, 2024; 2024-01-05=5 Jan 2024; 2024-01-05=05-Jan-2024
- adjudication: A purely numeric date whose day and month are both ambiguous between DD/MM and MM/DD (e.g. 03/04) scores incorrect by rule, never guessed from a locale assumption. A numeric date resolvable only by an unambiguous cue elsewhere in the same document (e.g. a day value greater than 12) is escalated to a human adjudicator, who records the resolving evidence, rather than parsed automatically.

## IDENTIFIER
- grader: normalised
- tolerance: -
- normalisation: strip_punctuation; strip_leading_zeros; casefold
- acceptable_variants: po=purchase order; inv=invoice; co=change order
- adjudication: The prefix expansions listed above are accepted; any other abbreviation not on this list is escalated to a human adjudicator rather than accepted by analogy. Leading-zero stripping that would change a semantically meaningful identifier (for example a check number where the zero is significant) is flagged for adjudication before the rule is applied.

## PARTY_NAME
- grader: normalised
- tolerance: -
- normalisation: casefold; strip_accents; strip_legal_suffix; ampersand_to_and
- acceptable_variants: -
- adjudication: This rubric states the general rule, not a name-by-name list — legal-suffix and casing differences are already handled by normalisation above. A trading name, DBA, or subsidiary alias for the same legal party is accepted only when the labeller records it as an explicit adjudication decision for that item; an unstated abbreviation is never auto-accepted by analogy to another item.

## ENUM_CATEGORY
- grader: exact
- tolerance: -
- normalisation: casefold; strip_whitespace
- acceptable_variants: not_applicable=n/a; not_applicable=na; not_applicable=none
- adjudication: The closed value list is stated per field at labelling time, never invented at grading time; a value outside the stated list is incorrect, never fuzzy-matched to the nearest category. A labeller who believes the stated list is missing a legitimate category escalates to a rubric revision (a new version), not a silent grading exception.

## COUNT
- grader: exact
- tolerance: -
- normalisation: strip_whitespace; strip_leading_zeros
- acceptable_variants: -
- adjudication: The expected and extracted values must be the same integer string after normalisation; spelled-out number words, ranges, and approximations ("about 12") are all incorrect by rule. A count that is ambiguous in the source document itself (for example a subtotal line that may or may not represent a count) is flagged for adjudication before labelling, not resolved by the grader.

## LINE_ITEM_DESCRIPTION
- grader: judge
- tolerance: -
- normalisation: -
- acceptable_variants: -
- adjudication: This field is graded by an LLM judge, never a deterministic rule, and is barred from headline scoring whenever judge-versus-human agreement (Krippendorff's alpha) falls below 0.667 on the measured sample; below that threshold it is reported separately as unresolved rather than folded into a passing score. Judge presentation order is randomised and tested for order effects, length cues are stripped from the compared text, and the judge is never a model from the same family as the model under test. Disagreements between the judge and a human label are adjudicated by a human and recorded as a decision, not overwritten silently.
