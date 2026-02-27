import socket
import threading

SERVER_IP = "192.168.1.25"  # Replace with server IP
PORT = 5000

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((SERVER_IP, PORT))

def receive_messages():
    while True:
        try:
            message = client.recv(1024).decode()
            print("\n" + message)
        except:
            print("Disconnected from server")
            client.close()
            break

threading.Thread(target=receive_messages, daemon=True).start()

while True:
    message = input()
    client.send(message.encode())