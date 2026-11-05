# mock_sage_server

A small Flask app that mimics Sage 300's REST Web API on the endpoints
`sage_bridge` needs. Not a Sage product — a contract-matching mock for
development and demos. **Never use as production truth.**

## Why this exists

Sage 300 is on-premise Windows software; there's no free sandbox you can
hit over the internet. To develop (and demo) integrations against Sage's
Web API without owning a Sage install, you need a server that:

- Speaks the same URL shape (`/v1.0/-/<company>/AR/Customers` etc.)
- Returns the same JSON response shapes
- Enforces the same auth (HTTP Basic Auth)
- Maintains batch + entry state so idempotency can be tested
- Rejects wrong credentials with a real 401

This does all of that in ~300 lines of Flask + SQLite.

## Install + run

```bash
pip install flask
python app.py                   # localhost:5555
python app.py --host 0.0.0.0 --port 8080
```

Behind nginx with TLS → the pattern for the demo deployment:
`https://mock-sage.datasmith-demo.zimpreneur.com`

## Auth

HTTP Basic Auth. Default credentials:

- user: `demo`
- pass: `demo123`

Override with env vars:
```bash
MOCK_SAGE_USER=myuser MOCK_SAGE_PASS=supersecret python app.py
```

## Endpoints

| Method | Path | Does |
|---|---|---|
| GET | `/` | Service banner |
| GET | `/Sage300WebApi/v1.0/-/<company>/AR/Customers` | List customers (supports `$top`) |
| POST | `/Sage300WebApi/v1.0/-/<company>/AR/Customers` | Create a customer (409 on duplicate) |
| POST | `/Sage300WebApi/v1.0/-/<company>/AR/InvoiceBatches` | Open a new batch |
| GET | `/Sage300WebApi/v1.0/-/<company>/AR/InvoiceBatches/<id>` | Read a batch with its entries |
| POST | `/Sage300WebApi/v1.0/-/<company>/AR/InvoiceEntries` | Add entry to a batch (idempotent on `ExternalReference`) |
| POST | `/Sage300WebApi/v1.0/-/<company>/AR/InvoiceBatches/<id>/Post` | Post the batch |

Both `/Sage300WebApi/v1.0/...` and the shorter `/v1.0/...` prefixes work
— some clients strip the IIS prefix.

## Test with curl

```bash
# List customers (empty on first run)
curl -u demo:demo123 http://localhost:5555/v1.0/-/DEMO01/AR/Customers

# Create a customer
curl -u demo:demo123 -X POST http://localhost:5555/v1.0/-/DEMO01/AR/Customers \
  -H 'Content-Type: application/json' \
  -d '{"CustomerNumber":"ACME001","CustomerName":"Acme Corp","GroupCode":"USD","AccountSetCode":"USA"}'

# Open a batch
curl -u demo:demo123 -X POST http://localhost:5555/v1.0/-/DEMO01/AR/InvoiceBatches \
  -H 'Content-Type: application/json' \
  -d '{"BatchDescription":"Test batch","BatchDate":"2026-11-05","BankCode":"USD"}'

# Add an entry (batch_number from previous response)
curl -u demo:demo123 -X POST http://localhost:5555/v1.0/-/DEMO01/AR/InvoiceEntries \
  -H 'Content-Type: application/json' \
  -d '{"BatchNumber":1,"CustomerNumber":"ACME001","DocumentType":"IN","DocumentNumber":"INV-001","DocumentTotal":100,"ExternalReference":"ODOO-123"}'

# Post the batch
curl -u demo:demo123 -X POST http://localhost:5555/v1.0/-/DEMO01/AR/InvoiceBatches/1/Post \
  -H 'Content-Type: application/json' -d '{}'

# Read it back
curl -u demo:demo123 http://localhost:5555/v1.0/-/DEMO01/AR/InvoiceBatches/1
```

## Storage

SQLite file `mock_sage.sqlite` next to `app.py`. Persistent across restarts.
To reset: delete the file + restart.

Override with `MOCK_SAGE_DB=/path/to/other.sqlite python app.py`.

## Deploying as a systemd service (demo server)

```ini
# /etc/systemd/system/mock-sage.service
[Unit]
Description=Mock Sage 300 Web API server
After=network.target

[Service]
User=mocksage
WorkingDirectory=/opt/mock_sage_server
ExecStart=/opt/mock_sage_server/venv/bin/python app.py --host 127.0.0.1 --port 5555
Environment=MOCK_SAGE_USER=demo
Environment=MOCK_SAGE_PASS=demo123
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Front with nginx + letsencrypt for `https://mock-sage.datasmith-demo.zimpreneur.com`.

## License

LGPL-3. See `../LICENSE`.
