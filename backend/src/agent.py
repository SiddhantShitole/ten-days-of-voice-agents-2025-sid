import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Annotated

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

# -------------------------
# Logging
# -------------------------
logger = logging.getLogger("lite_acp_agent")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)

load_dotenv(".env.local")

# -------------------------
# Product Catalog (Lite ACP)
# -------------------------
CATALOG = [
    # Kitchenware
    {"id": "bottle-001", "name": "Stainless Steel Water Bottle", "price": 599, "currency": "INR", "category": "kitchenware", "color": "silver"},
    {"id": "pan-001", "name": "Non-stick Frying Pan", "price": 899, "currency": "INR", "category": "kitchenware", "color": "black"},
    {"id": "cutlery-001", "name": "Premium Cutlery Set", "price": 1299, "currency": "INR", "category": "kitchenware", "color": "silver"},
    
    # Stationery
    {"id": "notebook-001", "name": "Hardcover Notebook", "price": 299, "currency": "INR", "category": "stationery", "color": "blue"},
    {"id": "pen-001", "name": "Luxury Fountain Pen", "price": 699, "currency": "INR", "category": "stationery", "color": "black"},
    {"id": "planner-001", "name": "2025 Daily Planner", "price": 499, "currency": "INR", "category": "stationery", "color": "green"},
    
    # Fitness
    {"id": "yoga-001", "name": "Eco-friendly Yoga Mat", "price": 1499, "currency": "INR", "category": "fitness", "color": "purple"},
    {"id": "dumbbell-001", "name": "Adjustable Dumbbells (2kg-10kg)", "price": 2499, "currency": "INR", "category": "fitness", "color": "black"},
    {"id": "towel-001", "name": "Microfiber Gym Towel", "price": 399, "currency": "INR", "category": "fitness", "color": "grey"},
    
    # Electronics
    {"id": "speaker-001", "name": "Bluetooth Speaker", "price": 1999, "currency": "INR", "category": "electronics", "color": "red"},
    {"id": "earbuds-001", "name": "Wireless Earbuds", "price": 2999, "currency": "INR", "category": "electronics", "color": "white"},
    {"id": "powerbank-001", "name": "10000mAh Power Bank", "price": 1499, "currency": "INR", "category": "electronics", "color": "black"},
    
    # Home Decor
    {"id": "lamp-001", "name": "LED Desk Lamp", "price": 799, "currency": "INR", "category": "homedecor", "color": "white"},
    {"id": "cushion-001", "name": "Velvet Cushion Cover", "price": 499, "currency": "INR", "category": "homedecor", "color": "maroon"},
    {"id": "wallart-001", "name": "Canvas Wall Art", "price": 1299, "currency": "INR", "category": "homedecor", "color": "multicolor"},
    
    # Snacks
    {"id": "chips-001", "name": "Masala Chips Pack", "price": 149, "currency": "INR", "category": "snacks", "color": "orange"},
    {"id": "nuts-001", "name": "Mixed Nuts 250g", "price": 399, "currency": "INR", "category": "snacks", "color": "brown"},
    {"id": "chocolate-001", "name": "Dark Chocolate Bar", "price": 199, "currency": "INR", "category": "snacks", "color": "black"},
]


# -------------------------
# User Session Data
# -------------------------
@dataclass
class Userdata:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    cart: List[Dict] = field(default_factory=list)
    orders: List[Dict] = field(default_factory=list)
    history: List[Dict] = field(default_factory=list)

# -------------------------
# Orders Handling
# -------------------------
def get_orders_file(session_id: str) -> str:
    return f"orders_{session_id}.json"

def _load_orders(session_id: str) -> List[Dict]:
    file = get_orders_file(session_id)
    if not os.path.exists(file):
        return []
    try:
        with open(file, "r") as f:
            return json.load(f)
    except Exception:
        return []

def _save_order(order: Dict, session_id: str):
    orders = _load_orders(session_id)
    orders.append(order)
    with open(get_orders_file(session_id), "w") as f:
        json.dump(orders, f, indent=2)

def create_order(line_items: List[Dict], session_id: str) -> Dict:
    total = 0
    items = []
    for li in line_items:
        pid = li["product_id"]
        qty = int(li.get("quantity", 1))
        prod = next((p for p in CATALOG if p["id"] == pid), None)
        if not prod:
            raise ValueError(f"Product {pid} not found")
        line_total = prod["price"] * qty
        total += line_total
        items.append({
            "product_id": pid,
            "name": prod["name"],
            "unit_price": prod["price"],
            "quantity": qty,
            "line_total": line_total
        })
    order = {
        "id": f"order-{uuid.uuid4().hex[:8]}",
        "items": items,
        "total": total,
        "currency": "INR",
        "created_at": datetime.utcnow().isoformat() + "Z"
    }
    _save_order(order, session_id)
    return order

def get_last_order(session_id: str) -> Optional[Dict]:
    orders = _load_orders(session_id)
    return orders[-1] if orders else None

# -------------------------
# Lite ACP Tools
# -------------------------
@function_tool
async def show_catalog(ctx: RunContext[Userdata], category: Annotated[Optional[str], Field(default=None)] = None) -> str:
    items = [p for p in CATALOG if category is None or p["category"] == category]
    if not items:
        return "No items found for that category."
    lines = [f"{p['id']}: {p['name']} — {p['price']} {p['currency']}" for p in items]
    return "Here are the items:\n" + "\n".join(lines)

@function_tool
async def add_to_cart(ctx: RunContext[Userdata], product_id: str, quantity: Annotated[int, Field(default=1)] = 1) -> str:
    prod = next((p for p in CATALOG if p["id"] == product_id), None)
    if not prod:
        return f"Product {product_id} not found."
    ctx.userdata.cart.append({"product_id": product_id, "quantity": quantity})
    return f"Added {quantity} x {prod['name']} to your cart."

@function_tool
async def show_cart(ctx: RunContext[Userdata]) -> str:
    if not ctx.userdata.cart:
        return "Your cart is empty."
    lines = []
    total = 0
    for li in ctx.userdata.cart:
        prod = next((p for p in CATALOG if p["id"] == li["product_id"]), None)
        if prod:
            line_total = prod["price"] * li["quantity"]
            total += line_total
            lines.append(f"{prod['name']} x {li['quantity']} = {line_total} {prod['currency']}")
    lines.append(f"Cart Total: {total} INR")
    return "\n".join(lines)

@function_tool
async def place_order(ctx: RunContext[Userdata]) -> str:
    if not ctx.userdata.cart:
        return "Cart empty. Add items before placing an order."
    order = create_order(ctx.userdata.cart, ctx.userdata.session_id)
    ctx.userdata.orders.append(order)
    ctx.userdata.cart = []
    return f"Order placed! ID: {order['id']}, Total: {order['total']} {order['currency']}"

@function_tool
async def last_order(ctx: RunContext[Userdata]) -> str:
    order = get_last_order(ctx.userdata.session_id)
    if not order:
        return "You have no previous orders."
    lines = [f"Order ID {order['id']} — Total {order['total']} {order['currency']}"]
    for item in order["items"]:
        lines.append(f"- {item['name']} x {item['quantity']} = {item['line_total']} {order['currency']}")
    return "\n".join(lines)

# -------------------------
# Agent
# -------------------------
class LiteACPAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
            You are a friendly Indian shopkeeper voice assistant.
            Help the user browse catalog, add items to cart, place orders, and show last orders.
            Keep responses short and clear for TTS.
            """,
            tools=[show_catalog, add_to_cart, show_cart, place_order, last_order]
        )

# -------------------------
# Entrypoint
# -------------------------
def prewarm(proc: JobProcess):
    try:
        proc.userdata["vad"] = silero.VAD.load()
    except Exception:
        logger.warning("VAD load failed; continuing without preloaded model.")

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}
    userdata = Userdata()
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(voice="en-US-marcus", style="Conversational", text_pacing=True),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata.get("vad"),
        userdata=userdata,
    )
    await session.start(agent=LiteACPAgent(), room=ctx.room, room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()))
    await ctx.connect()

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
