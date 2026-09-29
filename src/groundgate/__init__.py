"""Deterministic admission for LLM-extracted facts."""

from .admit import Verification, admit, verify
from .canonical import digest, jcs
from .model import Decision, Field, PacketError, Policy, Receipt, Schema

__version__ = "0.0.1"

__all__ = [
    "Decision",
    "Field",
    "PacketError",
    "Policy",
    "Receipt",
    "Schema",
    "Verification",
    "__version__",
    "admit",
    "digest",
    "jcs",
    "verify",
]
