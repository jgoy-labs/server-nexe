"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/chunkers/tests/test_code_chunker.py
Description: No description available.

www.jgoy.net
────────────────────────────────────
"""

import pytest

from memory.embeddings.chunkers import CodeChunker, Chunk, ChunkingResult

class TestCodeChunkerBasic:
  """Tests bàsics del CodeChunker."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_empty_text(self):
    """Text buit retorna result buit."""
    result = self.chunker.chunk("")

    assert result.total_chunks == 0
    assert result.chunks == []
    assert result.original_length == 0

  def test_whitespace_only(self):
    """Només whitespace retorna result buit."""
    result = self.chunker.chunk("  \n\n\t ")

    assert result.total_chunks == 0

  def test_returns_chunking_result(self):
    """chunk() retorna ChunkingResult."""
    result = self.chunker.chunk("def foo(): pass")

    assert isinstance(result, ChunkingResult)
    assert result.chunker_id == "chunker.code"

  def test_chunks_are_chunk_instances(self):
    """Els chunks són instàncies de Chunk."""
    result = self.chunker.chunk("def foo(): pass")

    for chunk in result.chunks:
      assert isinstance(chunk, Chunk)

class TestPythonFunctions:
  """Tests per detecció de funcions Python."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_simple_function(self):
    """Detecta funció simple."""
    code = '''def hello():
  print("Hello")
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert "def hello" in chunk.text
    assert chunk.metadata.get("code_type") == "function"
    assert chunk.metadata.get("name") == "hello"

  def test_async_function(self):
    """Detecta funció async."""
    code = '''async def fetch_data():
  await something()
  return data
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert "async def fetch_data" in chunk.text
    assert chunk.metadata.get("code_type") == "function"

  def test_function_with_decorator(self):
    """Detecta funció amb decorador."""
    code = '''@decorator
def decorated():
  pass
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert "@decorator" in chunk.text
    assert "def decorated" in chunk.text

  def test_function_with_docstring(self):
    """Detecta funció amb docstring."""
    code = '''def documented():
  """Aquesta funció fa coses."""
  return 42
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert '"""Aquesta funció fa coses."""' in chunk.text

  def test_multiple_functions(self):
    """Detecta múltiples funcions com chunks separats."""
    code = '''def func1():
  pass

def func2():
  pass

def func3():
  pass
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks == 3

    names = [c.metadata.get("name") for c in result.chunks]
    assert "func1" in names
    assert "func2" in names
    assert "func3" in names

class TestPythonClasses:
  """Tests per detecció de classes Python."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_simple_class(self):
    """Detecta classe simple."""
    code = '''class MyClass:
  pass
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert "class MyClass" in chunk.text
    assert chunk.metadata.get("code_type") == "class"
    assert chunk.metadata.get("name") == "MyClass"

  def test_class_with_inheritance(self):
    """Detecta classe amb herència."""
    code = '''class Child(Parent):
  def __init__(self):
    super().__init__()
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert "class Child(Parent)" in chunk.text

  def test_class_with_decorator(self):
    """Detecta classe amb decorador."""
    code = '''@dataclass
class Data:
  name: str
  value: int
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert "@dataclass" in chunk.text
    assert "class Data" in chunk.text

  def test_class_includes_methods(self):
    """Classe inclou tots els mètodes."""
    code = '''class Calculator:
  def add(self, a, b):
    return a + b

  def subtract(self, a, b):
    return a - b
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert "def add" in chunk.text
    assert "def subtract" in chunk.text

class TestNoOverlap:
  """Tests per verificar NO overlap (Architectural decision)."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_no_overlap_between_functions(self):
    """NO hi ha overlap entre funcions."""
    code = '''def func1():
  line1 = 1
  line2 = 2
  return line1 + line2

def func2():
  x = 10
  y = 20
  return x * y
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks == 2

    func1_text = result.chunks[0].text
    func2_text = result.chunks[1].text

    assert "line1" not in func2_text
    assert "line2" not in func2_text

    assert "x = 10" not in func1_text
    assert "y = 20" not in func1_text

  def test_config_chunk_overlap_is_zero(self):
    """Config chunk_overlap és 0."""
    assert self.chunker.config["chunk_overlap"] == 0

class TestJavaScript:
  """Tests per detecció de JavaScript/TypeScript."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_javascript_function(self):
    """Detecta funció JavaScript."""
    code = '''function hello() {
  console.log("Hello");
}
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.js"})

    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert "function hello" in chunk.text
    assert chunk.metadata.get("code_type") == "function"

  def test_async_javascript_function(self):
    """Detecta funció async JavaScript."""
    code = '''async function fetchData() {
  const data = await fetch(url);
  return data;
}
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.js"})

    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert "async function fetchData" in chunk.text

  def test_arrow_function(self):
    """Detecta arrow function."""
    code = '''const add = (a, b) => {
  return a + b;
};
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.js"})

    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert "const add" in chunk.text
    assert chunk.metadata.get("code_type") == "arrow_function"

  def test_export_function(self):
    """Detecta export function."""
    code = '''export function exportedFunc() {
  return "exported";
}
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.js"})

    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert "export function exportedFunc" in chunk.text

  def test_javascript_class(self):
    """Detecta classe JavaScript."""
    code = '''class Component {
  constructor() {
    this.state = {};
  }

  render() {
    return null;
  }
}
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.js"})

    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert "class Component" in chunk.text
    assert chunk.metadata.get("code_type") == "class"

  def test_typescript_detection(self):
    """Detecta llenguatge TypeScript per extensió."""
    code = '''function typed(x: number): string {
  return x.toString();
}
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.ts"})

    assert result.metadata.get("language") == "typescript"

class TestLanguageDetection:
  """Tests per detecció de llenguatge."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_detect_python_by_extension(self):
    """Detecta Python per extensió."""
    result = self.chunker.chunk("def foo(): pass", metadata={"file_path": "test.py"})
    assert result.metadata.get("language") == "python"

  def test_detect_python_pyi(self):
    """Detecta Python stub files."""
    result = self.chunker.chunk("def foo(): ...", metadata={"file_path": "test.pyi"})
    assert result.metadata.get("language") == "python"

  def test_detect_javascript_by_extension(self):
    """Detecta JavaScript per extensió."""
    result = self.chunker.chunk("function f() {}", metadata={"file_path": "test.js"})
    assert result.metadata.get("language") == "javascript"

  def test_detect_jsx(self):
    """Detecta JSX."""
    result = self.chunker.chunk("function f() {}", metadata={"file_path": "test.jsx"})
    assert result.metadata.get("language") == "javascript"

  def test_detect_typescript_by_extension(self):
    """Detecta TypeScript per extensió."""
    result = self.chunker.chunk("function f() {}", metadata={"file_path": "test.ts"})
    assert result.metadata.get("language") == "typescript"

  def test_detect_tsx(self):
    """Detecta TSX."""
    result = self.chunker.chunk("function f() {}", metadata={"file_path": "test.tsx"})
    assert result.metadata.get("language") == "typescript"

  def test_unknown_language_fallback(self):
    """Llenguatge desconegut usa fallback."""
    result = self.chunker.chunk("some code", metadata={"file_path": "test.xyz"})
    assert result.metadata.get("language") == "unknown"

class TestFallbackChunking:
  """Tests per chunking fallback (indentació)."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_fallback_for_unknown_language(self):
    """Llengua desconeguda usa chunking per indentació."""
    code = '''block1
  indented content
  more content

block2
  other content
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.unknown"})

    assert result.total_chunks >= 1

class TestSupports:
  """Tests pel mètode supports()."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_supports_python_extension(self):
    """Suporta extensió Python."""
    assert self.chunker.supports(file_extension="py")
    assert self.chunker.supports(file_extension=".py")
    assert self.chunker.supports(file_extension="pyi")

  def test_supports_javascript_extension(self):
    """Suporta extensió JavaScript."""
    assert self.chunker.supports(file_extension="js")
    assert self.chunker.supports(file_extension="jsx")
    assert self.chunker.supports(file_extension="mjs")

  def test_supports_typescript_extension(self):
    """Suporta extensió TypeScript."""
    assert self.chunker.supports(file_extension="ts")
    assert self.chunker.supports(file_extension="tsx")

  def test_not_supports_text_extension(self):
    """No suporta extensió text."""
    assert not self.chunker.supports(file_extension="txt")
    assert not self.chunker.supports(file_extension="md")

  def test_supports_code_content_type(self):
    """Suporta content_type 'code'."""
    assert self.chunker.supports(content_type="code")
    assert self.chunker.supports(content_type="source")

  def test_not_supports_text_content_type(self):
    """No suporta content_type 'text'."""
    assert not self.chunker.supports(content_type="text")

class TestMetadata:
  """Tests per metadata del chunker."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_metadata_id(self):
    """Metadata té ID correcte."""
    assert self.chunker.metadata["id"] == "chunker.code"

  def test_metadata_formats(self):
    """Metadata té formats correctes."""
    formats = self.chunker.metadata["formats"]
    assert "py" in formats
    assert "js" in formats
    assert "ts" in formats

  def test_metadata_content_types(self):
    """Metadata té content_types correctes."""
    types = self.chunker.metadata["content_types"]
    assert "code" in types
    assert "source" in types

class TestImportsHandling:
  """Tests per handling d'imports."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_imports_included_with_first_function(self):
    """Imports s'inclouen amb la primera funció."""
    code = '''import os
from typing import Dict

def main():
  pass
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks >= 1
    first_chunk = result.chunks[0]

    assert "import os" in first_chunk.text
    assert "from typing import Dict" in first_chunk.text

  def test_can_disable_imports_inclusion(self):
    """Pot desactivar inclusió d'imports."""
    chunker = CodeChunker(include_imports=False)
    code = '''import os

def main():
  pass
'''
    result = chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks >= 1

class TestRealWorldCode:
  """Tests amb codi real."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_complex_python_module(self):
    """Chunk d'un mòdul Python complex."""
    code = '''"""Module docstring."""

import os
import sys
from typing import Dict, List, Optional

CONSTANT = 42

@dataclass
class Config:
  """Configuration class."""
  name: str
  value: int

def setup() -> None:
  """Setup function."""
  print("Setting up...")

async def fetch_data(url: str) -> Dict:
  """Fetch data from URL."""
  async with aiohttp.ClientSession() as session:
    async with session.get(url) as response:
      return await response.json()

class Processor:
  """Main processor class."""

  def __init__(self, config: Config):
    self.config = config

  def process(self, data: List) -> List:
    return [self._transform(item) for item in data]

  def _transform(self, item):
    return item * 2
'''
    result = self.chunker.chunk(code, metadata={"file_path": "module.py"})

    assert result.total_chunks >= 3

    types = [c.metadata.get("code_type") for c in result.chunks]
    assert "class" in types
    assert "function" in types

  def test_complex_javascript_module(self):
    """Chunk d'un mòdul JavaScript complex."""
    code = '''import { useState } from 'react';

const API_URL = 'https://api.example.com';

export async function fetchUser(id) {
  const response = await fetch(`${API_URL}/users/${id}`);
  return response.json();
}

class UserService {
  constructor(baseUrl) {
    this.baseUrl = baseUrl;
  }

  async getUser(id) {
    return fetchUser(id);
  }
}

const createHandler = (callback) => {
  return (event) => {
    event.preventDefault();
    callback(event.target.value);
  };
};

export default UserService;
'''
    result = self.chunker.chunk(code, metadata={"file_path": "service.js"})

    assert result.total_chunks >= 2