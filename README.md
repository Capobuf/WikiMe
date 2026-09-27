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
- `/imports`: upload multiplo/copia-incolla, analisi e anteprima di export RouterOS e SwitchOS
- `/devices`: inventario dei dispositivi generato dalle configurazioni importate
- `/documentation`: struttura delle sezioni documentali
- `/document`: preview HTML del documento cliente

## Struttura

`app/models.py` contiene i modelli essenziali; `app/routes/` contiene le route divise per area; `app/templates/` contiene pagine e partial Jinja; `app/demo.py` contiene esclusivamente il seed demo; `tests/` contiene i test essenziali.

## Test

```powershell
pytest
```

## Limiti e sicurezza

Non esiste autenticazione. Il POC non deve essere esposto su Internet. I parser di configurazione usano whitelist di campi: il file originale e i valori di password, secret, community e chiavi non vengono conservati. Gli export `.rsc` e `.swb` sono esclusi da Git, ma i dati strutturati importati restano nel database SQLite locale. Il modello dati è ancora provvisorio e il database può essere eliminato e ricreato durante l'esplorazione.
