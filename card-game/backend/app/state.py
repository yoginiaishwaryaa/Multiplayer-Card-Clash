import asyncio
import random
from typing import List, Dict, Any, Optional
from .models import Message, GameState
from .utils import card_label

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
        
        # Game State
        self.center_piles: List[List[Dict]] = [[], []]
        self.hand: List[Dict] = []
        self.deck: List[Dict] = []
        self.winner: Optional[str] = None

        # Distributed Control state
        self.token_holder: Optional[str] = None
        
        # Mutex (Ricart-Agrawala) - used as the Move Token mechanism
        self.mutex_state = "RELEASED"
        self.mutex_request_ts = 0
        self.mutex_replies_received = set()
        self.deferred_replies = []
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
        """Internal log addition. Deterministic events should use this."""
        log_entry = {
            "timestamp": self.lamport_clock,
            "category": category,
            "message": message,
            "details": details
        }
        self.logs.append(log_entry)
        # Sort logs by timestamp, then node_id if available in message or metadata
        # For now, we append as they arrive, but ideally we'd re-sort if we had a full event log.
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

    def player_has_card(self, card: Dict) -> bool:
        return any(c["rank"] == card["rank"] and c["suit"] == card["suit"] for c in self.hand)

    def to_ui_dict(self):
        return {
            "node_id": self.node_id,
            "game": {
                "center_piles": self.center_piles,
                "hand": self.hand,
                "deck_size": len(self.deck)
            },
            "winner": self.winner,
            "token": {
                "holder": self.token_holder,
                "is_held_by_me": self.mutex_state == "HELD"
            },
            "mutex": {
                "state": self.mutex_state
            },
            "logs": self.logs[::-1] # Newest first for UI
        }
