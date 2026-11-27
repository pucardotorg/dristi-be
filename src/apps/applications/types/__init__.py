"""Application type specs (spec 0033 #3). Importing this package registers every type."""

from . import registry
from .bail import Bail
from .edit_litigant import EditLitigantDetails
from .hearing_reschedule import AdvanceHearing, PostponeHearing
from .others import AdditionOfWitness, PoaChange, ProductionOfDocuments, WarrantByHand
from .simple import (
    AbsentApplication,
    CaseSettlement,
    CaseTransfer,
    CaseWithdrawal,
    DelayCondonation,
    Generic,
    Objection,
    ReopenEvidence,
)

ALL_TYPES = (
    Bail,
    EditLitigantDetails,
    CaseSettlement,
    CaseTransfer,
    CaseWithdrawal,
    DelayCondonation,
    Generic,
    AdvanceHearing,
    PostponeHearing,
    PoaChange,
    ProductionOfDocuments,
    AdditionOfWitness,
    WarrantByHand,
    AbsentApplication,
    ReopenEvidence,
    Objection,
)

for _spec in ALL_TYPES:
    if registry.get(_spec.code) is None:
        registry.register(_spec())
