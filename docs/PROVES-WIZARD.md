# Provar el wizard d'instal·lació amb una RAM simulada

Eina **permanent** per provar el wizard gràfic (`installer/swift-wizard`) des de qualsevol Mac,
sense necessitar una màquina de cada mida.

**Per què existeix:** el wizard tria quins models ofereix segons la RAM de la màquina. El cas que
decideix el seu comportament és un **Mac de 24 GB** — `mistral_small_24b` demana **exactament
18,0 GB** i el límit és **exactament 18,0** —, i ningú té una màquina de cada mida a mà. Sense
això, aquest cas no es pot verificar mai a la pràctica.

## La variable

```
NEXE_WIZARD_RAM_GB=<un dels set valors de sota>
```

**Llista tancada. Aquests set i cap més:**

```
8 · 16 · 24 · 32 · 64 · 96 · 128
```

- **Sense la variable**: el wizard llegeix la RAM real i es comporta **exactament** com sempre.
- **Amb un valor de la llista**: **només canvia la font del número**. El tier, el filtre de mida i
  la recomanació corren pel camí de producció, sense cap branca especial.
- **Amb qualsevol altra cosa** (`20`, `48`, `0`, `-4`, `vint`, buit): **el wizard NO s'obre**.
  Escriu l'error a stderr, llista els valors vàlids i surt amb codi **2**.

```
$ NEXE_WIZARD_RAM_GB=20 swift run InstallNexe

NEXE_WIZARD_RAM_GB=20 no és un valor simulable.
Valors vàlids: 8, 16, 24, 32, 64, 96, 128.
Sense la variable, el wizard llegeix la RAM real de la màquina.
```

No arrodoneix al tier més proper ni cau a la RAM real en silenci: un valor mal escrit et deixaria
provant una màquina que no has demanat, i aquest wizard instal·la models segons la RAM.

### Per què aquests set

- **24 GB és obligatori**: és el tier del **marge zero** (`mistral_small_24b` demana **18,0** i el
  llindar és **18,0**) — el punt més crític de tot el smoke. I és maquinari real i comú: **MacBook
  Air M2/M3 i Mac mini porten 24 GB de sèrie**.
- **32 i 64** són **els dos costats de la frontera de l'`alia_40b`**: `32 × 0,75 = 24 < 43,2` → gris;
  `64 × 0,75 = 48 > 43,2` → actiu.
- **128 és el sostre**: per sobre, `ramTier` satura a `tier_32` igualment, o sigui que simular una
  màquina més gran **no aporta res**.

## ⚠️ Banner obligatori

Quan l'override és actiu, el wizard mostra un **banner taronja a dalt** de la pantalla de selecció:

> **MODE PROVA — RAM simulada: 24 GB (real: 128 GB). El wizard tria els models segons aquest
> número, no segons la teva màquina.**

El banner **no es pot desactivar** i surt també en builds de release. És a posta: aquest wizard
**instal·la models segons la RAM**, i una execució de prova confosa amb una de real pot acabar
instal·lant un model que la màquina no aguanta.

Si veus aquest banner sense voler-ho: **atura't i treu la variable de l'entorn.**

## Com llançar-lo

```bash
cd installer/swift-wizard
swift build

# Un tier concret (canvia el número):
NEXE_WIZARD_RAM_GB=24 swift run InstallNexe

# O el binari ja construït:
NEXE_WIZARD_RAM_GB=24 .build/debug/InstallNexe
```

Els set valors, un darrere l'altre:

```bash
for r in 8 16 24 32 64 96 128; do
  echo "── $r GB ──"; NEXE_WIZARD_RAM_GB=$r swift run InstallNexe
done
```

## Què s'ha d'esperar a cada valor

| RAM simulada | Pestanya | Límit (×0,75) | Recomanat (corona) | Grisos / no clicables |
|---:|---|---:|---|---|
| 8 GB | `tier_8` | 6,0 | `qwen35_4b` | — |
| 16 GB | `tier_16` | 12,0 | `qwen35_9b` | — |
| **24 GB** | `tier_24` | **18,0** | **`mistral_small_24b`** | `qwen35_27b`, `gpt_oss_20b` |
| 32 GB | `tier_32` | 24,0 | `qwen35_35b_moe` | `mixtral_8x7b`, `alia_40b` |
| 64 GB | `tier_32` | 48,0 | `qwen35_35b_moe` | — (`alia_40b` **actiu**) |
| 96 GB | `tier_32` | 72,0 | `qwen35_35b_moe` | — |
| 128 GB | `tier_32` | 96,0 | `qwen35_35b_moe` | — |

**Els dos casos que realment importen:**

- **24 GB — el marge zero.** `mistral_small_24b` demana 18,0 i el límit és 18,0. Ha de sortir
  **seleccionable i amb la corona**. Si surt gris, el comparador del wizard ha deixat de ser
  estricte (`>` → `>=`, el fix B171) i s'ha trencat alguna cosa.
- **64 GB — el sostre obert.** La pestanya diu «32 GB+» i `alia_40b` (43,2 GB) ha de sortir
  **actiu**, mentre que a 32 GB ha de sortir gris.

## Quan una taula d'aquestes canvia

Els números surten de `installer/swift-wizard/Resources/models.json` i de la lògica de
`ModelPickerView.swift`. Si algú canvia un `ram_gb`, un coeficient o un tier, aquesta taula queda
desactualitzada — hi ha guards a `tests/test_catalog_sync.py` que ho canten, i s'ha d'actualitzar
aquest document alhora.
