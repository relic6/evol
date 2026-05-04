"""Anchor lifecycle: parsing, hashing, drift detection.

Anchors are EVOL's immutable value constraints. Their **hash** is the
identity used to detect when the user has edited ``evol.config.yaml`` —
SDK MUST react by snapshotting Memory before continuing (CONTRACT §13 A-4,
DATA-MODEL §8.3).
"""

from __future__ import annotations

import hashlib

from evol.config.schema import AnchorConfig
from evol.core.time_utils import utc_now_iso
from evol.core.types import Anchor


def compute_rule_hash(rule: str) -> str:
    """Compute the canonical sha256 hash of an anchor rule body.

    Rule bodies are hashed as UTF-8 with no normalization beyond stripping
    leading/trailing whitespace — this matches the substring-equivalence the
    user would intuit when editing the config file by hand.
    """
    body = rule.strip().encode("utf-8")
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


def parse_anchors(
    configs: list[AnchorConfig], *, activated_at: str | None = None
) -> list[Anchor]:
    """Convert config-form anchors to runtime ``Anchor`` objects.

    Args:
        configs: list of :class:`AnchorConfig` from a validated :class:`Config`.
        activated_at: optional override for the activation timestamp (mainly
            useful in tests). Defaults to ``utc_now_iso()`` when omitted.
    """
    ts = activated_at or utc_now_iso()
    return [
        Anchor(
            index=i,
            description=ac.description,
            kind=ac.kind,
            rule=ac.rule,
            rule_hash=compute_rule_hash(ac.rule),
            activated_at=ts,
            deactivated_at=None,
        )
        for i, ac in enumerate(configs)
    ]


def detect_anchor_drift(
    current: list[Anchor],
    stored: list[Anchor],
) -> list[int]:
    """Return indices where current and stored anchors differ.

    "Differ" is defined by ``rule_hash`` — the rule body is canonical, so a
    hash change means a meaningful change. Length differences are also
    reported (positions present in one list but not the other are flagged).

    Args:
        current: anchors freshly parsed from ``evol.config.yaml``.
        stored: anchors recorded in the runtime ``manifest.yaml``.

    Returns:
        Indices of drifted anchors. Empty list iff everything matches.
    """
    drift: list[int] = []
    for i in range(max(len(current), len(stored))):
        cur = current[i] if i < len(current) else None
        sto = stored[i] if i < len(stored) else None
        if cur is None or sto is None:
            drift.append(i)
            continue
        if cur.rule_hash != sto.rule_hash:
            drift.append(i)
    return drift


__all__ = ["compute_rule_hash", "detect_anchor_drift", "parse_anchors"]
