"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/chunkers/code_chunker.py
Description: No description available.

www.jgoy.net
────────────────────────────────────
"""

import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseChunker, Chunk, ChunkingResult

class CodeChunker(BaseChunker):
  """
  Chunker per codi font que respecta estructures.

  IMPORTANT (Architectural decision):
  - NO overlap en codi: funcions/classes són unitats atòmiques
  - Regex primer: AST només si regex falla en casos reals

  Estratègia:
  - Detecta funcions i classes completes
  - Inclou decoradors i docstrings
  - Metadata amb nom funció/classe i tipus
  - Fallback a chunks per indentació per llenguatges desconeguts

  Example:
    chunker = CodeChunker()
    result = chunker.chunk(python_code, metadata={'file_path': 'module.py'})
    for chunk in result.chunks:
      print(f"{chunk.metadata['code_type']}: {chunk.metadata['name']}")
  """

  metadata: Dict[str, Any] = {
    "id": "chunker.code",
    "name": "Code Chunker",
    "description": "Smart chunking for source code preserving functions/classes",
    "category": "code",
    "version": "1.0.0",
    "formats": ["py", "pyi", "pyx", "js", "jsx", "ts", "tsx", "mjs"],
    "content_types": ["code", "source", "script"],
  }

  default_config: Dict[str, Any] = {
    "max_chunk_size": 3000,
    "chunk_overlap": 0,
    "min_chunk_size": 20,
    "include_imports": True,
  }

  PYTHON_FUNCTION = re.compile(r"^(async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)
  PYTHON_CLASS = re.compile(r"^class\s+(\w+)\s*[:\(]", re.MULTILINE)
  PYTHON_DECORATOR = re.compile(r"^@[\w\.]+", re.MULTILINE)

  JS_FUNCTION = re.compile(r"^(async\s+)?function\s+(\w+)\s*\(", re.MULTILINE)
  JS_CLASS = re.compile(r"^class\s+(\w+)", re.MULTILINE)
  JS_ARROW = re.compile(
    r"^(export\s+)?(const|let|var)\s+(\w+)\s*=\s*(async\s+)?\([^)]*\)\s*=>",
    re.MULTILINE,
  )
  JS_EXPORT_FUNCTION = re.compile(
    r"^export\s+(async\s+)?function\s+(\w+)\s*\(", re.MULTILINE
  )

  def chunk(
    self,
    text: str,
    document_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
  ) -> ChunkingResult:
    """
    Chunk codi font preservant funcions i classes completes.

    Args:
      text: Codi font a chunkejar
      document_id: ID opcional del document
      metadata: Metadata amb file_path per detectar llenguatge

    Returns:
      ChunkingResult amb chunks atòmics (funcions/classes)
    """
    if not text or not text.strip():
      return ChunkingResult(
        document_id=document_id,
        chunks=[],
        total_chunks=0,
        original_length=0,
        chunker_id=self.metadata["id"],
      )

    doc_id = document_id or str(uuid.uuid4())
    meta = metadata or {}
    original_length = len(text)

    language = meta.get("language") or self._detect_language(
      meta.get("file_path", "")
    )

    if language == "python":
      raw_chunks = self._chunk_python(text)
    elif language in ("javascript", "typescript"):
      raw_chunks = self._chunk_javascript(text)
    else:
      raw_chunks = self._chunk_by_indentation(text)

    chunks: List[Chunk] = []
    for idx, (chunk_text, chunk_meta) in enumerate(raw_chunks):
      start = text.find(chunk_text)
      if start == -1:
        start = 0

      chunk = Chunk.create(
        text=chunk_text,
        start=start,
        end=start + len(chunk_text),
        index=idx,
        document_id=doc_id,
        chunk_type=chunk_meta.get("type", "code"),
        language=language,
        metadata={
          **meta,
          "name": chunk_meta.get("name"),
          "code_type": chunk_meta.get("type"),
        },
      )
      chunks.append(chunk)

    return ChunkingResult(
      document_id=doc_id,
      chunks=chunks,
      total_chunks=len(chunks),
      original_length=original_length,
      chunker_id=self.metadata["id"],
      metadata={"language": language},
    )

  def supports(
    self, file_extension: Optional[str] = None, content_type: Optional[str] = None
  ) -> bool:
    """Indica si suporta el format/tipus."""
    if file_extension:
      ext = file_extension.lower().lstrip(".")
      return ext in self.metadata["formats"]
    if content_type:
      return content_type.lower() in self.metadata["content_types"]
    return False

  def _detect_language(self, file_path: str) -> str:
    """Detecta llenguatge per extensió de fitxer."""
    if not file_path or "." not in file_path:
      return "unknown"

    ext = file_path.split(".")[-1].lower()

    if ext in ("py", "pyi", "pyx", "pxd"):
      return "python"
    elif ext in ("js", "jsx", "mjs"):
      return "javascript"
    elif ext in ("ts", "tsx"):
      return "typescript"

    return "unknown"

  def _chunk_python(self, text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Chunk codi Python per funcions i classes.

    Detecta:
    - Funcions (def, async def) amb decoradors
    - Classes amb decoradors
    - Imports (opcionals al primer chunk)
    """
    chunks: List[Tuple[str, Dict[str, Any]]] = []
    lines = text.split("\n")

    imports: List[str] = []
    code_start = 0

    for i, line in enumerate(lines):
      stripped = line.strip()
      if stripped.startswith(("import ", "from ")):
        imports.append(line)
        code_start = i + 1
      elif stripped and not stripped.startswith("#"):
        break

    definitions: List[Tuple[str, Dict[str, Any]]] = []
    i = code_start

    while i < len(lines):
      line = lines[i]
      stripped = line.strip()

      if not stripped or stripped.startswith("#"):
        i += 1
        continue

      decorators: List[str] = []
      while stripped.startswith("@"):
        decorators.append(line)
        i += 1
        if i >= len(lines):
          break
        line = lines[i]
        stripped = line.strip()

      if not line.startswith((" ", "\t")):
        match_func = self.PYTHON_FUNCTION.match(stripped)
        match_class = self.PYTHON_CLASS.match(stripped)

        if match_func or match_class:
          definition_lines = decorators + [line]
          j = i + 1

          while j < len(lines):
            next_line = lines[j]
            next_stripped = next_line.strip()

            if not next_stripped:
              definition_lines.append(next_line)
              j += 1
              continue

            if not next_line.startswith((" ", "\t")):
              break

            definition_lines.append(next_line)
            j += 1

          chunk_text = "\n".join(definition_lines).rstrip()

          if match_func:
            name = match_func.group(2)
            chunk_type = "function"
          else:
            name = match_class.group(1)
            chunk_type = "class"

          definitions.append((chunk_text, {"name": name, "type": chunk_type}))
          i = j
          continue

      i += 1

    if not definitions:
      return [(text, {"name": "module", "type": "module"})]

    if imports and self.config["include_imports"] and definitions:
      import_text = "\n".join(imports) + "\n\n"
      first_text, first_meta = definitions[0]
      definitions[0] = (import_text + first_text, first_meta)

    return definitions

  def _chunk_javascript(self, text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Chunk codi JavaScript/TypeScript.

    Detecta:
    - function (async function)
    - class
    - Arrow functions (const/let/var x = () => {})
    - export function
    """
    chunks: List[Tuple[str, Dict[str, Any]]] = []
    lines = text.split("\n")
    i = 0

    while i < len(lines):
      line = lines[i]
      stripped = line.strip()

      if not stripped:
        i += 1
        continue

      is_func = self.JS_FUNCTION.match(stripped)
      is_export_func = self.JS_EXPORT_FUNCTION.match(stripped)
      is_class = self.JS_CLASS.match(stripped)
      is_arrow = self.JS_ARROW.match(stripped)

      if is_func or is_export_func or is_class or is_arrow:
        brace_count = stripped.count("{") - stripped.count("}")
        definition_lines = [line]
        j = i + 1

        while j < len(lines) and brace_count > 0:
          next_line = lines[j]
          brace_count += next_line.count("{") - next_line.count("}")
          definition_lines.append(next_line)
          j += 1

        chunk_text = "\n".join(definition_lines)

        if is_func:
          name = is_func.group(2)
          chunk_type = "function"
        elif is_export_func:
          name = is_export_func.group(2)
          chunk_type = "function"
        elif is_class:
          name = is_class.group(1)
          chunk_type = "class"
        else:
          name = is_arrow.group(3)
          chunk_type = "arrow_function"

        chunks.append((chunk_text, {"name": name, "type": chunk_type}))
        i = j
      else:
        i += 1

    if not chunks:
      return [(text, {"name": "module", "type": "module"})]

    return chunks

  def _chunk_by_indentation(self, text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Fallback: chunk per blocs d'indentació.

    Per llenguatges no suportats, separa per blocs a nivell 0.
    """
    lines = text.split("\n")
    chunks: List[Tuple[str, Dict[str, Any]]] = []
    current_block: List[str] = []

    for line in lines:
      if line.strip() and not line.startswith((" ", "\t")) and current_block:
        chunk_text = "\n".join(current_block).strip()
        if chunk_text:
          chunks.append((chunk_text, {"name": "block", "type": "block"}))
        current_block = [line]
      else:
        current_block.append(line)

    if current_block:
      chunk_text = "\n".join(current_block).strip()
      if chunk_text:
        chunks.append((chunk_text, {"name": "block", "type": "block"}))

    if not chunks:
      return [(text, {"name": "module", "type": "module"})]

    return chunks