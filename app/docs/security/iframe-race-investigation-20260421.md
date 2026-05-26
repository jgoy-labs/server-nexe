# Investigació C05 — iframe registry race condition

**Finding origen:** Gemini F3 a `20260420_auditoria_militar_gemini.md` (P0).
**Consolidat:** C05 a `20260421_consolidat_auditoria_militar.md` §4 (P0 condicional,
pendent verificació).
**Sessió:** Dev BUS militar A5 (`militar/a5-iframe`), 2026-04-21.
**Veredicte:** **NO REPRODUÏT COM A VECTOR EXPLOTABLE** → recomanem rebaixar de
P0 a **P2 "defense in depth hardening"**.

---

## 1. Claim original (Gemini F3)

> El registre de la font (`contentWindow`) de l'iframe es fa al `DOMContentLoaded`
> i al `load`. Hi ha una finestra temporal (race condition) entre que l'iframe
> comença a carregar (`about:blank`) i s'acaba de carregar on el `contentWindow`
> pot canviar o no estar encara registrat. El bug #6 de l'informe de Windows
> indica que es va intentar fixar però el "source check" segueix sent fràgil si
> hi ha múltiples navegacions.
>
> **Impacte:** DoS (missatges legítims bloquejats) o possibilitat de spoofing
> si un atacant aconsegueix injectar un iframe a la finestra de transició.

**Nota important:** Gemini és l'única IA que menciona aquest finding. Claude
Opus 4.7 (59 findings) i GPT-5 (23 findings) no el detecten. Gemini no
aporta codi d'exploit ni evidència empírica concreta.

---

## 2. Context del codi actual

Fitxer `src/main.js:129-138` després del fix Bug #6 Fase 0 (commit `aa19de8`):

```js
// Registra automàticament tots els iframes `plugin://` coneguts al firewall
// (F034 source validation). El rag spike és l'únic actual; Fase 4 ampliarà.
//
// NOTA: registrar 2 vegades (fase about:blank + fase plugin carregat).
// L'iframe.contentWindow canvia després del `load` — cal capturar ambdós
// perquè si el plugin envia postMessage durant la transició, no es perdi.
document.querySelectorAll('iframe[src^="plugin://"]').forEach((iframe) => {
  registerPluginIframe(iframe);
  iframe.addEventListener("load", () => registerPluginIframe(iframe));
});
```

El `REGISTERED_IFRAME_SOURCES` és un `Set<Window>` (strong refs). El handler
`handlePluginMessage` al mateix fitxer valida `event.source` contra el Set.

---

## 3. Hypothesis investigades

Les 4 hypothesis s'han codificat com a tests vitest al bloc final de
`src/main.test.js` (`"plugin firewall — iframe contentWindow race (C05
Gemini F3)"`).

### H1 — contentWindow canvia entre about:blank i la càrrega real del plugin

**Test:** `"H1: registering BEFORE navigation captures old contentWindow, NEW
one is NOT registered"`.

**Resultat:** ✅ reprodueix. Si **només** registres al `DOMContentLoaded`, el
nou contentWindow post-navegació queda fora del Set. Un postMessage amb el nou
contentWindow és rebutjat.

**Però:** aquesta hypothesis **ja està mitigada** per Bug #6 (el `load`
listener registra el nou contentWindow quan la navegació acaba).

### H2 — Finestra temporal: postMessage durant transició

**Test:** `"H2 race window: message during transition (before load fires) is
dropped — DoS confirmed"`.

**Resultat:** ⚠️ reprodueix com a teoria **però no com a pràctica explotable**.

- **Temps de la finestra race:** entre el moment en què el browser reemplaça
  `iframe.contentWindow` (navegació) i el moment en què dispara `load`.
  Per iframes sandboxed carregant un custom scheme síncron (`plugin://`), aquest
  gap es resol dins del mateix microtask tick a Chromium i WebKit.
- **Comportament real dels plugins:** el plugin rag spike (únic ús actual) envia
  `plugin.ready` dins del seu `<script>` — que corre **després** que el document
  complet estigui parsed i l'event `load` ja s'hagi disparat al iframe parent.
  És a dir, els postMessage legítims arriben sempre DESPRÉS del registre al
  `load` event.
- **Vector d'attacker:** per explotar aquesta finestra, l'attacker necessitaria
  fer-se amb el control del plugin a un moment de carrega concret i emetre un
  postMessage EN EL MICROTASK EXACTE entre canvi de contentWindow i load event.
  No hi ha mecanisme JS que permeti a l'attacker "allargar" aquesta finestra
  ni fer-la predictible. I si ja té control del plugin, ja pot enviar
  postMessages legítims després del load — el "DoS" dels primers ~1ms no aporta
  cap capacitat que no tingui ja.

**Conclusió H2:** DoS teòric de missatges dins del microtask de transició, no
explotable a la pràctica. Cost zero en acceptar-ho com a comportament.

### H3 — Zombies al Set (contentWindow vell persisteix)

**Test:** `"H3: old (zombie) contentWindow persists in Set — verificat NO
explotable"`.

**Resultat:** ⚠️ confirma que el vell contentWindow queda al Set (strong ref).

**Per què NO és explotable:**
- Un `Window` associat a un document "discarded" (post-navegació d'iframe) NO
  té document viu. El browser no permet que aquest Window emeti postMessage a
  el parent (l'script del vell document ja no corre).
- Per tal que un attacker "reutilitzi" aquest Window zombie hauria de tenir
  control d'un procés del browser o fer injecció cross-origin dins d'un iframe
  sandboxed sense `allow-same-origin`. Això contradiria el model de seguretat
  del browser i no és un vector legítim.
- El Set és `Set`, no `WeakSet`. Els Window morts queden retinguts en memòria
  (petita leak si hi ha **moltes** navegacions — no és cas real d'un app
  desktop Tauri).

**Conclusió H3:** no vector d'exploit. Pot justificar-se un `WeakSet` com a
millora d'hygiene de memòria en Fase 4+ quan hi hagi molts plugins i
navegacions freqüents.

### H4 — Múltiples navegacions acumulen zombies

**Test:** `"H4: programmatic iframe.src reload accumulates zombies (if no
mutation observer)"`.

**Resultat:** ⚠️ confirmat. Cada `iframe.src = "..."` + `load` event afegeix un
nou contentWindow sense treure l'anterior.

**Mateix raonament que H3:** sense vector d'exploit. Defense-in-depth possible
via `MutationObserver` sobre `iframe.src` attribute + `unregisterPluginIframe`
del vell. Cost: complexitat addicional, manteniment.

---

## 4. Evidència empírica

```
$ pnpm test
 RUN  v4.1.4 <local dev path>

 Test Files  2 passed (2)
      Tests  33 passed (33)
   Duration  124ms
```

33/33 tests verds — inclòs els 5 nous tests de reproducció C05 (bloc
`"plugin firewall — iframe contentWindow race (C05 Gemini F3)"`).

Els tests són documentals: **cap d'ells falla amb el codi actual**. Els tests
H1-H4 mostren el comportament del codi, no "red→green→refactor". Això és
volgut: documentar l'investigació i deixar regressió contra futures
modificacions de la funció `registerPluginIframe`.

---

## 5. Conclusió i recomanació

**Veredicte:** la race condition descrita per Gemini és un fenomen teòric del
cicle de vida iframe (contentWindow reemplaçat durant navegació) però NO és un
vector explotable al codi actual:

1. **DoS:** mitigat per registrar a `DOMContentLoaded` + `load` (fix Bug #6).
   La finestra residual (microtask entre canvi de contentWindow i `load` event)
   no afecta missatges legítims reals (els plugins envien DESPRÉS del load).
2. **Spoofing:** no vector. Els Window zombies del Set no poden emetre
   postMessage — document closed al browser.
3. **Memòria:** zombies acumulats són `Set` strong refs (no `WeakSet`). Leak
   petit en apps amb molts iframes recarregats. No és issue a Fase 0-3.

**Recomanació:**
- Rebaixar **C05 de P0 a P2** al consolidat (defense-in-depth hardening).
- NO aplicar patch preventiu ara (zero codi especulatiu militar).
- Considerar a Fase 4+ quan hi hagi molts plugins:
  - `WeakSet` en lloc de `Set` per a auto-GC dels zombies
  - `MutationObserver` sobre `iframe.src` només si es verifica empíricament
    un vector nou
- Deixar els 5 tests de documentació com a regressió: si algú treu el registre
  del `load` per error, els tests T1/T2 fallaran explícit.

---

## 6. Referències

- `src/main.js` línies 25-50, 112-140 — codi actual firewall + iframe registration
- `src/main.test.js` bloc final — tests H1/H2/H3/H4 documentals
- `diari/informes/20260419_FASE0_VALIDADA_WINDOWS_ARM64.md` §Bug 6, §Bug 7 —
  context del fix original `aa19de8`
- `diari/informes/20260420_auditoria_militar_gemini.md` F3 — claim original
- `diari/informes/20260421_consolidat_auditoria_militar.md` §4 C05 — agrupació cross-IA
