"""Tier 2 signal: activation relationship (blueprint Sec 6.1).

Base confidence 0.55, adjusted up for deliberate-activation signals and
capped low when the activator is a known high-volume activator (an
exchange or energy-rental service that has activated thousands of
unrelated accounts) -- documented in the blueprint as the #1
false-positive source for this signal, so the label whitelist check is
mandatory, not optional.
"""

from __future__ import annotations

from dataclasses import dataclass

BASE_CONFIDENCE = 0.55
REPEATED_FUNDING_BONUS = 0.20
DELIBERATE_ACTIVATION_BONUS = 0.10
LABELED_ACTIVATOR_CAP = 0.05


@dataclass
class ActivationLink:
    activator: str
    activated: str
    activation_tx: str
    confidence: float
    signals: list[dict]


def compute_activation_confidence(
    *,
    activator_is_labeled_service: bool,
    repeated_resource_funding: bool,
    via_account_create_contract: bool,
) -> tuple[float, list[dict]]:
    signals: list[dict] = [{"type": "activation_relationship", "weight": BASE_CONFIDENCE}]
    confidence = BASE_CONFIDENCE

    if repeated_resource_funding:
        confidence += REPEATED_FUNDING_BONUS
        signals.append({"type": "repeated_resource_funding", "weight": REPEATED_FUNDING_BONUS})

    if via_account_create_contract:
        confidence += DELIBERATE_ACTIVATION_BONUS
        signals.append({"type": "deliberate_account_create_contract", "weight": DELIBERATE_ACTIVATION_BONUS})

    if activator_is_labeled_service:
        confidence = min(confidence, LABELED_ACTIVATOR_CAP)
        signals.append({"type": "labeled_activator_cap_applied", "weight": None})

    return min(confidence, 1.0), signals


def build_activation_link(
    activator: str,
    activated: str,
    activation_tx: str,
    *,
    activator_is_labeled_service: bool,
    repeated_resource_funding: bool,
    via_account_create_contract: bool,
) -> ActivationLink:
    confidence, signals = compute_activation_confidence(
        activator_is_labeled_service=activator_is_labeled_service,
        repeated_resource_funding=repeated_resource_funding,
        via_account_create_contract=via_account_create_contract,
    )
    return ActivationLink(activator=activator, activated=activated, activation_tx=activation_tx,
                           confidence=confidence, signals=signals)
