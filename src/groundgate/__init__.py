"""Deterministic admission for LLM-extracted facts."""

from .admit import Verification, admit, verify
from .canonical import digest, jcs
from .feedback import feedback_message
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

__version__ = "0.6.1"

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
    "feedback_message",
    "jcs",
    "verify",
]
