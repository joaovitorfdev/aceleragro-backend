"""Producer eligibility classification (spreadsheet legacy + current rules)."""

from __future__ import annotations

from decimal import Decimal

from acelera_agro.engine.types import ClassificationInput, ClassificationResult

# --- Spreadsheet legacy thresholds (Safra 2021/22 BB workbook quirks) ---
# Documented quirks vs the adjacent table / headers in Enquadramento:
# - Grupo B ceiling uses R$ 10_000 (not the current Pronaf B R$ 60_000).
# - Grupo AF ceiling in formula J49 uses R$ 5_000_000 while the side table
#   shows R$ 500_000; we follow the **table** (500_000) as the intended band
#   for AF, which still classifies the acceptance case (RBA 215_418) as AF.
# - Header text says "1/3" agro share; the formula uses 50%. We use 50%.
# - Pronamp ceiling in the sheet uses R$ 2_000_000 (not current R$ 3_500_000).
# - Condition comparing a text label to 10000 is always true in Excel; ignored.
_SPREADSHEET_GRUPO_B_MAX = Decimal("10000")
_SPREADSHEET_AF_MAX = Decimal("500000")
_SPREADSHEET_PRONAMP_MAX = Decimal("2000000")
_SPREADSHEET_AF_AGRO_MIN = Decimal("0.50")
_SPREADSHEET_PRONAMP_AGRO_MIN = Decimal("0.80")

# --- Current parametric thresholds (Plano Safra / MCR research 2026) ---
_CURRENT_PRONAF_B_MAX = Decimal("60000")
_CURRENT_PRONAF_MAX = Decimal("500000")
_CURRENT_PRONAMP_MAX = Decimal("3500000")
_CURRENT_PRONAMP_AGRO_MIN = Decimal("0.80")
_DEFAULT_VBP_FACTOR = Decimal("1")
_SPECIAL_ACTIVITY_VBP_FACTOR = Decimal("0.70")  # milk, coffee, fruit, horticulture


def classify_producer_spreadsheet_rule(input: ClassificationInput) -> ClassificationResult:
    """Classify using the legacy BB spreadsheet Enquadramento rule.

    Returns group codes: ``B``, ``AF``, ``PRONAMP``, ``OTHER``.
    """
    rba = Decimal(input.total_rba)
    agro = Decimal(input.agro_revenue_share)

    if rba <= _SPREADSHEET_GRUPO_B_MAX:
        code = "B"
    elif rba <= _SPREADSHEET_AF_MAX and agro >= _SPREADSHEET_AF_AGRO_MIN:
        code = "AF"
    elif rba <= _SPREADSHEET_PRONAMP_MAX and agro >= _SPREADSHEET_PRONAMP_AGRO_MIN:
        code = "PRONAMP"
    else:
        code = "OTHER"

    return ClassificationResult(group_code=code, rule_source="spreadsheet_legacy")


def classify_producer_current_rule(input: ClassificationInput) -> ClassificationResult:
    """Classify using current Pronaf / Pronamp parametric criteria.

    - Pronaf B: family gross income up to R$ 60_000.
    - Pronaf: up to R$ 500_000.
    - Pronamp: up to R$ 3_500_000 with at least 80% agro revenue.
    - When ``milk_vbp_factor`` is set (milk / coffee / fruit / horticulture),
      that factor (typically 0.70) scales RBA before comparing income ceilings.
      If omitted, factor 1.0 is used (no VBP reduction).
    """
    factor = (
        Decimal(input.milk_vbp_factor)
        if input.milk_vbp_factor is not None
        else _DEFAULT_VBP_FACTOR
    )
    # Guard against accidental factors outside the known special-activity band
    # without rejecting legitimate 1.0 (no reduction).
    if factor <= 0:
        raise ValueError("milk_vbp_factor must be positive")

    effective_rba = Decimal(input.total_rba) * factor
    agro = Decimal(input.agro_revenue_share)

    if effective_rba <= _CURRENT_PRONAF_B_MAX:
        code = "PRONAF_B"
    elif effective_rba <= _CURRENT_PRONAF_MAX:
        code = "PRONAF"
    elif effective_rba <= _CURRENT_PRONAMP_MAX and agro >= _CURRENT_PRONAMP_AGRO_MIN:
        code = "PRONAMP"
    else:
        code = "OTHER"

    return ClassificationResult(group_code=code, rule_source="current_mcr")


# Re-export for callers that want the documented special-activity factor.
SPECIAL_ACTIVITY_VBP_FACTOR = _SPECIAL_ACTIVITY_VBP_FACTOR
