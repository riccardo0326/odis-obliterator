# ODIS Creator – GFF Bulk Text Removal

## Project Specification – Version 1.0

### 1. Obiettivo del progetto

Realizzare un sistema di automazione modulare e affidabile per ODIS Creator, in grado di elaborare in modalità batch/semi-automatica un elevato numero di GFF / Diagnostic Objects (es. 800+ elementi da lista `input_gff.txt`).

L'obiettivo primario è la rimozione puntuale e pulita del riferimento testuale **"Lamborghini"** dai blocchi funzionali:
* **Message** (finestre informative e di notifica ODIS Service)
* **Question** (finestre con quesiti e opzioni decisionali per il tester)
* **Comment** (commenti e annotazioni interne della struttura)

In aggiunta, il sistema provvede alla storicizzazione automatica inserendo nel campo metadati `Version comment:` la dicitura standard:
> `Removed Lamborghini labels`

Il sistema mantiene la massima tracciabilità di ogni operazione ed errore tramite log strutturati e screenshot diagnostici salvati nella cartella `/logs`.

---

### 2. Architettura del Sistema

Il sistema adotta un'architettura distribuita a due macchine:

```text
┌────────────────────────────────────────────────────────┐
│ PC 1: Worker (Lamborghini VPN / ODIS Creator)          │
│ - ODIS Creator (Ambiente di editing grafico)          │
│ - Power Automate Desktop / Python Worker              │
│ - Esecuzione comandi UI, coordinate e inserimento testi│
└──────────────────────────▲─────────────────────────────┘
                           │  Comunicazione Diretta LAN HTTP
                           │  (stessa rete Wi-Fi locale)
┌──────────────────────────▼─────────────────────────────┐
│ PC 2: Controller & AI Brain (EDAG VPN / Germania)      │
│ - Python Controller (FastAPI / Typer / Orchestrator)   │
│ - Coda di lavoro GFF (`input_gff.txt`)                 │
│ - Kelpie Gateway (`gemini-3.7-flash` con Vision)       │
│ - Motore di visione/coordinate per navigazione canvas  │
│ - Logging & Reporting (`/logs`)                        │
└────────────────────────────────────────────────────────┘
```

#### 2.1 Componente Worker (PC Lamborghini)
- Esegue in primo piano su Windows con ODIS Creator aperto.
- Esegue la Parte A deterministica (ricerca, apertura GFF, espansione albero).
- Cattura gli screenshot dell'area canvas / flowchart per il Controller.
- Riceve le istruzioni sulle coordinate dei click da effettuare o sui campi testo da modificare.
- Esegue il salvataggio e la chiusura della funzione.

#### 2.2 Componente Controller & AI Gateway (PC EDAG)
- Gestisce la sequenza dei task da `input_gff.txt`.
- Espone API REST / socket / file-watcher per dialogare con il Worker.
- Interroga **Kelpie** (con modello multimodale `gemini-3.7-flash`) passando l'immagine del canvas per identificare coordinate precise di blocchi (`Message`, `Question`, `Comment`) o risolvere edge cases.
- Registra ogni azione, timestamp e stato finale in `/logs`.

---

### 3. Workflow Operativo End-to-End

Il ciclo standard per ciascuna funzione è strutturato in 14 passaggi:

1. **Home / Editing View:** Verifica dello stato iniziale pronto con modulo `Editing` attivo.
2. **Apertura Ricerca:** Click sull'11° pulsante nella toolbar in alto (icona *torcia gialla*).
3. **Full Text Search:** Selezione del tab `Full Text Search` e inserimento del nome completo della funzione in `Search text:`, avvio con `OK`.
4. **Chiusura Notifica Fine Ricerca:** Pressione del tasto `OK` sul popup modale `Search ended`.
5. **Apertura Funzione da Risultati:** Doppio click sulla riga corrispondente (`Function test`) nella griglia `Search Results`.
6. **Selezione Posizione d'Uso (`Usage locations`):** Selezione del primo risultato nella gerarchia, click su `OK` e attesa caricamento albero in `Knowledge base navigator`.
7. **Apertura Test Sequence:** Click destro sull'area di sfondo grigio della scheda aperta e selezione della voce `Test sequence`.
8. **Minimizzazione Pannelli:** Click su *Minimize* (`_`) su `Palette`, `Search Results` e `Recently-Used Objects` per liberare l'area canvas.
9. **Espansione Canvas & Scansione:** Click sul fondo bianco della colonna centrale dei Test Step per visualizzare l'intero diagramma di flusso.
10. **Individuazione ed Editing Blocchi Target:**
    * **`Message`**: Apertura doppio click, rimozione di "Lamborghini" (preservando tag come `@[std]...`), conferma con `OK`.
    * **`Comment`**: Apertura doppio click, rimozione di "Lamborghini", conferma con `OK`.
    * **`Question`**: Apertura doppio click, rimozione di "Lamborghini" (preservando variabili come `%str_...%`), conferma con `OK`.
11. **Chiusura Test Module & Salvataggio:** Click sulla `X` della tab `[Nome_Funzione] (Test module)` e click su `Save`.
12. **Compilazione Version Comment:** Click sul box a sfondo giallo `Version comment:` e digitazione di `Removed Lamborghini labels`.
13. **Chiusura Scheda Funzione & Salvataggio Finale:** Click sulla `X` della tab principale `[Nome_Funzione]`, click su `Save` e ritorno a Home.
14. **Passaggio alla GFF Successiva:** Aggiornamento del registro di log e caricamento del record successivo.

---

### 4. Gestione degli Edge Case & Error Recovery

* **Edge Case 1: `Validation error` Popup:** Se premendo `OK` compare l'errore modale *"Dialog validation failed"*, il sistema clicca `OK` sul popup di errore e corregge il blocco prima di proseguire.
* **Edge Case 2: Nessun risultato di ricerca:** Se la funzione non viene trovata o compare timeout, lo stato viene marcato come `NOT_FOUND` e si passa alla successiva senza bloccare il batch.
* **Edge Case 3: Blocco funzione / Read-Only:** Se la funzione è bloccata o in sola lettura, viene marcata come `LOCKED` con screenshot diagnostico in `/logs`.
* **Edge Case 4: ODIS bloccato / Crash:** Meccanismo di watchdog con timeout; se ODIS non risponde per oltre 60s, il Controller genera un allarme critico.

---

### 5. Configurazione Kelpie & Modelli AI

* **Gateway:** Kelpie CLI / Daemon (`https://oauth.ai.container.edag`)
* **Modello Primario:** `gemini-3.7-flash` (vision multimodale per analisi canvas ad alta velocità).
* **Modelli Alternativi:** `gemini-3.8-flash`, `gpt-5.6-luna-gwc`, `claude-haiku-4-5`.
* **Autenticazione:** Token JWT estratto via `kelpie auth print-access-token` o proxy locale `kelpie serve run -p 18080`.

---

### 6. Struttura Dati Input & Output

* **Input:** `data/input_gff.txt` (un nome funzione per riga).
* **Logs & Reports:** `logs/run_YYYY-MM-DD_HH-mm-ss/`
  * `summary.json`: Metriche complessive (totale, successo, falliti, saltati, tempo).
  * `execution.log`: Log testuale sequenziale di ogni operazione.
  * `errors/`: Screenshot catturati in corrispondenza di anomalie.
