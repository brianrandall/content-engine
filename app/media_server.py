import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


# =========================================================
# CONFIG
# =========================================================

BASE_DIR = Path(__file__).resolve().parents[1]

OUTPUT_DIR = (
    BASE_DIR / "output"
)

HOST = os.getenv(
    "MEDIA_SERVER_HOST",
    "0.0.0.0",
)

PORT = int(
    os.getenv(
        "MEDIA_SERVER_PORT",
        "8080",
    )
)


# =========================================================
# SERVER
# =========================================================

class MediaRequestHandler(
    SimpleHTTPRequestHandler
):

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        super().__init__(
            *args,
            directory=str(OUTPUT_DIR),
            **kwargs,
        )

    def log_message(
        self,
        format,
        *args,
    ):
        print(
            f"[MEDIA] {self.address_string()} "
            f"- {format % args}"
        )


class MediaServer:
    """
    Local HTTP server used to expose generated
    media files through Tailscale Funnel.
    """

    def __init__(
        self,
        host=HOST,
        port=PORT,
        directory=OUTPUT_DIR,
    ):
        self.host = host
        self.port = port
        self.directory = Path(
            directory
        )

        self.server = None
        self.thread = None

    def start(self):
        """
        Start the media server in a background thread.
        """

        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.server = ThreadingHTTPServer(
            (
                self.host,
                self.port,
            ),
            MediaRequestHandler,
        )

        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )

        self.thread.start()

        print(
            f"[MEDIA] Server running at "
            f"http://{self.host}:{self.port}"
        )

        print(
            f"[MEDIA] Serving: "
            f"{self.directory}"
        )

        return self

    def stop(self):
        """
        Stop the media server.
        """

        if self.server:
            self.server.shutdown()
            self.server.server_close()

            self.server = None

        if self.thread:
            self.thread.join(
                timeout=5
            )

            self.thread = None

        print(
            "[MEDIA] Server stopped."
        )


# =========================================================
# CONVENIENCE FUNCTION
# =========================================================

def start_media_server():
    """
    Start the Content Engine media server.
    """

    return MediaServer().start()


# =========================================================
# STANDALONE MODE
# =========================================================

def main():

    server = start_media_server()

    print(
        "Content Engine media server running."
    )

    print(
        "Press Ctrl+C to stop."
    )

    try:

        while True:
            threading.Event().wait(
                3600
            )

    except KeyboardInterrupt:

        print()

        server.stop()


if __name__ == "__main__":
    main()