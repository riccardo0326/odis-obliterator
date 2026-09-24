# TASKS.md – Piano di Implementazione Dettagliato

Elenco ordinato dei task atomici per gli sviluppatori / agenti di codifica per l'architettura **Standalone Local su PC Lamborghini**. Ogni task è autocontenuto, testabile e tracciabile.

---

## Tabella di Avanzamento

| Task ID | Titolo | Componente | Dipendenze | Stato |
|---|---|---|---|---|
| **TASK-001** | Scaffolding Progetto & Configurazione | Shared | Nessuna | `COMPLETED` |
| **TASK-002** | Client Kelpie Gateway (`gemini-3.7-flash`) | Controller | TASK-001 | `COMPLETED` |
| **TASK-003** | Modulo Pulizia Testo (`text_cleaner`) & Test | Controller | TASK-001 | `COMPLETED` |
| **TASK-004** | Motore Visione & Mappatura Coordinate (Kelpie) | Controller | TASK-002 | `COMPLETED` |
| **TASK-005** | Server FastAPI & Orchestratore Coda GFF | Controller | TASK-003, TASK-004 | `COMPLETED` |
| **TASK-006** | Servizio Logging Strutturato & Reportistica | Controller | TASK-005 | `COMPLETED` |
| **TASK-007** | Driver UI Worker & Cattura Schermo | Worker | TASK-001 | `COMPLETED` |
| **TASK-008** | Runner Workflow End-to-End (14 Passaggi) | Worker | TASK-005, TASK-007 | `COMPLETED` |
| **TASK-009** | Test di Integrazione & Modalità Dry-Run | E2E | TASK-006, TASK-008 | `COMPLETED` |
| **TASK-010** | Guida al Setup & Configurazione Distribuita | Docs | TASK-009 | `COMPLETED` |
| **TASK-011** | Asset Icone & Motore Visione Locale a Template Matching | Worker | TASK-007 | `COMPLETED` |
| **TASK-012** | Integrazione WorkflowRunner con Visione Locale | Worker | TASK-008, TASK-011 | `COMPLETED` |
| **TASK-013** | Standalone Local Orchestrator & CLI Runner | Worker | TASK-011, TASK-012 | `COMPLETED` |
| **TASK-014** | Suite di Test Standalone Locale & Validazione E2E | Tests | TASK-013 | `COMPLETED` |
| **TASK-015** | Aggiornamento Documentazione Operativa Standalone & Quickstart | Docs | TASK-014 | `COMPLETED` |

---

## Dettaglio dei Task Completati (TASK-001 → TASK-011)

- **TASK-001:** Setup ambiente, `requirements.txt`, bundle `wheels/` per installazione offline, `controller/config.py`.
- **TASK-002:** Client Kelpie per interrogazioni al modello multimodale `gemini-3.7-flash`.
- **TASK-003:** Modulo deterministico `controller/text_cleaner.py` per la bonifica del testo con conservazione inviolabile di tag macro `@[std]...` e variabili `%str_...%`.
- **TASK-004:** Motore di visione basato su Vision LLM remoto per parsing canvas.
- **TASK-005:** Server FastAPI e orchestratore di sessione con supporto resume per architettura distribuita.
- **TASK-006:** Logger strutturato, scrittura `summary.json`, `execution.log`, `state.json` e cattura screenshot d'errore.
- **TASK-007:** Driver UI Windows per click, doppio click, hotkeys, digitazione e cattura screenshot selettivo.
- **TASK-008:** Runner sequenziale dei 14 passaggi del workflow ODIS Creator e gestione edge case popup `Validation error`.
- **TASK-009:** Test di integrazione distributed dry-run e verifica di conformità.
- **TASK-010:** Documentazione manuale per la topologia distribuita.
- **TASK-011:** Asset template icone in `assets/icons/` e motore di visione locale deterministico a Template Matching `LocalVisionEngine` in `worker/local_vision.py` con NMS e ordinamento top-to-bottom.
- **TASK-012:** Integrazione del provider vision in-process nel `WorkflowRunner`, con bypass del client HTTP in modalità locale e fallback remoto compatibile.
- **TASK-013:** Runner standalone locale `worker/standalone.py` con CLI argparse, orchestrazione persistente, resume, dry-run/live, gestione interruzioni e reportistica.
- **TASK-014:** Suite di test locale per template matching, deduplicazione, ordinamento, input canvas, batch standalone, resume, interruzioni, reportistica e validazione dell’intera suite.
- **TASK-015:** README e PROJECT-SPEC aggiornati con Standalone Local primaria, installazione offline, quickstart operativo, CLI, report, resume e troubleshooting.

---

## Dettaglio dei Nuovi Task Standalone Local (TASK-011 → TASK-015)

### TASK-011: Asset Icone & Motore Visione Locale a Template Matching (`worker/local_vision.py`)
- **Obiettivo:** 
  1. Creare la directory `assets/icons/` e predisporre i template grafici delle icone fisse di ODIS Creator:
     - `icon_message.png` (pergamena verde)
     - `icon_question.png` (punto interrogativo verde / fumetto)
     - `icon_comment.png` (foglio memo ciano)
  2. Implementare la classe `LocalVisionEngine` in `worker/local_vision.py` che:
     - Carica i template icona da `assets/icons/`.
     - Esegue il template matching bidimensionale sull'immagine del canvas (usando Pillow/PyScreeze/OpenCV).
     - Applica deduplicazione per cluster di vicinanza (distanza minima tra rilevamenti per evitare falsi positivi doppi).
     - Converte le coordinate trovate in coordinate normalizzate `[0.0, 1.0]` e coordinate assolute a schermo.
     - Ordina i blocchi rilevati per sequenza di flusso top-to-bottom ($Y$ crescente, poi $X$).
- **Criteri di Accettazione:**
  - `LocalVisionEngine` rileva correttamente blocchi Message, Question e Comment su canvas di test con accuratezza >= 95%.
  - Restituisce istanze validate di `DetectedBlock`.
  - Zero chiamate di rete o dipendenze da server esterni.

---

### TASK-012: Integrazione WorkflowRunner con Visione Locale
- **Obiettivo:**
  1. Aggiornare `worker/workflow_runner.py` per accettare direttamente `LocalVisionEngine` o un vision provider in-process.
  2. Consentire l'esecuzione del Passo 8 (Espansione Canvas & Scansione) tramite il motore locale senza passare per `ControllerClient` HTTP quando si opera in modalità standalone.
  3. Mantenere la compatibilità con la modalità remota se configurata.
- **Criteri di Accettazione:**
  - `WorkflowRunner.step_8_expand_canvas_and_scan()` funziona correttamente sia con motore locale che con client HTTP.
  - Tutti i test esistenti in `tests/test_workflow_runner.py` continuano a passare con esito positivo.

---

### TASK-013: Standalone Local Orchestrator & CLI Runner (`worker/standalone.py`)
- **Obiettivo:**
  1. Implementare il punto di ingresso autonomo `worker/standalone.py` per l'esecuzione su PC Lamborghini.
  2. Integrare in un unico loop locale:
     - Inizializzazione sessione e logger in `logs/run_YYYY-MM-DD_HH-mm-ss/`.
     - Caricamento lista GFF da `data/input_gff.txt`.
     - Supporto per il resume automatico da `state.json` (skip dei task già completati `SUCCESS`).
     - Esecuzione sequenziale del 14-step `WorkflowRunner` per ciascuna GFF.
     - Aggiornamento real-time di `state.json` ed `execution.log`.
     - Generazione del report finale `summary.json`.
  3. Interfaccia a riga di comando (CLI argparse):
     - `--dry-run`: Esegue la scansione e simulazione senza inviare click fisici.
     - `--no-dry-run` / `--live`: Modalità di produzione reale su ODIS Creator.
     - `--input-file`, `-i`: Percorso personalizzato del file input GFF (default: `data/input_gff.txt`).
     - `--max-tasks`, `-n`: Limite massimo di task da elaborare.
     - `--force-new`: Avvia una nuova sessione azzerando il resume.
     - `--verbose`, `-v`: Abilita logging a livello DEBUG.
- **Criteri di Accettazione:**
  - `python -m worker.standalone --dry-run` esegue l'intero ciclo di elaborazione batch localmente senza avviare server FastAPI o effettuare chiamate HTTP.
  - Gestione corretta dei segnali di interruzione (Ctrl+C) con salvataggio dello stato.

---

### TASK-014: Suite di Test Standalone Locale & Validazione E2E
- **Obiettivo:**
  1. Creare `tests/test_local_vision.py` con test completi per `LocalVisionEngine` (caricamento template, rilevamento, deduplicazione, ordinamento sequenziale, gestione canvas vuoto).
  2. Creare `tests/test_standalone.py` con test di integrazione per il runner `worker/standalone.py` (dry-run batch, resume da sessione precedente, interruzioni, reportistica).
  3. Verificare che l'intera suite di test del progetto passi al 100%.
- **Criteri di Accettazione:**
  - `python -m pytest` esegue con 100% test passati senza errori o regressioni.

---

### TASK-015: Aggiornamento Documentazione Operativa Standalone & Quickstart
- **Obiettivo:**
  1. Aggiornare `README.md` e `PROJECT-SPEC.md` evidenziando la modalità **Standalone Local (PC Lamborghini)** come configurazione primaria e raccomandata.
  2. Fornire una guida passo-passo ultra-chiara:
     - Copia cartella su PC Lamborghini.
     - Installazione offline delle dipendenze via `pip install --no-index --find-links=wheels -r requirements.txt`.
     - Popolamento di `data/input_gff.txt`.
     - Avvio test simulato: `python -m worker.standalone --dry-run`.
     - Avvio elaborazione effettiva: `python -m worker.standalone`.
     - Consultazione report e ripristino in caso di arresto.
- **Criteri di Accettazione:**
  - Manuale chiaro, privo di ambiguità e pronto per l'uso immediato da parte dell'operatore su PC Lamborghini.
