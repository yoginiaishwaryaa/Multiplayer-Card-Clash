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
        self.game_active = False
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

    def record_event(self, timestamp: int, node: str, event_type: str, message: str, details: Any = None):
        """Stores the globally synchronized event log."""
        log_entry = {
            "timestamp": timestamp,
            "category": "token" if "TOKEN" in event_type else "game",
            "message": f"[{event_type}] {message}" if event_type else message,
            "details": details,
            "node": node
        }
        self.logs.append(log_entry)
        # Sort logs by timestamp, then by node ID algebraically to ensure consistent ordering across all nodes
        self.logs.sort(key=lambda x: (x["timestamp"], x.get("node", "")))
        while len(self.logs) > self.max_logs:
            self.logs.pop(0)

    def add_log(self, category: str, message: str, details: Any = None):
        # Fallback for old local logs, though we migrate to record_event broadcast
        self.record_event(self.lamport_clock, self.node_id, "", message, details)

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
