# ODIS Obliterator - Manuale Operativo

ODIS Obliterator automatizza la rimozione del testo `Lamborghini` dai blocchi
`Message`, `Question` e `Comment` di ODIS Creator. La configurazione primaria e
raccomandata e **Standalone Local sul PC Lamborghini**: non richiede rete LAN,
VPN, server FastAPI o gateway AI.

La modalita distribuita con Controller EDAG resta disponibile come configurazione
legacy/opzionale, ma non e necessaria per l'elaborazione locale.

## Indice dei Contenuti

1. [Panoramica](#1-panoramica)
2. [Standalone Local](#2-standalone-local-pc-lamborghini)
3. [Quickstart Operativo](#3-quickstart-operativo)
4. [CLI Standalone](#4-cli-standalone)
5. [Workflow ODIS Creator](#5-workflow-odis-creator)
6. [Logging, Report e Resume](#6-logging-report-e-resume)
7. [Troubleshooting](#7-troubleshooting)
8. [Test](#8-test)
9. [Modalita Distribuita Legacy](#9-modalita-distribuita-legacy)

## 1. Panoramica e Obiettivo del Progetto

Il sistema elabora una lista di funzioni GFF, una per riga, nel file
`data/input_gff.txt`. Per ogni funzione:

- apre la funzione in ODIS Creator;
- individua localmente le icone `Message`, `Question` e `Comment`;
- rimuove solo `Lamborghini` dal testo;
- conserva macro come `@[std]AU00003_Ende` e variabili come `%str_Bauteil%`;
- inserisce `Removed Lamborghini labels` nel campo `Version comment:`;
- salva, chiude e registra il risultato.

## 2. Architettura Distribuita & Topologia di Rete

La topologia raccomandata e Standalone Local: entrambe le componenti girano sul
PC Lamborghini e non esiste un collegamento Controller/Worker. La topologia
distribuita legacy e descritta nella sezione 9.

## 2.1 Standalone Local (PC Lamborghini)

### Requisiti

- Windows 10/11;
- Python 3.10 o successivo;
- ODIS Creator installato e configurato;
- ODIS Creator aperto in primo piano nella vista `Editing`;
- nessuna connettivita di rete richiesta.

La configurazione distribuita legacy espone invece il controllo
`/api/v1/health` e la documentazione Swagger su `/docs` sul Controller FastAPI.

Il motore `LocalVisionEngine` usa i template in `assets/icons/` e il matching
locale Pillow, con deduplicazione e coordinate normalizzate. Il testo viene
pulito da `TextCleaner` in-process. La pipeline standalone non avvia FastAPI e
non effettua chiamate HTTP.

### Struttura rilevante

```text
assets/icons/                 Template Message/Question/Comment
data/input_gff.txt            Coda GFF, una funzione per riga
worker/standalone.py          CLI e orchestratore locale
worker/local_vision.py        Visione locale offline
worker/workflow_runner.py     Workflow UI di 14 passaggi
logs/run_YYYY-MM-DD_HH-mm-ss/ State, log, report e screenshot
wheels/                       Bundle dipendenze offline
```

## 3. Setup Ambiente su PC EDAG (Controller & AI Brain)

Questa installazione e opzionale e serve solo alla modalita distribuita legacy.
Il PC EDAG richiede rete, Kelpie autenticato, e il Controller FastAPI.

## 3.1 Quickstart Operativo Standalone

### Passo 1 - Copiare il progetto

Copiare l'intera cartella del progetto sul PC Lamborghini, inclusa la directory
`wheels/`. Esempio:

```powershell
Copy-Item -Recurse C:\sorgente\odis-obliterator C:\Tools\odis-obliterator
Set-Location C:\Tools\odis-obliterator
```

Non e necessario clonare repository o raggiungere internet sul PC target.

### Passo 2 - Installare le dipendenze offline

Eseguire dalla radice del progetto:

```powershell
python -m pip install --no-index --find-links=wheels -r requirements.txt
```

Il comando usa esclusivamente i pacchetti presenti in `wheels/`. Se un wheel
manca, fermarsi e completare il bundle su una macchina autorizzata prima di
procedere.

### Passo 3 - Preparare la coda GFF

Modificare `data/input_gff.txt` e inserire il nome completo di ogni funzione:

```text
# Le righe vuote e i commenti vengono ignorati
A16_4LA_91____1_518_88_Check_battery
LB63x_01____2_100_01_Engine_control
AU58x_09____3_400_12_Transmission_check
```

Verificare prima dell'avvio che i nomi corrispondano agli oggetti presenti in
ODIS Creator.

### Passo 4 - Preparare ODIS Creator

1. Avviare ODIS Creator.
2. Massimizzare la finestra e non sovrapporre altre finestre.
3. Impostare scaling Windows al 100% per una calibrazione standard.
4. Portarsi nella vista iniziale `Editing`, con `Knowledge base` attivo.
5. Non usare mouse o tastiera mentre il processo live e in esecuzione.

### Passo 5 - Eseguire il test simulato (Dry-Run)

```powershell
python -m worker.standalone --dry-run
```

Per una verifica limitata:

```powershell
python -m worker.standalone --dry-run --max-tasks 1 --verbose
```

Il dry-run esegue la coda e registra le azioni senza inviare click, digitazione
o salvataggi fisici. Verificare i file nella sessione `logs/` prima del live.

### Passo 6 - Eseguire l'elaborazione reale

```powershell
python -m worker.standalone
```

La modalita live invia le azioni a ODIS Creator. L'alternativa esplicita e:

```powershell
python -m worker.standalone --live
```

Questa e l'esecuzione di **Produzione**: usarla solo dopo aver verificato il
dry-run e il contenuto della coda.

Per interrompere in sicurezza usare `Ctrl+C`. Non chiudere forzatamente il
processo durante un salvataggio: lo stato viene comunque persistito e il resume
resetta il task interrotto al prossimo avvio.

## 4. Setup Ambiente su PC Lamborghini (Worker UI)

Per la configurazione primaria seguire il quickstart sopra: il worker standalone
e locale e non richiede `--controller-url` o `--health-only`.

## 4.1 CLI Standalone

| Opzione | Descrizione |
|---|---|
| `--dry-run` | Simula le azioni UI senza click fisici |
| `--live`, `--no-dry-run` | Esecuzione reale su ODIS Creator |
| `--input-file`, `-i` | File GFF alternativo; default `data/input_gff.txt` |
| `--max-tasks`, `-n` | Numero massimo di task per questa esecuzione |
| `--force-new` | Ignora il checkpoint piu recente e crea una nuova sessione |
| `--verbose`, `-v` | Abilita log console a livello DEBUG |

Esempio con file alternativo:

```powershell
python -m worker.standalone --dry-run -i data\smoke_gff.txt -n 5
```

`--dry-run` e `--live` sono mutuamente esclusivi. Senza nessuna opzione di
modalita viene usata l'esecuzione live.

## 5. Guida Operativa: Esecuzione del Batch

Il batch standalone si avvia con `python -m worker.standalone`. Le istruzioni
complete sono nella sezione 3.1.

## 5.1 Workflow ODIS Creator

Per ogni GFF vengono eseguiti i 14 passaggi definiti in `WORKFLOW.md`:

1. Home/Editing View e focus della finestra.
2. Apertura Full Text Search e inserimento del nome funzione.
3. Chiusura del popup `Search ended`.
4. Apertura del risultato e selezione della usage location.
5. Apertura di `Test sequence`.
6. Minimizzazione dei pannelli secondari.
7. Espansione e scansione locale del canvas.
8. Apertura dei blocchi target e lettura del testo.
9. Bonifica deterministica di `Message`, `Comment`, `Question`.
10. Gestione dell'eventuale popup `Validation error`.
11. Chiusura e salvataggio del Test Module.
12. Inserimento di `Removed Lamborghini labels`.
13. Salvataggio e chiusura dell'oggetto.
14. Verifica del ritorno alla Home e aggiornamento dello stato.

I blocchi `If`, `Subroutine`, `Expression`, `Read file`, `Write file` e `Set
status` non sono target. Macro, variabili, tag Rich Text e opzioni di risposta
non vengono rimossi.

## 6. Workflow Operativo End-to-End (14 Passaggi)

La sequenza operativa completa e riportata nella sezione 5.1.

## 6.1 Logging, Report e Resume

Ogni sessione crea:

```text
logs/run_YYYY-MM-DD_HH-mm-ss/
  state.json       Stato persistente di ogni GFF
  execution.log    Eventi cronologici della sessione
  summary.json     Totali, successi, errori e blocchi modificati
  errors/          Screenshot diagnostici degli errori UI
```

Consultare il report con PowerShell:

```powershell
Get-Content logs\run_YYYY-MM-DD_HH-mm-ss\summary.json
Get-Content logs\run_YYYY-MM-DD_HH-mm-ss\execution.log
```

Il resume e automatico: al riavvio vengono saltati i task `SUCCESS`, mentre i
task lasciati `IN_PROGRESS` da un arresto vengono riportati a `PENDING`. Per
ricominciare da zero usare `--force-new`. Non cancellare `state.json` se si
vuole conservare il resume.

## 7. Logging, Reportistica & Ripristino Sessione (Resume)

La sessione standalone salva sempre `state.json`, `execution.log`, `summary.json`
ed eventuali screenshot sotto `logs/`.

## 7.1 Troubleshooting

| Problema | Causa o soluzione |
|---|---|
| Template non caricati | Verificare `assets/icons/icon_message.png`, `icon_question.png`, `icon_comment.png`. |
| Coordinate disallineate | Massimizzare ODIS Creator e impostare scaling Windows al 100%. |
| `Validation error` | Il runner chiude il popup e tenta la gestione prevista dal workflow. Controllare `execution.log`. |
| GFF non trovata | Controllare spelling e contesto dell'oggetto in `data/input_gff.txt`. |
| Processo interrotto | Riavviare `python -m worker.standalone`; il resume riprende dal task non completato. |
| Installazione fallita | Verificare che `wheels/` contenga tutti i pacchetti richiesti e ripetere il comando offline. |
| Errore firewall/controller | La modalita standalone non richiede firewall, LAN, Controller o Kelpie. |

## 8. Risoluzione dei Problemi Comuni (Troubleshooting)

Consultare la tabella seguente per gli errori operativi piu frequenti.

## 8.1 Test

Eseguire la suite completa dalla radice del progetto:

```powershell
python -m pytest
```

Test specifici per la configurazione standalone:

```powershell
python -m pytest tests\test_local_vision.py tests\test_standalone.py -v
```

## 9. Esecuzione dei Test Unitari e di Integrazione

La suite completa si esegue con `python -m pytest`.

## 9.1 Modalita Distribuita Legacy

La modalita distribuita opzionale usa un PC EDAG con Controller FastAPI e
Kelpie `gemini-3.7-flash`. E richiesta una rete raggiungibile, la porta `8000`
e, se usato, il proxy Kelpie `18080`.

Autenticazione e proxy Kelpie sul PC EDAG:

```powershell
kelpie auth login
kelpie serve run -p 18080
```

Avvio del Controller:

```powershell
python -m uvicorn controller.app:app --host 0.0.0.0 --port 8000
```

Il worker legacy puo essere usato con `worker.agent`, ad esempio:

```powershell
python -m worker.agent --controller-url http://192.168.1.105:8000 --health-only
```

Questa configurazione non e il percorso raccomandato per il PC Lamborghini:
per l'elaborazione offline usare sempre `python -m worker.standalone`.
