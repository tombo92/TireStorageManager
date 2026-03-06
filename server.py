import os
from waitress import serve
from tsm import app

PORT = int(os.getenv("TSM_PORT", "5000"))
HOST = os.getenv("TSM_HOST", "0.0.0.0")  # bind all interfaces

if __name__ == "__main__":
    # Waitress is a production-grade WSGI server that supports Windows.
    # Use a reverse proxy for :80/:443 if you need standard ports/TLS.
    serve(app, host=HOST, port=PORT)