import json
import logging
import os
import asyncio
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
logger = logging.getLogger("voice_game_master")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)

load_dotenv(".env.local")

# -------------------------
# Game World
# -------------------------
WORLD = {
    "intro": {
        "desc": "You find yourself on Brinmere's damp shoreline. Nearby, a small wooden box is half-buried in sand, a ruined watchtower smolders inland, and a path leads east toward a few cottages.",
        "choices": {
            "inspect_box": {"desc": "Examine the wooden box on the shore.", "result_scene": "box"},
            "approach_tower": {"desc": "Move toward the crumbling watchtower.", "result_scene": "tower"},
            "walk_to_cottages": {"desc": "Follow the path to the cottages.", "result_scene": "cottages"},
        },
    },
    "box": {
        "desc": "The box feels warm. Inside, a folded note bears a cryptic map fragment and a riddle-like message: 'Beneath the tower, the latch hums.'",
        "choices": {
            "take_map": {"desc": "Take the map with you.", "result_scene": "tower_approach", "effects": {"add_journal": "Found map fragment: 'Beneath the tower, the latch hums.'"}},
            "leave_box": {"desc": "Leave the box untouched.", "result_scene": "intro"},
        },
    },
    "tower": {
        "desc": "The watchtower is partially ruined; embers glow inside. A rusty iron latch covers a hatch at its base.",
        "choices": {
            "try_latch_without_map": {"desc": "Try the hatch without guidance.", "result_scene": "latch_fail"},
            "search_around": {"desc": "Look for another way inside.", "result_scene": "secret_entrance"},
            "retreat": {"desc": "Return to the shoreline.", "result_scene": "intro"},
        },
    },
    "tower_approach": {
        "desc": "Holding the map, you approach the tower. Its marks hint at a hidden latch that vibrates faintly as you near.",
        "choices": {
            "open_hatch": {"desc": "Use the map and open the hatch carefully.", "result_scene": "latch_open", "effects": {"add_journal": "Used map clue to open the hatch."}},
            "search_around": {"desc": "Investigate the surroundings for hidden entrances.", "result_scene": "secret_entrance"},
            "retreat": {"desc": "Step back to the beach.", "result_scene": "intro"},
        },
    },
    "latch_fail": {
        "desc": "The latch resists, shaking the ground slightly. A rustling noise comes from inside the tower.",
        "choices": {
            "run_away": {"desc": "Flee to safety along the shore.", "result_scene": "intro"},
            "stand_ground": {"desc": "Prepare for whatever emerges.", "result_scene": "tower_combat"},
        },
    },
    "latch_open": {
        "desc": "The hatch swings open with a cold breeze. A spiral staircase descends into a dim cellar illuminated by glowing moss.",
        "choices": {
            "descend": {"desc": "Step down into the cellar.", "result_scene": "cellar"},
            "close_hatch": {"desc": "Close it and rethink your approach.", "result_scene": "tower_approach"},
        },
    },
    "secret_entrance": {
        "desc": "A narrow crevice hides beneath some rubble. Old rope dangles down, smelling of salt and iron.",
        "choices": {
            "squeeze_in": {"desc": "Climb down the rope into the cellar.", "result_scene": "cellar"},
            "mark_and_return": {"desc": "Mark this spot and head back to the shore.", "result_scene": "intro"},
        },
    },
    "cellar": {
        "desc": "You enter a circular chamber with faintly glowing runes. A stone pedestal holds a brass key and a sealed scroll.",
        "choices": {
            "take_key": {"desc": "Pick up the brass key.", "result_scene": "cellar_key", "effects": {"add_inventory": "brass_key", "add_journal": "Found brass key on pedestal."}},
            "open_scroll": {"desc": "Break the seal and read the scroll.", "result_scene": "scroll_reveal", "effects": {"add_journal": "Scroll reads: 'The tide remembers what the villagers forget.'"}},
            "leave_quietly": {"desc": "Exit the cellar silently.", "result_scene": "intro"},
        },
    },
    "cellar_key": {
        "desc": "The key in hand triggers a hidden panel revealing a small humming statue.",
        "choices": {
            "pledge_help": {"desc": "Promise to return what was taken.", "result_scene": "reward", "effects": {"add_journal": "Pledged to return the taken item."}},
            "refuse": {"desc": "Pocket the key and refuse.", "result_scene": "cursed_key", "effects": {"add_journal": "Pocketed the key; it feels heavy."}},
        },
    },
    "scroll_reveal": {
        "desc": "The scroll tells of a water spirit guarding a lost heirloom, hinting that the brass key 'speaks' if offered truthfully.",
        "choices": {
            "search_for_key": {"desc": "Search the pedestal for a key.", "result_scene": "cellar_key"},
            "leave_quietly": {"desc": "Leave the cellar and keep the knowledge.", "result_scene": "intro"},
        },
    },
    "tower_combat": {
        "desc": "A brine-soaked creature emerges hunched and hungry.",
        "choices": {
            "fight": {"desc": "Engage the creature.", "result_scene": "fight_win"},
            "flee": {"desc": "Run back to the shore.", "result_scene": "intro"},
        },
    },
    "fight_win": {
        "desc": "The creature retreats. A small engraved locket lies on the ground.",
        "choices": {
            "take_locket": {"desc": "Take the locket.", "result_scene": "reward", "effects": {"add_inventory": "engraved_locket", "add_journal": "Recovered engraved locket."}},
            "leave_locket": {"desc": "Leave it and tend to yourself.", "result_scene": "intro"},
        },
    },
    "reward": {
        "desc": "A quiet sense of resolution settles. Your story arc concludes, for now.",
        "choices": {
            "end_session": {"desc": "End session and return to shore.", "result_scene": "intro"},
            "keep_exploring": {"desc": "Search for more mysteries.", "result_scene": "intro"},
        },
    },
    "cursed_key": {
        "desc": "The key feels cold and heavy; it weighs on your thoughts.",
        "choices": {
            "seek_redemption": {"desc": "Try to make amends.", "result_scene": "reward"},
            "bury_key": {"desc": "Bury it and hope for relief.", "result_scene": "intro"},
        },
    },
}

# -------------------------
# Userdata
# -------------------------
@dataclass
class Userdata:
    player_name: Optional[str] = None
    current_scene: str = "intro"
    history: List[Dict] = field(default_factory=list)
    journal: List[str] = field(default_factory=list)
    inventory: List[str] = field(default_factory=list)
    named_npcs: Dict[str, str] = field(default_factory=dict)
    choices_made: List[str] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

# -------------------------
# Helper Functions
# -------------------------
def scene_text(scene_key: str, userdata: Userdata) -> str:
    scene = WORLD.get(scene_key)
    if not scene:
        return "You are in a void. What do you do?"
    desc = f"{scene['desc']}\n\nChoices:\n"
    for cid, cmeta in scene.get("choices", {}).items():
        desc += f"- {cmeta['desc']}\n"
    desc += "\nWhat do you do?"
    return desc

def apply_effects(effects: dict, userdata: Userdata):
    if not effects:
        return
    if "add_journal" in effects:
        userdata.journal.append(effects["add_journal"])
    if "add_inventory" in effects:
        userdata.inventory.append(effects["add_inventory"])

def summarize_scene_transition(old_scene: str, action_key: str, result_scene: str, userdata: Userdata) -> str:
    entry = {
        "from": old_scene,
        "action": action_key,
        "to": result_scene,
        "time": datetime.utcnow().isoformat() + "Z",
    }
    userdata.history.append(entry)
    userdata.choices_made.append(action_key)
    return f"You chose '{action_key}'."

# -------------------------
# Agent Tools
# -------------------------
@function_tool
async def start_adventure(
    ctx: RunContext[Userdata],
    player_name: Annotated[Optional[str], Field(description="Player name", default=None)] = None,
) -> str:
    userdata = ctx.userdata
    if player_name:
        userdata.player_name = player_name
    userdata.current_scene = "intro"
    userdata.history = []
    userdata.journal = []
    userdata.inventory = []
    userdata.named_npcs = {}
    userdata.choices_made = []
    userdata.session_id = str(uuid.uuid4())[:8]
    userdata.started_at = datetime.utcnow().isoformat() + "Z"
    opening = scene_text("intro", userdata)
    return opening

@function_tool
async def get_scene(ctx: RunContext[Userdata]) -> str:
    return scene_text(ctx.userdata.current_scene, ctx.userdata)

@function_tool
async def player_action(
    ctx: RunContext[Userdata],
    action: Annotated[str, Field(description="Player action")],
) -> str:
    userdata = ctx.userdata
    current = userdata.current_scene
    scene = WORLD.get(current)
    action_text = (action or "").strip()
    chosen_key = None
    if action_text.lower() in (scene.get("choices") or {}):
        chosen_key = action_text.lower()
    if not chosen_key:
        for cid, cmeta in (scene.get("choices") or {}).items():
            if cid in action_text.lower() or any(w in action_text.lower() for w in cmeta.get("desc", "").lower().split()[:4]):
                chosen_key = cid
                break
    if not chosen_key:
        resp = "I didn't catch that action.\n\n" + scene_text(current, userdata)
        return resp
    choice_meta = scene["choices"][chosen_key]
    result_scene = choice_meta.get("result_scene", current)
    apply_effects(choice_meta.get("effects", {}), userdata)
    note = summarize_scene_transition(current, chosen_key, result_scene, userdata)
    userdata.current_scene = result_scene
    return f"{note}\n\n{scene_text(result_scene, userdata)}"

@function_tool
async def show_journal(ctx: RunContext[Userdata]) -> str:
    userdata = ctx.userdata
    lines = [f"Session: {userdata.session_id} | Started at: {userdata.started_at}"]
    if userdata.player_name:
        lines.append(f"Player: {userdata.player_name}")
    if userdata.journal:
        lines.append("\nJournal:")
        for j in userdata.journal:
            lines.append(f"- {j}")
    if userdata.inventory:
        lines.append("\nInventory:")
        for it in userdata.inventory:
            lines.append(f"- {it}")
    lines.append("\nRecent choices:")
    for h in userdata.history[-6:]:
        lines.append(f"- {h['time']} | {h['from']} -> {h['to']} via {h['action']}")
    lines.append("\nWhat do you do?")
    return "\n".join(lines)

@function_tool
async def restart_adventure(ctx: RunContext[Userdata]) -> str:
    userdata = ctx.userdata
    userdata.current_scene = "intro"
    userdata.history = []
    userdata.journal = []
    userdata.inventory = []
    userdata.named_npcs = {}
    userdata.choices_made = []
    userdata.session_id = str(uuid.uuid4())[:8]
    userdata.started_at = datetime.utcnow().isoformat() + "Z"
    return scene_text("intro", userdata)

# -------------------------
# Game Master Agent
# -------------------------
class GameMasterAgent(Agent):
    def __init__(self):
        instructions = """
        You are 'Gem', the Game Master for a voice-only D&D-style adventure.
        You narrate scenes vividly, remember choices, journal entries, inventory and named locations.
        End each descriptive message with 'What do you do?'
        """
        super().__init__(
            instructions=instructions,
            tools=[start_adventure, get_scene, player_action, show_journal, restart_adventure],
        )

# -------------------------
# Entrypoint
# -------------------------
def prewarm(proc: JobProcess):
    try:
        proc.userdata["vad"] = silero.VAD.load()
    except Exception:
        logger.warning("VAD prewarm failed; continuing without it.")

async def entrypoint(ctx: JobContext):
    userdata = Userdata()
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(voice="en-US-marcus", style="Conversational", text_pacing=True),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata.get("vad"),
        userdata=userdata,
    )
    await session.start(
        agent=GameMasterAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()),
    )
    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
