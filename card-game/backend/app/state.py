import asyncio
from typing import List, Dict, Any, Optional
from .models import Message, GameState
import random

SUITS = ['♠', '♥', '♣', '♦']
RANKS = list(range(1, 14))  # 1=Ace, 2-10, 11=J, 12=Q, 13=K

def build_deck() -> List[Dict]:
    """Build a full shuffled 52-card deck as list of {rank, suit} dicts."""
    deck = [{"rank": r, "suit": s} for s in SUITS for r in RANKS]
    random.shuffle(deck)
    return deck

class StateManager:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.lamport_clock = 0
        self.clock_lock = asyncio.Lock()
        
        # Game State (Initially empty until synced by Node 1)
        self.center_piles: List[List[Dict]] = [[], []]
        self.hand: List[Dict] = []
        self.deck: List[Dict] = []
        
        # Turn Management
        self.current_turn_holder: Optional[str] = None
        self.turn_start_time: Optional[float] = None

        # Winner state
        self.winner: Optional[str] = None

        # Algorithm States
        self.has_token = False
        self.token_sequence = 0
        
        # Mutex (Ricart-Agrawala) - Used for "Grabbing" the Turn
        self.mutex_state = "RELEASED"
        self.mutex_request_ts = 0
        self.mutex_replies_received = set()
        self.deferred_replies = []
        
        # Snapshot (Chandy-Lamport)
        self.is_recording = False
        self.active_snapshots = {}
        
        # Synchronization
        self.mutex_event = asyncio.Event()
        
        # Logs for UI
        self.logs = []
        self.max_logs = 100

    async def get_next_ts(self):
        async with self.clock_lock:
            self.lamport_clock += 1
            return self.lamport_clock

    async def update_ts(self, received_ts: int):
        async with self.clock_lock:
            self.lamport_clock = max(self.lamport_clock, received_ts) + 1
            return self.lamport_clock

    def add_log(self, category: str, message: str, details: Any = None):
        log_entry = {
            "timestamp": self.lamport_clock,
            "category": category,
            "message": message,
            "details": details
        }
        self.logs.append(log_entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

    def to_ui_dict(self):
        import time
        time_left = 0
        if self.turn_start_time and self.has_token:
            elapsed = time.time() - self.turn_start_time
            time_left = max(0, 10 - elapsed)

        return {
            "node_id": self.node_id,
            "game": {
                "center_piles": self.center_piles,
                "hand": self.hand,
                "deck_size": len(self.deck),
                "current_turn": self.current_turn_holder,
                "turn_time_left": round(time_left, 1)
            },
            "winner": self.winner,
            "token": {
                "has_token": self.has_token,
                "sequence": self.token_sequence
            },
            "mutex": {
                "state": self.mutex_state,
                "replies": list(self.mutex_replies_received),
                "deferred": self.deferred_replies
            },
            "snapshot": {
                "is_active": len(self.active_snapshots) > 0
            },
            "logs": self.logs[::-1]
        }
