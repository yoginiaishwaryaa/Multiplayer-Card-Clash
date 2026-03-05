from pydantic import BaseModel
from typing import Optional, Dict, List, Any, Union

class Card(BaseModel):
    rank: int   # 1=Ace, 2-10, 11=Jack, 12=Queen, 13=King
    suit: str   # '♠', '♥', '♣', '♦'

class Message(BaseModel):
    type: str # 'TOKEN', 'MUTEX_REQUEST', 'MUTEX_REPLY', 'MARKER', 'SNAPSHOT_STATE', 'GAME_ACTION', 'HEARTBEAT'
    src: str
    dst: str
    id: str
    ts: int  # Lamport timestamp
    payload: Dict[str, Any]

class NodeConfig(BaseModel):
    node_id: str
    listen_host: str
    listen_port: int
    ui_port: int
    peers: Dict[str, str]  # node_id -> ws_url
    ring_order: List[str]
    is_initial_token_holder: bool = False

class GameState(BaseModel):
    center_piles: List[List[Dict]]  # Two piles, each a list of card dicts
    hand: List[Dict]                # Player's visible hand (list of card dicts)
    deck_size: int
    players_info: Dict[str, Dict[str, Any]] # node_id -> info (hand_size, etc)

class SnapshotData(BaseModel):
    node_id: str
    local_state: Dict[str, Any]
    channel_states: Dict[str, List[Message]] # src_node -> list of messages recorded
