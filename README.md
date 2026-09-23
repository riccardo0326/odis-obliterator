# ODIS Obliterator – Manuale Operativo & Guida al Setup

Sistema distribuito di automazione robotica e intelligenza artificiale per l'elaborazione batch e la bonifica testuale delle funzioni diagnostiche (GFF / Diagnostic Objects) in **ODIS Creator**.

---

## Indice dei Contenuti

1. [Panoramica e Obiettivo del Progetto](#1-panoramica-e-obiettivo-del-progetto)
2. [Architettura Distribuita & Topologia di Rete](#2-architettura-distribuita--topologia-di-rete)
3. [Setup Ambiente su PC EDAG (Controller & AI Brain)](#3-setup-ambiente-su-pc-edag-controller--ai-brain)
   - [3.1 Requisiti e Installazione](#31-requisiti-e-installazione)
   - [3.2 Configurazione Kelpie AI Gateway (`gemini-3.7-flash`)](#32-configurazione-kelpie-ai-gateway-gemini-37-flash)
   - [3.3 Configurazione Variabili d'Ambiente](#33-configurazione-variabili-dambiente)
   - [3.4 Avvio del Server Controller](#34-avvio-del-server-controller)
   - [3.5 Verifica dello Stato e Documentazione Swagger](#35-verifica-dello-stato-e-documentazione-swagger)
4. [Setup Ambiente su PC Lamborghini (Worker UI)](#4-setup-ambiente-su-pc-lamborghini-worker-ui)
   - [4.1 Requisiti e Installazione](#41-requisiti-e-installazione)
   - [4.2 Preparazione dell'Ambiente ODIS Creator](#42-preparazione-dellambiente-odis-creator)
   - [4.3 Test di Connettività verso il Controller](#43-test-di-connettività-verso-il-controller)
5. [Guida Operativa: Esecuzione del Batch](#5-guida-operativa-esecuzione-del-batch)
   - [5.1 Preparazione della Coda GFF (`data/input_gff.txt`)](#51-preparazione-della-coda-gff-datainput_gfftxt)
   - [5.2 Esecuzione in Modalità Dry-Run (Simulazione Sicura)](#52-esecuzione-in-modalità-dry-run-simulazione-sicura)
   - [5.3 Esecuzione in Modalità Produzione (Live)](#53-esecuzione-in-modalità-produzione-live)
   - [5.4 Parametri e Opzioni CLI del Worker](#54-parametri-e-opzioni-cli-del-worker)
6. [Workflow Operativo End-to-End (14 Passaggi)](#6-workflow-operativo-end-to-end-14-passaggi)
   - [6.1 Sintesi dei Passaggi](#61-sintesi-dei-passaggi)
   - [6.2 Invarianti e Conservazione dei Tag](#62-invarianti-e-conservazione-dei-tag)
7. [Logging, Reportistica & Ripristino Sessione (Resume)](#7-logging-reportistica--ripristino-sessione-resume)
   - [7.1 Struttura della Cartella `/logs`](#71-struttura-della-cartella-logs)
   - [7.2 Ripristino Automatico da Interruzione (Resume)](#72-ripristino-automatico-da-interruzione-resume)
8. [Risoluzione dei Problemi Comuni (Troubleshooting)](#8-risoluzione-dei-problemi-comuni-troubleshooting)
9. [Esecuzione dei Test Unitari e di Integrazione](#9-esecuzione-dei-test-unitari-e-di-integrazione)

---

## 1. Panoramica e Obiettivo del Progetto

**ODIS Obliterator** è stato concepito per automatizzare la bonifica testuale massiva su oltre 800 funzioni diagnostiche all'interno dell'editor grafico **ODIS Creator**.

### Obiettivi Principali:
- **Rimozione selettiva del termine `"Lamborghini"`** dai blocchi funzionali:
  - `Message` (messaggi informativi e istruzioni operatore per ODIS Service)
  - `Question` (domande interattive con opzioni Yes/No o selezione da lista)
  - `Comment` (commenti e annotazioni interne alla struttura)
- **Inviolabilità dei metadati tecnici:** conservazione rigorosa di tag macro (es. `@[std]AU00003_Ende`) e variabili di sistema (es. `%str_Bauteil%`, `%str_Steuergeraet%`).
- **Tracciabilità automatica delle versioni:** inserimento della nota standard `"Removed Lamborghini labels"` nel campo `Version comment:`.
- **Controllo visivo con Vision LLM:** analisi del canvas grafico tramite il modello multimodale `gemini-3.7-flash` (via Kelpie AI Gateway) per il calcolo normalizzato delle coordinate dei blocchi da modificare.

---

## 2. Architettura Distribuita & Topologia di Rete

Il sistema adotta un'architettura distribuita a **due macchine Windows** connesse alla medesima rete locale Wi-Fi:

```text
┌────────────────────────────────────────────────────────────────────────┐
│ PC 1: Worker (PC Lamborghini)                                          │
│ - Connessione: VPN Lamborghini                                         │
│ - Applicazioni: ODIS Creator (aperto in primo piano), Agent Worker     │
│ - Responsabilità: Acquisizione screenshot canvas, click UI, digitazione│
└───────────────────────────────────▲────────────────────────────────────┘
                                    │
                                    │ Chiamate HTTP REST Dirette
                                    │ (LAN Wi-Fi locale, es. porta 8000)
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│ PC 2: Controller & AI Brain (PC EDAG)                                  │
│ - Connessione: VPN EDAG (Germania)                                     │
│ - Applicazioni: Controller FastAPI, Orchestratore GFF, Kelpie Gateway  │
│ - Modello AI: gemini-3.7-flash (Vision multimodale)                    │
│ - Responsabilità: Coda GFF, calcolo coordinate, sanitizzazione, logs   │
└────────────────────────────────────────────────────────────────────────┘
```

### Configurazione di Rete:
1. Entrambi i PC devono essere collegati alla **stessa rete Wi-Fi locale** (o rete LAN cablata).
2. Sul **PC EDAG (Controller)**, determinare l'indirizzo IP locale eseguendo in PowerShell:
   ```powershell
   ipconfig
   ```
   Individuare l'indirizzo IPv4 della scheda Wi-Fi (es. `192.168.1.105` o `10.0.0.50`).
3. Verificare che il Firewall di Windows sul PC EDAG consenta connessioni in ingresso sulla porta **8000** (e facoltativamente **18080** se si usa il proxy Kelpie locale).

---

## 3. Setup Ambiente su PC EDAG (Controller & AI Brain)

Il PC EDAG ospita il server REST FastAPI, il motore di orchestrazione della coda di lavoro e il client verso Kelpie AI Gateway.

### 3.1 Requisiti e Installazione
- **Sistema Operativo:** Windows 10 / 11
- **Python:** Versione 3.10 o successiva
- **VPN:** EDAG attiva (necessaria per raggiungere il gateway Kelpie)

Clonare il repository o copiare la cartella di progetto, quindi installare le dipendenze:
```powershell
cd C:\Users\rp99480\dev\odis-obliterator
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3.2 Configurazione Kelpie AI Gateway (`gemini-3.7-flash`)
Assicurarsi che la CLI di Kelpie sia installata e autenticata con le credenziali aziendali EDAG:
```powershell
kelpie auth login
```

È possibile verificare il token o avviare il proxy locale di Kelpie sulla porta `18080`:
```powershell
kelpie serve run -p 18080
```
In alternativa, il client utilizzerà direttamente il token generato da `kelpie auth print-access-token`.

### 3.3 Configurazione Variabili d'Ambiente
Creare o modificare il file `.env` nella radice del progetto:
```ini
# Configurazione Controller FastAPI
CONTROLLER_HOST=0.0.0.0
CONTROLLER_PORT=8000

# Kelpie Gateway & Modello Multimodale
KELPIE_BASE_URL=https://oauth.ai.container.edag
KELPIE_PROXY_URL=http://127.0.0.1:18080
KELPIE_MODEL=gemini-3.7-flash
TIMEOUT=60.0

# Parametri di Dominio
TARGET_KEYWORD=Lamborghini
VERSION_COMMENT=Removed Lamborghini labels
DRY_RUN=false
```

### 3.4 Avvio del Server Controller
Avviare il server FastAPI in ascolto su tutte le interfacce (`0.0.0.0`):
```powershell
python -m uvicorn controller.app:app --host 0.0.0.0 --port 8000
```
All'avvio, il controller verificherà la disponibilità di sessioni precedenti non completate per l'eventuale ripristino automatico.

### 3.5 Verifica dello Stato e Documentazione Swagger
- **Swagger UI:** Aprire il browser all'indirizzo `http://localhost:8000/docs`
- **Health Check:** `http://localhost:8000/api/v1/health` (dovrà restituire `{"status": "ok", "kelpie": "connected", "model": "gemini-3.7-flash"}`)

---

## 4. Setup Ambiente su PC Lamborghini (Worker UI)

Il PC Lamborghini esegue l'applicativo **ODIS Creator** e l'agente Python che simula le azioni utente e acquisisce gli screenshot del canvas.

### 4.1 Requisiti e Installazione
- **Sistema Operativo:** Windows 10 / 11
- **Python:** Versione 3.10 o successiva
- **ODIS Creator:** Installato e configurato
- **VPN:** Lamborghini attiva

Installare le dipendenze sul PC Lamborghini:
```powershell
cd C:\percorso\odis-obliterator
python -m pip install -r requirements.txt
```

### 4.2 Preparazione dell'Ambiente ODIS Creator
1. Avviare **ODIS Creator**.
2. Massimizzare la finestra principale a schermo intero (risoluzione consigliata: 1920x1080, scaling 100%).
3. Verificare che l'applicazione sia posizionata nella vista iniziale **`Editing`** con la scheda **`Knowledge base`** attiva.
4. Non sovrapporre altre finestre a ODIS Creator durante l'esecuzione live.

### 4.3 Test di Connettività verso il Controller
Prima di avviare il workflow, testare la raggiungibilità del Controller dal PC Lamborghini:
```powershell
python -m worker.agent --controller-url http://192.168.1.105:8000 --health-only
```
*(Sostituire `192.168.1.105` con l'IP effettivo del PC EDAG).*

Se il test ha successo, verrà stampato lo stato di connessione `Controller Health: {'status': 'ok', ...}`.

---

## 5. Guida Operativa: Esecuzione del Batch

### 5.1 Preparazione della Coda GFF (`data/input_gff.txt`)
Inserire i nomi completi degli oggetti diagnostici da processare all'interno del file `data/input_gff.txt` sul PC EDAG, uno per riga:
```text
# Esempio lista funzioni GFF
A16_4LA_91____1_518_88_Check_battery
LB63x_01____2_100_01_Engine_control
AU58x_09____3_400_12_Transmission_check
```
Le righe vuote o che iniziano con `#` vengono automaticamente ignorate.

---

### 5.2 Esecuzione in Modalità Dry-Run (Simulazione Sicura)
La modalità **Dry-Run** consente di collaudare l'intero flusso di comunicazione e l'analisi visiva di `gemini-3.7-flash` **senza inviare click fisici o modificare i dati in ODIS Creator**.

Sul PC Lamborghini:
```powershell
python -m worker.agent --controller-url http://192.168.1.105:8000 --dry-run --verbose
```

In modalità Dry-Run:
- Le chiamate REST, il download dei task, l'analisi del canvas e la logica di sanitizzazione vengono eseguiti regolarmente.
- Le azioni fisiche (click del mouse, inserimento tastiera, salvataggi) vengono registrate solo a livello di log interno senza interagire con il sistema operativo.

---

### 5.3 Esecuzione in Modalità Produzione (Live)
Quando il collaudo in Dry-Run è verificato con successo, avviare l'elaborazione reale:

Sul PC Lamborghini:
```powershell
python -m worker.agent --controller-url http://192.168.1.105:8000 --no-dry-run
```

L'agente:
1. Richiede al Controller il prossimo task dalla coda.
2. Esegue la sequenza dei 14 passaggi su ODIS Creator.
3. Modifica i blocchi contenenti "Lamborghini" e compila il commento di versione `"Removed Lamborghini labels"`.
4. Notifica l'esito al Controller e ripete il ciclo fino allo svuotamento della coda.

---

### 5.4 Parametri e Opzioni CLI del Worker
L'agente Worker supporta i seguenti parametri da riga di comando:

| Parametro | Descrizione | Default |
|---|---|---|
| `--controller-url`, `-c` | URL base dell'API del Controller | `http://127.0.0.1:8000` |
| `--dry-run` | Attiva la modalità di simulazione senza modifiche fisiche | `False` |
| `--no-dry-run` | Attiva la modalità reale di produzione | `True` (se non specificato diversamente) |
| `--poll-interval`, `-p` | Intervallo di polling tra un task e il successivo (in secondi) | `1.0` |
| `--max-tasks`, `-n` | Limite massimo di task da elaborare prima di uscire | Tutti i task in coda |
| `--health-only` | Esegue solo il check di connettività verso il Controller ed esce | `False` |
| `--verbose`, `-v` | Abilita il logging dettagliato (DEBUG) | `False` (INFO) |

---

## 6. Workflow Operativo End-to-End (14 Passaggi)

### 6.1 Sintesi dei Passaggi
Per ogni GFF della lista, il sistema esegue rigidamente la seguente sequenza:

1. **Passo 0 (Home):** Verifica dello stato pronto nella schermata iniziale `Editing`.
2. **Passo 1 (Ricerca):** Click sull'11° pulsante della toolbar (icona torcia gialla) e selezione del tab `Full Text Search`.
3. **Passo 2 (Input Search):** Digitazione del nome della funzione nel campo `Search text:` e conferma con `OK`.
4. **Passo 3 (Chiusura Popup):** Click su `OK` nel popup modale `Search ended`.
5. **Passo 4 (Selezione Risultato):** Doppio click sulla riga corrispondente (`Function test`) nella griglia `Search Results`.
6. **Passo 5 (Usage Locations):** Selezione del primo risultato nella gerarchia, conferma con `OK` e attesa espansione albero.
7. **Passo 6 (Test Sequence):** Click con tasto destro sull'area grigia della scheda aperta e selezione di `Test sequence`.
8. **Passo 7 (Minimizzazione Pannelli):** Click su `Minimize` (`_`) su `Palette`, `Search Results` e `Recently-Used Objects`.
9. **Passo 8 (Espansione Canvas):** Click sullo sfondo bianco della colonna centrale dei Test Step per aprire l'intero grafo.
10. **Passi 9-11 (Scansione & Editing Blocchi Target):**
    - Analisi visiva dello screenshot canvas inviato a `gemini-3.7-flash`.
    - Apertura ed editing selettivo dei blocchi rilevati:
      - **`Message`:** Rimozione di "Lamborghini", preservando tag `@[std]...` e Rich Text.
      - **`Comment`:** Rimozione di "Lamborghini" dal testo del commento.
      - **`Question`:** Rimozione di "Lamborghini", preservando variabili `%str_...%` e opzioni di risposta.
11. **Passo 12 (Chiusura Modulo & Salvataggio):** Click sulla `X` della tab `[Nome_Funzione] (Test module)` e click su `Save`.
12. **Passo 13 (Version Comment):** Click sul box giallo `Version comment:` e digitazione della stringa `"Removed Lamborghini labels"`.
13. **Passo 14 (Chiusura Scheda & Ritorno a Home):** Click sulla `X` della scheda oggetto, click su `Save` e verifica del ritorno allo stato iniziale (Passo 0).

---

### 6.2 Invarianti e Conservazione dei Tag
Durante la pulizia testuale:
- **Macro e Tag di Sistema:** Stringhe come `@[std]AU00003_Ende` **NON DEVONO MAI** essere alterate o rimosse.
- **Variabili Dinamiche:** Segnaposto come `%str_Bauteil%`, `%str_Steuergeraet%` e `%num_...%` rimangono intatti.
- **Punteggiatura e Formattazione:** Gli a capo multipli e la punteggiatura circostante vengono ripuliti in modo armonico senza spezzare la semantica del messaggio.

---

## 7. Logging, Reportistica & Ripristino Sessione (Resume)

### 7.1 Struttura della Cartella `/logs`
Ad ogni avvio di sessione batch, il Controller crea una sottocartella dedicata all'interno di `logs/`:

```text
logs/
└── run_YYYY-MM-DD_HH-mm-ss/
    ├── summary.json          # Metriche complessive (totale, successi, falliti, tempo, blocchi modificati)
    ├── state.json            # Snapshot persistente dello stato di ogni singolo task
    ├── execution.log         # Log cronologico dettagliato riga per riga
    └── errors/               # Screenshot ad alta risoluzione catturati in caso di anomalie
        ├── [Nome_Funzione]_[timestamp].png
        └── ...
```

#### Esempio di `summary.json`:
```json
{
  "total": 842,
  "success": 839,
  "failed": 3,
  "skipped": 0,
  "start_time": "2026-09-22T15:00:00Z",
  "end_time": "2026-09-22T18:45:00Z",
  "total_blocks_modified": 1420,
  "is_completed": true
}
```

---

### 7.2 Ripristino Automatico da Interruzione (Resume)
In caso di arresto imprevisto (es. interruzione di rete, chiusura accidentale o riavvio):
1. Riavviare il Controller: l'Orchestratore carica automaticamente l'ultimo `state.json` presente in `/logs`.
2. I task completati con stato `SUCCESS` rimangono marcati come tali e **non vengono ripetuti**.
3. I task interrotti a metà (stato `IN_PROGRESS`) vengono reimpostati su `PENDING` per essere rielaborati in modo pulito e sicuro.
4. Riavviando il Worker, l'elaborazione riprenderà istantaneamente dal primo task non completato.

---

## 8. Risoluzione dei Problemi Comuni (Troubleshooting)

| Problema Riscontrato | Possibile Causa | Soluzione Consigliata |
|---|---|---|
| **Errore di connessione Worker ↔ Controller** | Firewall di Windows attivo o IP non raggiungibile | Verificare con `ping <IP_CONTROLLER>` e aggiungere una regola in ingresso nel Firewall di Windows sul PC EDAG per la porta TCP `8000`. |
| **Popup "Validation error" in ODIS** | Incoerenza temporanea o validazione campi Rich Text | L'agente include un gestore automatico: clicca `OK` sul popup di errore e corregge il blocco prima di procedere. |
| **Funzione non trovata (`NOT_FOUND`)** | Nome GFF errato in `input_gff.txt` o oggetto non presente nel DB | Il Controller registra l'anomalia in `execution.log` e prosegue automaticamente con la funzione successiva. |
| **Kelpie Gateway Error / Timeout** | Token JWT scaduto o VPN EDAG disconnessa | Eseguire nuovamente `kelpie auth login` sul PC EDAG e verificare che la VPN EDAG verso la Germania sia attiva. |
| **Coordinate disallineate sul Canvas** | Risoluzione o DPI scaling di Windows non impostati al 100% | Impostare lo scaling dello schermo di Windows al 100% (96 DPI) e massimizzare ODIS Creator prima dell'avvio. |

---

## 9. Esecuzione dei Test Unitari e di Integrazione

Per verificare l'integrità di tutti i moduli software (Controller, Client Kelpie, Text Cleaner, Vision Engine, UI Driver, Workflow Runner e Test di Integrazione End-to-End):

```powershell
python -m pytest -v
```

Per eseguire una verifica specifica dei test di integrazione in modalità Dry-Run:
```powershell
python -m pytest tests/test_integration_dry_run.py -v
```

---

*Documentazione aggiornata e verificata per ODIS Obliterator Release v1.0.*
