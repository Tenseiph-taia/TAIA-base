import asyncio
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
import sqlparse
from mcp.server.fastmcp import FastMCP

# ── Init ───────────────────────────────────────────────────────────────────────
mcp = FastMCP("Nexus-Sales-Integration", host="0.0.0.0", port=8000)
logger = logging.getLogger("nexus-sales")
logging.basicConfig(level=logging.INFO)

DB_PATH = Path(os.getenv("DB_PATH", "/app/data/sales_demo.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _init_db() -> None:
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                id               INTEGER PRIMARY KEY,
                name             TEXT    NOT NULL,
                sku              TEXT    UNIQUE,
                price            REAL    NOT NULL,
                stock_quantity   INTEGER NOT NULL,
                description      TEXT
            );

            CREATE TABLE IF NOT EXISTS sales_orders (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name    TEXT    NOT NULL,
                contact_email    TEXT    NOT NULL,
                product_name     TEXT    NOT NULL,
                quantity         INTEGER NOT NULL,
                total_price      REAL    NOT NULL,
                status           TEXT    DEFAULT 'PENDING',
                notes            TEXT,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at      TIMESTAMP,
                reviewed_by      TEXT
            );
        """)

        # Seed Nexus Grid Systems products
        if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO products (name, sku, price, stock_quantity, description) VALUES (?, ?, ?, ?, ?)",[
                    ("Vertex Hub Pro",       "NGS-VHP-01",  1450.00,    50, "Centralized smart building controller with AI optimization"),
                    ("Omni-Link Mesh Node",  "NGS-OLN-05",   320.00,   200, "Industrial-grade mesh networking node for large-scale IoT"),
                    ("SkyStream Analytics",  "NGS-SSA-YR",   899.00, 9999, "Annual subscription for real-time sensor data visualization"),
                    ("Nexus Core Dev-Kit",   "NGS-CDK-02",   199.00,   100, "Advanced prototyping kit for custom grid automation"),
                ],
            )
        conn.commit()
    logger.info(f"[Nexus-Sales] Database ready at {DB_PATH}")

_init_db()

_BANNED_KEYWORDS = {"INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "ATTACH", "DETACH", "PRAGMA", "VACUUM"}

def _validate_select(sql: str) -> tuple[bool, str]:
    sql = sql.strip().rstrip(";")
    statements = sqlparse.parse(sql)
    if len(statements) != 1: return False, "Only a single SQL statement is allowed."
    stmt = statements[0]
    if stmt.get_type() != "SELECT": return False, "Only SELECT statements are permitted."
    tokens_upper = {t.normalized.upper() for t in stmt.flatten()}
    blocked = tokens_upper & _BANNED_KEYWORDS
    if blocked: return False, f"Disallowed keyword(s) detected: {', '.join(blocked)}"
    return True, "OK"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
def _valid_email(email: str) -> bool: return bool(_EMAIL_RE.match(email))

@mcp.tool()
def get_database_schema() -> str:
    """Returns the live ERP database schema. Call FIRST before writing SQL."""
    return """
    TABLE: products
      id              INTEGER  PRIMARY KEY
      name            TEXT     Product display name
      sku             TEXT     Unique product code
      price           REAL     Unit price in USD
      stock_quantity  INTEGER  Units available
      description     TEXT     Marketing description

    TABLE: sales_orders
      id              INTEGER  PRIMARY KEY (auto)
      customer_name   TEXT     Full name of the customer
      contact_email   TEXT     Customer email
      product_name    TEXT     Name of the ordered product
      quantity        INTEGER  Number of units ordered
      total_price     REAL     quantity × unit price
      status          TEXT     PENDING | APPROVED | REJECTED
      notes           TEXT     Optional notes from reviewer
    """

@mcp.tool()
async def query_erp_database(sql_query: str) -> str:
    """Executes a READ-ONLY SELECT query against the ERP database."""
    is_safe, reason = _validate_select(sql_query)
    if not is_safe: return f"SECURITY ERROR: {reason}"
    def _run():
        with _conn() as conn:
            return[dict(row) for row in conn.execute(sql_query).fetchmany(100)]
    try:
        rows = await asyncio.to_thread(_run)
        return json.dumps(rows, indent=2, default=str) if rows else "Query returned no results."
    except Exception as e: return f"Database error: {e}"

@mcp.tool()
async def check_product_availability(product_name: str) -> str:
    """Quick lookup: is this product in stock and what does it cost?"""
    def _run():
        with _conn() as conn:
            return[dict(r) for r in conn.execute("SELECT name, sku, price, stock_quantity, description FROM products WHERE name LIKE ? LIMIT 5", (f"%{product_name}%",)).fetchall()]
    try:
        rows = await asyncio.to_thread(_run)
        return json.dumps(rows, indent=2) if rows else f"No product matching '{product_name}' found."
    except Exception as e: return f"Lookup failed: {e}"

@mcp.tool()
async def submit_sales_order(customer_name: str, contact_email: str, product_name: str, quantity: int) -> str:
    """Submits a quote/order and deducts inventory immediately."""
    customer_name, contact_email, product_name = customer_name.strip(), contact_email.strip().lower(), product_name.strip()
    if not customer_name: return "Error: Customer name cannot be empty."
    if not _valid_email(contact_email): return f"Error: '{contact_email}' is not valid."
    if quantity <= 0: return "Error: Quantity must be at least 1."

    def _run():
        with _conn() as conn:
            product = conn.execute("SELECT id, name, price, stock_quantity FROM products WHERE name LIKE ? LIMIT 1", (f"%{product_name}%",)).fetchone()
            if not product: return None, f"Product '{product_name}' not found."
            if product["stock_quantity"] < quantity:
                return None, f"Insufficient stock. Requested {quantity}, only {product['stock_quantity']} available."
            
            total_price = product["price"] * quantity
            
            # Deduct Inventory
            conn.execute("UPDATE products SET stock_quantity = stock_quantity - ? WHERE id = ?", (quantity, product["id"]))
            
            cursor = conn.execute(
                "INSERT INTO sales_orders (customer_name, contact_email, product_name, quantity, total_price, status) VALUES (?, ?, ?, ?, ?, 'PENDING')",
                (customer_name, contact_email, product["name"], quantity, total_price)
            )
            conn.commit()
            return cursor.lastrowid, None

    try:
        order_id, error = await asyncio.to_thread(_run)
        if error: return f"Order failed: {error}"
        return f"✅ Order #{order_id} submitted! Status: PENDING Admin Verification."
    except Exception as e: return f"Failed to submit order: {e}"

@mcp.tool()
async def get_order_status(order_id: int) -> str:
    """Checks the status of an order."""
    def _run():
        with _conn() as conn:
            row = conn.execute("SELECT * FROM sales_orders WHERE id = ?", (order_id,)).fetchone()
            return dict(row) if row else None
    try:
        order = await asyncio.to_thread(_run)
        return json.dumps(order, indent=2, default=str) if order else f"No order found with ID #{order_id}."
    except Exception as e: return f"Lookup failed: {e}"

if __name__ == "__main__":
    mcp.run(transport="sse")