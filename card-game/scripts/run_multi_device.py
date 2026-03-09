import subprocess
import sys
import os
import json
import socket
import argparse

def get_all_ips():
    ips = []
    try:
        hostname = socket.gethostname()
        _, _, ip_list = socket.gethostbyname_ex(hostname)
        for ip in ip_list:
            if not ip.startswith("127."):
                ips.append(ip)
    except:
        pass
    
    # Fallback/Additional check using the connection trick
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        conn_ip = s.getsockname()[0]
        if conn_ip not in ips and conn_ip != '127.0.0.1':
            ips.append(conn_ip)
        s.close()
    except:
        pass
        
    return ips if ips else ["127.0.0.1"]

def get_config(node_id):
    config_path = f"nodes/{node_id}.json"
    with open(config_path, "r") as f:
        return json.load(f)

def run_node(node_id):
    config_path = f"nodes/{node_id}.json"
    return subprocess.Popen([sys.executable, "-m", "backend.app.main", "--config", config_path])

def run_frontend(port, backend_port):
    env = os.environ.copy()
    env["VITE_NODE_UI_WS"] = f"ws://localhost:{backend_port}/ws/ui"
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    return subprocess.Popen([npm_cmd, "run", "dev", "--", "--port", str(port), "--host"], cwd="frontend", env=env)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Run a single node with auto-detected LAN IP')
    parser.add_argument('--node', type=str, required=True, help='Which node to run? (node1, node2, node3)')
    args = parser.parse_args()

    all_ips = get_all_ips()
    print(f"Detected network IPs: {', '.join(all_ips)}")
    
    # Use the first one as primary candidate for the printout
    lan_ip = all_ips[0]
    
    # Read config
    config = get_config(args.node)
    
    ui_port = config["ui_port"]
    peer_port = config["listen_port"]
    frontend_port = 3000 + int(args.node[-1])

    print(f"\n[BACKEND] Starting {args.node}...")
    print(f" - UI Channel (WebSocket): Port {ui_port}")
    print(f" - Peer Channel (TCP): Port {peer_port}")
    backend_p = run_node(args.node)
    
    import time
    time.sleep(1)
    
    print(f"[FRONTEND] Starting React UI on port {frontend_port}...")
    frontend_p = run_frontend(frontend_port, ui_port)

    print("\n" + "="*50)
    print("ACTION REQUIRED FOR MULTI-DEVICE PLAY:")
    print("="*50)
    print("Your laptops must share a real LAN IP.")
    for ip in all_ips:
        status = "(Most Likely)" if not ip.startswith("192.168.56") else "(Virtual/Skip)"
        print(f" - Candidate IP: {ip} {status}")
    
    print("-" * 50)
    print(f"Tell other players to add this to their JSON 'peers' section:")
    print(f" (Replace 'IP' with your real LAN IP from above)")
    print(f"   \"{args.node}\": \"IP:{peer_port}\"")
    print("-" * 50)
    print(f"3. OPEN YOUR BROWSER AT: http://localhost:{frontend_port}")
    print("="*50 + "\n")

    try:
        backend_p.wait()
        frontend_p.wait()
    except KeyboardInterrupt:
        print("Shutting down...")
        backend_p.terminate()
        frontend_p.terminate()
