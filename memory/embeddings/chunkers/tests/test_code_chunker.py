"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/embeddings/chunkers/tests/test_code_chunker.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest

from memory.embeddings.chunkers import CodeChunker, Chunk, ChunkingResult

class TestCodeChunkerBasic:
  """Basic tests for CodeChunker."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_empty_text(self):
    """Empty text returns empty result."""
    result = self.chunker.chunk("")

    assert result.total_chunks == 0
    assert result.chunks == []
    assert result.original_length == 0

  def test_whitespace_only(self):
    """Whitespace only returns empty result."""
    result = self.chunker.chunk("  \n\n\t ")

    assert result.total_chunks == 0

  def test_returns_chunking_result(self):
    """chunk() returns ChunkingResult."""
    result = self.chunker.chunk("def foo(): pass")

    assert isinstance(result, ChunkingResult)
    assert result.chunker_id == "chunker.code"

  def test_chunks_are_chunk_instances(self):
    """Chunks are instances of Chunk."""
    result = self.chunker.chunk("def foo(): pass")

    for chunk in result.chunks:
      assert isinstance(chunk, Chunk)

class TestPythonFunctions:
  """Tests for Python function detection."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_simple_function(self):
    """Detects simple function."""
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
    """Detects async function."""
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
    """Detects function with decorator."""
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
    """Detects function with docstring."""
    code = '''def documented():
  """Aquesta funció fa coses."""
  return 42
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert '"""Aquesta funció fa coses."""' in chunk.text

  def test_multiple_functions(self):
    """Detects multiple functions as separate chunks."""
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
  """Tests for Python class detection."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_simple_class(self):
    """Detects simple class."""
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
    """Detects class with inheritance."""
    code = '''class Child(Parent):
  def __init__(self):
    super().__init__()
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert "class Child(Parent)" in chunk.text

  def test_class_with_decorator(self):
    """Detects class with decorator."""
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
    """Class includes all methods."""
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
  """Tests to verify NO overlap (Architectural decision)."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_no_overlap_between_functions(self):
    """There is NO overlap between functions."""
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
    """Config chunk_overlap is 0."""
    assert self.chunker.config["chunk_overlap"] == 0

class TestJavaScript:
  """Tests for JavaScript/TypeScript detection."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_javascript_function(self):
    """Detects JavaScript function."""
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
    """Detects async JavaScript function."""
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
    """Detects arrow function."""
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
    """Detects export function."""
    code = '''export function exportedFunc() {
  return "exported";
}
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.js"})

    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert "export function exportedFunc" in chunk.text

  def test_javascript_class(self):
    """Detects JavaScript class."""
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
    """Detects TypeScript language by extension."""
    code = '''function typed(x: number): string {
  return x.toString();
}
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.ts"})

    assert result.metadata.get("language") == "typescript"

class TestLanguageDetection:
  """Tests for language detection."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_detect_python_by_extension(self):
    """Detects Python by extension."""
    result = self.chunker.chunk("def foo(): pass", metadata={"file_path": "test.py"})
    assert result.metadata.get("language") == "python"

  def test_detect_python_pyi(self):
    """Detects Python stub files."""
    result = self.chunker.chunk("def foo(): ...", metadata={"file_path": "test.pyi"})
    assert result.metadata.get("language") == "python"

  def test_detect_javascript_by_extension(self):
    """Detects JavaScript by extension."""
    result = self.chunker.chunk("function f() {}", metadata={"file_path": "test.js"})
    assert result.metadata.get("language") == "javascript"

  def test_detect_jsx(self):
    """Detects JSX."""
    result = self.chunker.chunk("function f() {}", metadata={"file_path": "test.jsx"})
    assert result.metadata.get("language") == "javascript"

  def test_detect_typescript_by_extension(self):
    """Detects TypeScript by extension."""
    result = self.chunker.chunk("function f() {}", metadata={"file_path": "test.ts"})
    assert result.metadata.get("language") == "typescript"

  def test_detect_tsx(self):
    """Detects TSX."""
    result = self.chunker.chunk("function f() {}", metadata={"file_path": "test.tsx"})
    assert result.metadata.get("language") == "typescript"

  def test_unknown_language_fallback(self):
    """Unknown language uses fallback."""
    result = self.chunker.chunk("some code", metadata={"file_path": "test.xyz"})
    assert result.metadata.get("language") == "unknown"

class TestFallbackChunking:
  """Tests for fallback chunking (indentation)."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_fallback_for_unknown_language(self):
    """Unknown language uses indentation-based chunking."""
    code = '''block1
  indented content
  more content

block2
  other content
'''
    result = self.chunker.chunk(code, metadata={"file_path": "test.unknown"})

    assert result.total_chunks >= 1

class TestSupports:
  """Tests for the supports() method."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_supports_python_extension(self):
    """Supports Python extension."""
    assert self.chunker.supports(file_extension="py")
    assert self.chunker.supports(file_extension=".py")
    assert self.chunker.supports(file_extension="pyi")

  def test_supports_javascript_extension(self):
    """Supports JavaScript extension."""
    assert self.chunker.supports(file_extension="js")
    assert self.chunker.supports(file_extension="jsx")
    assert self.chunker.supports(file_extension="mjs")

  def test_supports_typescript_extension(self):
    """Supports TypeScript extension."""
    assert self.chunker.supports(file_extension="ts")
    assert self.chunker.supports(file_extension="tsx")

  def test_not_supports_text_extension(self):
    """Does not support text extension."""
    assert not self.chunker.supports(file_extension="txt")
    assert not self.chunker.supports(file_extension="md")

  def test_supports_code_content_type(self):
    """Supports content_type 'code'."""
    assert self.chunker.supports(content_type="code")
    assert self.chunker.supports(content_type="source")

  def test_not_supports_text_content_type(self):
    """Does not support content_type 'text'."""
    assert not self.chunker.supports(content_type="text")

class TestMetadata:
  """Tests for chunker metadata."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_metadata_id(self):
    """Metadata has correct ID."""
    assert self.chunker.metadata["id"] == "chunker.code"

  def test_metadata_formats(self):
    """Metadata has correct formats."""
    formats = self.chunker.metadata["formats"]
    assert "py" in formats
    assert "js" in formats
    assert "ts" in formats

  def test_metadata_content_types(self):
    """Metadata has correct content_types."""
    types = self.chunker.metadata["content_types"]
    assert "code" in types
    assert "source" in types

class TestImportsHandling:
  """Tests for imports handling."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_imports_included_with_first_function(self):
    """Imports are included with the first function."""
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
    """Can disable import inclusion."""
    chunker = CodeChunker(include_imports=False)
    code = '''import os

def main():
  pass
'''
    result = chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks >= 1

class TestRealWorldCode:
  """Tests with real-world code."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_complex_python_module(self):
    """Chunk of a complex Python module."""
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
    """Chunk of a complex JavaScript module."""
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