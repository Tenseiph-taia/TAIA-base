import asyncio
import logging
import os
import sqlite3
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Nexus Admin API", version="1.0.0")
logger = logging.getLogger("nexus-admin")
logging.basicConfig(level=logging.INFO)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DB_PATH = Path(os.getenv("DB_PATH", "/app/data/sales_demo.db"))
LIBRECHAT_URL = os.getenv("LIBRECHAT_URL", "http://localhost:3080")
AGENT_ID = os.getenv("AGENT_ID", "agent_taia_default")
API_KEY = os.getenv("API_KEY", "sk-...")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

def _configure_sqlite(conn: sqlite3.Connection) -> None:
    """Configure SQLite for concurrent access with WAL mode."""
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA synchronous=NORMAL;")

class ChatRequest(BaseModel):
    messages: list[dict]

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Initialize and configure SQLite
with _conn() as conn:
    _configure_sqlite(conn)

def send_approval_email(customer_email: str, order_id: int, product_name: str, notes: str):
    if not SMTP_USER or not SMTP_PASS: return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Order #{order_id} Approved | Nexus Grid Systems"
    msg["From"] = f"Nexus Sales Team <{SMTP_USER}>"
    msg["To"] = customer_email

    safe_notes = notes if notes else 'No additional notes.'
    html_content = f"""
    <html>
      <body style="font-family: 'Segoe UI', Arial, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background-color: #00d4ff; padding: 20px; text-align: center; border-radius: 8px 8px 0 0;">
            <h2 style="color: #0b0e14; margin: 0; font-weight: 700; letter-spacing: 0.5px;">Nexus Grid Systems</h2>
        </div>
        <div style="border: 1px solid #ddd; border-top: none; padding: 20px; border-radius: 0 0 8px 8px;">
            <p>Hello,</p>
            <p>Your infrastructure order has been manually verified and approved by our engineering team.</p>
            <table style="width: 100%; border-collapse: collapse; margin-top: 15px;">
                <tr><td style="padding: 10px 0; border-bottom: 1px solid #eee;"><strong>Order ID:</strong></td><td style="padding: 10px 0; border-bottom: 1px solid #eee;">#{order_id}</td></tr>
                <tr><td style="padding: 10px 0; border-bottom: 1px solid #eee;"><strong>Product:</strong></td><td style="padding: 10px 0; border-bottom: 1px solid #eee;">{product_name}</td></tr>
                <tr><td style="padding: 10px 0; border-bottom: 1px solid #eee;"><strong>Status:</strong></td><td style="padding: 10px 0; border-bottom: 1px solid #eee; color: #00d4ff; font-weight: bold;">APPROVED</td></tr>
            </table>
            <p style="margin-top: 25px;"><strong>Admin Notes:</strong><br>
            <span style="background: #f8f9fa; padding: 12px; display: block; border-left: 4px solid #00d4ff; margin-top: 8px;">{safe_notes}</span></p>
        </div>
      </body>
    </html>
    """
    msg.attach(MIMEText(html_content, "html"))
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, customer_email, msg.as_string())
        server.quit()
    except Exception as e: logger.error(f"[Email Error] {e}")

class ReviewPayload(BaseModel):
    reviewed_by: str
    notes: Optional[str] = None

@app.get("/health")
def health(): return {"status": "ok"}

@app.get("/stats")
async def get_stats():
    def _run():
        with _conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM sales_orders").fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM sales_orders WHERE status='PENDING'").fetchone()[0]
            approved = conn.execute("SELECT COUNT(*) FROM sales_orders WHERE status='APPROVED'").fetchone()[0]
            rejected = conn.execute("SELECT COUNT(*) FROM sales_orders WHERE status='REJECTED'").fetchone()[0]
            revenue = conn.execute("SELECT COALESCE(SUM(total_price),0) FROM sales_orders WHERE status='APPROVED'").fetchone()[0]
            return {"total": total, "pending": pending, "approved": approved, "rejected": rejected, "approved_revenue": round(revenue, 2)}
    return await asyncio.to_thread(_run)

@app.get("/orders")
async def list_orders(status: Optional[str] = None):
    def _run():
        with _conn() as conn:
            if status: return[dict(r) for r in conn.execute("SELECT * FROM sales_orders WHERE status=? ORDER BY created_at DESC", (status.upper(),)).fetchall()]
            return[dict(r) for r in conn.execute("SELECT * FROM sales_orders ORDER BY created_at DESC").fetchall()]
    return await asyncio.to_thread(_run)

@app.post("/orders/{order_id}/approve")
async def approve_order(order_id: int, payload: ReviewPayload, background_tasks: BackgroundTasks):
    def _run():
        with _conn() as conn:
            row = conn.execute("SELECT * FROM sales_orders WHERE id=?", (order_id,)).fetchone()
            if not row: return {"error": "not_found"}
            if row["status"] != "PENDING": return {"error": "not_pending"}
            conn.execute("UPDATE sales_orders SET status='APPROVED', reviewed_at=?, reviewed_by=?, notes=? WHERE id=?", (datetime.utcnow().isoformat(), payload.reviewed_by, payload.notes, order_id))
            conn.commit()
            return {"error": None, "data": dict(row)}
    result = await asyncio.to_thread(_run)
    if result["error"] == "not_found": raise HTTPException(status_code=404)
    if result["error"] == "not_pending": raise HTTPException(status_code=409)
    order_data = result["data"]
    email_target = order_data.get("contact_email") or "client@example.com"
    background_tasks.add_task(send_approval_email, email_target, order_id, order_data.get("product_name"), payload.notes)
    return {"order_id": order_id, "status": "APPROVED"}

@app.post("/orders/{order_id}/reject")
async def reject_order(order_id: int, payload: ReviewPayload):
    def _run():
        with _conn() as conn:
            row = conn.execute("SELECT status, product_name, quantity FROM sales_orders WHERE id=?", (order_id,)).fetchone()
            if not row: return "not_found"
            if row["status"] != "PENDING": return "not_pending"
            
            conn.execute("UPDATE sales_orders SET status='REJECTED', reviewed_at=?, reviewed_by=?, notes=? WHERE id=?", (datetime.utcnow().isoformat(), payload.reviewed_by, payload.notes, order_id))
            # Restore Inventory
            conn.execute("UPDATE products SET stock_quantity = stock_quantity + ? WHERE name = ?", (row["quantity"], row["product_name"]))
            conn.commit()
            return "ok"
    result = await asyncio.to_thread(_run)
    if result == "not_found": raise HTTPException(status_code=404)
    if result == "not_pending": raise HTTPException(status_code=409)
    return {"order_id": order_id, "status": "REJECTED"}

@app.post("/demo/reset")
async def reset_demo_database():
    def _run():
        with _conn() as conn:
            conn.execute("DELETE FROM sales_orders")
            conn.execute("DELETE FROM sqlite_sequence WHERE name='sales_orders'")
            conn.execute("UPDATE products SET stock_quantity = 50 WHERE sku = 'NGS-VHP-01'")
            conn.execute("UPDATE products SET stock_quantity = 200 WHERE sku = 'NGS-OLN-05'")
            conn.execute("UPDATE products SET stock_quantity = 9999 WHERE sku = 'NGS-SSA-YR'")
            conn.execute("UPDATE products SET stock_quantity = 100 WHERE sku = 'NGS-CDK-02'")
            conn.commit()
    await asyncio.to_thread(_run)
    return {"status": "success"}

@app.get("/products")
async def list_products():
    def _run():
        with _conn() as conn: return[dict(r) for r in conn.execute("SELECT * FROM products ORDER BY name").fetchall()]
    return await asyncio.to_thread(_run)

@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Proxy streaming chat requests to LibreChat API."""
    async def event_generator():
        try:
            async with httpx.AsyncClient() as client:
                headers = {
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "messages": request.messages,
                    "stream": True,
                    "model": AGENT_ID,
                }
                async with client.stream(
                    "POST",
                    f"{LIBRECHAT_URL}/api/agents/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60.0,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line:
                            if line.startswith('data: '):
                                yield f"{line}\n\n"
                            else:
                                yield f"data: {line}\n\n"
        except Exception as e:
            yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    import asyncio
    import concurrent.futures
    from uvicorn import Config, Server

    async def serve():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=20))
        config = Config(app, host="0.0.0.0", port=8001)
        server = Server(config)
        await server.serve()

    asyncio.run(serve())