# ADR-0002: Empaquetament Python amb venv relocatable

**Data:** 2026-04-17
**Estat:** Superseded by ADR-0018
**Decidit per:** Jordi Goy

## Context

server-nexe és un projecte Python/FastAPI amb ~29 dependències al `requirements.txt`. Cal empaquetar-lo dins `nexe-app.app` (macOS) i AppImage (Linux) com a sidecar, de manera que:
- L'usuari no hagi d'instal·lar Python ni pip manualment
- El build sigui reproduïble amb CI/CD
- El canal de distribució sigui autocontingut

## Decisió

**Una sola via d'empaquetament per v1: venv relocatable**, via script `build-python-bundle.sh` ja existent al repo server-nexe.

El venv viu dins:
- `nexe-app.app/Contents/Resources/server-nexe/python-bundle/` (release)
- Durant dev, el venv extern de server-nexe s'usa tal qual (server-nexe arrencat manualment)

## Alternatives considerades

| Opció | Motiu descart |
|---|---|
| **PyInstaller** | Inicialització lenta (unpacking), stack traces poc clars, problemes amb C extensions |
| **briefcase (BeeWare)** | Maduresa variable, corba d'aprenentatge, menys control |
| **Nuitka** | Enfocat a compilar Python a C — scope diferent, més lent a build |
| **Docker bundle** | Massa pesat, requereix Docker al client, viola sobirania |
| **Dos vies (venv + PyInstaller)** | Duplicació d'esforç, risc de divergència, complicació CI |

## Conseqüències

**Positives:**
- Reutilitzem script `build-python-bundle.sh` ja validat a server-nexe
- Debugging simple: és un venv estàndard
- Arrencada ràpida (sense unpacking)
- Transparent: es pot inspeccionar el bundle

**Negatives / riscos:**
- Mida del bundle superior a binaris compilats (~250MB amb deps Python)
- Relocatable venv a macOS requereix cura amb rutes absolutes (scripts wrapper)
- Diferents Python binaries per arquitectura (x86_64 vs arm64)

**Mitigacions:**
- Dos canals de distribució: `full` (amb Chromium, ~300MB) i `lite` (sense, ~80MB, Chromium primer-run install)
- Script wrapper `run-nexe` gestiona variables d'entorn i rutes
- CI matriu: macos-latest-arm + ubuntu-20.04

## Referències

- original plan (not in template)
- Script existent: `<your-backend>/installer/<your-build-script>`
