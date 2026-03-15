"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/ollama_module/workflow/nodes/ollama_node.py
Description: OllamaNode per Workflow Engine. Node d'integració amb Ollama LLM amb prompt templating, streaming i config management.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

try:
  import httpx
except ImportError as e:
  raise ImportError(
    "httpx is required for OllamaNode. "
    "Install it with: pip install httpx>=0.25.0"
  ) from e

import os
import re
import logging
from typing import Dict, Any, Optional
from nexe_flow.core.node import Node, NodeMetadata, NodeInput, NodeOutput

DEFAULT_BASE_URL = "http://localhost:11434"
logger = logging.getLogger(__name__)

DANGEROUS_PROMPT_PATTERNS = [
  r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
  r"forget\s+(all\s+)?instructions?",
  r"disregard\s+(all\s+)?(previous|prior)\s+(instructions?|commands?)",
  r"print\s+(all|system|admin|secret|key|password|token)",
  r"show\s+(me\s+)?(all|system|admin|config|secret)",
  r"reveal\s+(all|system|admin|config|secret)",
  r"(list|display)\s+(all\s+)?(secrets?|keys?|passwords?|tokens?)",
  r"what\s+(are|is)\s+(your|the)\s+(secret|key|password|token|api_key)",
  r"system\s+prompt",
  r"admin\s+mode",
  r"debug\s+mode",
  r"<\s*script",
  r"javascript:",
  r"\$\{.*\}",
  r"\{\{.*\}\}",
]

ALLOWED_OLLAMA_MODELS = [
  "llama3.2:3b",
  "llama3.2:1b",
  "llama3.2",
  "llama3.2:latest",
  "llama3.1:8b",
  "llama3.1:70b",
  "llama3.1",
  "llama3:8b",
  "llama3",
  "mistral:7b",
  "mistral:latest",
  "mistral",
  "codellama:7b",
  "codellama",
  "phi3:mini",
  "phi3",
  "qwen2.5-coder:32b",
  "qwen2.5-coder:7b",
  "gemma2:9b",
  "gemma3:27b",
  "hdnh2006/salamandra-7b-instruct:q4_K_M",
  "hdnh2006/salamandra-2b-instruct",
]

def validate_ollama_prompt(prompt: str) -> None:
  """
  Validate prompt for injection attempts.

  Detects prompt injection patterns

  Args:
    prompt: User prompt to validate

  Raises:
    ValueError: If prompt contains suspicious patterns
  """
  prompt_lower = prompt.lower()

  for pattern in DANGEROUS_PROMPT_PATTERNS:
    if re.search(pattern, prompt_lower, re.IGNORECASE):
      logger.warning(
        f"🚨 SECURITY: Prompt injection attempt detected: pattern='{pattern}' "
        f"prompt_preview='{prompt[:100]}...'"
      )
      raise ValueError(
        f"Prompt rejected: contains suspicious pattern that may attempt "
        f"to override system behavior or extract secrets"
      )

def validate_ollama_model(model: str) -> None:
  """
  Validate model is in allowlist.

  Only allow approved models

  Args:
    model: Model name to validate

  Raises:
    ValueError: If model not in allowlist
  """
  model_base = model.split(':')[0] if ':' in model else model

  if model not in ALLOWED_OLLAMA_MODELS and model_base not in ALLOWED_OLLAMA_MODELS:
    logger.warning(
      f"🚨 SECURITY: Model not in allowlist: model='{model}' "
      f"allowed={ALLOWED_OLLAMA_MODELS}"
    )
    raise ValueError(
      f"Model '{model}' not in allowlist. Allowed models: {', '.join(ALLOWED_OLLAMA_MODELS)}"
    )

def sanitize_ollama_response(response: str) -> str:
  """
  Sanitize LLM response to prevent accidental secret leakage.

  Redact potential secrets from responses

  Args:
    response: Raw LLM response

  Returns:
    Sanitized response with secrets redacted
  """
  response = re.sub(r'\b[a-f0-9]{32,128}\b', '[REDACTED_API_KEY]', response, flags=re.IGNORECASE)

  response = re.sub(r'/Users/[^/\s]+(/[^\s]*)?', '[REDACTED_PATH]', response)
  response = re.sub(r'/home/[^/\s]+(/[^\s]*)?', '[REDACTED_PATH]', response)
  response = re.sub(r'C:\\Users\\[^\\\s]+(\\.]*)?', '[REDACTED_PATH]', response)

  response = re.sub(r'(API_KEY|SECRET|PASSWORD|TOKEN)=[^\s]+', r'\1=[REDACTED]', response, flags=re.IGNORECASE)

  return response

class OllamaNode(Node):
  """
  Node que crida Ollama local per generar text amb LLMs.

  Inputs:
    - prompt (string, required): Text prompt per l'LLM
    - model (string, optional): Model a utilitzar (default: "llama3.2")
    - temperature (number, optional): Creativitat 0.0-2.0 (default: 0.7)
    - max_tokens (number, optional): Màxim tokens resposta (default: None)
    - system (string, optional): System prompt (default: None)

  Outputs:
    - response (string): Text generat per l'LLM
    - model_used (string): Model utilitzat
    - tokens (number): Tokens utilitzats (aproximat)

  Example YAML:
    nodes:
     - id: ask_question
      type: ollama.chat
      config:
       prompt: "Explain quantum computing in simple terms"
       model: "llama3.2"
       temperature: 0.7
  """

  def __init__(self, base_url: Optional[str] = None):
    """
    Initialize OllamaNode.

    Args:
      base_url: URL base d'Ollama (default: http://localhost:11434)
    """
    super().__init__()
    if base_url is None:
      base_url = (
        os.getenv("NEXE_OLLAMA_HOST")
        or os.getenv("OLLAMA_HOST")
        or DEFAULT_BASE_URL
      )

    self.base_url = base_url.rstrip("/")
    logger.info("OllamaNode initialized - base_url=%s", self.base_url)

  def get_metadata(self) -> NodeMetadata:
    """Return node metadata."""
    return NodeMetadata(
      id="ollama.chat",
      name="Ollama Chat",
      version="1.0.0",
      description="Genera text utilitzant Ollama local (llama, mistral, etc.)",
      category="llm",
      inputs=[
        NodeInput(
          name="prompt",
          type="string",
          required=True,
          description="Text prompt per l'LLM"
        ),
        NodeInput(
          name="model",
          type="string",
          required=False,
          default="llama3.2",
          description="Model Ollama (llama3.2, mistral, etc.)"
        ),
        NodeInput(
          name="temperature",
          type="number",
          required=False,
          default=0.7,
          description="Creativitat 0.0-2.0 (més alt = més creatiu)"
        ),
        NodeInput(
          name="max_tokens",
          type="number",
          required=False,
          default=None,
          description="Màxim tokens a generar (None = il·limitat)"
        ),
        NodeInput(
          name="system",
          type="string",
          required=False,
          default=None,
          description="System prompt (instruccions per l'LLM)"
        )
      ],
      outputs=[
        NodeOutput(
          name="response",
          type="string",
          description="Text generat per l'LLM"
        ),
        NodeOutput(
          name="model_used",
          type="string",
          description="Model utilitzat"
        ),
        NodeOutput(
          name="tokens",
          type="number",
          description="Tokens aproximats utilitzats"
        )
      ],
      icon="🤖",
      color="#10a37f"
    )

  async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute Ollama API call.

    Args:
      inputs: Node inputs (prompt, model, temperature, etc.)

    Returns:
      Dict amb response, model_used, tokens

    Raises:
      ValueError: Si prompt està buit
      httpx.HTTPError: Si Ollama no està disponible
    """
    self.validate_inputs(inputs)

    prompt = inputs['prompt']
    model = inputs.get('model', 'llama3.2')
    temperature = inputs.get('temperature', 0.7)
    max_tokens = inputs.get('max_tokens', None)
    system = inputs.get('system', None)

    if not prompt or not prompt.strip():
      raise ValueError("Prompt cannot be empty")

    validate_ollama_prompt(prompt)
    if system:
      validate_ollama_prompt(system)

    validate_ollama_model(model)

    stream_callback = inputs.get('stream_callback', None)
    use_streaming = stream_callback is not None

    payload = {
      "model": model,
      "prompt": prompt,
      "stream": use_streaming,
      "keep_alive": "30m",
      "options": {
        "temperature": temperature
      }
    }

    if system:
      payload["system"] = system

    if max_tokens:
      payload["options"]["num_predict"] = int(max_tokens)

    import time
    start_time = time.perf_counter()
    token_count = 0

    try:
      from plugins.workflow_engine.core.execution.sequential_executor import _verbose_logger
    except ImportError:
      _verbose_logger = None

    try:
      if use_streaming:
        generated_text = ""
        async with httpx.AsyncClient(timeout=120.0) as client:
          async with client.stream(
            "POST",
            f"{self.base_url}/api/generate",
            json=payload
          ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
              if line:
                import json
                chunk = json.loads(line)
                token = chunk.get("response", "")
                if token:
                  generated_text += token
                  token_count += 1
                  if stream_callback:
                    stream_callback(token)
                  if _verbose_logger:
                    elapsed = time.perf_counter() - start_time
                    _verbose_logger.llm_streaming_progress(token_count, elapsed)
                if chunk.get("done", False):
                  break
      else:
        async with httpx.AsyncClient(timeout=120.0) as client:
          response = await client.post(
            f"{self.base_url}/api/generate",
            json=payload
          )
          response.raise_for_status()
          data = response.json()
          generated_text = data.get("response", "")
          token_count = data.get("eval_count", int(len(generated_text.split()) * 1.3))

    except httpx.ConnectError:
      raise ConnectionError(
        f"Cannot connect to Ollama at {self.base_url}. "
        "Make sure Ollama is running (ollama serve)"
      )
    except httpx.TimeoutException:
      raise TimeoutError(
        f"Ollama request timed out after 120s. "
        f"Model '{model}' might be too large or prompt too complex."
      )
    except httpx.HTTPStatusError as e:
      if e.response.status_code == 404:
        raise ValueError(
          f"Model '{model}' not found. "
          f"Pull it first: ollama pull {model}"
        )
      raise

    elapsed_s = time.perf_counter() - start_time
    tokens_per_second = token_count / elapsed_s if elapsed_s > 0 else 0

    sanitized_text = sanitize_ollama_response(generated_text)

    system_tokens = len(system) // 4 if system else 0
    prompt_tokens = len(prompt) // 4 if prompt else 0

    return {
      "response": sanitized_text,
      "model_used": model,
      "tokens": token_count,
      "tokens_per_second": round(tokens_per_second, 1),
      "elapsed_ms": round(elapsed_s * 1000, 1),
      "system_prompt": system[:200] if system else "",
      "system_tokens": system_tokens,
      "prompt_tokens": prompt_tokens,
    }