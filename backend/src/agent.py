import logging
import os
import sqlite3
from datetime import datetime
from typing import Annotated, Optional
from dataclasses import dataclass
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

logger = logging.getLogger("agent")
load_dotenv(".env.local")

DB_FILE = "fraud_db.sqlite"

@dataclass
class FraudCase:
    userName: str
    securityIdentifier: str
    cardEnding: str
    transactionName: str
    transactionAmount: str
    transactionTime: str
    transactionSource: str
    case_status: str = "pending_review"
    notes: str = ""


def get_db_path():
    return os.path.join(os.path.dirname(__file__), DB_FILE)


def get_conn():
    path = get_db_path()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def seed_database():
    """Create SQLite DB and insert sample rows if empty."""
    conn = get_conn()
    cur = conn.cursor()

    # FIXED SQL — CLEAN, NO BROKEN LINES
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS fraud_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            userName TEXT NOT NULL,
            securityIdentifier TEXT,
            cardEnding TEXT,
            transactionName TEXT,
            transactionAmount TEXT,
            transactionTime TEXT,
            transactionSource TEXT,
            case_status TEXT DEFAULT 'pending_review',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """
    )

    cur.execute("SELECT COUNT(1) FROM fraud_cases")
    if cur.fetchone()[0] == 0:
        sample_data = [
    (
        "Alice", "11122", "4521",
        "Starbucks Coffee", "$25.50", "8:30 AM EST", "starbucks.com",
        "pending_review", "Automated flag: Multiple small orders in short time."
    ),
    (
        "Bob", "22334", "3345",
        "Apple Store", "$1,200.00", "2:45 PM EST", "apple.com",
        "pending_review", "Automated flag: High-value purchase on new device."
    ),
    (
        "Charlie", "33445", "6677",
        "Walmart Groceries", "$340.75", "10:15 AM EST", "walmart.com",
        "pending_review", "Automated flag: Large order at unusual time."
    ),
    (
        "Diana", "44556", "8899",
        "Netflix Subscription", "$15.99", "11:00 PM EST", "netflix.com",
        "pending_review", "Automated flag: Payment from new location."
    ),
    (
        "Ethan", "55667", "1122",
        "Amazon Purchase", "$85.99", "6:20 PM EST", "amazon.com",
        "pending_review", "Automated flag: Frequent orders from new account."
    )
]
        cur.executemany(
            """
            INSERT INTO fraud_cases (
                userName, securityIdentifier, cardEnding, transactionName,
                transactionAmount, transactionTime, transactionSource, case_status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sample_data,
        )
        conn.commit()

    conn.close()


# Initialize DB on load
seed_database()

@dataclass
class Userdata:
    active_case: Optional[FraudCase] = None

@function_tool
async def lookup_customer(
    ctx: RunContext[Userdata],
    name: Annotated[str, Field(description="The name the user provides")],
) -> str:
    """Lookup a customer in SQLite DB."""
    print(f"🔎 LOOKING UP: {name}")
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM fraud_cases WHERE LOWER(userName) = LOWER(?) LIMIT 1",
            (name,),
        )
        row = cur.fetchone()
        conn.close()

        if not row:
            return "User not found in the fraud database. Please repeat the name."

        record = dict(row)
        ctx.userdata.active_case = FraudCase(
            userName=record["userName"],
            securityIdentifier=record["securityIdentifier"],
            cardEnding=record["cardEnding"],
            transactionName=record["transactionName"],
            transactionAmount=record["transactionAmount"],
            transactionTime=record["transactionTime"],
            transactionSource=record["transactionSource"],
            case_status=record["case_status"],
            notes=record["notes"],
        )

        return (
            f"Record Found.\n"
            f"User: {record['userName']}\n"
            f"Security ID (Expected): {record['securityIdentifier']}\n"
            f"Transaction: {record['transactionAmount']} at {record['transactionName']} ({record['transactionSource']})\n"
            f"Ask user for their Security Identifier now."
        )

    except Exception as e:
        return f"Database error: {str(e)}"


@function_tool
async def resolve_fraud_case(
    ctx: RunContext[Userdata],
    status: Annotated[str, Field(description="confirmed_safe or confirmed_fraud")],
    notes: Annotated[str, Field(description="Notes on the user's confirmation")],
) -> str:

    if not ctx.userdata.active_case:
        return "Error: No active case selected."

    case = ctx.userdata.active_case
    case.case_status = status
    case.notes = notes

    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE fraud_cases
            SET case_status = ?, notes = ?, updated_at = datetime('now')
            WHERE userName = ?
            """,
            (case.case_status, case.notes, case.userName),
        )
        conn.commit()

        # Confirm updated row
        cur.execute("SELECT * FROM fraud_cases WHERE userName = ?", (case.userName,))
        updated_row = dict(cur.fetchone())
        conn.close()

        print(f"✅ CASE UPDATED: {case.userName} -> {status}")

        if status == "confirmed_fraud":
            return (
                f"Fraud confirmed. Card ending {case.cardEnding} is now BLOCKED. "
                f"A replacement card will be issued.\n"
                f"DB Updated At: {updated_row['updated_at']}"
            )
        else:
            return (
                f"Transaction marked SAFE. Restrictions lifted.\n"
                f"DB Updated At: {updated_row['updated_at']}"
            )

    except Exception as e:
        return f"Error saving to DB: {e}"

class FraudAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
            You are 'Kubo', a Fraud Detection Specialist at State Bank Of India.
            Follow strict security protocol:

            1. Greeting + ask for first name.
            2. Immediately call lookup_customer(name).
            3. Ask for Security Identifier.
            4. If correct → continue. If incorrect → end call politely.
            5. Explain suspicious transaction.
            6. Ask: Did you make this transaction?
               - YES → resolve_fraud_case('confirmed_safe')
               - NO → resolve_fraud_case('confirmed_fraud')
            7. Close professionally.
            """,
            tools=[lookup_customer, resolve_fraud_case],
        )

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    userdata = Userdata()

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-marcus",
            style="Conversational",
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata,
    )

    await session.start(
        agent=FraudAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()),
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))