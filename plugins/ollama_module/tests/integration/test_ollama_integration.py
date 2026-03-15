"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/ollama_module/tests/integration/test_ollama_integration.py
Description: Tests d'integració per mòdul Ollama. Valida workflow complet amb Ollama server, streaming, retries i timeouts.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest

# Skip - Tests d'integració pendents de migració completa a nexe_flow
pytest.skip("Integration tests pending full nexe_flow migration", allow_module_level=True)

from plugins.ollama_module.workflow.nodes.ollama_node import OllamaNode
from nexe_flow.core import (
  Flow as WorkflowDefinition,
  NodeRegistry,
  FlowExecutor as SequentialExecutor,
  Connection,
  FlowStatus as ExecutionStatus,
)

# PrintNode no existeix en nexe_flow base
class PrintNode:
  pass

pytestmark = pytest.mark.integration

@pytest.fixture
def ollama_node():
  """Create OllamaNode instance."""
  return OllamaNode()

@pytest.fixture
def registry_with_ollama():
  """Registry with OllamaNode and PrintNode."""
  registry = NodeRegistry()
  registry.register(OllamaNode())
  registry.register(PrintNode())
  return registry

@pytest.fixture
def executor_with_ollama(registry_with_ollama):
  """Executor with Ollama support."""
  return SequentialExecutor(registry_with_ollama)

class TestOllamaNodeReal:
  """Test OllamaNode with real Ollama server."""

  @pytest.mark.asyncio
  async def test_simple_question(self, ollama_node):
    """Test simple question with Ollama."""
    result = await ollama_node.execute({
      "prompt": "What is 2+2? Answer with just the number.",
      "model": "llama3.2",
      "temperature": 0.1,
      "max_tokens": 10
    })

    assert "response" in result
    assert result["model_used"] == "llama3.2"
    assert result["tokens"] > 0
    assert "4" in result["response"]

  @pytest.mark.asyncio
  async def test_with_system_prompt(self, ollama_node):
    """Test with system prompt."""
    result = await ollama_node.execute({
      "prompt": "Hello",
      "model": "llama3.2",
      "system": "You are a helpful assistant. Respond briefly.",
      "max_tokens": 20
    })

    assert "response" in result
    assert len(result["response"]) > 0

  @pytest.mark.asyncio
  async def test_creative_temperature(self, ollama_node):
    """Test with high temperature for creative response."""
    result = await ollama_node.execute({
      "prompt": "Write a creative word",
      "model": "llama3.2",
      "temperature": 1.5,
      "max_tokens": 5
    })

    assert "response" in result
    assert len(result["response"]) > 0

class TestOllamaWorkflow:
  """Test complete workflows with OllamaNode."""

  @pytest.mark.asyncio
  async def test_single_llm_node_workflow(self, executor_with_ollama):
    """Test workflow amb només OllamaNode."""
    workflow = WorkflowDefinition(
      name="simple-llm-test",
      nodes=[
        {
          "id": "ask_llm",
          "type": "ollama.chat",
          "config": {
            "prompt": "Say hello in one word",
            "model": "llama3.2",
            "temperature": 0.1,
            "max_tokens": 5
          }
        }
      ],
      connections=[]
    )

    context = await executor_with_ollama.execute(workflow)

    assert context.status == ExecutionStatus.COMPLETED
    assert len(context.nodes_completed) == 1

    response = context.artifact_store.get(
      context.workflow_id,
      "ask_llm",
      "response"
    )
    assert response is not None
    assert len(response) > 0

  @pytest.mark.asyncio
  async def test_llm_with_print_workflow(self, executor_with_ollama):
    """Test workflow LLM → Print."""
    workflow = WorkflowDefinition(
      name="llm-print-test",
      nodes=[
        {
          "id": "ask_llm",
          "type": "ollama.chat",
          "config": {
            "prompt": "What is the capital of France? Answer with just the city name.",
            "model": "llama3.2",
            "temperature": 0.1,
            "max_tokens": 10
          }
        },
        {
          "id": "print_response",
          "type": "console.print"
        }
      ],
      connections=[
        Connection(
          source_node="ask_llm",
          source_port="response",
          target_node="print_response",
          target_port="text"
        )
      ]
    )

    context = await executor_with_ollama.execute(workflow)

    assert context.status == ExecutionStatus.COMPLETED
    assert len(context.nodes_completed) == 2

    response = context.artifact_store.get(
      context.workflow_id,
      "ask_llm",
      "response"
    )
    assert "paris" in response.lower() or "París" in response

  @pytest.mark.asyncio
  async def test_multiple_llm_calls(self, executor_with_ollama):
    """Test workflow amb múltiples crides LLM."""
    workflow = WorkflowDefinition(
      name="multi-llm-test",
      nodes=[
        {
          "id": "llm1",
          "type": "ollama.chat",
          "config": {
            "prompt": "Say 'one'",
            "model": "llama3.2",
            "max_tokens": 5
          }
        },
        {
          "id": "llm2",
          "type": "ollama.chat",
          "config": {
            "prompt": "Say 'two'",
            "model": "llama3.2",
            "max_tokens": 5
          }
        }
      ],
      connections=[]
    )

    context = await executor_with_ollama.execute(workflow)

    assert context.status == ExecutionStatus.COMPLETED
    assert len(context.nodes_completed) == 2

    response1 = context.artifact_store.get(context.workflow_id, "llm1", "response")
    response2 = context.artifact_store.get(context.workflow_id, "llm2", "response")

    assert response1 is not None
    assert response2 is not None

class TestOllamaErrors:
  """Test error scenarios with real Ollama."""

  @pytest.mark.asyncio
  async def test_invalid_model(self, ollama_node):
    """Test with non-existent model."""
    with pytest.raises(ValueError, match="Model .* not found"):
      await ollama_node.execute({
        "prompt": "Test",
        "model": "this-model-does-not-exist-xyz"
      })