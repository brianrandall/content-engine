import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import (
    datetime,
    timezone,
    timedelta,
)

import requests
from dotenv import load_dotenv, set_key


# =========================================================
# CONFIG
# =========================================================

HOST = "127.0.0.1"
PORT = 8080

BASE_DIR = Path(
    __file__
).resolve().parents[1]

ENV_FILE = BASE_DIR / ".env"

load_dotenv(
    ENV_FILE
)

CLIENT_ID = os.getenv(
    "INSTAGRAM_CLIENT_ID"
)

CLIENT_SECRET = os.getenv(
    "INSTAGRAM_CLIENT_SECRET"
)

REDIRECT_URI = (
    "https://brianmacm1.tail02ee1d.ts.net/callback"
)

TOKEN_ENDPOINT = (
    "https://api.instagram.com/oauth/access_token"
)


# =========================================================
# ENV HELPERS
# =========================================================

def save_env_value(
    key: str,
    value: str,
):
    """
    Safely update one value in .env without
    replacing the rest of the file.
    """

    set_key(
        str(ENV_FILE),
        key,
        value,
    )


# =========================================================
# TOKEN EXCHANGE
# =========================================================

def exchange_code(
    code: str,
):
    """
    Exchange an Instagram authorization code
    for a short-lived token, then immediately
    exchange that token for a long-lived token.
    """

    if not CLIENT_ID:
        raise RuntimeError(
            "INSTAGRAM_CLIENT_ID is not set "
            "in .env"
        )

    if not CLIENT_SECRET:
        raise RuntimeError(
            "INSTAGRAM_CLIENT_SECRET is not set "
            "in .env"
        )

    # -----------------------------------------------------
    # STEP 1: Authorization code -> short-lived token
    # -----------------------------------------------------

    response = requests.post(
        TOKEN_ENDPOINT,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code": code,
        },
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(
            "Instagram short-lived token exchange "
            f"failed ({response.status_code}): "
            f"{response.text}"
        )

    short_data = response.json()

    short_token = short_data.get(
        "access_token"
    )

    user_id = short_data.get(
        "user_id"
    )

    if not short_token:
        raise RuntimeError(
            "Instagram token response did not "
            "contain an access_token."
        )

    # -----------------------------------------------------
    # STEP 2: Short-lived -> long-lived token
    # -----------------------------------------------------

    long_response = requests.get(
        "https://graph.instagram.com/access_token",
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": CLIENT_SECRET,
            "access_token": short_token,
        },
        timeout=30,
    )

    if not long_response.ok:
        raise RuntimeError(
            "Instagram long-lived token exchange "
            f"failed ({long_response.status_code}): "
            f"{long_response.text}"
        )

    long_data = long_response.json()

    long_token = long_data.get(
        "access_token"
    )

    expires_in = long_data.get(
        "expires_in"
    )

    if not long_token:
        raise RuntimeError(
            "Instagram long-lived token response "
            "did not contain an access_token."
        )

    if not expires_in:
        raise RuntimeError(
            "Instagram long-lived token response "
            "did not contain expires_in."
        )

    # -----------------------------------------------------
    # STEP 3: Save credentials
    # -----------------------------------------------------

    save_env_value(
        "INSTAGRAM_ACCESS_TOKEN",
        long_token,
    )

    if user_id:
        save_env_value(
            "INSTAGRAM_USER_ID",
            str(user_id),
        )

    # Save expiration timestamp.
    expires_at = (
        datetime.now(timezone.utc)
        + timedelta(seconds=int(expires_in))
    )

    save_env_value(
        "INSTAGRAM_TOKEN_EXPIRES_AT",
        expires_at.isoformat(),
    )

    return {
        "user_id": user_id,
        "token_saved": True,
        "expires_in": int(expires_in),
        "expires_at": expires_at.isoformat(),
    }

# =========================================================
# OAUTH CALLBACK
# =========================================================

class OAuthHandler(
    BaseHTTPRequestHandler
):

    def do_GET(self):

        parsed = urlparse(
            self.path
        )

        if parsed.path != "/callback":

            self.send_response(404)
            self.end_headers()

            self.wfile.write(
                b"Not found."
            )

            return

        params = parse_qs(
            parsed.query
        )

        code = params.get(
            "code",
            [None],
        )[0]

        error = params.get(
            "error",
            [None],
        )[0]

        print()
        print("=" * 60)

        if error:

            print(
                "INSTAGRAM OAUTH ERROR"
            )

            print()
            print(error)

        elif code:

            print(
                "INSTAGRAM OAUTH CODE RECEIVED"
            )

            print()
            print(
                "Exchanging code for access token..."
            )

            try:

                result = exchange_code(
                    code
                )

                print()
                print(
                    "INSTAGRAM ACCESS TOKEN SAVED"
                )

                print()
                print(
                    f"Instagram User ID: "
                    f"{result['user_id']}"
                )

                print()
                print(
                    "Updated .env:"
                )

                print(
                    "  INSTAGRAM_ACCESS_TOKEN"
                )

                print(
                    "  INSTAGRAM_USER_ID"
                )

                print()
                expires_days = (
                    result["expires_in"] / 86400
                )

                print(
                    f"Token lifetime: "
                    f"{expires_days:.1f} days"
                )

                print(
                    f"Token expires: "
                    f"{result['expires_at']}"
                )

                print()
                print(
                    "The access token itself "
                    "was not printed."
                )

            except Exception as exc:

                print()
                print(
                    "INSTAGRAM TOKEN EXCHANGE FAILED"
                )

                print()
                print(
                    f"{type(exc).__name__}: {exc}"
                )

        else:

            print(
                "Instagram callback received "
                "without code or error."
            )

        print("=" * 60)
        print()

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/html",
        )

        self.end_headers()

        self.wfile.write(
            b"""
            <html>
                <body>
                    <h1>Authorization received.</h1>
                    <p>
                        You can close this window.
                    </p>
                </body>
            </html>
            """
        )

    def log_message(
        self,
        format,
        *args,
    ):
        return


# =========================================================
# SERVER
# =========================================================

def main():

    if not CLIENT_ID:

        raise RuntimeError(
            "INSTAGRAM_CLIENT_ID is not set "
            "in .env"
        )

    if not CLIENT_SECRET:

        raise RuntimeError(
            "INSTAGRAM_CLIENT_SECRET is not set "
            "in .env"
        )

    server = HTTPServer(
        (HOST, PORT),
        OAuthHandler,
    )

    print(
        "Instagram OAuth callback listening "
        f"on http://{HOST}:{PORT}/callback"
    )

    print(
        "Waiting for Instagram authorization..."
    )

    server.serve_forever()


if __name__ == "__main__":
    main()