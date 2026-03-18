"""
────────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: memory/rag/header_parser.py
Description: Parser for standardized RAG document headers

www.jgoy.net · https://server-nexe.org
────────────────────────────────────────
"""

import os
import re
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# === CONSTANTS ===
HEADER_VERSION = "1.0"
HEADER_START = "# === METADATA RAG ==="
HEADER_END = "---"

VALID_PRIORITIES = ["P0", "P1", "P2", "P3"]
VALID_TYPES = ["docs", "tutorial", "api", "faq", "notes", "config", "other"]
VALID_LANGS = ["ca", "es", "en", "multi"]
DEFAULT_COLLECTIONS = ["nexe_web_ui", "user_knowledge", "system"]

# Chunk size limits
MIN_CHUNK_SIZE = 400
MAX_CHUNK_SIZE = 2000
DEFAULT_CHUNK_SIZE = 800

# Tags limits
MIN_TAGS = 1
MAX_TAGS = 15


@dataclass
class RAGHeader:
    """Standardized RAG header structure"""

    # Obligatoris
    versio: str = HEADER_VERSION
    data: str = ""
    id: str = ""
    abstract: str = ""
    tags: List[str] = field(default_factory=list)
    chunk_size: int = DEFAULT_CHUNK_SIZE
    priority: str = "P2"

    # Opcionals
    lang: str = field(default_factory=lambda: os.getenv("NEXE_LANG", "ca").split("-")[0].lower())
    type: str = "docs"
    collection: str = "user_knowledge"
    author: str = ""
    expires: Optional[str] = None
    related: List[str] = field(default_factory=list)

    # Metadades internes
    is_valid: bool = False
    validation_errors: List[str] = field(default_factory=list)
    raw_header: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for metadata"""
        return {
            "versio": self.versio,
            "data": self.data,
            "id": self.id,
            "abstract": self.abstract,
            "tags": self.tags,
            "chunk_size": self.chunk_size,
            "priority": self.priority,
            "lang": self.lang,
            "type": self.type,
            "collection": self.collection,
            "author": self.author,
            "expires": self.expires,
            "related": self.related
        }


class RAGHeaderParser:
    """
    Parser for standardized RAG document headers.

    Expected format:
    ```
    # === METADATA RAG ===
    versio: "1.0"
    data: 2025-12-29
    id: document-id-unic
    abstract: "Descripció breu del document"
    tags: [tag1, tag2, tag3]
    chunk_size: 800
    priority: P1
    lang: ca
    type: docs
    ---

    [Contingut del document...]
    ```
    """

    def __init__(self):
        self.errors = []

    def parse(self, content: str) -> Tuple[RAGHeader, str]:
        """
        Parses a document and extracts the RAG header.

        Args:
            content: Full document content

        Returns:
            Tuple[RAGHeader, str]: (parsed header, content without header)
        """
        self.errors = []
        header = RAGHeader()

        # Buscar capçalera
        header_text, body = self._extract_header(content)

        if not header_text:
            # No header found - return default values
            header.is_valid = False
            header.validation_errors = ["No RAG header found"]
            return header, content

        header.raw_header = header_text

        # Parsear camps
        parsed = self._parse_yaml_like(header_text)

        # Assignar camps obligatoris
        header.versio = str(parsed.get("versio", HEADER_VERSION)).strip('"\'')
        header.data = str(parsed.get("data", "")).strip('"\'')
        header.id = str(parsed.get("id", "")).strip('"\'')
        header.abstract = str(parsed.get("abstract", "")).strip('"\'')
        header.tags = self._parse_list(parsed.get("tags", []))
        header.chunk_size = self._parse_int(parsed.get("chunk_size"), DEFAULT_CHUNK_SIZE)
        header.priority = str(parsed.get("priority", "P2")).strip('"\'').upper()

        # Assignar camps opcionals
        _default_lang = os.getenv("NEXE_LANG", "ca").split("-")[0].lower()
        header.lang = str(parsed.get("lang", _default_lang)).strip('"\'').lower()
        header.type = str(parsed.get("type", "docs")).strip('"\'').lower()
        header.collection = str(parsed.get("collection", "user_knowledge")).strip('"\'')
        header.author = str(parsed.get("author", "")).strip('"\'')
        header.expires = parsed.get("expires")
        if header.expires:
            header.expires = str(header.expires).strip('"\'')
            if header.expires.lower() == "null":
                header.expires = None
        header.related = self._parse_list(parsed.get("related", []))

        # Validar
        header.validation_errors = self._validate(header)
        header.is_valid = len(header.validation_errors) == 0

        if header.validation_errors:
            logger.warning(f"Capçalera RAG amb errors: {header.validation_errors}")
        else:
            logger.info(f"Capçalera RAG vàlida: id={header.id}, priority={header.priority}")

        return header, body

    def _extract_header(self, content: str) -> Tuple[str, str]:
        """Extract header from content"""
        lines = content.split('\n')
        header_lines = []
        body_start = 0
        in_header = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Detectar inici de capçalera
            if "METADATA RAG" in stripped or stripped.startswith("versio:"):
                in_header = True
                if "METADATA RAG" not in stripped:
                    header_lines.append(line)
                continue

            # Detectar fi de capçalera
            if in_header and (stripped == "---" or stripped == ""):
                if stripped == "---":
                    body_start = i + 1
                else:
                    # Línia buida - comprovar si ve més capçalera (camp o comentari de secció)
                    if i + 1 < len(lines) and (
                        ":" in lines[i + 1] or lines[i + 1].strip().startswith('#')
                    ):
                        continue
                    body_start = i + 1
                break

            if in_header:
                header_lines.append(line)

        if not header_lines:
            return "", content

        header_text = '\n'.join(header_lines)
        body = '\n'.join(lines[body_start:]).strip()

        return header_text, body

    def _parse_yaml_like(self, text: str) -> Dict[str, Any]:
        """Parse simplified YAML format"""
        result = {}

        for line in text.split('\n'):
            line = line.strip()

            # Ignorar comentaris i línies buides
            if not line or line.startswith('#'):
                continue

            # Buscar key: value
            match = re.match(r'^(\w+):\s*(.*)$', line)
            if match:
                key = match.group(1).lower()
                value = match.group(2).strip()

                # Detectar llistes [item1, item2]
                if value.startswith('[') and value.endswith(']'):
                    # Parsejar llista
                    list_content = value[1:-1]
                    items = [item.strip().strip('"\'') for item in list_content.split(',')]
                    result[key] = [item for item in items if item]
                else:
                    result[key] = value

        return result

    def _parse_list(self, value: Any) -> List[str]:
        """Convert value to list"""
        if isinstance(value, list):
            return [str(v).strip() for v in value if v]
        if isinstance(value, str):
            if value.startswith('[') and value.endswith(']'):
                items = value[1:-1].split(',')
                return [item.strip().strip('"\'') for item in items if item.strip()]
            return [value] if value else []
        return []

    def _parse_int(self, value: Any, default: int) -> int:
        """Convert value to integer"""
        if value is None:
            return default
        try:
            return int(str(value).strip())
        except ValueError:
            return default

    def _validate(self, header: RAGHeader) -> List[str]:
        """Validate header fields"""
        errors = []

        # Camps obligatoris
        if not header.id:
            errors.append("Camp 'id' obligatori")

        if not header.abstract:
            errors.append("Camp 'abstract' obligatori")
        elif len(header.abstract) > 500:
            errors.append(f"'abstract' massa llarg ({len(header.abstract)}/500 chars)")

        if len(header.tags) < MIN_TAGS:
            errors.append(f"Mínim {MIN_TAGS} tags requerits")
        elif len(header.tags) > MAX_TAGS:
            errors.append(f"Màxim {MAX_TAGS} tags permesos")

        # Validar chunk_size
        if header.chunk_size < MIN_CHUNK_SIZE:
            errors.append(f"chunk_size mínim: {MIN_CHUNK_SIZE}")
        elif header.chunk_size > MAX_CHUNK_SIZE:
            errors.append(f"chunk_size màxim: {MAX_CHUNK_SIZE}")

        # Validar priority
        if header.priority not in VALID_PRIORITIES:
            errors.append(f"priority ha de ser: {', '.join(VALID_PRIORITIES)}")

        # Validar lang
        if header.lang not in VALID_LANGS:
            errors.append(f"lang ha de ser: {', '.join(VALID_LANGS)}")

        # Validar type
        if header.type not in VALID_TYPES:
            errors.append(f"type ha de ser: {', '.join(VALID_TYPES)}")

        # Validar data (format YYYY-MM-DD)
        if header.data:
            try:
                datetime.strptime(header.data, "%Y-%m-%d")
            except ValueError:
                errors.append("'data' ha de tenir format YYYY-MM-DD")

        # Validar expires si existeix
        if header.expires:
            try:
                datetime.strptime(header.expires, "%Y-%m-%d")
            except ValueError:
                errors.append("'expires' ha de tenir format YYYY-MM-DD o null")

        return errors

    def create_header(
        self,
        id: str,
        abstract: str,
        tags: List[str],
        priority: str = "P2",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        **kwargs
    ) -> str:
        """
        Create a formatted RAG header.

        Args:
            id: Unique document ID
            abstract: Brief description
            tags: List of tags
            priority: P0|P1|P2|P3
            chunk_size: Chunk size
            **kwargs: Optional fields (lang, type, collection, author, expires, related)

        Returns:
            str: Formatted header
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        header = f"""# === METADATA RAG ===
versio: "{HEADER_VERSION}"
data: {today}
id: {id}

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "{abstract[:500]}"
tags: [{', '.join(tags[:MAX_TAGS])}]
chunk_size: {chunk_size}
priority: {priority.upper()}
"""

        # Afegir camps opcionals
        optional_fields = []

        lang = kwargs.get('lang', 'ca')
        if lang:
            optional_fields.append(f"lang: {lang}")

        doc_type = kwargs.get('type', 'docs')
        if doc_type:
            optional_fields.append(f"type: {doc_type}")

        collection = kwargs.get('collection')
        if collection:
            optional_fields.append(f"collection: {collection}")

        author = kwargs.get('author')
        if author:
            optional_fields.append(f'author: "{author}"')

        expires = kwargs.get('expires')
        optional_fields.append(f"expires: {expires if expires else 'null'}")

        related = kwargs.get('related', [])
        if related:
            optional_fields.append(f"related: [{', '.join(related)}]")

        if optional_fields:
            header += "\n# === OPCIONAL ===\n"
            header += '\n'.join(optional_fields)

        header += "\n---\n"

        return header


# Instància global
_parser = RAGHeaderParser()


def parse_rag_header(content: str) -> Tuple[RAGHeader, str]:
    """Helper function to parse RAG header"""
    return _parser.parse(content)


def create_rag_header(**kwargs) -> str:
    """Helper function to create RAG header"""
    return _parser.create_header(**kwargs)


def get_parser() -> RAGHeaderParser:
    """Get parser instance"""
    return _parser


__all__ = [
    "RAGHeader",
    "RAGHeaderParser",
    "parse_rag_header",
    "create_rag_header",
    "get_parser",
    "VALID_PRIORITIES",
    "VALID_TYPES",
    "VALID_LANGS"
]
