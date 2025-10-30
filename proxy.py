from socket import *
import sys
import os
import hashlib

if len(sys.argv) <= 1:
    print('Usage : "python ProxyServer.py server_ip"\n[server_ip : It is the IP Address Of Proxy Server]')
    sys.exit(2)

# Create a server socket, bind it to a port and start listening
tcpSerSock = socket(AF_INET, SOCK_STREAM)

tcpSerSock.bind((sys.argv[1], 8888))
tcpSerSock.listen(1)

cache = {}

while 1:
    # Start receiving data from the client
    print('Ready to serve...')
    tcpCliSock, addr = tcpSerSock.accept()
    print('Received a connection from:', addr)

    message = tcpCliSock.recv(4096).decode()

    try:
        method = message.split()[0]
        url = message.split()[1]
        filename = url.partition("/")[2]
        if (filename[0] == '/'):
            filename = filename[1:]
        if (filename[-1] == '/'):
            filename = filename[0:-1]
        headers, _, body = message.partition("\r\n\r\n")
    except:
        continue

    print("\033[33m")
    print(f"Method: {method}")
    print(f"URL: {url}")
    print(f"filename: {filename}")
    print("\033[0m", end="")
        
    fileExist = "false"

    directoryList = filename.split('/')
    filepath = ""
    if (len(directoryList) >= 2) :
        for directory in directoryList[0:-1]:
            directory += "folder"
            filepath += directory
            if not os.path.exists(filepath):
                os.makedirs(filepath)
                print("Directory created:", directory)
            else:
                print("Directory already exists:", directory)
            filepath += '/'

    filepath += directoryList[-1].replace('?', '-&-')

    print(filepath)

    if method == "POST":
        body_hash = hashlib.md5(body.encode()).hexdigest()
        cache_key = (method, url, body_hash)
        if cache_key in cache:
            print("\033[32m-- CACHE HIT --\033[0m")
            tcpCliSock.send(cache[cache_key])
            tcpCliSock.close()
            continue

    try:
        # Check whether the file exists in the cache
        f = open(filepath, "rb")
        outputdata = f.readlines()
        fileExist = "true"

        for line in outputdata:
            tcpCliSock.send(line)
        f.close()

        print("\033[32m-- CACHE HIT --\033[0m")

    # Error handling for file not found in cache
    except IOError:
        if fileExist == "false":
            # Create a socket on the proxyserver
            c = socket(AF_INET, SOCK_STREAM)

            hostn = filename.replace("www.", "", 1)
            
            print("\033[33m", end="")
            print(f"Host: {hostn}")
            print("\033[0m", end="")

            try:
                # Connect to the socket to port 80
                c.connect((hostn.partition('/')[0], 80))

                # Create a temporary file on this socket and ask port 80 for the file requested by the client
                fileobj = c.makefile('rwb', 0)

                if method == "POST":
                    request_line = f"POST http://{filename} HTTP/1.0\r\n"
                    fileobj.write((request_line + headers + "\r\n\r\n" + body).encode())
                else:
                    fileobj.write(("GET http://" + filename + " HTTP/1.0\r\n\r\n").encode())

                # Read the response into buffer
                buffer = fileobj.read()

                print("\033[31m-- CACHE MISS --\033[0m")

                if method == "GET":
                    tmpFile = open("./" + filepath, "wb")
                    tmpFile.write(buffer)
                    tmpFile.close()
                else:
                    cache[cache_key] = buffer

                tcpCliSock.send(buffer)

            except Exception as e:
                print("Illegal request:", e)
        else:
            # HTTP response message for file not found
            tcpCliSock.send("HTTP/1.0 404 Not Found\r\n".encode())
            tcpCliSock.send("Content-Type:text/html\r\n".encode())
            tcpCliSock.send("<html><body><h1>404 Not Found</h1></body></html>".encode())

    # Close the client and the server sockets
    tcpCliSock.close()

tcpSerSock.close()
