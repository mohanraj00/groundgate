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
from .pack import load_pack

__version__ = "0.9.0"

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
    "load_pack",
    "verify",
]
