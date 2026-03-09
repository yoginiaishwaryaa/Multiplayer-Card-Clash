import asyncio
import json
import socket
import threading
import time
from typing import Dict, Callable, Awaitable, List, Optional, Any
from .models import Message, NodeConfig
from .utils import log_debug

class NetworkManager:
    def __init__(self, config: NodeConfig, on_message: Callable[[Message], Awaitable[None]]):
        self.config = config
        self.on_message = on_message
        self.peers: Dict[str, socket.socket] = {}
        self.ui_websockets = set()
        self.latency_min = 0.05 # 50ms
        self.latency_max = 0.2  # 200ms
        
        # Loop will be set during connect_to_peers which is called from within the event loop
        self.loop = None
        
        # Setup Server socket
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((config.listen_host, config.listen_port))
        self.server.listen()

    async def connect_to_peers(self):
        self.loop = asyncio.get_running_loop()
        
        # Start server accept thread
        threading.Thread(target=self._accept_connections, daemon=True).start()
        
        # Start client connection threads
        for node_id, addr in self.config.peers.items():
            threading.Thread(target=self._maintain_connection, args=(node_id, addr), daemon=True).start()

    def _accept_connections(self):
        print(f"[{self.config.node_id}] TCP Server running at {self.config.listen_port}")
        while True:
            try:
                conn, addr = self.server.accept()
                threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True).start()
            except Exception as e:
                print(f"[TCP Server Error] {e}")
                break

    def _handle_client(self, conn: socket.socket, addr: tuple):
        print(f"[{self.config.node_id}] Accepted incoming connection from {addr}")
        # The incoming connection is just a receiver channel.
        # We don't save it to self.peers, since we only use self.peers for sending.
        
        while True:
            try:
                # Read line-delimited JSON
                data = self._read_line(conn)
                if not data:
                    break
                
                msg_dict = json.loads(data)
                msg = Message(**msg_dict)
                # Pass back to the async event loop to handle game state updates safely
                asyncio.run_coroutine_threadsafe(self.on_message(msg), self.loop)
            except Exception as e:
                break
        
        conn.close()

    def _maintain_connection(self, node_id: str, addr: str):
        ip_raw, port_str = addr.split(':')
        ip = ip_raw.strip().rstrip('.')
        port = int(port_str.strip())
        
        while True:
            try:
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client.connect((ip, port))
                print(f"[{self.config.node_id}] Outbound connected to peer {node_id} at {addr}")
                self.peers[node_id] = client
                
                # Keep thread alive to detect disconnects (we only send on this socket)
                # If recv returns empty, connection is dead.
                while True:
                    data = client.recv(1024)
                    if not data:
                        break
            except Exception as e:
                pass
            finally:
                if node_id in self.peers:
                    del self.peers[node_id]
                try:
                    client.close()
                except:
                    pass
            
            time.sleep(2)  # Retry delay

    def _read_line(self, conn: socket.socket) -> str:
        """Reads from socket until a newline is found."""
        buffer = bytearray()
        while True:
            try:
                b = conn.recv(1)
                if not b:
                    return ""
                if b == b'\n':
                    return buffer.decode('utf-8', errors='replace')
                buffer.extend(b)
            except Exception as e:
                return ""

    async def send_to_peer(self, node_id: str, msg: Message):
        if node_id in self.peers:
            import random
            delay = random.uniform(self.latency_min, self.latency_max)
            await asyncio.sleep(delay)
            
            try:
                payload = msg.model_dump_json() + "\n"
                # Send inside a separate thread space or use sendall 
                self.peers[node_id].sendall(payload.encode())
            except Exception as e:
                print(f"Failed to send to {node_id}: {e}")

    async def broadcast(self, msg: Message, exclude: Optional[List[str]] = None):
        exclude = exclude or []
        tasks = []
        for peer_id in self.config.peers.keys():
            if peer_id not in exclude:
                tasks.append(self.send_to_peer(peer_id, msg))
        if tasks:
            await asyncio.gather(*tasks)

    async def notify_ui(self, state_dict: Dict[str, Any]):
        if not self.ui_websockets:
            return
        
        payload = json.dumps({"type": "STATE_UPDATE", "data": state_dict})
        disconnected = set()
        for ws in list(self.ui_websockets):  # iterate over a snapshot copy
            try:
                await ws.send_text(payload)
            except Exception:
                disconnected.add(ws)
        
        for ws in disconnected:
            self.ui_websockets.discard(ws)
