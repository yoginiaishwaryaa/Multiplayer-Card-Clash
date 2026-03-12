import asyncio
import uuid
import json
from ..models import Message

class SnapshotProtocol:
    """Chandy-Lamport Distributed Snapshot Algorithm"""
    def __init__(self, node_id, state, network):
        self.node_id = node_id
        self.state = state
        self.network = network

    async def initiate(self):
        snapshot_id = str(uuid.uuid4())[:8]
        self.state.add_log("snapshot", f"Initiating snapshot {snapshot_id}")
        await self._start_snapshot(snapshot_id, initiator_id=self.node_id)

    async def _start_snapshot(self, snapshot_id, arrival_channel=None, initiator_id=None):
        # 1. Record local state
        local_state = {
            "hand": list(self.state.hand),
            "deck_size": len(self.state.deck),
            "center_piles": [list(p) for p in self.state.center_piles],
            "has_token": self.state.has_token,
            "mutex_state": self.state.mutex_state
        }
        
        # 2. MARKER logic
        peers = list(self.network.config.peers.keys())
        self.state.active_snapshots[snapshot_id] = {
            "id": snapshot_id,
            "initiator": initiator_id,
            "local_state": local_state,
            "channel_states": {p: [] for p in peers},
            "missing_markers": set(peers),
            "is_recording": {p: True for p in peers},
            "collected_states": {} # For collecting results if we are initiator
        }
        
        # If marker arrived on a channel, stop recording that channel immediately
        if arrival_channel:
            self.state.active_snapshots[snapshot_id]["is_recording"][arrival_channel] = False
            self.state.active_snapshots[snapshot_id]["missing_markers"].discard(arrival_channel)

        msg = Message(
            type="MARKER",
            src=self.node_id,
            dst="all",
            id=str(uuid.uuid4()),
            ts=await self.state.get_next_ts(),
            payload={
                "snapshot_id": snapshot_id,
                "initiator": initiator_id
            }
        )
        await self.network.broadcast(msg)

        # Check if already finished (e.g. no peers)
        if not self.state.active_snapshots[snapshot_id]["missing_markers"]:
            await self._finish_local_snapshot(snapshot_id)

    async def handle_marker(self, msg: Message):
        snapshot_id = msg.payload["snapshot_id"]
        initiator_id = msg.payload.get("initiator")
        sender = msg.src
        
        if snapshot_id not in self.state.active_snapshots:
            # First time seeing this marker
            await self._start_snapshot(snapshot_id, arrival_channel=sender, initiator_id=initiator_id)
        else:
            # Already active, stop recording for this channel
            snap = self.state.active_snapshots[snapshot_id]
            if sender in snap["is_recording"]:
                snap["is_recording"][sender] = False
                snap["missing_markers"].discard(sender)

        # check if finished recording
        if snapshot_id in self.state.active_snapshots and not self.state.active_snapshots[snapshot_id]["missing_markers"]:
            await self._finish_local_snapshot(snapshot_id)

    async def _finish_local_snapshot(self, snapshot_id):
        snap = self.state.active_snapshots[snapshot_id]
        self.state.add_log("snapshot", f"Finished local recording for {snapshot_id}")
        
        # Broadcast the local result so initiator can collect it
        result_msg = Message(
            type="SNAPSHOT_STATE",
            src=self.node_id,
            dst="all",
            id=str(uuid.uuid4()),
            ts=await self.state.get_next_ts(),
            payload={
                "snapshot_id": snapshot_id,
                "local_state": snap["local_state"],
                "channel_states": snap["channel_states"]
            }
        )
        await self.network.broadcast(result_msg)

    async def handle_snapshot_state(self, msg: Message):
        snapshot_id = msg.payload["snapshot_id"]
        if snapshot_id in self.state.active_snapshots:
            snap = self.state.active_snapshots[snapshot_id]
            snap["collected_states"][msg.src] = {
                "local": msg.payload["local_state"],
                "channels": msg.payload["channel_states"]
            }
            
            # If we are the initiator and we have all states...
            expected = len(self.network.config.peers) + 1
            if len(snap["collected_states"]) + 1 == expected and snap["initiator"] == self.node_id:
                
                full_snapshot = {
                    "id": snapshot_id,
                    "nodes": snap["collected_states"]
                }
                full_snapshot["nodes"][self.node_id] = {
                    "local": snap["local_state"],
                    "channels": snap["channel_states"]
                }
                
                # Show snapshot result in event log
                result_str = json.dumps(full_snapshot, default=str)
                self.state.add_log("snapshot", f"GLOBAL SNAPSHOT {snapshot_id} COMPLETE. Result: {result_str}")
                await self.network.notify_ui({
                    "type": "SNAPSHOT_COMPLETE",
                    "snapshot": full_snapshot
                })

    def record_message(self, msg: Message):
        for snap_id, snap in self.state.active_snapshots.items():
            if snap.get("is_recording", {}).get(msg.src):
                # Only record if we are still recording this channel
                msg_copy = msg.model_dump() if hasattr(msg, "model_dump") else msg.dict()
                snap["channel_states"][msg.src].append(msg_copy)

