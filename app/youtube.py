from pathlib import Path
from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

BASE_DIR = Path(__file__).resolve().parents[1]

CLIENT_SECRET = BASE_DIR / "credentials" / "youtube_client_secret.json"
TOKEN_FILE = BASE_DIR / "token.json"


def get_youtube_service():
    credentials = None

    if TOKEN_FILE.exists():
        credentials = Credentials.from_authorized_user_file(
            TOKEN_FILE,
            SCOPES,
        )

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        if not CLIENT_SECRET.exists():
            raise RuntimeError(
                f"Missing YouTube OAuth credentials:\n{CLIENT_SECRET}"
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            CLIENT_SECRET,
            SCOPES,
        )

        credentials = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")

    return build("youtube", "v3", credentials=credentials)


def upload_video(video_path: Path, title: str, description: str):
    """Upload a vertical short-form video to YouTube."""

    if not video_path.exists():
        raise RuntimeError(f"Video does not exist: {video_path}")

    youtube = get_youtube_service()

    # YouTube does not expose a separate "Short" upload type in the
    # Data API. A video is classified as a Short from its format/length.
    # We therefore keep the upload metadata normal and rely on the
    # generated 9:16, short-duration source video for Shorts classification.
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
        "contentDetails": {
            "caption": "false",
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
    )

    request = youtube.videos().insert(
        part="snippet,status,contentDetails",
        body=body,
        media_body=media,
    )

    response = None

    while response is None:
        status, response = request.next_chunk()

        if status:
            print(
                "YouTube upload: "
                f"{int(status.progress() * 100)}%"
            )

    video_id = response["id"]

    return {
        "post_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }


def get_video_stats(video_id: str):
    """Retrieve current statistics for a YouTube video."""

    youtube = get_youtube_service()

    response = youtube.videos().list(
        part="statistics,snippet",
        id=video_id,
    ).execute()

    items = response.get("items", [])

    if not items:
        raise RuntimeError(f"YouTube video not found: {video_id}")

    video = items[0]
    statistics = video.get("statistics", {})
    snippet = video.get("snippet", {})

    return {
        "views": int(statistics.get("viewCount", 0)),
        "likes": int(statistics.get("likeCount", 0)),
        "comments": int(statistics.get("commentCount", 0)),
        "shares": None,
        "saves": None,
        "published_at": snippet.get("publishedAt"),
        "stats_updated_at": datetime.now(timezone.utc).isoformat(),
    }

