# ODIS Creator – Workflow Operativo Dettagliato

Documento di tracciamento e analisi dettagliata del workflow per l'automazione ODIS Creator (rimozione testo target da blocchi Message/Question).

---

## Indice dei Passaggi

- [Passo 0: Schermata Iniziale (Home / Editing View)](#passo-0-schermata-iniziale-home--editing-view)
- [Passo 1: Apertura Finestra di Ricerca & Selezione "Full Text Search"](#passo-1-apertura-finestra-di-ricerca--selezione-full-text-search)
- [Passo 2: Inserimento Nome Funzione & Avvio Ricerca](#passo-2-inserimento-nome-funzione--avvio-ricerca)
- [Passo 3: Chiusura Popup di Notifica Fine Ricerca ("Search ended")](#passo-3-chiusura-popup-di-notifica-fine-ricerca-search-ended)
- [Passo 4: Selezione & Apertura della Funzione dai Risultati di Ricerca](#passo-4-selezione--apertura-della-funzione-dai-risultati-di-ricerca)
- [Passo 5: Selezione della Posizione d'Uso ("Usage locations") & Caricamento Alberatura](#passo-5-selezione-della-posizione-duso-usage-locations--caricamento-alberatura)
- [Passo 6: Apertura Sequenza di Test ("Test sequence") tramite Menu Contestuale](#passo-6-apertura-sequenza-di-test-test-sequence-tramite-menu-contestuale)
- [Passo 7: Apertura Editor Test Module & Minimizzazione Pannelli Non Necessari](#passo-7-apertura-editor-test-module--minimizzazione-pannelli-non-necessari)
- [Passo 8: Visualizzazione Completa Funzione & Scansione dei Blocchi Target](#passo-8-visualizzazione-completa-funzione--scansione-dei-blocchi-target)
- [Passo 9: Apertura & Modifica del Blocco "Message"](#passo-9-apertura--modifica-del-blocco-message)
- [Passo 10: Apertura & Modifica del Blocco "Comment"](#passo-10-apertura--modifica-del-blocco-comment)
- [Passo 11: Apertura & Modifica del Blocco "Question"](#passo-11-apertura--modifica-del-blocco-question)
- [Passo 12: Chiusura Test Module & Salvataggio Modifiche](#passo-12-chiusura-test-module--salvataggio-modifiche)
- [Passo 13: Inserimento Commento di Versione ("Version comment")](#passo-13-inserimento-commento-di-versione-version-comment)
- [Passo 14: Chiusura Scheda Funzione & Salvataggio Finale (Ritorno a Home)](#passo-14-chiusura-scheda-funzione--salvataggio-finale-ritorno-a-home)
- [Edge Case / Gestione Errori: Popup di Validazione ("Validation error")](#edge-case--gestione-errori-popup-di-validazione-validation-error)

---

## Dettaglio Passaggi

### Passo 0: Schermata Iniziale (Home / Editing View)

**Descrizione dello stato:**
L'applicazione ODIS Creator si trova nella schermata iniziale in modalità `Editing`.

**Elementi UI rilevati:**
1. **Barra del Titolo & Menu Principale:**
   - Titolo finestra: `ODIS Creator - [workspace/user] - Data classification: confidential`
   - Menu: `File`, `Edit`, `View`, `Insert`, `Extras`, `Help`
2. **Barra degli Strumenti:**
   - Dropdown contesti (`No context`, `en-GB`)
   - Icone di azione rapida (tra cui icona con binocolo per la Ricerca globale)
3. **Pannello Laterale Sinistro (Accordion `Editing`):**
   - Voci modulo: `Equipment Network`, `Knowledge base` (selezionato di default), `Function Library`, `Control Module Tree`, `DTC memory`, `Vehicle project`, `Supplemental documents`, `XML Templates`, `Brand Variables`.
4. **Pannello Navigatore Sinistro:**
   - Tab attivi: `Knowledge base navigator`, `Function library navigator`
5. **Area di Lavoro Destra (Superiore):**
   - Area centrale/superiore grigia (vuota, conterrà gli editor/flow chart una volta aperti).
6. **Pannello Risultati Ricerca (Centro-Destra):**
   - Scheda `Search Results` con griglia (`Name`, `Status`, `Object type`, `Version`, `Brand`).
   - Icone strumenti scheda in alto a destra: icona lente/binocolo (nuova ricerca), filtro, refresh, massimizza/riduci, chiudi.
7. **Pannello Oggetti Recenti (In basso a destra):**
   - Scheda `Recently-Used Objects` (mostra elenco storico modifiche/oggetti aperti).
8. **Pannello Proprietà (In basso a sinistra):**
   - Schede `Editorial object properties`, `Editorial Object History`.
9. **Barra di Stato (In basso):**
   - Indicatore memoria (es. `1124M of 1632M`) e codice vista (es. `Editing View: Knowledge base navigator`).

**Condizione di partenza per PAD:**
- Finestra ODIS Creator massimizzata/in primo piano.
- Sezione `Editing` attiva.

---

### Passo 1: Apertura Finestra di Ricerca & Selezione "Full Text Search"

**Azione da eseguire:**
1. Cliccare sull'**11° pulsante** nella barra degli strumenti in alto (icona con **torcia gialla**).
2. Si apre la finestra di dialogo modale **`Search`**.
3. Nella finestra di dialogo `Search`, cliccare sulla scheda/tab **`Full Text Search`** (la finestra si apre di default su `Object Search`).

**Elementi UI della finestra modale `Search`:**
- Titolo finestra: `Search`
- Tab disponibili:
  - `Object Search` (default)
  - `Full Text Search` (target da selezionare)
  - `ID Search`
- Pulsanti a fondo finestra: `OK`, `Cancel`

---

### Passo 2: Inserimento Nome Funzione & Avvio Ricerca

**Azione da eseguire:**
1. Digitare il **nome intero della funzione** (o GFF da elaborare) nel campo di testo **`Search text:`**.
2. **NON modificare** le altre opzioni/checkbox (lasciare la configurazione predefinita di `Search in:`: Metadata, Source language contents, Source language display names).
3. Premere il pulsante **`OK`** (o inviare Invio) per avviare la ricerca.

**Elementi UI rilevati nella scheda `Full Text Search`:**
- Campo testo: `Search text:`
- Sezione `Search in:` (checkbox di default attive):
  - `Metadata (for example, data from object editor)` (selezionato)
  - `Source language contents (for example, in XML content)` (selezionato)
  - `Source language display names` (selezionato)
  - `Translated display names` (deselezionato)
  - `Translated contents (for example, in translated XML content)` (deselezionato)
- Pulsante di conferma: `OK`
- Pulsante di annullamento: `Cancel`

---

### Passo 3: Chiusura Popup di Notifica Fine Ricerca ("Search ended")

**Descrizione:**
Al termine dell'elaborazione della ricerca, ODIS Creator visualizza una finestra di popup modale informativa.

**Azione da eseguire:**
1. Attendere la comparsa della finestra di dialogo `Search ended`.
2. Cliccare sul pulsante **`OK`** per chiudere il popup.

**Elementi UI rilevati:**
- Titolo finestra: `Search ended`
- Testo informativo: *"The search is complete. The search results can be found in the search results view of the editing view."*
- Icona: Info blu (ℹ)
- Pulsante di chiusura: `OK`

---

### Passo 4: Selezione & Apertura della Funzione dai Risultati di Ricerca

**Descrizione:**
Dopo la chiusura del popup di notifica, la scheda `Search Results` (pannello centrale/destro) viene popolata con i risultati corrispondenti al testo cercato.

**Azione da eseguire:**
1. Individuare la riga corrispondente alla funzione desiderata nella tabella di `Search Results`.
2. Eseguire un **doppio click** con il tasto sinistro del mouse sulla riga della funzione (Object type: `Function test`).

**Elementi UI rilevati nel pannello `Search Results`:**
- Tab: `Search Results`
- Colonne della tabella:
  - `Name`: Nome identificativo della funzione/GFF (es. `A16_4LA_91____1_518_88_Check_battery`)
  - `Status`: Stato (es. `Risk release`, `In processing`, ecc.)
  - `Object type`: Tipo di oggetto (es. `Function test` con relativa icona)
  - `Version`: Versione (es. `1.0.0`)
  - `Brand`: Brand associati (es. `A, L`)

---

### Passo 5: Selezione della Posizione d'Uso ("Usage locations") & Caricamento Alberatura

**Descrizione:**
Al doppio click sulla funzione viene aperta la finestra di dialogo modale **`Usage locations`**, che elenca i nodi del Knowledge base in cui è impiegata la funzione.

**Azione da eseguire:**
1. Attendere l'apertura della finestra `Usage locations`.
2. Selezionare il primo risultato disponibile nella lista / gerarchia.
3. Cliccare sul pulsante **`OK`** (o premere Invio).
4. **Attendere il caricamento e l'espansione dell'alberatura** nel pannello sinistro (`Knowledge base navigator`).

**Elementi UI rilevati:**
- Titolo finestra: `Usage locations`
- Istruzione: *"Select the desired usage location that is to be used."*
- Filtri/Checkbox: `Filter:`, `Only particular brand:`, `All ECU usage locations:`
- Elenco risultati: Struttura a nodi/colonne (es. `LB63x_26 | Body | Electrical_Equipment | 01_Self_diagnostic_capable_systems ...` con sotto `Function tests | [Nome_Funzione]`)
- Pulsanti: `OK`, `Cancel`

---

### Passo 6: Apertura Sequenza di Test ("Test sequence") tramite Menu Contestuale

**Descrizione:**
All'apertura della funzione viene visualizzata la scheda dettagli dell'oggetto (con prefisso asterisco es. `*A16_4LA_91____1_518_88_Check_battery`) contenente metadati come System name, Title, Tester description, Version history.

**Azione da eseguire:**
1. Fare **click con il tasto destro del mouse** sull'area di sfondo grigio della scheda aperta.
2. Dal menu contestuale a tendina che compare, cliccare sulla voce **`Test sequence`**.

**Elementi UI rilevati:**
- Scheda attiva: `*[Nome_Funzione]`
- Menu contestuale:
  - `Test sequence` (voce da selezionare)
  - `Replace content`

---

### Passo 7: Apertura Editor Test Module & Minimizzazione Pannelli Non Necessari

**Descrizione:**
ODIS Creator apre una nuova scheda dell'editor grafico: `[Nome_Funzione] (Test module)`.
L'interfaccia visualizza:
- A sinistra: Elenco dei Test Step della funzione (es. `Global`, `Note regarding ...`, `Evaluate event ...`, `Ignition`, ecc.).
- Al centro: Il diagramma di flusso a blocchi relativo al Test Step selezionato.
- A destra in alto: Il pannello `Palette` (strumenti grafici).
- In basso: Il gruppo pannelli `Search Results` / `XML` / `Java Code` e sotto `Recently-Used Objects`.

**Azione da eseguire:**
Per massimizzare lo spazio di lavoro ed evitare ingombri visivi:
1. Cliccare sull'icona **`Minimize`** (`_`) del pannello **`Palette`** (in alto a destra). **NON** cliccare sulla `X` (chiudi).
2. Cliccare sull'icona **`Minimize`** (`_`) del pannello centrale inferiore (**`Search Results` / `XML` / `Java Code`**). **NON** cliccare sulla `X`.
3. Cliccare sull'icona **`Minimize`** (`_`) del pannello inferiore (**`Recently-Used Objects`**). **NON** cliccare sulla `X`.

**Elementi UI rilevati:**
- Scheda attiva: `[Nome_Funzione] (Test module)`
- Pulsanti di controllo pannelli secondari:
  - Icona Trattino (`_`) per Riduci a icona / Minimizza.

---

### Passo 8: Visualizzazione Completa Funzione & Scansione dei Blocchi Target

**Descrizione del Layout Pulito:**
1. **Sinistra:** `Knowledge base navigator` (alberatura dei nodi).
2. **Centro:** Sequenza dei Test Step della funzione (`Global`, `Note regarding ...`, `Evaluate event ...`, `Ignition`, ecc.).
3. **Destra:** Diagramma di flusso a blocchi della funzione / Test Step.

**Azione da eseguire per il workflow di analisi:**
1. **Visualizzazione completa:** Cliccare sull'area di sfondo bianco della **sezione centrale** (la colonna dei Test Step) per espandere / visualizzare l'intera funzione e tutti i suoi rami nell'area canvas a destra.
2. **Scansione verticale/flusso:** Scorrere verticalmente l'intero diagramma della funzione.
3. **Individuazione ed apertura dei blocchi target:** Ogni volta che lungo il flusso si incontra uno dei seguenti blocchi:
   - **`Message`** (icona con pergamena / foglio verde con bordo piegato)
   - **`Question`** (icona con punto interrogativo verde / fumetto)
   - **`Comment`** (blocco note / commento)
   
   Eseguire un **doppio click** (o comando di apertura) sul blocco per aprire la relativa finestra di editing dei testi.

**Blocchi da ignorare (non target):**
- `Read file`, `If` (decisione/rombo giallo), `Set status`, `Subroutine` (rettangolo giallo), `Expression`, `Write file`, ecc.

---

### Passo 9: Apertura & Modifica del Blocco "Message"

**Descrizione:**
Al doppio click su un blocco `Message`, si apre la finestra di dialogo modale `Message [Identificativo_Funzione]`.

**Azione da eseguire:**
1. Esaminare l'area di testo dell'editor.
2. Rilevare la presenza della parola target **"Lamborghini"** (es. nel testo `- Ignore the event memory Lamborghini entry`).
3. Rimuovere il riferimento "Lamborghini" preservando il resto del testo, la punteggiatura e i tag/riferimenti di sistema (es. tag `@[std]...`).
4. Cliccare sul pulsante **`OK`** per confermare e chiudere il blocco (oppure `Cancel` se non sono necessarie modifiche).

**Elementi UI rilevati nella finestra `Message dialog`:**
- Titolo finestra: `Message [Nome_Oggetto]`
- Descrizione: *"If a message text is to be displayed in the ODIS Service, this action element is used."*
- Barra di formattazione testo: Font (`Arial`, `Courier`, `Symbols`), stili, colori, allineamento, `Icons`.
- Barra icone a sinistra: Simboli di avviso, informazione, frecce, `Standard`, `Expand`.
- Area testo principale: Controllo Rich Text multi-riga.
- Pulsanti ausiliari: `Variable`, `Keyword`.
- Opzioni fondo finestra: Checkbox `Bars`, Radio `Confirmation: Yes / No`, `after [X] Seconds`, `Print`, `Print preview...`.
- Pulsanti di azione: `OK`, `Cancel`.

---

### Passo 10: Apertura & Modifica del Blocco "Comment"

**Descrizione:**
Al doppio click su un blocco `Comment`, si apre la finestra di dialogo modale `Comment [Identificativo_Funzione]`.

**Azione da eseguire:**
1. Esaminare il campo testo **`Text:`**.
2. Rilevare la presenza della parola target **"Lamborghini"**.
3. Rimuovere il testo indesiderato.
4. Cliccare sul pulsante **`OK`** per confermare (oppure `Cancel` se non modificato).

**Elementi UI rilevati nella finestra `Commentary dialog`:**
- Titolo finestra: `Comment [Nome_Oggetto]`
- Descrizione: *"The statement adds commentary to the function test structure. The commentary does not appear in..."*
- Campo testo: `Text:` (area di testo multilinea semplice)
- Pulsanti di azione: `OK`, `Cancel`

---

### Passo 11: Apertura & Modifica del Blocco "Question"

**Descrizione:**
Al doppio click su un blocco `Question`, si apre la finestra di dialogo modale `Question [Identificativo_Funzione]`.

**Azione da eseguire:**
1. Esaminare l'area di testo dell'editor della domanda.
2. Rilevare la presenza della parola target **"Lamborghini"**.
3. Rimuovere il testo target "Lamborghini", avendo cura di preservare variabili di sistema (es. `%str_Bauteil%`, `%str_Steuergeraet%`), formattazione e sintassi.
4. Lasciare inalterate le opzioni di risposta (`Yes/No` o `Select`) a meno di istruzioni specifiche.
5. Cliccare sul pulsante **`OK`** per confermare e chiudere (oppure `Cancel` se non modificato).

**Elementi UI rilevati nella finestra `Question dialog`:**
- Titolo finestra: `Question [Nome_Oggetto]`
- Descrizione: *"This action element assists in creating a question for the user. Possible answers are yes/no/unknown or a selection."*
- Barra formattazione: Font, stili, colori, allineamento, `Icons`.
- Barra laterale: Icone informative, di pericolo, frecce, `Standard`, `Expand`.
- Area testo domanda: Rich text editor con evidenziazione variabili.
- Pulsanti ausiliari: `Variable`, `Keyword`.
- Opzioni di risposta (pannello destro):
  - Radio `Yes/No` (con `OK = Yes / No`, `Unknown`)
  - Radio `Select` (tabella scelte `Selection number` / `Response` e bottoni `+ - ↑ ↓`)
- Pulsanti di azione: `OK`, `Cancel`.

---

### Passo 12: Chiusura Test Module & Salvataggio Modifiche

**Descrizione:**
Terminata la scansione di tutti i blocchi e l'eliminazione dei testi target nella sequenza:

**Azione da eseguire:**
1. Individuare la linguetta/scheda attiva **`*[Nome_Funzione] (Test module)`**.
2. Cliccare sulla **`X`** rossa di chiusura posta all'estremità destra della linguetta della scheda (tooltip *Close*).
3. Quando compare la richiesta/finestra di dialogo di conferma, cliccare su **`Save`** (o `Yes`) per salvare le modifiche apportate al modulo di test.

**Elementi UI rilevati:**
- Tab: `*[Nome_Funzione] (Test module)`
- Pulsante di chiusura: Icona `X` rossa sulla tab attiva (con indicazione tooltip *Close*).

---

### Passo 13: Inserimento Commento di Versione ("Version comment")

**Descrizione:**
Dopo la chiusura e il salvataggio del modulo di test, la schermata ritorna alla scheda principale dell'oggetto/funzione (es. `*[Nome_Funzione]`) ora in modalità di modifica (con numero di versione incrementato, es. `1.0.1`).

**Azione da eseguire:**
1. Cliccare sulla casella di testo a sfondo **giallo** corrispondente al campo **`Version comment:`**.
2. Digitare la stringa descrittiva:
   ```text
   Removed Lamborghini labels
   ```

**Elementi UI rilevati:**
- Scheda attiva: `*[Nome_Funzione]`
- Campo testo: `Version comment:` (box di testo evidenziato in giallo)
- Versione aggiornata visualizzata nei selettori numerici `Version: [Major] [Minor] [Patch]`.

---

### Passo 14: Chiusura Scheda Funzione & Salvataggio Finale (Ritorno a Home)

**Descrizione:**
Inserito il commento di versione, si procede alla chiusura dell'oggetto funzione e al salvataggio definitivo per tornare allo stato di partenza.

**Azione da eseguire:**
1. Individuare la linguetta/scheda dell'oggetto funzione **`*[Nome_Funzione]`**.
2. Cliccare sulla **`X`** di chiusura della linguetta.
3. Al popup di richiesta salvataggio delle modifiche, cliccare su **`Save`** (o `Yes`).
4. Verificare che l'applicazione sia ritornata alla schermata principale di partenza ([Passo 0](#passo-0-schermata-iniziale-home--editing-view)).
5. Il ciclo per la singola funzione/GFF è completato con successo ed il sistema è pronto per processare la successiva.

**Elementi UI rilevati:**
- Tab: `*[Nome_Funzione]`
- Pulsante di chiusura: Icona `X` sulla tab della funzione.
- Dialogo di salvataggio: Pulsante `Save` / `Yes`.

---

### Edge Case / Gestione Errori: Popup di Validazione ("Validation error")

**Descrizione dell'evento:**
In alcuni casi (ad esempio difformità di formattazione o variabili nel testo come `%str_bauteil%`), quando si preme il pulsante `OK` su una finestra di dialogo (es. `Question dialog` o `Message dialog`), l'applicazione mostra un popup modale di errore: **`Validation error`** (*"Dialog validation failed. Please enter correct data."*).

**Azione / Regola operativa da eseguire:**
1. Rilevare la comparsa del popup `Validation error` (o dialoghi di conferma/warning analoghi).
2. Cliccare sul pulsante **`OK`** del popup di errore per chiuderlo.
3. Se necessario, correggere l'incoerenza o premere nuovamente **`OK`** sulla finestra padre.


