"""Pure Decimal calculation engine (no Django)."""

from acelera_agro.engine.capacity import compute_payment_capacity
from acelera_agro.engine.classification import (
    SPECIAL_ACTIVITY_VBP_FACTOR,
    classify_producer_current_rule,
    classify_producer_spreadsheet_rule,
)
from acelera_agro.engine.debt import amortize_existing_debts
from acelera_agro.engine.schedule import build_proposal_schedule
from acelera_agro.engine.types import (
    CapacityYearInput,
    CapacityYearResult,
    ClassificationInput,
    ClassificationResult,
    DebtInput,
    ProposalScheduleInput,
    YearPayment,
    round_money,
)

__all__ = [
    "CapacityYearInput",
    "CapacityYearResult",
    "ClassificationInput",
    "ClassificationResult",
    "DebtInput",
    "ProposalScheduleInput",
    "SPECIAL_ACTIVITY_VBP_FACTOR",
    "YearPayment",
    "amortize_existing_debts",
    "build_proposal_schedule",
    "classify_producer_current_rule",
    "classify_producer_spreadsheet_rule",
    "compute_payment_capacity",
    "round_money",
]
