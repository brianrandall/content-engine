from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from datetime import datetime, timezone


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
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

def get_video_stats(
    video_id: str,
):
    """
    Retrieve current statistics for a YouTube video.
    """

    youtube = get_youtube_service()

    response = youtube.videos().list(
        part="statistics,snippet",
        id=video_id,
    ).execute()

    items = response.get("items", [])

    if not items:
        raise RuntimeError(
            f"YouTube video not found: {video_id}"
        )

    video = items[0]

    statistics = video.get(
        "statistics",
        {},
    )

    snippet = video.get(
        "snippet",
        {},
    )

    return {
        "views": int(
            statistics.get("viewCount", 0)
        ),
        "likes": int(
            statistics.get("likeCount", 0)
        ),
        "comments": int(
            statistics.get("commentCount", 0)
        ),
        "shares": None,
        "saves": None,
        "published_at": snippet.get(
            "publishedAt"
        ),
        "stats_updated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
    }