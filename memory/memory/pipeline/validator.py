"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/pipeline/validator.py
Description: Deterministic validator — 6 dimensions, decision tree. v1: 2 trust levels.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from typing import Optional

from ..models.memory_entry import ExtractedFact, ValidatorResult
from ..models.memory_types import TrustLevel, ValidatorDecision
from .schema_enforcer import SchemaEnforcer

logger = logging.getLogger(__name__)

# Score weights (v1 simple)
TRUST_SCORES = {
    TrustLevel.TRUSTED: 1.0,
    TrustLevel.UNTRUSTED: 0.5,
}


class Validator:
    """
    Deterministic validator with 6 dimensions.

    Dimensions:
    - trust: Source reliability (trusted > untrusted)
    - explicitness: Explicit declaration vs inferred
    - stability: Likely to still be true tomorrow
    - future_utility: Useful in future conversations
    - novelty: New vs already known
    - contradiction_risk: Contradicts existing memory

    Decisions: reject, stage_only, promote_episodic, upsert_profile
    """

    def __init__(self, schema_enforcer: Optional[SchemaEnforcer] = None):
        self._schema = schema_enforcer or SchemaEnforcer()

    def validate(
        self,
        fact: ExtractedFact,
        trust_level: TrustLevel = TrustLevel.UNTRUSTED,
        existing_value: Optional[str] = None,
    ) -> ValidatorResult:
        """
        Validate an extracted fact and decide its destination.

        Args:
            fact: The extracted fact from the extractor
            trust_level: Trust level of the source
            existing_value: Current value in store (for novelty/contradiction)

        Returns:
            ValidatorResult with decision and scores
        """
        scores = self._compute_scores(fact, trust_level, existing_value)
        decision = self._decide(fact, scores, trust_level)

        return ValidatorResult(
            decision=decision,
            scores=scores,
            reason=self._explain(decision, scores),
            trust_level=trust_level,
        )

    def _compute_scores(
        self,
        fact: ExtractedFact,
        trust_level: TrustLevel,
        existing_value: Optional[str],
    ) -> dict:
        """Compute 6 dimension scores."""
        # Trust
        trust = TRUST_SCORES.get(trust_level, 0.5)

        # Explicitness: corrections and identity facts are explicit
        explicitness = 0.9 if fact.is_correction else (
            0.8 if "identity" in fact.tags else (
                0.6 if "preference" in fact.tags else 0.4
            )
        )

        # Stability: identity facts are stable, preferences moderate
        stability = 0.9 if fact.attribute in (
            "name", "birth_year", "nationality", "location_origin"
        ) else (
            0.7 if "identity" in fact.tags else (
                0.5 if "preference" in fact.tags else 0.4
            )
        )

        # Future utility: based on importance
        future_utility = fact.importance

        # Novelty: if we have existing value, check if different
        if existing_value is not None:
            if fact.value and fact.value.lower().strip() == existing_value.lower().strip():
                novelty = 0.1  # Same value, just a confirmation
            else:
                novelty = 0.9  # Different value, contradiction or update
        else:
            novelty = 0.8  # New information

        # Contradiction risk
        if existing_value is not None and fact.value:
            if fact.value.lower().strip() != existing_value.lower().strip():
                contradiction_risk = 0.8
                if fact.is_correction:
                    contradiction_risk = 0.3  # User explicitly correcting
            else:
                contradiction_risk = 0.0
        else:
            contradiction_risk = 0.0

        return {
            "trust": trust,
            "explicitness": explicitness,
            "stability": stability,
            "future_utility": future_utility,
            "novelty": novelty,
            "contradiction_risk": contradiction_risk,
        }

    def _decide(
        self,
        fact: ExtractedFact,
        scores: dict,
        trust_level: TrustLevel,
    ) -> ValidatorDecision:
        """Decision tree based on scores."""
        trust = scores["trust"]
        explicitness = scores["explicitness"]
        novelty = scores["novelty"]
        contradiction = scores["contradiction_risk"]
        future_utility = scores["future_utility"]

        # Very low novelty = already known, skip
        if novelty < 0.2:
            return ValidatorDecision.REJECT

        # High contradiction + untrusted = reject
        if contradiction > 0.7 and trust_level == TrustLevel.UNTRUSTED:
            return ValidatorDecision.STAGE_ONLY

        # Corrections always promoted (user explicitly correcting)
        if fact.is_correction and explicitness > 0.7:
            if fact.attribute:
                canonical, _ = self._schema.resolve(fact.attribute)
                if canonical:
                    return ValidatorDecision.UPSERT_PROFILE
            return ValidatorDecision.PROMOTE_EPISODIC

        # Profile-worthy: has schema attribute + explicit + trusted/important
        if fact.attribute:
            canonical, method = self._schema.resolve(fact.attribute)
            if canonical and method != "none":
                if trust >= 0.8 or explicitness >= 0.7:
                    return ValidatorDecision.UPSERT_PROFILE
                return ValidatorDecision.STAGE_ONLY

        # Episodic-worthy: decent scores
        composite = (
            trust * 0.25
            + explicitness * 0.20
            + future_utility * 0.25
            + novelty * 0.15
            + (1.0 - contradiction) * 0.15
        )

        if composite >= 0.55:
            return ValidatorDecision.PROMOTE_EPISODIC
        if composite >= 0.35:
            return ValidatorDecision.STAGE_ONLY
        return ValidatorDecision.REJECT

    @staticmethod
    def _explain(decision: ValidatorDecision, scores: dict) -> str:
        """Generate human-readable explanation."""
        top_factors = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
        factors_str = ", ".join(f"{k}={v:.2f}" for k, v in top_factors)
        return f"{decision.value}: {factors_str}"


__all__ = ["Validator", "ValidatorResult"]
