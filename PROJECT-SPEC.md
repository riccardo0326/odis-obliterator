# ODIS Creator – GFF Bulk Text Removal

## Project Specification – Version 2.0 (Standalone Local Architecture)

### 1. Obiettivo del Progetto

Realizzare un sistema di automazione modulare, offline e affidabile per **ODIS Creator**, in grado di elaborare in modalità batch un elevato numero di GFF / Diagnostic Objects (es. 800+ elementi da lista `data/input_gff.txt`) direttamente sul **PC Lamborghini**.

L'obiettivo primario è la rimozione puntuale del riferimento testuale **"Lamborghini"** dai blocchi funzionali:
* **Message** (finestre informative e di notifica ODIS Service)
* **Question** (finestre con quesiti e opzioni decisionali per il tester)
* **Comment** (commenti e annotazioni interne della struttura)

In aggiunta, il sistema provvede alla storicizzazione automatica inserendo nel campo metadati `Version comment:` la dicitura standard:
> `Removed Lamborghini labels`

Il sistema mantiene la massima tracciabilità di ogni operazione ed errore tramite log strutturati e screenshot diagnostici salvati nella cartella `/logs`.

---

### 2. Architettura del Sistema: Standalone Locale (PC Lamborghini)

A causa dei criteri di sicurezza aziendali (VPN aziendale con isolamento di rete locale, firewall e blocco di software terzi come AnyDesk), il sistema opera in modalità **100% Standalone Locale**:

```text
┌────────────────────────────────────────────────────────────────────────┐
│ PC Lamborghini (Windows 10/11)                                          │
│                                                                        │
│ ┌──────────────────────┐  ┌──────────────────────────────────────────┐ │
│ │ ODIS Creator         │  │ Standalone CLI Runner (worker/standalone)│ │
│ │ - Knowledge Base     │  │ ├─ Queue Manager (data/input_gff.txt)    │ │
│ │ - Test Module Editor │◄─┼─┼─ 14-Step Workflow (workflow_runner.py) │ │
│ │ - Flowchart Canvas   │  │ ├─ Local Vision (local_vision.py)        │ │
│ └──────────────────────┘  │ ├─ Deterministic TextCleaner             │ │
│                           │ └─ Logger & State Manager (logs/)        │ │
│                           └──────────────────────────────────────────┘ │
│                                                                        │
│ 100% Offline – Zero dipendenze di rete LAN, server remoti o VPN esterne│
└────────────────────────────────────────────────────────────────────────┘
```

#### 2.1 Vantaggi dell'Architettura Standalone:
- **Zero problemi di connettività:** Nessun blocco firewall, routing VPN o interruzione Wi-Fi.
- **Riconoscimento istantaneo:** Template Matching locale per l'individuazione ad altissima velocità dei blocchi canvas (`Message`, `Question`, `Comment`).
- **Installazione Offline Garantita:** Pacchetto dipendenze pre-scaricato in `/wheels`.

---

### 3. Workflow Operativo End-to-End (14 Passaggi)

Il ciclo standard per ciascuna funzione è strutturato in 14 passaggi sequenziali:

1. **Home / Editing View:** Verifica dello stato iniziale pronto con modulo `Editing` attivo.
2. **Apertura Ricerca:** Click sull'11° pulsante nella toolbar in alto (icona *torcia gialla*).
3. **Full Text Search:** Selezione del tab `Full Text Search` e inserimento del nome completo della funzione in `Search text:`, avvio con `OK`.
4. **Chiusura Notifica Fine Ricerca:** Pressione del tasto `OK` sul popup modale `Search ended`.
5. **Apertura Funzione da Risultati:** Doppio click sulla riga corrispondente (`Function test`) nella griglia `Search Results`.
6. **Selezione Posizione d'Uso (`Usage locations`):** Selezione del primo risultato nella gerarchia, click su `OK` e attesa caricamento albero in `Knowledge base navigator`.
7. **Apertura Test Sequence:** Click destro sull'area di sfondo grigio della scheda aperta e selezione della voce `Test sequence`.
8. **Minimizzazione Pannelli:** Click su *Minimize* (`_`) su `Palette`, `Search Results` e `Recently-Used Objects` per liberare l'area canvas.
9. **Espansione Canvas & Scansione Locale:** Click sul fondo bianco della colonna centrale dei Test Step e scansione del canvas tramite `LocalVisionEngine` a template matching.
10. **Individuazione ed Editing Blocchi Target:**
    * **`Message`**: Apertura doppio click, rimozione di "Lamborghini" (preservando tag come `@[std]...`), conferma con `OK`.
    * **`Comment`**: Apertura doppio click, rimozione di "Lamborghini", conferma con `OK`.
    * **`Question`**: Apertura doppio click, rimozione di "Lamborghini" (preservando variabili come `%str_...%`), conferma con `OK`.
11. **Chiusura Test Module & Salvataggio:** Click sulla `X` della tab `[Nome_Funzione] (Test module)` e click su `Save`.
12. **Compilazione Version Comment:** Click sul box a sfondo giallo `Version comment:` e digitazione di `Removed Lamborghini labels`.
13. **Chiusura Scheda Funzione & Salvataggio Finale:** Click sulla `X` della tab principale `[Nome_Funzione]`, click su `Save` e ritorno a Home.
14. **Passaggio alla GFF Successiva:** Aggiornamento di `state.json` e caricamento del record successivo.

---

### 4. Gestione degli Edge Case & Error Recovery

* **Edge Case 1: `Validation error` Popup:** Se premendo `OK` compare l'errore modale *"Dialog validation failed"*, il sistema clicca `OK` sul popup di errore e corregge il blocco prima di proseguire.
* **Edge Case 2: Nessun risultato di ricerca:** Se la funzione non viene trovata, lo stato viene marcato come `NOT_FOUND` in `state.json` e si passa alla successiva senza bloccare il batch.
* **Edge Case 3: Blocco funzione / Read-Only:** Se la funzione è bloccata o in sola lettura, viene marcata come `LOCKED` con screenshot diagnostico in `/logs`.
* **Edge Case 4: ODIS bloccato / Eccezione UI:** Meccanismo di sicurezza `recover_to_home()` che preme Escape, chiude le schede aperte e riporta l'interfaccia allo stato iniziale sicuro.

---

### 5. Struttura Dati Input & Output

* **Input:** `data/input_gff.txt` (un nome funzione per riga).
* **Logs & Reports:** `logs/run_YYYY-MM-DD_HH-mm-ss/`
  * `summary.json`: Metriche complessive (totale, successo, falliti, saltati, tempo, blocchi modificati).
  * `state.json`: Mappa di avanzamento task-per-task per garantire il resume trasparente.
  * `execution.log`: Log testuale sequenziale di ogni operazione.
   * `errors/`: Screenshot catturati in corrispondenza di anomalie.

---

### 6. Procedura Operativa Standalone Local

La procedura ufficiale sul PC Lamborghini e completamente offline e non
richiede l'avvio di `controller.app` o di un server HTTP.

#### 6.1 Installazione

1. Copiare l'intera cartella del progetto sul PC Lamborghini, inclusa
   `assets/`, `data/`, `worker/`, `logs/` e `wheels/`.
2. Aprire PowerShell nella directory del progetto.
3. Installare i pacchetti esclusivamente dal bundle locale:

```powershell
python -m pip install --no-index --find-links=wheels -r requirements.txt
```

#### 6.2 Preparazione ed esecuzione

1. Inserire i nomi GFF in `data/input_gff.txt`, uno per riga.
2. Avviare ODIS Creator, massimizzarlo e portarlo in `Editing` / `Knowledge base`.
3. Eseguire la simulazione:

```powershell
python -m worker.standalone --dry-run
```

4. Se il report e corretto, avviare l'elaborazione reale:

```powershell
python -m worker.standalone
```

Per usare un file alternativo o limitare il batch:

```powershell
python -m worker.standalone --input-file data\smoke_gff.txt --max-tasks 5
```

Le opzioni `--live` e `--no-dry-run` rendono esplicita la modalita reale;
`--force-new` ignora il checkpoint precedente e `--verbose` abilita il debug.

#### 6.3 Ripristino e reportistica

Al termine o dopo un'interruzione, consultare:

```text
logs/run_YYYY-MM-DD_HH-mm-ss/state.json
logs/run_YYYY-MM-DD_HH-mm-ss/execution.log
logs/run_YYYY-MM-DD_HH-mm-ss/summary.json
logs/run_YYYY-MM-DD_HH-mm-ss/errors/
```

Riavviando `python -m worker.standalone`, i task `SUCCESS` vengono saltati e
i task rimasti `IN_PROGRESS` vengono reimpostati a `PENDING`. Questo consente
di riprendere senza ricominciare il batch. Usare `--force-new` solo quando si
vuole creare una nuova sessione indipendente.

#### 6.4 Vincoli di sicurezza operativa

- Il dry-run non invia click, digitazione o salvataggi a ODIS Creator.
- Il live richiede ODIS Creator in primo piano e nessun input manuale concorrente.
- Il motore locale non effettua chiamate di rete.
- Il percorso distribuito Controller/Kelpie e opzionale e non fa parte del
  quickstart standalone.
