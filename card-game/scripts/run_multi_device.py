import subprocess
import sys
import os
import json
import socket
import argparse

def get_lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

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

    lan_ip = get_lan_ip()
    print(f"Detected your LAN IP as: {lan_ip}")
    
    # Read config
    config = get_config(args.node)
    
    frontend_port = 3000 + int(args.node[-1])
    backend_port = config["ui_port"]

    print(f"Starting Backend {args.node} on port {backend_port}...")
    backend_p = run_node(args.node)
    
    import time
    time.sleep(1)
    
    print(f"Starting Frontend on port {frontend_port}...")
    frontend_p = run_frontend(frontend_port, backend_port)

    print("\n===============================")
    print(f"Node is running! Tell other devices to connect their peers to:")
    print(f" {lan_ip}:{backend_port}")
    print(f"\nAccess the UI on this device at: http://localhost:{frontend_port}")
    print(f"Access the UI remotely at: http://{lan_ip}:{frontend_port}")
    print("===============================\n")

    try:
        backend_p.wait()
        frontend_p.wait()
    except KeyboardInterrupt:
        print("Shutting down...")
        backend_p.terminate()
        frontend_p.terminate()
