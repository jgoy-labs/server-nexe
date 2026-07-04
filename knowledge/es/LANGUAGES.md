# === METADATA RAG ===
versio: "1.0"
data: 2026-05-29
id: nexe-languages
collection: nexe_documentation

# === CONTENIDO RAG (OBLIGATORIO) ===
abstract: "Como server-nexe gestiona los idiomas: detecta el idioma de cada mensaje del usuario (unos 75 idiomas, deteccion offline con lingua) y responde en ese mismo idioma, no en el idioma de instalacion (NEXE_LANG). Explica el pipeline de deteccion y la directiva de respuesta, el papel de NEXE_LANG como reserva, y el comportamiento en mensajes cortos o cambios de idioma. Documenta la correccion del bug por el que hasta la 1.0.4 respondia siempre en el idioma fijo de instalacion (por defecto catalan); la deteccion automatica se anadio en la 1.0.5."
tags: [idiomas, lengua, language, i18n, multilingue, deteccion, lingua, nexe-lang, multi-idioma]
chunk_size: 600
priority: P2

# === OPCIONAL ===
lang: es
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Idiomas — server-nexe 1.0.7

## En qué idiomas puedes hablar con Nexe

Puedes escribir a Nexe en cualquiera de los idiomas principales del mundo (unos 75: catalán, español, inglés, francés, alemán, italiano, portugués, neerlandés, ruso, chino, japonés, árabe…). Nexe **detecta el idioma de tu mensaje y responde en ese mismo idioma**, sin que tengas que configurar nada.

La calidad de la respuesta depende del modelo local cargado: los modelos grandes dominan más idiomas; los pequeños (4B) responden mejor en los idiomas más comunes.

## Cómo elige el idioma (pipeline)

En cada mensaje que envías:

1. **Detección.** Nexe detecta el idioma de tu mensaje con `lingua` (una librería de detección que funciona 100% offline, sin conexión). Es precisa incluso con textos cortos y con idiomas cercanos (catalán, español, portugués…). Antes de detectar, ignora los bloques de código y las URLs para que no confundan el resultado.
2. **Selección del prompt.** Elige el prompt de sistema en tu idioma (catalán, español o inglés); para el resto de idiomas usa el inglés como base.
3. **Directiva de respuesta.** Añade una instrucción clara para que el modelo responda en el idioma detectado. La instrucción se refuerza al final del prompt, porque los modelos pequeños obedecen mejor la instrucción más cercana a la generación.
4. **Respuesta.** El modelo genera la respuesta en tu idioma.

Si el mensaje es demasiado corto o ambiguo (por ejemplo "ok", "gracias") o es solo código, Nexe mantiene el idioma de configuración para no equivocarse.

## El idioma de instalación (NEXE_LANG)

`NEXE_LANG` es el idioma por defecto de la instalación. Solo se usa como **opción de reserva** cuando la detección no es fiable. **No limita** el idioma de las respuestas: aunque instales Nexe en catalán, te responderá en inglés si le escribes en inglés.

## Notas

- **Cambio de idioma a media conversación:** puedes cambiar de idioma cuando quieras y Nexe se adapta. Dentro de una conversación ya iniciada en un idioma, el cambio puede costar un poco más (el historial de la conversación influye); si quieres un cambio limpio, abre una conversación nueva.
- **Corrección (1.0.5):** hasta la versión 1.0.4, Nexe respondía siempre en el idioma fijo de instalación (por defecto catalán) aunque el usuario escribiera en otro idioma. Este comportamiento se **corrigió en la 1.0.5** con la detección automática del idioma del mensaje.
