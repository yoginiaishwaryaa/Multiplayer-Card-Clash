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
        
        # Game State
        full_deck = build_deck()
        start_card1 = full_deck.pop()
        start_card2 = full_deck.pop()
        self.center_piles: List[List[Dict]] = [[start_card1], [start_card2]]

        HAND_SIZE = 5
        self.hand: List[Dict] = [full_deck.pop() for _ in range(HAND_SIZE)]
        self.deck: List[Dict] = full_deck  # Face-down private draw pile

        # Winner state — set to winning node_id when someone empties their hand
        self.winner: Optional[str] = None

        # Algorithm States
        self.has_token = False
        self.token_sequence = 0
        
        # Mutex (Ricart-Agrawala)
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
        return {
            "node_id": self.node_id,
            "game": {
                "center_piles": self.center_piles,
                "hand": self.hand,
                "deck_size": len(self.deck)
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
