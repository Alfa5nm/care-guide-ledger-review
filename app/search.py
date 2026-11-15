import json
import math
import re
from collections import Counter

# Synonym groups define the local vocabulary shared by queries and documents.
CONCEPTS = [
    ("billing", "bill", "invoice", "receipt", "statement", "payable", "invoicing"),
    ("vendor", "supplier", "merchant", "seller", "provider", "distributor"),
    ("customer", "client", "buyer", "purchaser", "recipient"),
    ("shipping", "shipping fee", "freight", "delivery", "transport", "courier", "logistics"),
    ("stationery", "stationary", "office supplies", "notebook", "paper", "pen", "pens"),
    ("hardware", "computer", "laptop", "monitor", "keyboard", "equipment", "electronics"),
    ("consulting", "consultancy", "advisory", "professional services", "consultation"),
    ("software", "subscription", "licence", "license", "saas"),
    ("tax", "vat", "gst", "duty", "levy"),
    ("discount", "rebate", "markdown", "deduction"),
    ("refund", "credit note", "reimbursement", "reversal"),
    ("maintenance", "repair", "servicing", "upkeep", "inspection"),
    ("food", "meal", "catering", "groceries", "beverage"),
    ("medical", "healthcare", "clinic", "hospital", "pharmacy"),
    ("rent", "lease", "rental", "occupancy"),
    ("resale", "wholesale", "bulk", "trade"),
    ("balance", "amount due", "outstanding", "owed", "unpaid"),
]
STOP = set("the a an for to of and in on from with find show all me".split())


def terms(text):
    return re.findall(r"[^\W_]+", text.lower())


def vector(text):
    tokens = terms(text)
    counts = Counter()
    for token in set(tokens) - STOP:
        counts[f"word:{token}"] = 0.22
    joined = " " + " ".join(tokens) + " "
    for index, words in enumerate(CONCEPTS):
        if any(f" {word} " in joined for word in words):
            counts[f"concept:{index}"] = 1
    length = math.sqrt(sum(weight * weight for weight in counts.values()))
    return {key: value / length for key, value in counts.items()} if length else {}


def index_document(db, document_id, body, name):
    invoices = db.execute("SELECT data FROM invoices WHERE document_id=?", (document_id,))
    facts = " ".join(
        str(value)
        for invoice in invoices
        for value in json.loads(invoice["data"]).values()
        if value is not None
    )
    full_text = f"{name}\n{facts}\n{body}"
    db.execute("DELETE FROM document_search WHERE document_id=?", (document_id,))
    db.execute("INSERT INTO document_search VALUES (?,?)", (document_id, full_text))
    # Bound the sparse vector's size even for large, mostly unique documents.
    features = vector(f"{facts[:20000]}\n{name}\n{body[:40000]}")
    db.execute("INSERT OR REPLACE INTO search_vectors VALUES (?,?)", (document_id, json.dumps(features)))


def search(db, query, mode, status, limit=40):
    tokens = terms(query)[:12]
    if not tokens:
        return []
    if mode == "keyword":
        rows = db.execute(
            """SELECT d.id,d.name,d.status,d.stage,d.progress,d.attempt,d.processing_ms,
                      snippet(document_search,1,'','',' … ',22) AS excerpt
               FROM document_search JOIN documents d ON d.id=document_search.document_id
               WHERE document_search MATCH ? AND (? IS NULL OR d.status=?)
               ORDER BY bm25(document_search) LIMIT ?""",
            (" AND ".join(f'"{token}"*' for token in tokens), status, status, limit),
        )
        return [dict(row) for row in rows]
    query_vector = vector(query)
    matches = []
    rows = db.execute(
        """SELECT d.id,d.name,d.status,d.stage,d.progress,d.attempt,d.processing_ms,
                  substr(d.body,1,240) AS excerpt,v.vector
           FROM search_vectors v JOIN documents d ON d.id=v.document_id
           WHERE (? IS NULL OR d.status=?)""", (status, status),
    )
    for row in rows:
        features = json.loads(row["vector"])
        score = sum(weight * features.get(key, 0) for key, weight in query_vector.items())
        if score > 0.04:
            result = dict(row)
            result.pop("vector")
            result["score"] = round(score, 4)
            matches.append(result)
    return sorted(matches, key=lambda match: -match["score"])[:limit]
