import json
import logging
import os
import sqlite3
import uuid
import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Annotated

from dotenv import load_dotenv
from pydantic import Field
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RoomInputOptions,
    WorkerOptions,
    cli,
    function_tool,
    RunContext,
)

from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

load_dotenv(".env.local")

DB_NAME = "order_db.sqlite"

def db_path():
    return os.path.join(os.path.dirname(__file__), DB_NAME)

def conn():
    c = sqlite3.connect(db_path(), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON;")
    return c

def ensure_db():
    c = conn()
    cur = c.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS catalog (
      id TEXT PRIMARY KEY,
      name TEXT,
      category TEXT,
      price REAL,
      brand TEXT,
      size TEXT,
      units TEXT,
      tags TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
      order_id TEXT PRIMARY KEY,
      timestamp TEXT,
      total REAL,
      customer_name TEXT,
      address TEXT,
      status TEXT,
      created_at TEXT DEFAULT (datetime('now')),
      updated_at TEXT DEFAULT (datetime('now'))
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS order_items (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      order_id TEXT,
      item_id TEXT,
      name TEXT,
      unit_price REAL,
      quantity INTEGER,
      notes TEXT,
      FOREIGN KEY(order_id) REFERENCES orders(order_id) ON DELETE CASCADE
    )""")
    cur.execute("SELECT COUNT(1) FROM catalog")
    if cur.fetchone()[0] == 0:
        sample = [
    ("bread-400g","Britannia Bread 400g","Bakery",50.0,"Britannia","400g","pack",json.dumps(["bread","breakfast"])),
    ("eggs-6pc","Fresh Eggs Pack of 6","Dairy & Eggs",65.0,"Farm Fresh","6pcs","tray",json.dumps(["eggs","protein"])),
    ("oil-1l","Fortune Sunflower Oil 1L","Staples",145.0,"Fortune","1L","bottle",json.dumps(["cooking oil","essential"])),
    ("biscuit-parle-g","Parle-G Biscuits 800g","Snacks",72.0,"Parle","800g","pack",json.dumps(["biscuits","snack"])),
    ("coffee-200g","Nescafé Classic Coffee 200g","Beverages",340.0,"Nescafé","200g","jar",json.dumps(["coffee","caffeine"])),
    ("dal-tur-1kg","Tur Dal 1kg","Staples",130.0,"Urad","1kg","bag",json.dumps(["dal","protein"])),
    ("soap-4pack","Dettol Soap (4 x 125g)","Personal Care",199.0,"Dettol","4x125g","pack",json.dumps(["soap","hygiene"])),
    ("shampoo-340ml","Dove Shampoo 340ml","Personal Care",265.0,"Dove","340ml","bottle",json.dumps(["hair care"])),
    ("salt-1kg","Tata Salt 1kg","Staples",28.0,"Tata","1kg","pack",json.dumps(["salt","essential"])),
    ("chips-lays-50g","Lays Classic Salted 50g","Snacks",20.0,"Lays","50g","pack",json.dumps(["chips","snack"]))
]

        cur.executemany("""
            INSERT INTO catalog (id,name,category,price,brand,size,units,tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, sample)
        c.commit()
    c.close()

ensure_db()

@dataclass
class CartLine:
    item_id: str
    name: str
    unit_price: float
    quantity: int = 1
    notes: str = ""

@dataclass
class SessionState:
    cart: List[CartLine] = field(default_factory=list)
    customer: Optional[str] = None
    order_ref: Optional[str] = None

def find_item_db(item_id: str):
    c = conn()
    r = c.execute("SELECT * FROM catalog WHERE LOWER(id)=LOWER(?) LIMIT 1", (item_id,)).fetchone()
    c.close()
    return dict(r) if r else None

def search_db(q: str, limit: int = 10):
    qlike = f"%{q.lower()}%"
    c = conn()
    rows = c.execute("SELECT * FROM catalog WHERE LOWER(name) LIKE ? OR LOWER(tags) LIKE ? LIMIT ?", (qlike, qlike, limit)).fetchall()
    c.close()
    res = []
    for r in rows:
        rec = dict(r)
        try:
            rec["tags"] = json.loads(rec.get("tags") or "[]")
        except Exception:
            rec["tags"] = []
        res.append(rec)
    return res

def cart_total(cart: List[CartLine]) -> float:
    return round(sum(c.unit_price * c.quantity for c in cart), 2)

def persist_order(order_id: str, cust: str, addr: str, items: List[CartLine], total: float):
    c = conn()
    cur = c.cursor()
    cur.execute("INSERT INTO orders (order_id, timestamp, total, customer_name, address, status) VALUES (?, ?, ?, ?, ?, ?)",
                (order_id, datetime.utcnow().isoformat()+"Z", total, cust, addr, "received"))
    for it in items:
        cur.execute("INSERT INTO order_items (order_id,item_id,name,unit_price,quantity,notes) VALUES (?,?,?,?,?,?)",
                    (order_id, it.item_id, it.name, it.unit_price, it.quantity, it.notes))
    c.commit()
    c.close()

def read_order(order_id: str):
    c = conn()
    o = c.execute("SELECT * FROM orders WHERE order_id = ? LIMIT 1", (order_id,)).fetchone()
    if not o:
        c.close()
        return None
    items = [dict(r) for r in c.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,)).fetchall()]
    od = dict(o)
    od["items"] = items
    c.close()
    return od

def update_order_status(order_id: str, new_status: str):
    c = conn()
    cur = c.cursor()
    cur.execute("UPDATE orders SET status = ?, updated_at = datetime('now') WHERE order_id = ?", (new_status, order_id))
    c.commit()
    changed = cur.rowcount
    c.close()
    return changed > 0

async def simulate_progress(order_id: str):
    flow = ["received","confirmed","shipped","out_for_delivery","delivered"]
    await asyncio.sleep(4)
    for s in flow[1:]:
        o = read_order(order_id)
        if not o or o.get("status") == "cancelled":
            return
        update_order_status(order_id, s)
        await asyncio.sleep(4)

def save_summary_file(data: dict):
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "summaries"))
    os.makedirs(base, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(base, f"{ts}_{str(uuid.uuid4())[:8]}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path

@function_tool
async def find_item(ctx: RunContext[SessionState], q: Annotated[str, Field(description="query")]):
    items = search_db(q)
    if not items:
        return f"No results for '{q}'."
    lines = [f"{it['id']} | {it['name']} | ₹{it['price']:.2f}" for it in items[:10]]
    return "Results:\n" + "\n".join(lines)

@function_tool
async def add_item(ctx: RunContext[SessionState], item_id: Annotated[str, Field(description="id")], quantity: Annotated[int, Field(description="quantity", default=1)], notes: Annotated[str, Field(description="notes", default="")]):
    it = find_item_db(item_id)
    if not it:
        return f"Item '{item_id}' not found."
    for cl in ctx.userdata.cart:
        if cl.item_id.lower() == item_id.lower():
            cl.quantity += quantity
            if notes:
                cl.notes = notes
            return f"Updated {cl.name} to qty {cl.quantity}. Total: ₹{cart_total(ctx.userdata.cart):.2f}"
    cl = CartLine(item_id=item_id, name=it["name"], unit_price=float(it["price"]), quantity=quantity, notes=notes)
    ctx.userdata.cart.append(cl)
    return f"Added {quantity} x {cl.name}. Cart total: ₹{cart_total(ctx.userdata.cart):.2f}"

@function_tool
async def remove_item(ctx: RunContext[SessionState], item_id: Annotated[str, Field(description="id")]):
    before = len(ctx.userdata.cart)
    ctx.userdata.cart = [c for c in ctx.userdata.cart if c.item_id.lower() != item_id.lower()]
    if len(ctx.userdata.cart) == before:
        return f"Item {item_id} was not in cart."
    return f"Removed {item_id}. Cart total: ₹{cart_total(ctx.userdata.cart):.2f}"

@function_tool
async def set_qty(ctx: RunContext[SessionState], item_id: Annotated[str, Field(description="id")], quantity: Annotated[int, Field(description="qty")]):
    if quantity < 1:
        return await remove_item(ctx, item_id)
    for cl in ctx.userdata.cart:
        if cl.item_id.lower() == item_id.lower():
            cl.quantity = quantity
            return f"Set {cl.name} to {quantity}. Total: ₹{cart_total(ctx.userdata.cart):.2f}"
    return f"Item {item_id} not in cart."

@function_tool
async def show_cart(ctx: RunContext[SessionState]):
    if not ctx.userdata.cart:
        return "Cart is empty."
    lines = [f"{c.quantity} x {c.name} @ ₹{c.unit_price:.2f} = ₹{c.unit_price * c.quantity:.2f}" for c in ctx.userdata.cart]
    return "Your cart:\n" + "\n".join(lines) + f"\nTotal: ₹{cart_total(ctx.userdata.cart):.2f}"

@function_tool
async def add_recipe(ctx: RunContext[SessionState], dish: Annotated[str, Field(description="dish")]):
    mapping = {
        "chai": ["milk-amul-1l","tea-250g","sugar-1kg","ginger-100g"],
        "maggi": ["maggi-masala"]
    }
    k = dish.strip().lower()
    if k not in mapping:
        return f"No recipe for {dish}."
    added = []
    for iid in mapping[k]:
        it = find_item_db(iid)
        if not it:
            continue
        found = False
        for cl in ctx.userdata.cart:
            if cl.item_id.lower() == iid.lower():
                cl.quantity += 1
                found = True
                break
        if not found:
            ctx.userdata.cart.append(CartLine(item_id=iid, name=it["name"], unit_price=float(it["price"]), quantity=1))
        added.append(it["name"])
    return f"Added {', '.join(added)}. Total: ₹{cart_total(ctx.userdata.cart):.2f}"

@function_tool
async def place_order(ctx: RunContext[SessionState], customer_name: Annotated[str, Field(description="name")], address: Annotated[str, Field(description="address")]):
    if not ctx.userdata.cart:
        return "Cart empty."
    oid = str(uuid.uuid4())[:8]
    total = cart_total(ctx.userdata.cart)
    persist_order(oid, customer_name, address, ctx.userdata.cart, total)
    ctx.userdata.cart = []
    ctx.userdata.customer = customer_name
    ctx.userdata.order_ref = oid
    try:
        asyncio.create_task(simulate_progress(oid))
    except RuntimeError:
        pass
    summary = {"order_id": oid, "customer": customer_name, "total": total, "timestamp": datetime.utcnow().isoformat()+"Z"}
    save_summary_file(summary)
    return f"Order placed. ID: {oid}. Total: ₹{total:.2f}"

@function_tool
async def cancel_order(ctx: RunContext[SessionState], order_id: Annotated[str, Field(description="order id")]):
    o = read_order(order_id)
    if not o:
        return f"No order {order_id}."
    if o.get("status") == "delivered":
        return f"Order {order_id} already delivered."
    update_order_status(order_id, "cancelled")
    return f"Order {order_id} cancelled."

@function_tool
async def order_status(ctx: RunContext[SessionState], order_id: Annotated[str, Field(description="order id")]):
    o = read_order(order_id)
    if not o:
        return f"No order {order_id}."
    return f"Order {order_id} status: {o.get('status')} (updated {o.get('updated_at')})"

class ShopAgent(Agent):
    def __init__(self):
        super().__init__(instructions="""
You are an assistant for a grocery shop.
Use the provided tools to search, manage cart, and place orders.
""", tools=[find_item, add_item, remove_item, set_qty, show_cart, add_recipe, place_order, cancel_order, order_status])

def prewarm(p: JobProcess):
    try:
        p.userdata["vad"] = silero.VAD.load()
    except Exception:
        pass

async def entrypoint(ctx: JobContext):
    ud = SessionState()
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(voice="en-US-marcus", style="Conversational"),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata.get("vad"),
        userdata=ud,
    )
    await session.start(agent=ShopAgent(), room=ctx.room, room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()))
    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
