# ======================================================
# 🧠 ACTIVE RECALL COACH - TEACH-THE-TUTOR
# 🎯 Three learning modes: learn, quiz, teach_back
# ======================================================

import os
import json
import asyncio
from dataclasses import dataclass, field
from typing import Optional, Literal
from dotenv import load_dotenv

from livekit.agents import Agent, AgentSession, RunContext, function_tool, RoomInputOptions
from livekit.agents import WorkerOptions, cli

# 🔌 Plugins
from livekit.plugins import murf, silero, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.plugins import deepgram, google

load_dotenv(".env.local")

# ======================================================
# 📚 CONTENT AND CONVERSATION STORAGE
# ======================================================

CONTENT_FILE = os.path.join(os.path.dirname(__file__), "../shared-data/day4_tutor_content.json")
CONVO_FILE = os.path.join(os.path.dirname(__file__), "../shared-data/day4_conversation.json")

def load_content():
    try:
        with open(CONTENT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Error loading content file: {e}")
        return []

def save_conversation(data):
    try:
        with open(CONVO_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"⚠️ Error saving conversation: {e}")

COURSE_CONTENT = load_content()

# ======================================================
# 🧠 STATE MANAGEMENT
# ======================================================

@dataclass
class TutorState:
    current_topic_id: Optional[str] = None
    current_topic_data: Optional[dict] = None
    mode: Literal["learn", "quiz", "teach_back"] = "learn"

    def set_topic(self, topic_id: str):
        topic = next((t for t in COURSE_CONTENT if t["id"].lower() == topic_id.lower()), None)
        if topic:
            self.current_topic_id = topic_id
            self.current_topic_data = topic
            return True
        return False

@dataclass
class Userdata:
    tutor_state: TutorState = field(default_factory=TutorState)
    agent_session: Optional[AgentSession] = None
    conversation: list = field(default_factory=list)

# ======================================================
# 🛠️ TOOLS
# ======================================================

@function_tool
async def select_topic(ctx: RunContext[Userdata], topic_id: str) -> str:
    state = ctx.userdata.tutor_state
    if state.set_topic(topic_id):
        msg = f"Topic set to {state.current_topic_data['title']}."
        ctx.userdata.conversation.append({"action": "select_topic", "topic": topic_id})
        save_conversation(ctx.userdata.conversation)
        return msg + " Which mode do you want: learn, quiz, or teach_back?"
    else:
        available = ", ".join([t["id"] for t in COURSE_CONTENT])
        return f"Topic not found. Available topics: {available}"

@function_tool
async def set_mode(ctx: RunContext[Userdata], mode: str) -> str:
    mode = mode.lower()
    state = ctx.userdata.tutor_state
    state.mode = mode

    session = ctx.userdata.agent_session
    if session:
        if mode == "learn":
            session.tts.update_options(voice="en-US-matthew", style="Promo")
            text = f"Let's learn about {state.current_topic_data['title']}: {state.current_topic_data['summary']}"
        elif mode == "quiz":
            session.tts.update_options(voice="en-US-alicia", style="Conversational")
            text = f"Quiz time! {state.current_topic_data['sample_question']}"
        elif mode == "teach_back":
            session.tts.update_options(voice="en-US-ken", style="Promo")
            text = f"Teach it back! Explain {state.current_topic_data['title']} to me."
        else:
            return "Invalid mode. Choose learn, quiz, or teach_back."
    else:
        text = "Agent session not initialized."

    ctx.userdata.conversation.append({"action": "set_mode", "mode": mode, "text": text})
    save_conversation(ctx.userdata.conversation)
    return text

@function_tool
async def evaluate_teach_back(ctx: RunContext[Userdata], user_response: str) -> str:
    state = ctx.userdata.tutor_state
    correct = state.current_topic_data.get("correct_answer", "").lower()
    score = 10 if user_response.strip().lower() == correct else 5
    feedback = f"Your explanation got a score of {score}/10."
    ctx.userdata.conversation.append({"action": "teach_back", "user": user_response, "feedback": feedback})
    save_conversation(ctx.userdata.conversation)
    return feedback

# ======================================================
# 🧠 AGENT DEFINITION
# ======================================================

class TutorAgent(Agent):
    def __init__(self):
        topic_list = ", ".join([f"{t['id']} ({t['title']})" for t in COURSE_CONTENT])
        super().__init__(
            instructions=f"""
            You are an Active Recall Coach. Topics: {topic_list}.
            Modes:
            - learn: explain the topic (Matthew)
            - quiz: ask the sample question (Alicia)
            - teach_back: ask user to explain topic (Ken)
            """,
            tools=[select_topic, set_mode, evaluate_teach_back],
        )

# ======================================================
# 🎬 PREWARM AND ENTRYPOINT
# ======================================================

def prewarm(proc):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx):
    userdata = Userdata()

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(voice="en-US-matthew", style="Promo", text_pacing=True),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata.get("vad"),
        userdata=userdata,
    )

    userdata.agent_session = session

    await session.start(
        agent=TutorAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()),
    )

    await ctx.connect()

# ======================================================
# 🏁 MAIN
# ======================================================

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
