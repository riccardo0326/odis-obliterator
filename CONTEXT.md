# CONTEXT.md – Contesto di Dominio e Specifiche di Sistema

## 1. Panoramica del Progetto
**ODIS Obliterator** è un sistema di automazione distribuito progettato per l'elaborazione batch di funzioni diagnostiche (GFF / Diagnostic Objects) all'interno dell'applicativo **ODIS Creator**.
Lo scopo principale è la bonifica testuale massiva: rimozione del termine target **"Lamborghini"** dai blocchi utente (`Message`, `Question`, `Comment`) e l'aggiornamento automatico della tracciabilità di versione.

---

## 2. Modello di Dominio (Domain Entities)

### 2.1 Entità ODIS Creator
- **GFF / Diagnostic Object / Function Test:**
  L'oggetto di primo livello nel Knowledge Base (es. `A16_4LA_91____1_518_88_Check_battery`). Contiene metadati (System name, Title, Version, Brand assignment) e la sequenza di test sottostante.
- **Test Module / Test Sequence:**
  L'editor grafico a diagramma di flusso in cui sono modellati i passi di test e le logiche di diagnosi.
- **Test Step:**
  Unità logiche raggruppate nella colonna centrale (es. `Global`, `Note regarding ...`, `Evaluate event ...`, `Ignition`). Ciascun step racchiude un grafo di blocchi.
- **Blocchi Target (Action Elements):**
  1. **`Message`:** Finestra informativa/istruzioni mostrata a video nell'ODIS Service durante la diagnosi. Supporta formattazione Rich Text e macro/tag di sistema (es. `@[std]AU00003_Ende`).
  2. **`Question`:** Punto decisionale interattivo per l'operatore (scelte `Yes/No` o selezione da lista). Spesso include variabili dinamiche formattate come `%str_Bauteil%` o `%str_Steuergeraet%`.
  3. **`Comment`:** Annotazione testuale interna all'albero diagnostico, non visibile all'utente finale del tester.
- **Blocchi Non Target (da ignorare):**
  - `If` (rombo di decisione logica), `Subroutine` (chiamate a funzioni ausiliarie), `Expression` (calcoli/assegnazioni), `Read file` / `Write file`, `Set status`.
- **Metadati di Versione (`Version comment`):**
  Casella a sfondo giallo nella scheda dell'oggetto principale in cui registrare la causale di modifica obbligatoria: `"Removed Lamborghini labels"`.

---

## 3. Ambiente e Topologia di Esecuzione

Il sistema opera su **due macchine Windows fisicamente distinte**, connesse alla medesima rete Wi-Fi locale:

| Ruolo | Macchina | Connettività / VPN | Componenti Eseguiti | Responsabilità |
|---|---|---|---|---|
| **Worker** | PC Lamborghini | VPN Lamborghini | ODIS Creator, Agent Worker (Python/PAD) | Esecuzione click fisici, input testi, cattura screenshot canvas, salvataggi |
| **Controller & Brain** | PC EDAG | VPN EDAG (Germania) | Python Controller (FastAPI/Orchestrator), Kelpie AI Gateway | Coda GFF, elaborazione logica, chiamate Vision LLM (`gemini-3.7-flash`), logging in `/logs` |

### Comunicazione di Rete
- I due computer comunicano tramite **chiamate HTTP REST dirette** sulla rete LAN Wi-Fi locale.
- Il Controller espone le API di orchestrazione (es. `http://<CONTROLLER_IP>:8000`) a cui il Worker invia richieste e payload di stato/screenshot, ricevendo istruzioni su coordinate e testi.

---

## 4. Ruolo del Vision LLM (Kelpie / `gemini-3.7-flash`)
- **Perché l'LLM:** L'editor del Test Module in ODIS Creator è un canvas grafico basato su coordinate relative. I blocchi possono variare di posizione e numero a seconda della funzione.
- **Compito dell'LLM:** Ricevere lo screenshot dell'area canvas e restituire le coordinate $(X, Y)$ normalizzate dei blocchi `Message`, `Question` e `Comment` da cliccare, oltre a guidare la gestione di popup ed edge cases.
- **Principio di sicurezza:** L'LLM non genera comandi non autorizzati né altera la logica del diagramma di flusso; si limita all'individuazione visuale e alla classificazione dei testi.

---

## 5. Vincoli e Invarianti di Dominio (Constraints & Invariants)

1. **Invariante di Punteggiatura e Tag:**
   - I tag speciali (es. `@[std]...`) e le variabili (es. `%str_...%`) **NON DEVONO MAI** essere alterati o eliminati durante la rimozione della parola "Lamborghini".
2. **Invariante di Chiusura e Stato Home:**
   - Una funzione è considerata `SUCCESS` solo se:
     1. Il Test Module è stato salvato e chiuso (`X`).
     2. Il `Version comment` è stato compilato.
     3. La scheda Diagnostic Object è stata salvata e chiusa (`X`).
     4. L'interfaccia è ritornata stabilmente alla schermata Home (`Editing View`).
3. **Idempotenza e Resume:**
   - Se un'elaborazione viene interrotta, il controller deve poter riprendere dal punto esatto leggendo lo stato di avanzamento da `logs/`.
