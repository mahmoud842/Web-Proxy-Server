from socket import *
import sys
import sqlite3
import hashlib
from datetime import datetime
import threading

class ProxyServer:
    def __init__(self, host, port=8888):
        self.host = host
        self.port = port
        self.db_name = "proxy_cache.db"
        self.init_database()
        
    def init_database(self):
        """Initialize SQLite database for caching"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cache (
                url TEXT PRIMARY KEY,
                content BLOB,
                content_type TEXT,
                timestamp TEXT
            )
        ''')
        conn.commit()
        conn.close()
        print(f"Database initialized: {self.db_name}")
    
    def get_from_cache(self, url):
        """Retrieve cached content from database"""
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute("SELECT content, content_type FROM cache WHERE url = ?", (url,))
            result = cursor.fetchone()
            conn.close()
            return result if result else None
        except Exception as e:
            print(f"Cache retrieval error: {e}")
            return None
    
    def save_to_cache(self, url, content, content_type="text/html"):
        """Save content to database cache"""
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            timestamp = datetime.now().isoformat()
            cursor.execute('''
                INSERT OR REPLACE INTO cache (url, content, content_type, timestamp)
                VALUES (?, ?, ?, ?)
            ''', (url, content, content_type, timestamp))
            conn.commit()
            conn.close()
            print(f"Cached: {url}")
        except Exception as e:
            print(f"Cache save error: {e}")
    
    def parse_http_request(self, request):
        """Parse HTTP request and extract method, URL, and headers"""
        lines = request.split('\r\n')
        if len(lines) < 1:
            return None, None, None, None
        
        request_line = lines[0].split()
        if len(request_line) < 2:
            return None, None, None, None
        
        method = request_line[0]
        url = request_line[1]
        
        # Extract body for POST requests
        body = ""
        if method == "POST":
            try:
                body_index = request.index('\r\n\r\n') + 4
                body = request[body_index:]
            except:
                body = ""
        
        return method, url, lines, body
    
    def handle_connect(self, client_socket, target_host, target_port):
        """Handle HTTPS CONNECT method (tunnel)"""
        try:
            # Connect to the target server
            server_socket = socket(AF_INET, SOCK_STREAM)
            server_socket.settimeout(10)
            
            print(f"Tunneling to {target_host}:{target_port}...")
            server_socket.connect((target_host, target_port))
            
            # Send success response to client
            client_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            print("Tunnel established")
            
            # Set sockets to non-blocking for bidirectional relay
            client_socket.setblocking(0)
            server_socket.setblocking(0)
            
            # Relay data between client and server
            self.relay_data(client_socket, server_socket)
            
        except Exception as e:
            print(f"CONNECT tunnel error: {e}")
            try:
                error_response = b"HTTP/1.1 502 Bad Gateway\r\n\r\n"
                client_socket.sendall(error_response)
            except:
                pass
        finally:
            try:
                server_socket.close()
            except:
                pass
    
    def relay_data(self, client_socket, server_socket):
        """Relay data bidirectionally between client and server"""
        import select
        
        sockets = [client_socket, server_socket]
        timeout = 60  # 60 seconds idle timeout
        
        try:
            while True:
                # Wait for data on either socket
                readable, _, exceptional = select.select(sockets, [], sockets, timeout)
                
                if exceptional:
                    break
                
                if not readable:
                    # Timeout
                    break
                
                for sock in readable:
                    try:
                        data = sock.recv(8192)
                        if not data:
                            return
                        
                        # Send to the other socket
                        if sock is client_socket:
                            server_socket.sendall(data)
                        else:
                            client_socket.sendall(data)
                    except:
                        return
        except:
            pass
    
    def handle_client(self, client_socket, addr):
        """Handle individual client connection"""
        try:
            # Receive request from client
            request = client_socket.recv(8192).decode('utf-8', errors='ignore')
            
            if not request:
                client_socket.close()
                return
            
            print(f"\n{'='*60}")
            print(f"Request from {addr}:")
            print(request.split('\r\n')[0])  # Print first line only
            
            # Parse the request
            method, url, headers, body = self.parse_http_request(request)
            
            if not method or not url:
                self.send_error(client_socket, "400 Bad Request", "Invalid HTTP request")
                client_socket.close()
                return
            
            # Handle CONNECT method for HTTPS
            if method == "CONNECT":
                # Parse host:port from URL
                if ':' in url:
                    target_host, target_port = url.split(':', 1)
                    target_port = int(target_port)
                else:
                    target_host = url
                    target_port = 443
                
                print(f"Method: CONNECT, Target: {target_host}:{target_port}")
                self.handle_connect(client_socket, target_host, target_port)
                client_socket.close()
                return
            
            # Extract hostname and path for GET/POST
            if url.startswith('http://'):
                url = url[7:]  # Remove http://
            elif url.startswith('/'):
                url = url[1:]  # Remove leading /
            
            # Parse hostname and path
            if '/' in url:
                hostname, path = url.split('/', 1)
                path = '/' + path
            else:
                hostname = url
                path = '/'
            
            print(f"Method: {method}, Host: {hostname}, Path: {path}")
            
            # Check if GET or POST request
            if method not in ["GET", "POST"]:
                self.send_error(client_socket, "501 Not Implemented", 
                              f"Method {method} is not supported")
                client_socket.close()
                return
            
            # Check cache for GET requests
            if method == "GET":
                cached = self.get_from_cache(url)
                if cached:
                    content, content_type = cached
                    print("✓ Cache HIT - Serving from database")
                    self.send_response(client_socket, content, content_type)
                    client_socket.close()
                    return
                else:
                    print("✗ Cache MISS - Fetching from server")
            
            # Forward request to actual web server
            self.forward_request(client_socket, method, hostname, path, body, url)
            
        except Exception as e:
            print(f"Error handling client: {e}")
            try:
                self.send_error(client_socket, "500 Internal Server Error", str(e))
            except:
                pass
        finally:
            try:
                client_socket.close()
            except:
                pass
    
    def forward_request(self, client_socket, method, hostname, path, body, original_url):
        """Forward request to target server and relay response"""
        server_socket = None
        try:
            # Create socket to connect to target server
            server_socket = socket(AF_INET, SOCK_STREAM)
            server_socket.settimeout(10)  # 10 second timeout
            
            # Connect to target server on port 80
            print(f"Connecting to {hostname}:80...")
            server_socket.connect((hostname, 80))
            print("Connected!")
            
            # Build HTTP request
            if method == "GET":
                http_request = f"GET {path} HTTP/1.0\r\n"
                http_request += f"Host: {hostname}\r\n"
                http_request += "Connection: close\r\n"
                http_request += "\r\n"
            else:  # POST
                http_request = f"POST {path} HTTP/1.0\r\n"
                http_request += f"Host: {hostname}\r\n"
                http_request += f"Content-Length: {len(body)}\r\n"
                http_request += "Connection: close\r\n"
                http_request += "\r\n"
                http_request += body
            
            # Send request to server
            server_socket.sendall(http_request.encode())
            
            # Receive response from server
            response = b""
            while True:
                chunk = server_socket.recv(4096)
                if not chunk:
                    break
                response += chunk
            
            print(f"Received {len(response)} bytes from server")
            
            # Parse response to extract content type
            try:
                header_end = response.index(b'\r\n\r\n')
                headers = response[:header_end].decode('utf-8', errors='ignore')
                content_type = "text/html"
                for line in headers.split('\r\n'):
                    if line.lower().startswith('content-type:'):
                        content_type = line.split(':', 1)[1].strip()
                        break
            except:
                content_type = "text/html"
            
            # Cache GET responses
            if method == "GET" and response:
                self.save_to_cache(original_url, response, content_type)
            
            # Send response to client
            client_socket.sendall(response)
            print("Response sent to client")
            
        except timeout:
            print("Connection timeout")
            self.send_error(client_socket, "504 Gateway Timeout", 
                          "Server took too long to respond")
        except gaierror:
            print(f"DNS resolution failed for {hostname}")
            self.send_error(client_socket, "502 Bad Gateway", 
                          f"Could not resolve hostname: {hostname}")
        except ConnectionRefusedError:
            print(f"Connection refused by {hostname}")
            self.send_error(client_socket, "502 Bad Gateway", 
                          f"Connection refused by {hostname}")
        except Exception as e:
            print(f"Error forwarding request: {e}")
            self.send_error(client_socket, "502 Bad Gateway", 
                          f"Error connecting to server: {str(e)}")
        finally:
            if server_socket:
                server_socket.close()
    
    def send_response(self, client_socket, content, content_type="text/html"):
        """Send cached response to client"""
        try:
            client_socket.sendall(content)
        except Exception as e:
            print(f"Error sending response: {e}")
    
    def send_error(self, client_socket, status, message):
        """Send HTTP error response"""
        try:
            response = f"HTTP/1.0 {status}\r\n"
            response += "Content-Type: text/html\r\n"
            response += "Connection: close\r\n"
            response += "\r\n"
            response += f"<html><body><h1>{status}</h1><p>{message}</p></body></html>"
            client_socket.sendall(response.encode())
        except Exception as e:
            print(f"Error sending error response: {e}")
    
    def start(self):
        """Start the proxy server"""
        # Create and configure server socket
        server_socket = socket(AF_INET, SOCK_STREAM)
        server_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        
        try:
            server_socket.bind((self.host, self.port))
            server_socket.listen(5)
            print(f"\n{'='*60}")
            print(f"Proxy Server Started")
            print(f"Listening on {self.host}:{self.port}")
            print(f"Database: {self.db_name}")
            print(f"Supports: HTTP GET/POST + HTTPS tunneling")
            print(f"{'='*60}\n")
            print("Configure your browser to use this proxy:")
            print(f"  HTTP Proxy: {self.host}")
            print(f"  Port: {self.port}")
            print(f"  HTTPS Proxy: {self.host}")
            print(f"  Port: {self.port}")
            print(f"\nFor HTTP-only sites: http://{self.host}:{self.port}/www.example.com")
            print(f"{'='*60}\n")
            
            while True:
                print("Ready to serve...")
                client_socket, addr = server_socket.accept()
                print(f"Connection from: {addr}")
                
                # Handle each client in a separate thread for concurrent connections
                client_thread = threading.Thread(
                    target=self.handle_client, 
                    args=(client_socket, addr)
                )
                client_thread.daemon = True
                client_thread.start()
                
        except KeyboardInterrupt:
            print("\n\nShutting down proxy server...")
        except Exception as e:
            print(f"Server error: {e}")
        finally:
            server_socket.close()
            print("Server socket closed")


def main():
    if len(sys.argv) <= 1:
        print('Usage: python ProxyServer.py <server_ip>')
        print('Example: python ProxyServer.py localhost')
        print('         python ProxyServer.py 0.0.0.0')
        sys.exit(2)
    
    proxy = ProxyServer(sys.argv[1], 8888)
    proxy.start()


if __name__ == "__main__":
    main()