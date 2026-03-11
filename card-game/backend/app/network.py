import asyncio
import json
import socket
import threading
import time
import logging
from typing import Dict, Callable, Awaitable, List, Optional, Any
from .models import Message, NodeConfig

logger = logging.getLogger("NetworkManager")

class NetworkManager:
    def __init__(self, config: NodeConfig, on_message: Callable[[Message], Awaitable[None]]):
        self.config = config
        self.on_message = on_message
        self.peers: Dict[str, socket.socket] = {} # Outbound connections
        self.peer_lock = threading.Lock()
        
        self.loop = None
        
        # Setup Server socket for P2P TCP Mesh
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((config.listen_host, config.listen_port))
        self.server.listen(5)
        
        logger.info(f"P2P TCP Server listening on {config.listen_host}:{config.listen_port}")

    async def start_server(self):
        self.loop = asyncio.get_running_loop()
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while True:
            try:
                conn, addr = self.server.accept()
                threading.Thread(target=self._handle_incoming, args=(conn, addr), daemon=True).start()
            except Exception as e:
                logger.error(f"Accept error: {e}")
                break

    def _handle_incoming(self, conn: socket.socket, addr: tuple):
        # First message from a peer should be their ID
        try:
            line = self._read_line(conn)
            if not line: return
            
            data = json.loads(line)
            if data.get("type") == "IDENTIFY":
                remote_id = data.get("node_id")
                logger.info(f"Inbound mesh connection from {remote_id} ({addr})")
                
                # We use this connection for receiving messages
                while True:
                    line = self._read_line(conn)
                    if not line: break
                    
                    msg_dict = json.loads(line)
                    msg = Message(**msg_dict)
                    if self.loop:
                        asyncio.run_coroutine_threadsafe(self.on_message(msg), self.loop)
        except Exception as e:
            logger.debug(f"Incoming connection closed: {e}")
        finally:
            conn.close()

    async def handle_discovery(self, remote_peers: Dict[str, str]):
        """Called when signaling server provides updated peer list."""
        for nid, addr in remote_peers.items():
            if nid == self.config.node_id: continue
            
            # Mesh Symmetry Rule: Only the peer with the lexicographically smaller ID initiates
            with self.peer_lock:
                if nid not in self.peers and self.config.node_id < nid:
                    logger.info(f"Mesh: Initiating outbound to {nid} at {addr}")
                    threading.Thread(target=self._maintain_connection, args=(nid, addr), daemon=True).start()

    def _maintain_connection(self, nid: str, addr: str):
        host, port = addr.split(':')
        port = int(port)
        
        while True:
            client = None
            try:
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client.connect((host, port))
                
                # Identity handshake
                id_msg = json.dumps({"type": "IDENTIFY", "node_id": self.config.node_id}) + "\n"
                client.sendall(id_msg.encode())
                
                with self.peer_lock:
                    self.peers[nid] = client
                
                logger.info(f"Outbound mesh connected to {nid}")
                
                # Keep alive/detect disconnect
                while True:
                    # We only send on this socket. To detect disconnect, we can't easily rely on recv 
                    # if the other side isn't sending. But TCP will error on send.
                    # We can use a small heartbeat if needed, but for now we wait.
                    time.sleep(5)
                    if client.fileno() == -1: break
            except Exception:
                pass
            finally:
                with self.peer_lock:
                    if nid in self.peers: del self.peers[nid]
                if client: client.close()
            
            time.sleep(3) # Retry delay

    def _read_line(self, conn: socket.socket) -> str:
        buffer = bytearray()
        while True:
            try:
                b = conn.recv(1)
                if not b: return ""
                if b == b'\n': return buffer.decode()
                buffer.extend(b)
            except Exception:
                return ""

    async def send_to_peer(self, nid: str, msg: Message):
        with self.peer_lock:
            sock = self.peers.get(nid)
        if sock:
            await self._send_raw(sock, msg)

    async def broadcast(self, msg: Message):
        tasks = []
        with self.peer_lock:
            for nid, sock in self.peers.items():
                tasks.append(self._send_raw(sock, msg))
        if tasks:
            await asyncio.gather(*tasks)

    async def _send_raw(self, sock: socket.socket, msg: Message):
        try:
            payload = msg.model_dump_json() + "\n"
            sock.sendall(payload.encode())
        except Exception:
            pass

    async def notify_ui(self, state_dict: Dict[str, Any]):
        # The main.py handles UI websockets now, but for consistency:
        pass
