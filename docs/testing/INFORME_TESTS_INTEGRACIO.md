# Informe de Tests d'Integració Reals — Nexe 0.8

**Data:** 2026-03-15
**Durada dels tests:** 4 minuts 25 segons
**Resultat:** 62 PASSED, 0 FAILED

---

## Entorn de test

| Component | Detalls |
|-----------|---------|
| **Servidor** | Nexe 0.8 a `localhost:9119` |
| **Engine principal** | MLX — Qwen3-32B-4bit |
| **Ollama** | 16 models (phi3:mini, llama3:8b, llama2:13b, mistral, gemma3:27b...) |
| **Qdrant** | localhost:6333 — operatiu |
| **Mòduls carregats** | mlx_module, security, llama_cpp_module, web_ui_module, ollama_module, embeddings, rag, memory |

---

## Resultats per àrea

### Health & Status (8 tests)
| Test | Resultat |
|------|----------|
| `GET /` — System info | PASSED |
| `GET /health` — Operatiu | PASSED |
| `GET /status` — Engine i mòduls | PASSED |
| `GET /health/ready` — Readiness | PASSED |
| `GET /health/circuits` — Circuit breakers | PASSED |
| `GET /api/info` — API endpoints | PASSED |
| `GET /v1` — API v1 root | PASSED |
| `GET /info` — Info general | PASSED |

### Security (4 tests)
| Test | Resultat |
|------|----------|
| `GET /security/health` | PASSED |
| `GET /security/info` | PASSED |
| `POST /security/scan` (CSRF requerit) | PASSED |
| `POST /security/scan` sense auth | PASSED (403) |

### Memory — Store & Search (7 tests)
| Test | Resultat |
|------|----------|
| Store text a Qdrant | PASSED |
| Store amb metadata | PASSED |
| Store sense auth | PASSED (401/403) |
| Search contingut guardat | PASSED |
| Search sense resultats | PASSED |
| Search amb limit=1 | PASSED |
| Search sense auth | PASSED (401/403) |

### Chat — MLX / Qwen3-32B (4 tests)
| Test | Resultat |
|------|----------|
| Pregunta simple (2+2=4) | PASSED |
| Format de resposta OpenAI-compatible | PASSED |
| System prompt | PASSED |
| Max tokens | PASSED |

### Chat — Ollama Petit / phi3:mini (3 tests)
| Test | Resultat |
|------|----------|
| Chat bàsic | PASSED |
| Resposta amb contingut | PASSED |
| Pregunta en català | PASSED |

### Chat — Ollama Mitjà / llama3:8b (2 tests)
| Test | Resultat |
|------|----------|
| Pregunta complexa | PASSED |
| Generació de codi Python | PASSED |

### Chat — Ollama Gran / llama2:13b (2 tests)
| Test | Resultat |
|------|----------|
| Pregunta de raonament | PASSED |
| Context llarg | PASSED |

### Chat — Streaming SSE (3 tests)
| Test | Resultat |
|------|----------|
| Format SSE (data: chunks) | PASSED |
| Resposta completa concatenada | PASSED |
| Marker [DONE] al final | PASSED |

### Chat — RAG (2 tests)
| Test | Resultat |
|------|----------|
| Chat amb RAG usa context memòria | PASSED |
| Chat sense RAG | PASSED |

### Chat — Multilingüe (3 tests)
| Test | Resultat |
|------|----------|
| Català — Via Làctia | PASSED |
| Castellà — Fotosíntesi | PASSED |
| Anglès — DNA | PASSED |

### Chat — Error Handling (4 tests)
| Test | Resultat |
|------|----------|
| Sense autenticació → 401/403 | PASSED |
| Messages buit → fallback graceful | PASSED |
| Payload invàlid → 422 | PASSED |
| Model inexistent → fallback engine | PASSED |

### UI — Sessions (3 tests)
| Test | Resultat |
|------|----------|
| Crear sessió | PASSED |
| Llistar sessions | PASSED |
| Cicle de vida complet (crear → info → historial → eliminar) | PASSED |

### UI — Chat (3 tests)
| Test | Resultat |
|------|----------|
| Chat simple via UI | PASSED |
| Chat amb sessió específica | PASSED |
| Chat sense auth → 401/403 | PASSED |

### UI — File Upload (2 tests)
| Test | Resultat |
|------|----------|
| Upload fitxer .txt | PASSED |
| Upload sense auth → 401/403 | PASSED |

### UI — Memory (3 tests)
| Test | Resultat |
|------|----------|
| Save memòria via UI | PASSED |
| Recall memòria via UI | PASSED |
| Recall sense auth → 401/403 | PASSED |

### Bootstrap (2 tests)
| Test | Resultat |
|------|----------|
| Bootstrap info | PASSED |
| Bootstrap info sense auth (públic) | PASSED |

### Admin System (2 tests)
| Test | Resultat |
|------|----------|
| System health | PASSED |
| System status | PASSED |

### End-to-End (2 tests)
| Test | Resultat |
|------|----------|
| Pipeline RAG complet (store → chat → recall → verify) | PASSED |
| UI chat → recall historial sessió | PASSED |

### Multi-Engine (2 tests)
| Test | Resultat |
|------|----------|
| Mateixa pregunta MLX vs Ollama → tots diuen "Paris" | PASSED |
| Engines disponibles verificats | PASSED |

---

## Descobriments

1. **CSRF**: L'endpoint `/security/scan` requereix CSRF token (no és exempt com `/v1/*` o `/ui/*`).
2. **Fallback graceful**: El servidor accepta `messages=[]` i models inexistents fent fallback a engines disponibles — comportament robust.
3. **Streaming funciona**: SSE amb format `data: {json}` + `[DONE]` correcte.
4. **RAG pipeline complet**: Store → indexació Qdrant → search → recall funciona end-to-end.
5. **Multi-engine**: MLX i Ollama retornen respostes coherents a la mateixa pregunta.
6. **i18n**: El servidor respon correctament en català, castellà i anglès.
7. **Sessions UI**: Cicle complet (crear, xatejar, historial, eliminar) funciona.

---

## Fitxer de tests

`tests/test_integration_real.py` — 62 tests d'integració reals

### Executar
```bash
# Amb servidor actiu
pytest tests/test_integration_real.py -v --override-ini="addopts=" --tb=short

# O amb pytest-full.ini
pytest -c pytest-full.ini tests/test_integration_real.py -v --tb=short
```

### Requisits
- Servidor Nexe a localhost:9119
- Ollama a localhost:11434 amb phi3:mini, llama3:8b, llama2:13b
- Qdrant a localhost:6333
- NEXE_PRIMARY_API_KEY configurat

---

*Generat: 2026-03-15 | 62 tests | 0 failures | Servidor Nexe 0.8*
