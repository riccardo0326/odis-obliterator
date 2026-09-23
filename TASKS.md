# TASKS.md – Piano di Implementazione Dettagliato

Elenco ordinato dei task atomici per gli sviluppatori / agenti di codifica. Ogni task è autocontenuto, testabile e tracciabile.

---

## Tabella di Avanzamento

| Task ID | Titolo | Componente | Dipendenze | Stato |
|---|---|---|---|---|
| **TASK-001** | Scaffolding Progetto & Configurazione | Shared | Nessuna | `COMPLETED` |
| **TASK-002** | Client Kelpie Gateway (`gemini-3.7-flash`) | Controller | TASK-001 | `COMPLETED` |
| **TASK-003** | Modulo Pulizia Testo (`text_cleaner`) & Test | Controller | TASK-001 | `COMPLETED` |
| **TASK-004** | Motore Visione & Mappatura Coordinate | Controller | TASK-002 | `COMPLETED` |
| **TASK-005** | Server FastAPI & Orchestratore Coda GFF | Controller | TASK-003, TASK-004 | `COMPLETED` |
| **TASK-006** | Servizio Logging Strutturato & Reportistica | Controller | TASK-005 | `COMPLETED` |
| **TASK-007** | Driver UI Worker & Cattura Schermo | Worker | TASK-001 | `COMPLETED` |
| **TASK-008** | Runner Workflow End-to-End (14 Passaggi) | Worker | TASK-005, TASK-007 | `COMPLETED` |
| **TASK-009** | Test di Integrazione & Modalità Dry-Run | E2E | TASK-006, TASK-008 | `COMPLETED` |
| **TASK-010** | Guida al Setup, Configurazione di Rete & Manuale Utente | Docs | TASK-009 | `COMPLETED` |

---

## Dettaglio dei Task

### TASK-001: Scaffolding Progetto & Configurazione
- **Obiettivo:** Creare la struttura directory di progetto, configurare i file di dipendenze `requirements.txt` (FastAPI, Uvicorn, Pydantic, Pillow, PyAutoGUI, Requests, PyTest) e il modulo `controller/config.py` con caricamento variabili d'ambiente (host, porta, timeout, modello predefinito `gemini-3.7-flash`).
- **Criteri di Accettazione:** Ambiente virtuale installabile senza conflitti, `config.py` validato tramite test unitario.

---

### TASK-002: Client Kelpie Gateway (`gemini-3.7-flash`)
- **Obiettivo:** Sviluppare `controller/kelpie_client.py` per gestire l'autenticazione tramite `kelpie auth print-access-token` o reverse proxy locale `kelpie serve run -p 18080`, e inviare prompt multimodali (testo + immagine base64) all'endpoint Kelpie/Gemini.
- **Criteri di Accettazione:** Test di chiamata con invio di un'immagine di test a `gemini-3.7-flash` e ricezione corretta della risposta JSON.

---

### TASK-003: Modulo Pulizia Testo (`text_cleaner`) & Test
- **Obiettivo:** Implementare in `controller/text_cleaner.py` la funzione di rimozione della parola target `"Lamborghini"` (case-insensitive, con gestione corretta di spazi e punteggiatura) garantendo l'inviolabilità assoluta di tag come `@[std]...` e variabili come `%str_...%`.
- **Criteri di Accettazione:** Suite di test pytest completa con almeno 15 casi reali (es. blocchi Message, Question e Comment).

---

### TASK-004: Motore Visione & Mappatura Coordinate
- **Obiettivo:** Implementare in `controller/vision_engine.py` il parser visuale del canvas. Invia lo screenshot a `gemini-3.7-flash` con system prompt specializzato per identificare blocchi `MESSAGE`, `QUESTION`, `COMMENT` e restituire le coordinate relative normalizzate `[0.0, 1.0]`.
- **Criteri di Accettazione:** Parsing affidabile degli screenshot reali raccolti durante la fase di analisi.

---

### TASK-005: Server FastAPI & Orchestratore Coda GFF
- **Obiettivo:** Implementare in `controller/app.py` e `controller/orchestrator.py` gli endpoint REST (`/api/v1/health`, `/api/v1/session/start`, `/api/v1/tasks/next`, `/api/v1/vision/analyze-canvas`, `/api/v1/text/clean`, `/api/v1/tasks/complete`) con supporto per resume automatico in caso di riavvio.
- **Criteri di Accettazione:** OpenAPI docs (`/docs`) funzionante e test endpoint con mock client.

---

### TASK-006: Servizio Logging Strutturato & Reportistica
- **Obiettivo:** Sviluppare `controller/logger_service.py` per registrare i log operativi e generare in `logs/run_YYYY-MM-DD_HH-mm-ss/` i file `summary.json`, `execution.log` e la cartella `errors/` con gli screenshot d'errore.
- **Criteri di Accettazione:** Report JSON con conteggi corretti di modifiche, tempi e stati.

---

### TASK-007: Driver UI Worker & Cattura Schermo
- **Obiettivo:** Sviluppare in `worker/ui_driver.py` e `worker/screen_capture.py` le primitive di interazione Windows (click, doppio click, click destro, inserimento testo, hotkeys e screenshot selettivo di bounding box).
- **Criteri di Accettazione:** Esecuzione affidabile di click simulati e cattura canvas in memoria.

---

### TASK-008: Runner Workflow End-to-End (14 Passaggi)
- **Obiettivo:** Implementare in `worker/workflow_runner.py` l'esecuzione sequenziale dei 14 passaggi documentati in `WORKFLOW.md`:
  1. Ricerca full text (Passi 1-3)
  2. Apertura funzione e alberatura (Passi 4-6)
  3. Minimizzazione pannelli ed espansione canvas (Passi 7-8)
  4. Scansione ed editing blocchi Message/Comment/Question (Passi 9-11)
  5. Chiusura modulo, Version comment `"Removed Lamborghini labels"`, chiusura finale (Passi 12-14)
  6. Handler per il popup modale `Validation error` (Edge Case).
- **Criteri di Accettazione:** Esecuzione del ciclo completo su una funzione di test con ritorno allo stato Home.

---

### TASK-009: Test di Integrazione & Modalità Dry-Run
- **Obiettivo:** Configurare la modalità `DRY_RUN = True` (scansione ed evidenziazione senza salvataggio su ODIS) e condurre test di integrazione tra PC EDAG (Controller) e PC Lamborghini (Worker) tramite rete Wi-Fi.
- **Criteri di Accettazione:** Esecuzione con esito positivo di una sessione batch di 3 GFF in Dry-Run.

---

### TASK-010: Guida al Setup, Configurazione di Rete & Manuale Utente
- **Obiettivo:** Creare la documentazione operativa completa (`README.md` e guida di deployment) che spieghi:
  1. Setup ambiente su PC EDAG (avvio Kelpie, avvio Controller FastAPI con binding su IP Wi-Fi).
  2. Setup ambiente su PC Lamborghini (installazione dipendenze minime Worker, configurazione IP del Controller).
  3. Istruzioni operative per l'inserimento della lista GFF in `data/input_gff.txt` e l'avvio del batch.
  4. Modalità di esecuzione Dry-Run vs Produzione.
  5. Risoluzione dei problemi comuni e consultazione dei log in `/logs`.
- **Criteri di Accettazione:** File `README.md` esaustivo e comprensibile per consentire l'avvio autonomo dell'automazione da parte di qualsiasi operatore.

