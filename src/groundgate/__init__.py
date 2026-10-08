"""Deterministic admission for LLM-extracted facts."""

from .admit import Verification, admit, verify
from .canonical import digest, jcs
from .model import (
    Decision,
    Field,
    Judgment,
    PacketError,
    Policy,
    Receipt,
    Schema,
    candidate_schema,
    extractor_schema,
)

__version__ = "0.5.0"

__all__ = [
    "Decision",
    "Field",
    "Judgment",
    "PacketError",
    "Policy",
    "Receipt",
    "Schema",
    "Verification",
    "__version__",
    "admit",
    "candidate_schema",
    "digest",
    "extractor_schema",
    "jcs",
    "verify",
]
