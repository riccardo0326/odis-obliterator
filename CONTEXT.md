# CONTEXT.md – Contesto di Dominio e Specifiche di Sistema

## 1. Panoramica del Progetto
**ODIS Obliterator** è un sistema di automazione robotica progettato per l'elaborazione batch e la bonifica testuale massiva di funzioni diagnostiche (GFF / Diagnostic Objects) all'interno dell'applicativo **ODIS Creator**.
Lo scopo principale è la rimozione puntuale del termine target **"Lamborghini"** dai blocchi utente (`Message`, `Question`, `Comment`) e l'aggiornamento automatico della tracciabilità di versione con il commento standard `"Removed Lamborghini labels"`.

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
  1. **`Message`:** Finestra informativa/istruzioni mostrata a video nell'ODIS Service durante la diagnosi. Icona grafica: pergamena verde con angolo piegato. Supporta formattazione Rich Text e macro/tag di sistema (es. `@[std]AU00003_Ende`).
  2. **`Question`:** Punto decisionale interattivo per l'operatore (scelte `Yes/No` o selezione da lista). Icona grafica: punto interrogativo verde / fumetto. Spesso include variabili dinamiche formattate come `%str_Bauteil%` o `%str_Steuergeraet%`.
  3. **`Comment`:** Annotazione testuale interna all'albero diagnostico, non visibile all'utente finale del tester. Icona grafica: foglio note/memo ciano.
- **Blocchi Non Target (da ignorare categoricamente):**
  - `If` (rombo di decisione logica), `Subroutine` (chiamate a funzioni ausiliarie), `Expression` (calcoli/assegnazioni), `Read file` / `Write file`, `Set status`.
- **Metadati di Versione (`Version comment`):**
  Casella a sfondo giallo nella scheda dell'oggetto principale in cui registrare la causale di modifica obbligatoria: `"Removed Lamborghini labels"`.

---

## 3. Topologia di Esecuzione: Standalone Local (PC Lamborghini)

A causa dei rigidi criteri di sicurezza aziendali (firewall restrittivo della VPN Lamborghini, isolamento del traffico di rete LAN locale e blocco di applicativi terzi come AnyDesk), il sistema è architettato per eseguire in modalità **100% Standalone Locale** sul **PC Lamborghini**:

| Aspetto | Configurazione Standalone Locale (Primaria) |
|---|---|
| **Macchina Target** | PC Lamborghini (Windows 10/11 con ODIS Creator) |
| **Connettività Richiesta** | **Nessuna (100% Offline)** – zero dipendenze da rete LAN, Wi-Fi, porte aperte o VPN esterne |
| **Componenti Eseguiti in Locale** | - Coda GFF & Orchestratore (`data/input_gff.txt`)<br>- Runner 14 passaggi UI (`worker/workflow_runner.py`)<br>- Driver Mouse/Tastiera (`worker/ui_driver.py`)<br>- Motore di Visione Locale a Template Matching (`worker/local_vision.py`)<br>- Modulo Pulizia Testo Deterministico (`controller/text_cleaner.py`)<br>- Logging, Screenshot di Errore e Resume (`controller/logger_service.py`) |
| **Installazione Dipendenze** | Offline pip tramite bundle pre-scaricato (`pip install --no-index --find-links=wheels -r requirements.txt`) |

### Vantaggi dell'Esecuzione Standalone
1. **Zero ostacoli di rete:** Nessun problema di porte bloccate, subnet irraggiungibili o interruzioni di connessione Wi-Fi.
2. **Prestazioni massime:** Riconoscimento istantaneo dei blocchi a schermo tramite Template Matching locale senza latenza di upload/chiamata API.
3. **Piena conformità e sicurezza:** Tutti i dati e gli screenshot rimangono circoscritti all'interno della postazione autorizzata.

---

## 4. Motore di Riconoscimento Visivo dei Blocchi (Vision Strategy)

### 4.1 Riconoscimento Locale via Template Matching (`LocalVisionEngine`)
- L'editor grafico di ODIS Creator adotta icone standard e fisse per ciascuna tipologia di blocco (`Message`, `Question`, `Comment`).
- Il motore locale esegue una scansione dell'area canvas catturata tramite screenshot cercando i pattern iconici pre-salvati in `assets/icons/` (`icon_message.png`, `icon_question.png`, `icon_comment.png`) con soglia di confidenza configurabile.
- I blocchi individuati vengono ordinati automaticamente in sequenza di flusso top-to-bottom (ordinamento per coordinata $Y$, poi per $X$) e convertiti in coordinate relative normalizzate $[0.0, 1.0]$ per il click del mouse.

### 4.2 Modalità Ibrida / Fallback Remoto (Opzionale)
- Se eseguito in un ambiente con connettività aperta verso il PC EDAG / Kelpie AI Gateway, il sistema può facoltativamente inoltrare gli screenshot al Vision LLM `gemini-3.7-flash` per analisi avanzate o edge case non standard.

---

## 5. Vincoli e Invarianti di Dominio (Constraints & Invariants)

1. **Invariante di Punteggiatura e Tag:**
   - I tag speciali (es. `@[std]AU00003_Ende`) e le variabili (es. `%str_...%`, `%num_...%`) **NON DEVONO MAI** essere alterati o eliminati durante la rimozione della parola "Lamborghini".
   - La punteggiatura residua (doppie virgole, punti orfani, spazi multipli) viene ripulita preservando la struttura sintattica delle frasi.
2. **Invariante di Chiusura e Stato Home:**
   - Una funzione è considerata `SUCCESS` solo se:
     1. Il Test Module è stato salvato e chiuso (`X`).
     2. Il `Version comment` è stato compilato con `"Removed Lamborghini labels"`.
     3. La scheda Diagnostic Object è stata salvata e chiusa (`X`).
     4. L'interfaccia è ritornata stabilmente alla schermata Home (`Editing View`).
3. **Idempotenza e Resume:**
   - Se un'elaborazione batch viene interrotta, il sistema riprende dal punto esatto leggendo lo stato di avanzamento dal file persistente `logs/run_.../state.json`.
4. **Modalità Dry-Run:**
   - Possibilità di eseguire una simulazione sicura al 100% (`--dry-run`) che scansiona la UI e valida la logica senza inviare click fisici o modificare i file in ODIS Creator.
