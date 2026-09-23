# DESIGN.md – Architettura Tecnica e Specifiche di Sistema

## 1. Architettura Generale dei Moduli

Il sistema **ODIS Obliterator** è composto da due package software modulari:

```text
odis-obliterator/
├── controller/                   # In esecuzione su PC EDAG (VPN Germania)
│   ├── app.py                    # Server FastAPI & Router REST
│   ├── config.py                 # Gestione configurazioni (IP, porte, modelli)
│   ├── orchestrator.py           # Gestione coda GFF, stati e resume
│   ├── kelpie_client.py          # Client per Kelpie AI Gateway (gemini-3.7-flash)
│   ├── vision_engine.py          # Analisi screenshot, prompt e coordinate
│   ├── text_cleaner.py           # Logica di pulizia testo e conservazione tag
│   └── logger_service.py         # Scrittura log strutturati e report JSON
│
├── worker/                       # In esecuzione su PC Lamborghini
│   ├── agent.py                  # Client worker (loop di polling ed esecuzione)
│   ├── ui_driver.py              # Azioni mouse/tastiera (PyAutoGUI / PyWinAuto / Win32)
│   ├── screen_capture.py         # Acquisizione screenshot ad alta precisione
│   └── workflow_runner.py        # Sequenza dei 14 passaggi UI
│
├── data/
│   └── input_gff.txt             # Lista GFF da processare (1 per riga)
└── logs/                         # Report di esecuzione e screenshot di errore
```

---

## 2. Specifiche API REST (Controller ↔ Worker)

Il Controller espone su `http://0.0.0.0:8000` (raggiungibile dal Worker via IP LAN Wi-Fi) i seguenti endpoint:

### 2.1 `GET /api/v1/health`
Verifica connettività e stato del Controller e del daemon Kelpie.
- **Response 200:** `{"status": "ok", "kelpie": "connected", "model": "gemini-3.7-flash"}`

### 2.2 `POST /api/v1/session/start`
Inizializza una nuova sessione di elaborazione batch o riprende la sessione interrotta.
- **Response 200:** `{"session_id": "run_2026-09-22_15-00-00", "total_gff": 842, "pending": 842}`

### 2.3 `GET /api/v1/tasks/next`
Fornisce al Worker il prossimo nome GFF da cercare ed elaborare.
- **Response 200:** `{"task_id": "GFF_042", "name": "A16_4LA_91____1_518_88_Check_battery"}`
- **Response 204:** Nessun task rimasto in coda.

### 2.4 `POST /api/v1/vision/analyze-canvas`
Invia lo screenshot del canvas grafico in Base64 per individuare i blocchi target.
- **Request Body:**
  ```json
  {
    "task_id": "GFF_042",
    "image_base64": "data:image/png;base64,...",
    "canvas_bbox": {"x": 510, "y": 120, "width": 1400, "height": 900}
  }
  ```
- **Response 200:**
  ```json
  {
    "blocks": [
      {
        "type": "MESSAGE",
        "relative_x": 0.45,
        "relative_y": 0.32,
        "label": "Message With this test..."
      },
      {
        "type": "COMMENT",
        "relative_x": 0.52,
        "relative_y": 0.58,
        "label": "Comment 1 = statisch"
      },
      {
        "type": "QUESTION",
        "relative_x": 0.61,
        "relative_y": 0.75,
        "label": "Question Yes/No,..."
      }
    ]
  }
  ```

### 2.5 `POST /api/v1/text/clean`
Esegue la depurazione del testo rimuovendo "Lamborghini" con validazione sintattica.
- **Request Body:**
  ```json
  {
    "block_type": "MESSAGE",
    "raw_text": "- Ignore the event memory Lamborghini entry\n\n@[std]AU00003_Ende"
  }
  ```
- **Response 200:**
  ```json
  {
    "cleaned_text": "- Ignore the event memory entry\n\n@[std]AU00003_Ende",
    "modified": true
  }
  ```

### 2.6 `POST /api/v1/tasks/complete`
Notifica la conclusione della GFF con metriche ed eventuali screenshot d'errore.
- **Request Body:**
  ```json
  {
    "task_id": "GFF_042",
    "status": "SUCCESS",
    "blocks_modified": {"message": 1, "comment": 1, "question": 0},
    "duration_seconds": 18.4,
    "error_details": null,
    "error_screenshot_base64": null
  }
  ```

---

## 3. Motore di Visione & Coordinate (Kelpie / `gemini-3.7-flash`)

### 3.1 Normalizzazione Coordinate
- L'LLM riceve lo screenshot dell'area canvas e restituisce coordinate $(X_{rel}, Y_{rel})$ in formato percentuale normalizzato $[0.0, 1.0]$.
- Il Worker mappa le coordinate reali a schermo con:
  $$X_{screen} = X_{canvas\_origin} + (X_{rel} \times W_{canvas})$$
  $$Y_{screen} = Y_{canvas\_origin} + (Y_{rel} \times H_{canvas})$$

### 3.2 Prompt Ingegnerizzato per `gemini-3.7-flash`
Il prompt impone un output JSON rigoroso e identifica unicamente i blocchi:
- `MESSAGE`: Icona pergamena verde con bordo piegato.
- `QUESTION`: Icona con punto interrogativo verde / fumetto.
- `COMMENT`: Icona note/commento ciano.
Ignora categoricamente rombi `If`, rettangoli gialli `Subroutine`, `Read file` e `Write file`.

---

## 4. Macchina a Stati del Worker

```text
[0. IDLE / HOME] 
       │
       ▼
[1. SEARCHING] ──(Not Found)──► [LOG ERROR] ──► [RETURN HOME]
       │
       ▼
[2. OPENING_TREE & TEST_SEQUENCE]
       │
       ▼
[3. MINIMIZING_PANELS & EXPANDING_CANVAS]
       │
       ▼
[4. SCANNING_CANVAS & DETECTING_BLOCKS]
       │
       ▼
[5. EDITING_BLOCKS (Message/Question/Comment)] ◄──► [HANDLE VALIDATION ERROR POPUP]
       │
       ▼
[6. SAVING_TEST_MODULE]
       │
       ▼
[7. ADDING_VERSION_COMMENT ("Removed Lamborghini labels")]
       │
       ▼
[8. SAVING_OBJECT & RETURNING_HOME] ──► [NOTIFY CONTROLLER SUCCESS]
```

---

## 5. Schema di Logging e Reporting

Alla fine di ogni batch o in real-time, il Controller aggiorna:
- `logs/run_YYYY-MM-DD_HH-mm-ss/summary.json`:
  ```json
  {
    "total": 842,
    "success": 839,
    "failed": 3,
    "skipped": 0,
    "start_time": "2026-09-22T15:00:00Z",
    "end_time": "2026-09-22T18:45:00Z",
    "total_blocks_modified": 1420
  }
  ```
- `logs/run_YYYY-MM-DD_HH-mm-ss/execution.log`: Log cronologico dettagliato riga per riga.
- `logs/run_YYYY-MM-DD_HH-mm-ss/errors/`: Screenshot `.png` nominati con `[Nome_Funzione]_[timestamp].png` in caso di errore/blocco.
