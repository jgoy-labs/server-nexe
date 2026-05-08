"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/tests/unit/test_ollama_node.py
Description: Unit tests for OllamaNode. Validates integration with Ollama API, prompt handling, response parsing and error cases.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from unittest.mock import patch, MagicMock

# Skip if the path is not correct
try:
  from plugins.ollama_module.workflow.nodes.ollama_node import OllamaNode
except ImportError:
  pytest.skip("OllamaNode not available", allow_module_level=True)

@pytest.fixture
def ollama_node():
  """Create OllamaNode instance."""
  return OllamaNode()

@pytest.fixture
def mock_ollama_response():
  """Mock successful Ollama API response."""
  return {
    "model": "llama3.2",
    "response": "The answer is 4.",
    "done": True
  }

class TestOllamaNodeMetadata:
  """Test OllamaNode metadata."""

  def test_get_metadata(self, ollama_node):
    """Test metadata structure."""
    metadata = ollama_node.get_metadata()

    assert metadata.id == "ollama.chat"
    assert metadata.name == "Ollama Chat"
    assert metadata.version == "1.0.0"
    assert metadata.category == "llm"
    assert metadata.icon == "🤖"

  def test_metadata_inputs(self, ollama_node):
    """Test input definitions."""
    metadata = ollama_node.get_metadata()

    input_names = [inp.name for inp in metadata.inputs]
    assert "prompt" in input_names
    assert "model" in input_names
    assert "temperature" in input_names
    assert "max_tokens" in input_names
    assert "system" in input_names

    prompt_input = next(inp for inp in metadata.inputs if inp.name == "prompt")
    assert prompt_input.required is True

    model_input = next(inp for inp in metadata.inputs if inp.name == "model")
    assert model_input.default == "llama3.2"

    temp_input = next(inp for inp in metadata.inputs if inp.name == "temperature")
    assert temp_input.default == 0.7

  def test_metadata_outputs(self, ollama_node):
    """Test output definitions."""
    metadata = ollama_node.get_metadata()

    output_names = [out.name for out in metadata.outputs]
    assert "response" in output_names
    assert "model_used" in output_names
    assert "tokens" in output_names

class TestOllamaNodeExecution:
  """Test OllamaNode execution."""

  @pytest.mark.asyncio
  async def test_execute_simple_prompt(self, ollama_node, mock_ollama_response):
    """Test simple prompt execution."""
    with patch("httpx.AsyncClient.post") as mock_post:
      mock_resp = MagicMock()
      mock_resp.json.return_value = mock_ollama_response
      mock_resp.raise_for_status = MagicMock()
      mock_post.return_value = mock_resp

      result = await ollama_node.execute({
        "prompt": "What is 2+2?"
      })

      assert result["response"] == "The answer is 4."
      assert result["model_used"] == "llama3.2"
      assert "tokens" in result
      assert isinstance(result["tokens"], int)

  @pytest.mark.asyncio
  async def test_execute_with_model(self, ollama_node):
    """Test execution with custom model."""
    with patch("httpx.AsyncClient.post") as mock_post:
      mock_resp = MagicMock()
      mock_resp.json.return_value = {
        "model": "mistral",
        "response": "Test response",
        "done": True
      }
      mock_resp.raise_for_status = MagicMock()
      mock_post.return_value = mock_resp

      result = await ollama_node.execute({
        "prompt": "Test prompt",
        "model": "mistral"
      })

      assert result["model_used"] == "mistral"
      assert result["response"] == "Test response"

  @pytest.mark.asyncio
  async def test_execute_with_temperature(self, ollama_node):
    """Test execution with custom temperature."""
    with patch("httpx.AsyncClient.post") as mock_post:
      mock_resp = MagicMock()
      mock_resp.json.return_value = {"response": "Test", "done": True}
      mock_resp.raise_for_status = MagicMock()
      mock_post.return_value = mock_resp

      await ollama_node.execute({
        "prompt": "Test",
        "temperature": 1.5
      })

      call_args = mock_post.call_args
      payload = call_args[1]["json"]
      assert payload["options"]["temperature"] == 1.5

  @pytest.mark.asyncio
  async def test_execute_with_max_tokens(self, ollama_node):
    """Test execution with max_tokens limit."""
    with patch("httpx.AsyncClient.post") as mock_post:
      mock_resp = MagicMock()
      mock_resp.json.return_value = {"response": "Short", "done": True}
      mock_resp.raise_for_status = MagicMock()
      mock_post.return_value = mock_resp

      await ollama_node.execute({
        "prompt": "Test",
        "max_tokens": 50
      })

      call_args = mock_post.call_args
      payload = call_args[1]["json"]
      assert payload["options"]["num_predict"] == 50

  @pytest.mark.asyncio
  async def test_execute_with_system_prompt(self, ollama_node):
    """Test execution with system prompt."""
    with patch("httpx.AsyncClient.post") as mock_post:
      mock_resp = MagicMock()
      mock_resp.json.return_value = {"response": "Formal response", "done": True}
      mock_resp.raise_for_status = MagicMock()
      mock_post.return_value = mock_resp

      await ollama_node.execute({
        "prompt": "Hello",
        "system": "You are a formal assistant"
      })

      call_args = mock_post.call_args
      payload = call_args[1]["json"]
      assert payload["system"] == "You are a formal assistant"

class TestOllamaNodeErrors:
  """Test OllamaNode error handling."""

  @pytest.mark.asyncio
  async def test_empty_prompt_error(self, ollama_node):
    """Test error on empty prompt."""
    with pytest.raises(ValueError, match="Prompt cannot be empty"):
      await ollama_node.execute({"prompt": ""})

    with pytest.raises(ValueError, match="Prompt cannot be empty"):
      await ollama_node.execute({"prompt": "  "})

  @pytest.mark.asyncio
  async def test_missing_prompt_error(self, ollama_node):
    """Test error on missing prompt."""
    with pytest.raises(ValueError, match="Missing required input"):
      await ollama_node.execute({})

  @pytest.mark.asyncio
  async def test_ollama_not_running(self, ollama_node):
    """Test error when Ollama is not running."""
    with patch("httpx.AsyncClient.post") as mock_post:
      import httpx
      mock_post.side_effect = httpx.ConnectError("Connection refused")

      with pytest.raises(ConnectionError, match="Cannot connect to Ollama"):
        await ollama_node.execute({"prompt": "Test"})

  @pytest.mark.asyncio
  async def test_model_not_found(self, ollama_node):
    """Test error when model doesn't exist."""
    with patch("httpx.AsyncClient.post") as mock_post:
      import httpx
      mock_resp = MagicMock()
      mock_resp.status_code = 404
      mock_post.side_effect = httpx.HTTPStatusError(
        "Not found",
        request=MagicMock(),
        response=mock_resp
      )

      with pytest.raises(ValueError, match="Model .* not in allowlist"):
        await ollama_node.execute({
          "prompt": "Test",
          "model": "nonexistent"
        })

  @pytest.mark.asyncio
  async def test_ollama_timeout(self, ollama_node):
    """Test timeout handling."""
    with patch("httpx.AsyncClient.post") as mock_post:
      import httpx
      mock_post.side_effect = httpx.TimeoutException("Timeout")

      with pytest.raises(TimeoutError, match="timed out"):
        await ollama_node.execute({"prompt": "Test"})

class TestOllamaNodeTokenCounting:
  """Test token counting approximation."""

  @pytest.mark.asyncio
  async def test_token_approximation_short_text(self, ollama_node):
    """Test token counting for short text."""
    with patch("httpx.AsyncClient.post") as mock_post:
      mock_resp = MagicMock()
      mock_resp.json.return_value = {
        "response": "Hello world",
        "done": True
      }
      mock_resp.raise_for_status = MagicMock()
      mock_post.return_value = mock_resp

      result = await ollama_node.execute({"prompt": "Test"})

      assert result["tokens"] == 2

  @pytest.mark.asyncio
  async def test_token_approximation_long_text(self, ollama_node):
    """Test token counting for longer text."""
    with patch("httpx.AsyncClient.post") as mock_post:
      mock_resp = MagicMock()
      long_text = " ".join(["word"] * 10)
      mock_resp.json.return_value = {
        "response": long_text,
        "done": True
      }
      mock_resp.raise_for_status = MagicMock()
      mock_post.return_value = mock_resp

      result = await ollama_node.execute({"prompt": "Test"})

      assert result["tokens"] == 13


class TestBuildPayload:
  """Test OllamaNode._build_payload."""

  def test_build_payload_minimal(self, ollama_node):
    """Minimal payload without system or max_tokens."""
    payload = ollama_node._build_payload("hello", "llama3.2", 0.7, None, None, False)
    assert payload["model"] == "llama3.2"
    assert payload["prompt"] == "hello"
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0.7
    assert "system" not in payload
    assert "num_predict" not in payload["options"]

  def test_build_payload_with_system(self, ollama_node):
    """Payload includes system when provided."""
    payload = ollama_node._build_payload("hello", "llama3.2", 0.7, None, "You are helpful", False)
    assert payload["system"] == "You are helpful"

  def test_build_payload_without_system(self, ollama_node):
    """Payload excludes system key when not provided."""
    payload = ollama_node._build_payload("hello", "llama3.2", 0.7, None, None, False)
    assert "system" not in payload

  def test_build_payload_with_max_tokens(self, ollama_node):
    """Payload includes num_predict when max_tokens provided."""
    payload = ollama_node._build_payload("hello", "llama3.2", 0.7, 100, None, False)
    assert payload["options"]["num_predict"] == 100

  def test_build_payload_without_max_tokens(self, ollama_node):
    """Payload excludes num_predict when max_tokens not provided."""
    payload = ollama_node._build_payload("hello", "llama3.2", 0.7, None, None, False)
    assert "num_predict" not in payload["options"]

  def test_build_payload_streaming_true(self, ollama_node):
    """Payload stream=True when streaming enabled."""
    payload = ollama_node._build_payload("hello", "llama3.2", 0.7, None, None, True)
    assert payload["stream"] is True

  def test_build_payload_streaming_false(self, ollama_node):
    """Payload stream=False when streaming disabled."""
    payload = ollama_node._build_payload("hello", "llama3.2", 0.7, None, None, False)
    assert payload["stream"] is False


class TestExecuteBlocking:
  """Test OllamaNode._execute_blocking."""

  @pytest.mark.asyncio
  async def test_execute_blocking_success(self, ollama_node):
    """Blocking execution returns (text, token_count) on success."""
    with patch("httpx.AsyncClient.post") as mock_post:
      mock_resp = MagicMock()
      mock_resp.json.return_value = {"response": "Hello world", "eval_count": 5}
      mock_resp.raise_for_status = MagicMock()
      mock_post.return_value = mock_resp

      payload = {
        "model": "llama3.2", "prompt": "Hi", "stream": False,
        "keep_alive": "30m", "options": {"temperature": 0.7}
      }
      text, count = await ollama_node._execute_blocking(payload, "http://localhost:11434")

      assert text == "Hello world"
      assert count == 5

  @pytest.mark.asyncio
  async def test_execute_blocking_connect_error(self, ollama_node):
    """Blocking execution raises ConnectionError on ConnectError."""
    with patch("httpx.AsyncClient.post") as mock_post:
      import httpx
      mock_post.side_effect = httpx.ConnectError("Connection refused")

      payload = {"model": "llama3.2", "prompt": "Hi", "stream": False, "keep_alive": "30m", "options": {}}
      with pytest.raises(ConnectionError, match="Cannot connect to Ollama"):
        await ollama_node._execute_blocking(payload, "http://localhost:11434")

  @pytest.mark.asyncio
  async def test_execute_blocking_timeout(self, ollama_node):
    """Blocking execution raises TimeoutError on TimeoutException."""
    with patch("httpx.AsyncClient.post") as mock_post:
      import httpx
      mock_post.side_effect = httpx.TimeoutException("Timeout")

      payload = {"model": "llama3.2", "prompt": "Hi", "stream": False, "keep_alive": "30m", "options": {}}
      with pytest.raises(TimeoutError, match="timed out"):
        await ollama_node._execute_blocking(payload, "http://localhost:11434")

  @pytest.mark.asyncio
  async def test_execute_blocking_404(self, ollama_node):
    """Blocking execution raises ValueError on model not found (404)."""
    with patch("httpx.AsyncClient.post") as mock_post:
      import httpx
      mock_resp = MagicMock()
      mock_resp.status_code = 404
      mock_post.side_effect = httpx.HTTPStatusError(
        "Not found", request=MagicMock(), response=mock_resp
      )

      payload = {"model": "llama3.2", "prompt": "Hi", "stream": False, "keep_alive": "30m", "options": {}}
      with pytest.raises(ValueError, match="not found"):
        await ollama_node._execute_blocking(payload, "http://localhost:11434")

  @pytest.mark.asyncio
  async def test_execute_blocking_other_http_error(self, ollama_node):
    """Blocking execution reraises non-404 HTTPStatusError."""
    with patch("httpx.AsyncClient.post") as mock_post:
      import httpx
      mock_resp = MagicMock()
      mock_resp.status_code = 500
      err = httpx.HTTPStatusError("Server error", request=MagicMock(), response=mock_resp)
      mock_post.side_effect = err

      payload = {"model": "llama3.2", "prompt": "Hi", "stream": False, "keep_alive": "30m", "options": {}}
      with pytest.raises(httpx.HTTPStatusError):
        await ollama_node._execute_blocking(payload, "http://localhost:11434")