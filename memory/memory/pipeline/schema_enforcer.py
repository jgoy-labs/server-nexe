"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/pipeline/schema_enforcer.py
Description: Profile schema enforcer — closed schema with alias mapping.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Closed schema: attribute -> {type, cardinality, merge, category, is_critical}
PROFILE_SCHEMA: Dict[str, Dict] = {
    # Identity
    "name": {"type": "string", "cardinality": "single", "merge": "replace", "category": "identity"},
    "birth_year": {"type": "int", "cardinality": "single", "merge": "replace", "category": "identity"},
    "birthday": {"type": "date", "cardinality": "single", "merge": "replace", "category": "identity"},
    "location": {"type": "string", "cardinality": "single", "merge": "replace", "category": "identity"},
    "location_origin": {"type": "string", "cardinality": "single", "merge": "replace", "category": "identity"},
    "nationality": {"type": "string", "cardinality": "single", "merge": "replace", "category": "identity"},
    "occupation": {"type": "string", "cardinality": "single", "merge": "replace", "category": "identity"},
    "company": {"type": "string", "cardinality": "single", "merge": "replace", "category": "identity"},
    "education": {"type": "string", "cardinality": "single", "merge": "replace", "category": "identity"},
    # Communication
    "preferred_language": {"type": "string", "cardinality": "single", "merge": "replace", "category": "communication"},
    "spoken_languages": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "communication"},
    "communication_style": {"type": "string", "cardinality": "single", "merge": "replace", "category": "communication"},
    "tone_preference": {"type": "string", "cardinality": "single", "merge": "replace", "category": "communication"},
    # Technical
    "tech_stack": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "technical"},
    "programming_languages": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "technical"},
    "tools": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "technical"},
    "os": {"type": "string", "cardinality": "single", "merge": "replace", "category": "technical"},
    "hardware": {"type": "string", "cardinality": "single", "merge": "replace", "category": "technical"},
    # Personal
    "pets": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "personal"},
    "family": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "personal"},
    "hobbies": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "personal"},
    "interests": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "personal"},
    "food_preferences": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "personal"},
    "allergies": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "personal", "is_critical": True},
    # Restrictions
    "constraints": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "restrictions"},
    "privacy_preferences": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "restrictions"},
    "topics_to_avoid": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "restrictions"},
    # Social
    "email": {"type": "string", "cardinality": "single", "merge": "replace", "category": "identity"},
    "website": {"type": "string", "cardinality": "single", "merge": "replace", "category": "identity"},
    "social_profiles": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "identity"},
    # Health
    "health_conditions": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "personal", "is_critical": True},
    "medications": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "personal", "is_critical": True},
    "dietary_restrictions": {"type": "list", "cardinality": "multi", "merge": "add_remove", "category": "personal"},
}

# Alias table: common alternative names -> canonical attribute
DEFAULT_ALIASES: Dict[str, str] = {
    # Catalan
    "nom": "name",
    "edat": "birth_year",
    "ciutat": "location",
    "poble": "location",
    "pais": "nationality",
    "feina": "occupation",
    "professio": "occupation",
    "treball": "occupation",
    "empresa": "company",
    "estudis": "education",
    "idioma": "preferred_language",
    "idiomes": "spoken_languages",
    "llengues": "spoken_languages",
    "mascota": "pets",
    "mascotes": "pets",
    "familia": "family",
    "aficions": "hobbies",
    "interessos": "interests",
    "alergies": "allergies",
    "al·lergies": "allergies",
    # Spanish
    "nombre": "name",
    "edad": "birth_year",
    "ciudad": "location",
    "localidad": "location",
    "pais": "nationality",
    "trabajo": "occupation",
    "profesion": "occupation",
    "programacion": "programming_languages",
    "herramientas": "tools",
    "mascotas": "pets",
    "alergias": "allergies",
    # English
    "age": "birth_year",
    "city": "location",
    "country": "nationality",
    "job": "occupation",
    "profession": "occupation",
    "work": "occupation",
    "languages": "spoken_languages",
    "lang": "preferred_language",
    "coding": "programming_languages",
    "tech": "tech_stack",
    "stack": "tech_stack",
    "hobby": "hobbies",
    "interest": "interests",
    "allergy": "allergies",
    "diet": "dietary_restrictions",
    "food": "food_preferences",
    "pet": "pets",
}


class SchemaEnforcer:
    """
    Enforces the closed profile schema.

    Resolution order: exact match -> alias match -> None (goes to episodic).
    """

    def __init__(self, extra_aliases: Optional[Dict[str, str]] = None):
        self._schema = dict(PROFILE_SCHEMA)
        self._aliases: Dict[str, str] = dict(DEFAULT_ALIASES)
        if extra_aliases:
            self._aliases.update(extra_aliases)

    def resolve(self, proposed_attribute: Optional[str]) -> Tuple[Optional[str], str]:
        """
        Resolve a proposed attribute to its canonical form.

        Returns:
            (canonical_attribute, resolution_method)
            resolution_method: "exact", "alias", or "none"
            If "none", attribute is None -> should go to episodic
        """
        if proposed_attribute is None:
            return None, "none"

        key = proposed_attribute.lower().strip()

        # Exact match
        if key in self._schema:
            return key, "exact"

        # Alias match
        if key in self._aliases:
            canonical = self._aliases[key]
            if canonical in self._schema:
                return canonical, "alias"

        return None, "none"

    def get_attribute_info(self, attribute: str) -> Optional[Dict]:
        """Get schema info for a canonical attribute."""
        return self._schema.get(attribute)

    def is_critical(self, attribute: str) -> bool:
        """Check if an attribute is critical (health, allergies, safety)."""
        info = self._schema.get(attribute)
        if info is None:
            return False
        return info.get("is_critical", False)

    def list_attributes(self) -> List[str]:
        """List all canonical attribute names."""
        return sorted(self._schema.keys())

    def list_categories(self) -> Dict[str, List[str]]:
        """Group attributes by category."""
        categories: Dict[str, List[str]] = {}
        for attr, info in self._schema.items():
            cat = info.get("category", "other")
            categories.setdefault(cat, []).append(attr)
        return categories

    def add_alias(self, raw_key: str, canonical: str) -> bool:
        """Add a new alias mapping. Returns False if canonical not in schema."""
        if canonical not in self._schema:
            return False
        self._aliases[raw_key.lower().strip()] = canonical
        return True


__all__ = [
    "SchemaEnforcer",
    "PROFILE_SCHEMA",
    "DEFAULT_ALIASES",
]
