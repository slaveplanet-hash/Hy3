"""Skill capability loader — extension point.

Learned and promoted skills (plan §12) register here as ``Capability`` objects with
``kind=SKILL`` and ``provenance="learned:<skill_id>"``. The skill library is empty
until the skill-learning pipeline runs, so this returns ``[]`` for now. The
registry contract is unchanged when skills start arriving.
"""
from __future__ import annotations

from ..capability import Capability


def load() -> list[Capability]:
    """No promoted skills yet; return an empty set."""
    return []
