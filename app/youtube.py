from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
]

BASE_DIR = Path(__file__).resolve().parents[1]

CLIENT_SECRET = (
    BASE_DIR
    / "credentials"
    / "youtube_client_secret.json"
)

TOKEN_FILE = BASE_DIR / "token.json"


def get_youtube_service():

    credentials = None

    if TOKEN_FILE.exists():

        credentials = (
            Credentials.from_authorized_user_file(
                TOKEN_FILE,
                SCOPES,
            )
        )

    if (
        credentials
        and credentials.expired
        and credentials.refresh_token
    ):

        credentials.refresh(
            Request()
        )

    if not credentials or not credentials.valid:

        if not CLIENT_SECRET.exists():

            raise RuntimeError(
                f"Missing YouTube OAuth credentials:\n"
                f"{CLIENT_SECRET}"
            )

        flow = (
            InstalledAppFlow
            .from_client_secrets_file(
                CLIENT_SECRET,
                SCOPES,
            )
        )

        credentials = (
            flow.run_local_server(
                port=0
            )
        )

        TOKEN_FILE.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )

    return build(
        "youtube",
        "v3",
        credentials=credentials,
    )


def upload_video(
    video_path: Path,
    title: str,
    description: str,
):

    if not video_path.exists():

        raise RuntimeError(
            f"Video does not exist: "
            f"{video_path}"
        )

    youtube = get_youtube_service()

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": "private",
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None

    while response is None:

        status, response = (
            request.next_chunk()
        )

        if status:

            print(
                "YouTube upload: "
                f"{int(status.progress() * 100)}%"
            )

    video_id = response["id"]

    return {
        "post_id": video_id,
        "url": (
            "https://www.youtube.com/watch?v="
            f"{video_id}"
        ),
    }