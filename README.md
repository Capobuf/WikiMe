# WikiMi POC

Prototipo locale esplorativo per validare la UX, l'organizzazione per cliente, il modello documentale e i futuri flussi di importazione di WikiMi. Privilegia codice semplice e rendering server-side; non anticipa l'architettura definitiva.

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

Variabili disponibili: `FLASK_ENV`, `SECRET_KEY` (usata soltanto per firmare la sessione che conserva il cliente corrente) e `DATABASE_PATH`.

## Pagine

- `/clients`: CRUD e selezione cliente
- `/client`: panoramica del cliente corrente
- `/sites`: CRUD sedi
- `/sources`: CRUD fonti
- `/settings/integrations`: configurazioni globali MikroTik, UniFi e Snipe-IT
- `/imports`: flusso e anteprima con dati demo isolati
- `/documentation`: struttura delle sezioni documentali
- `/document`: preview HTML del documento cliente

## Struttura

`app/models.py` contiene i modelli essenziali; `app/routes/` contiene le route divise per area; `app/templates/` contiene pagine e partial Jinja; `app/demo.py` contiene esclusivamente il seed demo; `tests/` contiene i test essenziali.

## Test

```powershell
pytest
```

## Limiti e sicurezza

Non esiste autenticazione. Il POC non deve essere esposto su Internet e non è adatto a dati reali sensibili. Non sono implementate connessioni, parser o sincronizzazioni reali. SQLite e il modello dati sono deliberatamente provvisori e il database può essere eliminato e ricreato durante l'esplorazione.

