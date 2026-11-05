"""mock_sage_server — a Flask app that mimics Sage 300's Web API.

Endpoints implemented (enough for the sage_bridge demo):

    GET  /                                                   → "I am a mock Sage"
    GET  /Sage300WebApi/v1.0/-/<company>/AR/Customers        → list customers
    POST /Sage300WebApi/v1.0/-/<company>/AR/Customers        → create customer
    POST /Sage300WebApi/v1.0/-/<company>/AR/InvoiceBatches   → open a batch
    GET  /Sage300WebApi/v1.0/-/<company>/AR/InvoiceBatches/<id>  → read a batch
    POST /Sage300WebApi/v1.0/-/<company>/AR/InvoiceEntries   → add entry to a batch
    POST /Sage300WebApi/v1.0/-/<company>/AR/InvoiceBatches/<id>/Post → post batch

Auth: HTTP Basic Auth. Default credentials: demo / demo123.

Store: SQLite file next to this script (mock_sage.sqlite). Persistent across
restarts so the invoice you pushed yesterday is still there today.

Run:
    pip install flask
    python app.py                 # http://localhost:5555
    python app.py --port 8080 --host 0.0.0.0

Behind nginx with TLS → reachable as https://mock-sage.datasmith-demo.zimpreneur.com

This is NOT a Sage product. It is a contract-matching mock for development
and demo use. Never connect a real integration to this as production truth.
"""
import argparse
import base64
import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import Flask, jsonify, request

app = Flask(__name__)

AUTH_USER = os.environ.get("MOCK_SAGE_USER", "demo")
AUTH_PASS = os.environ.get("MOCK_SAGE_PASS", "demo123")
DB_PATH = os.environ.get("MOCK_SAGE_DB", os.path.join(os.path.dirname(__file__), "mock_sage.sqlite"))


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS customer (
            company TEXT NOT NULL,
            customer_number TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (company, customer_number)
        );
        CREATE TABLE IF NOT EXISTS batch (
            company TEXT NOT NULL,
            batch_number INTEGER NOT NULL,
            description TEXT,
            batch_date TEXT,
            posted INTEGER DEFAULT 0,
            posted_at TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (company, batch_number)
        );
        CREATE TABLE IF NOT EXISTS entry (
            company TEXT NOT NULL,
            batch_number INTEGER NOT NULL,
            document_number TEXT NOT NULL,
            customer_number TEXT NOT NULL,
            document_total REAL,
            external_reference TEXT,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (company, batch_number, document_number)
        );
    """)
    conn.commit()
    conn.close()


def next_batch_number(company):
    conn = db()
    row = conn.execute(
        "SELECT COALESCE(MAX(batch_number), 0) + 1 AS n FROM batch WHERE company=?",
        (company,),
    ).fetchone()
    conn.close()
    return int(row["n"])


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def requires_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Basic "):
            return _auth_fail()
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8", errors="replace")
            user, _, pw = decoded.partition(":")
        except Exception:
            return _auth_fail()
        if user != AUTH_USER or pw != AUTH_PASS:
            return _auth_fail()
        return fn(*args, **kwargs)
    return wrapper


def _auth_fail():
    resp = jsonify({"error": {"code": "unauthorized", "message": "Invalid credentials"}})
    resp.status_code = 401
    resp.headers["WWW-Authenticate"] = 'Basic realm="Sage 300 Mock"'
    return resp


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return jsonify({
        "service": "Sage 300 Mock Server",
        "purpose": "Development/demo mock — mirrors Sage 300 Web API contract.",
        "repo": "https://github.com/estain-makaudze/zimpreneur-datasmith",
        "auth": "HTTP Basic Auth (demo / demo123 by default)",
        "endpoints": [
            "GET  /Sage300WebApi/v1.0/-/<company>/AR/Customers",
            "POST /Sage300WebApi/v1.0/-/<company>/AR/Customers",
            "POST /Sage300WebApi/v1.0/-/<company>/AR/InvoiceBatches",
            "GET  /Sage300WebApi/v1.0/-/<company>/AR/InvoiceBatches/<id>",
            "POST /Sage300WebApi/v1.0/-/<company>/AR/InvoiceEntries",
            "POST /Sage300WebApi/v1.0/-/<company>/AR/InvoiceBatches/<id>/Post",
        ],
    })


# --- Base URL shape mirrors Sage: /Sage300WebApi OR / (both accepted) ---
BASE = "/Sage300WebApi/v1.0/-/<company>"
BASE_SHORT = "/v1.0/-/<company>"


def _dual_route(path, **kwargs):
    """Register the same handler at both /Sage300WebApi/... and /v1.0/... so
    clients that strip or keep the /Sage300WebApi prefix both work in demo."""
    def decorator(fn):
        app.add_url_rule(f"{BASE}{path}", endpoint=fn.__name__ + "_full",
                         view_func=requires_auth(fn), **kwargs)
        app.add_url_rule(f"{BASE_SHORT}{path}", endpoint=fn.__name__ + "_short",
                         view_func=requires_auth(fn), **kwargs)
        return fn
    return decorator


# ---- Customers ----------------------------------------------------------------
@_dual_route("/AR/Customers", methods=["GET"])
def list_customers(company):
    top = int(request.args.get("$top", 100))
    conn = db()
    rows = conn.execute(
        "SELECT customer_number, payload FROM customer WHERE company=? ORDER BY customer_number LIMIT ?",
        (company, top),
    ).fetchall()
    conn.close()
    items = []
    for r in rows:
        import json as _json
        p = _json.loads(r["payload"])
        p["CustomerNumber"] = r["customer_number"]
        items.append(p)
    return jsonify({"@odata.context": f"{request.base_url}/$metadata", "value": items})


@_dual_route("/AR/Customers", methods=["POST"])
def create_customer(company):
    import json as _json
    payload = request.get_json(silent=True) or {}
    cn = payload.get("CustomerNumber")
    if not cn:
        return jsonify({"error": {"code": "validation", "message": "CustomerNumber required"}}), 400
    conn = db()
    try:
        conn.execute(
            "INSERT INTO customer (company, customer_number, payload, created_at) VALUES (?,?,?,?)",
            (company, cn, _json.dumps(payload), datetime.utcnow().isoformat() + "Z"),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": {"code": "conflict", "message": f"CustomerNumber {cn} already exists"}}), 409
    conn.close()
    return jsonify(payload), 201


# ---- Invoice Batches ----------------------------------------------------------
@_dual_route("/AR/InvoiceBatches", methods=["POST"])
def create_batch(company):
    payload = request.get_json(silent=True) or {}
    bn = next_batch_number(company)
    conn = db()
    conn.execute(
        "INSERT INTO batch (company, batch_number, description, batch_date, created_at) VALUES (?,?,?,?,?)",
        (company, bn, payload.get("BatchDescription") or "", payload.get("BatchDate"),
         datetime.utcnow().isoformat() + "Z"),
    )
    conn.commit()
    conn.close()
    return jsonify({
        "BatchNumber": bn,
        "BatchDescription": payload.get("BatchDescription"),
        "BatchDate": payload.get("BatchDate"),
        "Posted": False,
    }), 201


@_dual_route("/AR/InvoiceBatches/<int:batch_number>", methods=["GET"])
def read_batch(company, batch_number):
    conn = db()
    row = conn.execute(
        "SELECT * FROM batch WHERE company=? AND batch_number=?", (company, batch_number),
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": {"code": "not_found", "message": f"batch {batch_number} not found"}}), 404
    entries = conn.execute(
        "SELECT document_number, customer_number, document_total, external_reference FROM entry "
        "WHERE company=? AND batch_number=? ORDER BY document_number",
        (company, batch_number),
    ).fetchall()
    conn.close()
    return jsonify({
        "BatchNumber": row["batch_number"],
        "BatchDescription": row["description"],
        "BatchDate": row["batch_date"],
        "Posted": bool(row["posted"]),
        "PostedAt": row["posted_at"],
        "Entries": [dict(e) for e in entries],
    })


@_dual_route("/AR/InvoiceBatches/<int:batch_number>/Post", methods=["POST"])
def post_batch(company, batch_number):
    conn = db()
    row = conn.execute(
        "SELECT batch_number, posted FROM batch WHERE company=? AND batch_number=?",
        (company, batch_number),
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": {"code": "not_found", "message": f"batch {batch_number} not found"}}), 404
    if row["posted"]:
        conn.close()
        return jsonify({"BatchNumber": batch_number, "Posted": True, "Message": "already posted"})
    conn.execute(
        "UPDATE batch SET posted=1, posted_at=? WHERE company=? AND batch_number=?",
        (datetime.utcnow().isoformat() + "Z", company, batch_number),
    )
    conn.commit()
    conn.close()
    return jsonify({"BatchNumber": batch_number, "Posted": True})


# ---- Invoice Entries ----------------------------------------------------------
@_dual_route("/AR/InvoiceEntries", methods=["POST"])
def create_entry(company):
    import json as _json
    payload = request.get_json(silent=True) or {}
    bn = payload.get("BatchNumber")
    if bn is None:
        return jsonify({"error": {"code": "validation", "message": "BatchNumber required"}}), 400
    try:
        bn = int(bn)
    except (TypeError, ValueError):
        return jsonify({"error": {"code": "validation", "message": "BatchNumber must be int"}}), 400
    doc = payload.get("DocumentNumber") or f"AUTO-{bn}-{int(datetime.utcnow().timestamp())}"
    conn = db()
    batch = conn.execute(
        "SELECT posted FROM batch WHERE company=? AND batch_number=?", (company, bn),
    ).fetchone()
    if not batch:
        conn.close()
        return jsonify({"error": {"code": "not_found", "message": f"batch {bn} not found"}}), 404
    if batch["posted"]:
        conn.close()
        return jsonify({"error": {"code": "closed", "message": f"batch {bn} is already posted"}}), 409

    # Idempotency: look for an existing entry with the same ExternalReference
    ext = payload.get("ExternalReference")
    if ext:
        existing = conn.execute(
            "SELECT document_number FROM entry WHERE company=? AND batch_number=? AND external_reference=?",
            (company, bn, ext),
        ).fetchone()
        if existing:
            conn.close()
            return jsonify({
                "BatchNumber": bn,
                "DocumentNumber": existing["document_number"],
                "Duplicate": True,
                "Message": "Entry with same ExternalReference already present.",
            })

    try:
        conn.execute(
            "INSERT INTO entry (company, batch_number, document_number, customer_number, "
            "document_total, external_reference, payload, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (company, bn, doc, payload.get("CustomerNumber"),
             float(payload.get("DocumentTotal") or 0), ext, _json.dumps(payload),
             datetime.utcnow().isoformat() + "Z"),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": {"code": "conflict", "message": f"DocumentNumber {doc} already exists in batch {bn}"}}), 409
    conn.close()
    return jsonify({"BatchNumber": bn, "DocumentNumber": doc}), 201


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5555)
    args = parser.parse_args()

    init_db()
    print(f"mock_sage_server listening on http://{args.host}:{args.port}  db={DB_PATH}")
    app.run(host=args.host, port=args.port, debug=False)
