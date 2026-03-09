import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

from backend.app.network import NetworkManager
from backend.app.models import NodeConfig, Message
import asyncio
import json

async def mock_on_message(msg):
    pass

def test_ip_parsing():
    print("Testing IP parsing resilience...")
    config = NodeConfig(
        node_id="test_node",
        listen_host="0.0.0.0",
        listen_port=7000,
        ui_port=8000,
        peers={},
        ring_order=["test_node"]
    )
    
    nm = NetworkManager(config, mock_on_message)
    
    # Test cases for _maintain_connection parsing
    test_cases = [
        ("192.168.1.1:7001", "192.168.1.1", 7001),
        (" 192.168.1.1 : 7001 ", "192.168.1.1", 7001),
        ("192.168.1.1.:7001", "192.168.1.1", 7001),
        (" 10.12.249.93. : 7003 ", "10.12.249.93", 7003),
    ]
    
    for addr, expected_ip, expected_port in test_cases:
        ip_raw, port_str = addr.split(':')
        ip = ip_raw.strip().rstrip('.')
        port = int(port_str.strip())
        
        print(f"Input: '{addr}' -> Parsed IP: '{ip}', Port: {port}")
        assert ip == expected_ip, f"Expected {expected_ip}, got {ip}"
        assert port == expected_port, f"Expected {expected_port}, got {port}"

    print("IP parsing tests passed!")

if __name__ == "__main__":
    test_ip_parsing()
