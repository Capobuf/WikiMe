# WikiMe POC

Prototipo locale esplorativo per validare la UX, l'organizzazione per cliente, il modello documentale e i futuri flussi di importazione di WikiMe. Privilegia codice semplice e rendering server-side; non anticipa l'architettura definitiva.

## Stack

Python 3.11+, Flask, Jinja2, Flask-SQLAlchemy, SQLite, HTMX e Tabler/Bootstrap via CDN.

## Installazione e avvio

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
python run.py seed
python run.py
```

Aprire `http://127.0.0.1:5000`. Il database e le impostazioni globali vengono inizializzati automaticamente all'avvio. `python run.py seed` aggiunge due clienti, tre sedi e tre fonti demo; se sono già presenti clienti non modifica il database.

Dopo l'installazione, su Windows è anche possibile avviare l'applicazione con un doppio clic su `run.bat`.

Variabili disponibili: `FLASK_ENV`, `SECRET_KEY` (usata soltanto per firmare la sessione che conserva il cliente corrente) e `DATABASE_PATH`.

## Pagine

- `/clients`: CRUD e selezione cliente
- `/client`: panoramica del cliente corrente
- `/sites`: CRUD sedi
- `/sources`: CRUD fonti
- `/settings/integrations`: configurazioni globali MikroTik, UniFi e Snipe-IT
- `/settings/documentation`: preferenze documentali globali, indipendenti dalla sorgente
- `/imports`: upload multiplo/copia-incolla, analisi e anteprima di export RouterOS e SwitchOS
- `/devices`: inventario dei dispositivi generato dalle configurazioni importate
- `/documentation`: vista operativa della documentazione corrente
- `/document`: preview HTML del documento cliente

## Struttura

`app/models.py` contiene i modelli essenziali; `app/routes/` contiene le route divise per area; `app/templates/` contiene pagine e partial Jinja; `app/demo.py` contiene esclusivamente il seed demo; `tests/` contiene i test essenziali.

## Snapshot e documentazione

L'import salva in `Device.data["sections"]` lo snapshot completo normalizzato e sicuro del parser. Le checkbox del dispositivo decidono se importarlo; quelle degli elementi decidono se documentarli. Il reimport sostituisce lo snapshot, quindi gli elementi rimossi dall'apparato spariscono anche dal documento. Le note manuali restano nei campi `notes`, separati dai dati importati.

Le esclusioni sono salvate in `Device.data["documentation"]["excluded_items"]`, raggruppate per sezione. Ogni fingerprint SHA-256 include nome della sezione e contenuto normalizzato completo, serializzati come JSON canonico UTF-8. L'ordine delle chiavi non conta; una modifica al contenuto genera un nuovo fingerprint e ripropone l'elemento. I fingerprint assenti dallo snapshot vengono conservati: un elemento identico che ricompare resta escluso. Reselezionarlo nella preview elimina la sua esclusione. Righe perfettamente identiche condividono il fingerprint: se una è deselezionata, sono escluse tutte le copie identiche.

`app/documentation.py` centralizza i default e costruisce la projection condivisa da `/documentation` e `/document`, raggruppata per sede (inclusi gli apparati senza sede). Precedenza: esclusione puntuale, override sede, preferenza globale, default. `Device = hidden` nasconde la tabella degli apparati, non le altre categorie di rete, che hanno preferenze indipendenti.

Le preferenze globali sono un JSON nella singola riga `DocumentationSetting` con ID 1. I default sono: Device, VLAN, IP Addresses, DHCP, NAT e VPN in **detail**; Interfaces, Bridges, Routes / Gateway, DNS e VPN users in **summary**; DHCP leases e Firewall in **hidden**. Summary per le interfacce mostra soltanto porte significative in base ai campi disponibili (rinomina, note, VLAN, bridge, bonding, disabilitazione, SFP, PoE). Per alcune categorie semplici Summary e Detail coincidono. Le tabelle usano colonne esplicite e omettono quelle senza dati.

Nella creazione/modifica sede, **Eredita** non salva alcuna proprietà in `Site.documentation_overrides`; vengono memorizzate soltanto le scelte esplicite. Un override esplicito resta tale anche se attualmente uguale al globale. Le checkbox della preview rappresentano le esclusioni puntuali; le modalità Hidden/Summary/Detail, mostrate accanto alla sezione, si applicano separatamente. La checkbox di sezione agisce sulla pagina di elementi visibile.

Le vecchie impostazioni MikroTik `enabled_items` non sono più utilizzate e non vengono convertite automaticamente in preferenze globali. La pagina dell'integrazione rimanda alle preferenze documentali. I dati già scartati da import precedenti non sono recuperabili dal database: occorre reimportare la configurazione.

### Aggiornamento SQLite

Non serve ricreare il database: `db.create_all()` crea la nuova tabella delle preferenze e l'avvio aggiunge, se assente, la colonna JSON `site.documentation_overrides` con default `{}`. L'operazione è additiva e ripetibile; non introduce un framework di migrazione. Come per gli altri cambi di schema POC, conserva una copia del file SQLite prima dell'aggiornamento. Il parser e il suo insieme di dati supportati restano invariati; non vengono dedotte informazioni mancanti.

## Test

```powershell
pytest
```

## Limiti e sicurezza

Non esiste autenticazione. Il POC non deve essere esposto su Internet. I parser di configurazione usano whitelist di campi: il file originale e i valori di password, secret, community e chiavi non vengono conservati. Gli export `.rsc` e `.swb` sono esclusi da Git, ma i dati strutturati importati restano nel database SQLite locale. Il modello dati è ancora provvisorio e il database può essere eliminato e ricreato durante l'esplorazione.
