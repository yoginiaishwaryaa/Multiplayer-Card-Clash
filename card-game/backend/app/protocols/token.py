import asyncio
import uuid
from typing import Optional
from ..models import Message

class TokenProtocol:
    def __init__(self, node_id, state, network):
        self.node_id = node_id
        self.state = state
        self.network = network
        self.pass_task: Optional[asyncio.Task] = None

    async def start(self):
        if self.state.has_token:
            self.state.add_log("token", "Starting with token")
            # Auto-pass disabled for grab-to-play mode
            # self._start_pass_task()

    async def handle_token(self, msg: Message):
        # Avoid late tokens from old rounds if any
        if msg.payload.get("sequence", 0) <= self.state.token_sequence and self.state.token_sequence > 0:
            return 
        
        self.state.has_token = True
        self.state.token_sequence = msg.payload.get("sequence", 0)
        self.state.add_log("token", f"Received token (seq: {self.state.token_sequence})")
        
        # Auto-pass disabled for grab-to-play mode
        # self._start_pass_task()

    def _start_pass_task(self):
        if self.pass_task is not None and not self.pass_task.done():
            self.pass_task.cancel()
        self.pass_task = asyncio.create_task(self._token_pass_loop())

    async def _token_pass_loop(self):
        try:
            # Hold token for 3 seconds minimum for visibility
            await asyncio.sleep(3)
            await self.pass_token()
        except asyncio.CancelledError:
            pass

    async def pass_token(self):
        if not self.state.has_token:
            return
            
        self.state.has_token = False
        self.state.token_sequence += 1
        
        # Find next in ring
        ring = self.network.config.ring_order
        try:
            idx = ring.index(self.node_id)
            next_node = ring[(idx + 1) % len(ring)]
        except ValueError:
            self.state.add_log("token", "Error: Node not in ring order")
            return

        msg = Message(
            type="TOKEN",
            src=self.node_id,
            dst=next_node,
            id=str(uuid.uuid4()),
            ts=await self.state.get_next_ts(),
            payload={"sequence": self.state.token_sequence}
        )
        self.state.add_log("token", f"Passing token to {next_node}")
        await self.network.send_to_peer(next_node, msg)
        await self.network.notify_ui(self.state.to_ui_dict())

    async def use_token_for_action(self, action_name: str):
        if not self.state.has_token:
            self.state.add_log("token", "Permission denied: No token")
            return False
        self.state.add_log("token", f"Performing special action: {action_name}")
        return True

    async def regenerate_token(self):
        self.state.has_token = True
        self.state.token_sequence += 1000 # Jump ahead to override any old tokens
        self.state.add_log("token", "FORCED token regeneration")
        asyncio.create_task(self._token_pass_loop())
