# DESIGN.md – Architettura Tecnica e Specifiche di Sistema

## 1. Architettura Generale dei Moduli

**ODIS Obliterator** adotta un'architettura modulare incentrata sull'esecuzione **Standalone Locale sul PC Lamborghini** (senza alcuna dipendenza di rete o firewall), preservando la compatibilità con la modalità distribuita opzionale.

```text
odis-obliterator/
├── assets/
│   └── icons/                    # Template grafici delle icone fisse di ODIS Creator
│       ├── icon_message.png      # Template icona Message (pergamena verde)
│       ├── icon_question.png     # Template icona Question (punto interrogativo verde)
│       └── icon_comment.png      # Template icona Comment (blocco note ciano)
│
├── worker/                       # Esecuzione Standalone Locale (PC Lamborghini)
│   ├── standalone.py             # CLI Runner Standalone (Orchestrazione + Workflow locale)
│   ├── local_vision.py           # Motore di Visione Locale a Template Matching (Zero AI/Offline)
│   ├── workflow_runner.py        # Sequenza dei 14 passaggi UI su ODIS Creator
│   ├── ui_driver.py              # Azioni mouse/tastiera (PyAutoGUI / Windows Input)
│   ├── screen_capture.py         # Acquisizione screenshot ad alta precisione (Pillow)
│   └── agent.py                  # Client worker per modalità distribuita opzionale
│
├── controller/                   # Componenti Logici Condivisi & Servizi Ausiliari
│   ├── text_cleaner.py           # Logica di pulizia testo deterministica e conservazione tag
│   ├── orchestrator.py           # Gestore coda GFF, stati persistenti e resume
│   ├── logger_service.py         # Scrittura log strutturati, report JSON e screenshot errori
│   ├── config.py                 # Gestione configurazioni e parametri di runtime
│   ├── app.py                    # Server FastAPI (modalità distribuita legacy/opzionale)
│   ├── kelpie_client.py          # Client Kelpie AI Gateway (opzionale se connesso a EDAG)
│   └── vision_engine.py          # Motore Vision LLM remoto (opzionale)
│
├── wheels/                       # Archivio binari per installazione offline al 100%
├── data/
│   └── input_gff.txt             # Lista delle funzioni GFF da elaborare (1 per riga)
└── logs/                         # Report di esecuzione, sessioni e screenshot di errore
```

---

## 2. Motore di Riconoscimento Visivo Locale (`LocalVisionEngine`)

### 2.1 Principio di Funzionamento (Template Matching)
Nell'editor `Test Module` di ODIS Creator, i blocchi funzionali presentano icone standard fisse ad alta visibilità:
- **`MESSAGE`**: Icona pergamena verde con bordo superiore piegato.
- **`QUESTION`**: Icona punto interrogativo verde / fumetto.
- **`COMMENT`**: Icona memo/blocco note ciano.

Il modulo `worker/local_vision.py` acquisisce lo screenshot dell'area canvas ed esegue una ricerca bidimensionale di pattern tramite algoritmi di correlazione cross-template (PyScreeze / Pillow / OpenCV):

```text
┌──────────────────────────────────────────────┐
│ Area Canvas Screenshot (BBox)                │
│                                              │
│   ┌────────────┐                             │
│   │ [Icon_Msg] │ ──► Riconosciuto: MESSAGE   │  Coordinate: (X_rel: 0.45, Y_rel: 0.32)
│   └────────────┘                             │
│         │                                    │
│         ▼                                    │
│   ┌────────────┐                             │
│   │ [Icon_Ques]│ ──► Riconosciuto: QUESTION  │  Coordinate: (X_rel: 0.52, Y_rel: 0.58)
│   └────────────┘                             │
└──────────────────────────────────────────────┘
```

### 2.2 Deduplicazione e Ordinamento
1. **Non-Maximum Suppression (NMS) / Proximity Clustering:** Se una singola icona genera rilevamenti multipli ravvicinati a causa di pixel di bordo, il motore raggruppa le coordinate entro una distanza raggio $R = 15\text{px}$, mantenendo il punto centrale.
2. **Normalizzazione Coordinate:**
   $$X_{rel} = \frac{X_{match} - X_{canvas\_origin}}{W_{canvas}}, \quad Y_{rel} = \frac{Y_{match} - Y_{canvas\_origin}}{H_{canvas}}$$
3. **Ordinamento Sequenza di Flusso:** I blocchi rilevati vengono ordinati per coordinata $Y$ crescente (dall'alto verso il basso), e secondariamente per coordinata $X$ (da sinistra a destra), riproducendo fedelmente l'ordine naturale del diagramma di flusso.

---

## 3. Runner Standalone Locale (`worker/standalone.py`)

Il modulo `standalone.py` consente di eseguire l'intera pipeline batch in modo completamente autonomo su un singolo PC:

### 3.1 Diagramma di Flusso Standalone

```text
[Avvio CLI: python -m worker.standalone]
                 │
                 ▼
     [Caricamento Configurazione & Setup Logs]
                 │
                 ▼
     [Verifica / Resume Sessione da logs/state.json]
                 │
                 ▼
     [Caricamento Coda da data/input_gff.txt]
                 │
       ┌─────────┴─────────┐
       ▼                   ▼
 (Coda vuota)      (Task PENDING disponibile)
       │                   │
   [Fine Batch]            ▼
       │           [Passo 0-7: Ricerca & Apertura Test Module]
       ▼                   │
 [Report Finale]           ▼
                   [Passo 8: Screenshot Canvas & LocalVisionEngine]
                           │
                           ▼
                   [Passi 9-11: Loop sui blocchi rilevati]
                           ├─ Doppio click su coordinate blocco
                           ├─ Estrazione testo (Ctrl+A / Ctrl+C)
                           ├─ Bonifica deterministica (TextCleaner)
                           ├─ Se modificato: incolla (Ctrl+V) & OK
                           └─ Gestione popup Validation error
                           │
                           ▼
                   [Passo 12: Chiusura Test Module & Save]
                           │
                           ▼
                   [Passo 13: Inserimento Version Comment: "Removed Lamborghini labels"]
                           │
                           ▼
                   [Passo 14: Chiusura Oggetto & Ritorno a Home]
                           │
                           ▼
                   [Salvataggio Stato SUCCESS in state.json]
                           │
                           └─► (Passa al task successivo)
```

### 3.2 Modalità Operative CLI

| Comando | Descrizione |
|---|---|
| `python -m worker.standalone --dry-run` | **Simulazione sicura:** Esegue tutta la sequenza e l'analisi visiva senza inviare click o salvataggi su ODIS |
| `python -m worker.standalone` | **Produzione:** Esegue la bonifica batch reale sui file ODIS |
| `python -m worker.standalone --max-tasks 5` | Esegue un batch limitato a 5 funzioni per validazione rapida |
| `python -m worker.standalone --force-new` | Inizializza una nuova sessione ignorando il resume precedente |

---

## 4. Macchina a Stati del Workflow UI (14 Passaggi)

```text
[0. IDLE / HOME] 
       │
       ▼
[1. SEARCHING] ──(Not Found)──► [LOG NOT_FOUND] ──► [RETURN HOME]
       │
       ▼
[2. OPENING_TREE & TEST_SEQUENCE]
       │
       ▼
[3. MINIMIZING_PANELS & EXPANDING_CANVAS]
       │
       ▼
[4. SCANNING_CANVAS_LOCAL_TEMPLATE_MATCHING]
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
[8. SAVING_OBJECT & RETURNING_HOME] ──► [UPDATE STATE SUCCESS]
```

---

## 5. Schema di Logging e Reporting

La cartella `logs/run_YYYY-MM-DD_HH-mm-ss/` contiene:
- `summary.json`:
  ```json
  {
    "total": 842,
    "success": 839,
    "failed": 3,
    "skipped": 0,
    "start_time": "2026-09-24T10:00:00Z",
    "end_time": "2026-09-24T13:45:00Z",
    "total_blocks_modified": 1420,
    "is_completed": true
  }
  ```
- `state.json`: Mappa puntuale dello stato di avanzamento di ogni singola GFF per il supporto resume.
- `execution.log`: Traccia cronologica con timestamp di ogni step eseguito.
- `errors/`: Cattura automatica di screenshot nominati `[Nome_GFF]_[timestamp].png` in caso di errore UI.

---

## 6. Procedura di Installazione 100% Offline (PC Lamborghini)

Grazie alla cartella `wheels/` inclusa nel repository, l'installazione su PC Lamborghini non richiede connessione internet:

```powershell
# Esecuzione su PC Lamborghini (prompt PowerShell / CMD)
cd C:\percorso\odis-obliterator
python -m pip install --no-index --find-links=wheels -r requirements.txt
```
