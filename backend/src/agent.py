# ======================================================
# SDR Voice Agent for Freshworks
# ======================================================

import os
import json
from datetime import datetime
from dotenv import load_dotenv
from livekit.agents import (
    Agent, AgentSession, JobContext, WorkerOptions, cli,
    function_tool, RunContext, RoomInputOptions
)
from pydantic import Field
from dataclasses import dataclass, asdict
from typing import Optional

# Audio & AI Plugins
from livekit.plugins import deepgram, murf, silero, google, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

load_dotenv(".env.local")


## ======================================================
# Load FAQ (Absolute Safe Path)
# ======================================================

BASE_DIR = os.path.dirname(__file__)  # folder where agent.py exists

FAQ_FILE = os.path.join(BASE_DIR, "company_faq.json")
LEADS_FILE = os.path.join(BASE_DIR, "leads.json")
SUMMARY_FILE = os.path.join(BASE_DIR, "summaries.json")

print("📘 Loading FAQ from:", FAQ_FILE)

with open(FAQ_FILE, "r", encoding="utf-8") as f:
    FAQ_DATA = json.load(f)


def faq_lookup(query: str):
    """Very simple keyword-based FAQ search."""
    q = query.lower()
    for item in FAQ_DATA:
        if any(word in q for word in item["question"].lower().split()):
            return item["answer"]
    return None



# ======================================================
# Lead Data Structure
# ======================================================

@dataclass
class Lead:
    name: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    use_case: Optional[str] = None
    team_size: Optional[str] = None
    timeline: Optional[str] = None


@dataclass
class Memory:
    lead: Lead


# ======================================================
# TOOLS: Save lead field + finalize
# ======================================================

@function_tool
async def save_lead(
    ctx: RunContext[Memory],
    name: Optional[str] = Field(None),
    company: Optional[str] = Field(None),
    email: Optional[str] = Field(None),
    role: Optional[str] = Field(None),
    use_case: Optional[str] = Field(None),
    team_size: Optional[str] = Field(None),
    timeline: Optional[str] = Field(None)
):
    lead = ctx.userdata.lead

    if name: lead.name = name
    if company: lead.company = company
    if email: lead.email = email
    if role: lead.role = role
    if use_case: lead.use_case = use_case
    if team_size: lead.team_size = team_size
    if timeline: lead.timeline = timeline

    return "Lead information updated."


@function_tool
async def finalize_lead(ctx: RunContext[Memory]):
    lead = ctx.userdata.lead
    data = asdict(lead)
    data["captured_at"] = datetime.now().isoformat()

    # Save to leads.json
    leads = []
    if os.path.exists(LEADS_FILE):
        with open(LEADS_FILE, "r") as f:
            leads = json.load(f)
    leads.append(data)
    with open(LEADS_FILE, "w") as f:
        json.dump(leads, f, indent=4)

    # Save summary
    summary = f"{lead.name} from {lead.company} wants '{lead.use_case}' for a team of {lead.team_size}, expected timeline: {lead.timeline}"
    summaries = []
    if os.path.exists(SUMMARY_FILE):
        with open(SUMMARY_FILE, "r") as f:
            summaries = json.load(f)
    summaries.append({"summary": summary, "time": datetime.now().isoformat()})
    with open(SUMMARY_FILE, "w") as f:
        json.dump(summaries, f, indent=4)

    return "Thanks! Your details have been saved. Our team will reach out shortly."


# ======================================================
# The SDR AGENT Persona
# ======================================================

class SDRVoiceAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions=f"""
You are a friendly SDR for **Freshworks India**.

Your job:
1. Greet warmly.
2. Ask what brings the user here.
3. Answer questions strictly using FAQ below:
{json.dumps(FAQ_DATA, indent=2)}

4. Ask for lead details naturally:
   - name
   - company
   - email
   - role
   - use_case
   - team_size
   - timeline

5. When user says “that's all”, “done”, “thanks” — call `finalize_lead`.
""",
            tools=[save_lead, finalize_lead],
        )


# ======================================================
# ENTRYPOINT
# ======================================================

def prewarm(proc):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):

    memory = Memory(lead=Lead())

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        tts=murf.TTS(voice="en-US-natalie"),
        llm=google.LLM(model="gemini-2.5-flash"),
        vad=ctx.proc.userdata["vad"],
        turn_detection=MultilingualModel(),
        userdata=memory,
    )

    await session.start(
        agent=SDRVoiceAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm
        )
    )
