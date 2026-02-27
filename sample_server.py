import socket
import threading

HOST = "0.0.0.0"
PORT = 5000

clients = []

def broadcast(message):
    for client in clients:
        try:
            client.send(message.encode())
        except:
            client.close()
            clients.remove(client)

def handle_client(conn, addr):
    print(f"[NEW CONNECTION] {addr}")
    clients.append(conn)

    while True:
        try:
            message = conn.recv(1024).decode()
            if not message:
                break

            print(f"\n[{addr}] {message}")
            broadcast(f"[{addr}] {message}")

        except:
            break

    print(f"[DISCONNECTED] {addr}")
    clients.remove(conn)
    conn.close()

def server_input():
    while True:
        message = input()
        full_message = f"[SERVER] {message}"
        print(full_message)
        broadcast(full_message)

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen()

print(f"[STARTED] Server running on port {PORT}")

# Thread for server input
threading.Thread(target=server_input, daemon=True).start()

while True:
    conn, addr = server.accept()
    thread = threading.Thread(target=handle_client, args=(conn, addr))
    thread.start()