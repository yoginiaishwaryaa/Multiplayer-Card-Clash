import asyncio
import uuid
from ..models import Message

class MutexProtocol:
    """Ricart-Agrawala Mutual Exclusion"""
    def __init__(self, node_id: str, state, network):
        self.node_id = node_id
        self.state = state
        self.network = network

    async def request_access(self):
        # Only request if we don't already have it or want it
        if self.state.mutex_state != "RELEASED":
            return
        
        self.state.mutex_state = "WANTED"
        self.state.mutex_request_ts = await self.state.get_next_ts()
        self.state.mutex_replies_received = set()
        self.state.add_log("mutex", f"Requesting CS (ts: {self.state.mutex_request_ts})")
        
        msg = Message(
            type="MUTEX_REQUEST",
            src=self.node_id,
            dst="all",
            id=str(uuid.uuid4()),
            ts=self.state.mutex_request_ts,
            payload={}
        )
        await self.network.broadcast(msg)
        await self.network.notify_ui(self.state.to_ui_dict())

    async def handle_request(self, msg: Message):
        req_ts = msg.ts
        req_id = msg.src
        
        my_ts = self.state.mutex_request_ts
        my_id = self.node_id
        
        # Decision logic: Defer if I'm in HELD or (I'm WANTED AND I have priority)
        defer = False
        if self.state.mutex_state == "HELD":
            defer = True
        elif self.state.mutex_state == "WANTED":
            # Comparison for priority: (Time, NodeID)
            # If my request is 'earlier', I have priority and should defer him.
            if (my_ts, my_id) < (req_ts, req_id):
                defer = True
        
        if defer:
            if req_id not in self.state.deferred_replies:
                self.state.deferred_replies.append(req_id)
            self.state.add_log("mutex", f"Deferring reply to {req_id} (My TS: {my_ts}, His TS: {req_ts})")
        else:
            self.state.add_log("mutex", f"Replying immediately to {req_id}")
            await self._send_reply(req_id)

    async def handle_reply(self, msg: Message):
        if self.state.mutex_state != "WANTED":
            # Ignore late replies if already HELD or RELEASED
            return
            
        self.state.mutex_replies_received.add(msg.src)
        # Total nodes = len(peers) + 1 (self). We need replies from all other nodes.
        peer_count = len(self.network.config.peers)
        
        if len(self.state.mutex_replies_received) >= peer_count:
            self.state.mutex_state = "HELD"
            self.state.mutex_event.set()
            self.state.add_log("mutex", "Entered Critical Section")
            await self.network.notify_ui(self.state.to_ui_dict())

    async def release(self):
        if self.state.mutex_state != "HELD":
            return
            
        self.state.mutex_state = "RELEASED"
        deferred = self.state.deferred_replies
        self.state.deferred_replies = []
        self.state.add_log("mutex", f"Released CS. Sending {len(deferred)} deferred replies.")
        
        for peer_id in deferred:
            await self._send_reply(peer_id)
        
        await self.network.notify_ui(self.state.to_ui_dict())

    async def _send_reply(self, dst: str):
        msg = Message(
            type="MUTEX_REPLY",
            src=self.node_id,
            dst=dst,
            id=str(uuid.uuid4()),
            ts=await self.state.get_next_ts(),
            payload={}
        )
        await self.network.send_to_peer(dst, msg)

