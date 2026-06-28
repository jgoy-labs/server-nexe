# === METADATA RAG ===
versio: "1.0"
data: 2026-05-29
id: nexe-languages
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Com server-nexe gestiona els idiomes: detecta l'idioma de cada missatge de l'usuari (uns 75 idiomes, deteccio offline amb lingua) i respon en aquest mateix idioma, no en l'idioma d'instal-lacio (NEXE_LANG). Explica el pipeline de deteccio i la directiva de resposta, el paper de NEXE_LANG com a reserva, i el comportament en missatges curts o canvis d'idioma. Documenta la correccio del bug pel qual fins a la 1.0.4 responia sempre en l'idioma fix d'instal-lacio (per defecte catala); la deteccio automatica es va afegir a la 1.0.5."
tags: [idiomes, llengua, language, i18n, multilingue, deteccio, lingua, nexe-lang, multi-idioma]
chunk_size: 600
priority: P2

# === OPCIONAL ===
lang: ca
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Idiomes — server-nexe 1.0.6

## En quins idiomes pots parlar amb Nexe

Pots escriure a Nexe en qualsevol dels idiomes principals del món (uns 75: català, castellà, anglès, francès, alemany, italià, portuguès, neerlandès, rus, xinès, japonès, àrab…). Nexe **detecta l'idioma del teu missatge i respon en aquest mateix idioma**, sense que hagis de configurar res.

La qualitat de la resposta depèn del model local carregat: els models grans dominen més idiomes; els petits (4B) responen millor en els idiomes més comuns.

## Com tria l'idioma (pipeline)

A cada missatge que envies:

1. **Detecció.** Nexe detecta l'idioma del teu missatge amb `lingua` (una llibreria de detecció que funciona 100% offline, sense connexió). És precisa fins i tot amb textos curts i amb idiomes propers (català, castellà, portuguès…). Abans de detectar, ignora els blocs de codi i les URLs perquè no confonguin el resultat.
2. **Selecció del prompt.** Tria el prompt de sistema en el teu idioma (català, castellà o anglès); per a la resta d'idiomes fa servir l'anglès com a base.
3. **Directiva de resposta.** Afegeix una instrucció clara perquè el model respongui en l'idioma detectat. La instrucció es reforça al final del prompt, perquè els models petits obeeixen millor la instrucció més propera a la generació.
4. **Resposta.** El model genera la resposta en el teu idioma.

Si el missatge és massa curt o ambigu (per exemple "ok", "gràcies") o és només codi, Nexe manté l'idioma de configuració per no equivocar-se.

## L'idioma d'instal·lació (NEXE_LANG)

`NEXE_LANG` és l'idioma per defecte de la instal·lació. Només s'utilitza com a **opció de reserva** quan la detecció no és fiable. **No limita** l'idioma de les respostes: encara que instal·lis Nexe en català, et respondrà en anglès si li escrius en anglès.

## Notes

- **Canvi d'idioma a mig diàleg:** pots canviar d'idioma quan vulguis i Nexe s'adapta. Dins d'una conversa ja iniciada en un idioma, el canvi pot costar una mica més (l'historial de la conversa influeix); si vols un canvi net, obre una conversa nova.
- **Correcció (1.0.5):** fins a la versió 1.0.4, Nexe responia sempre en l'idioma fix d'instal·lació (per defecte català) encara que l'usuari escrivís en un altre idioma. Aquest comportament es va **corregir a la 1.0.5** amb la detecció automàtica de l'idioma del missatge.
