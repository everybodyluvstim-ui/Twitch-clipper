"""
Twitch Helix API helper.
Uses the Client Credentials flow (app access token) — no user login needed
since we only ever touch PUBLIC data (channel info + public VODs).
"""
import time
import requests

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
API_BASE = "https://api.twitch.tv/helix"


class TwitchClient:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None
        self._token_expires_at = 0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        resp = requests.post(TOKEN_URL, params={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data["expires_in"]
        return self._token

    def _headers(self):
        return {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {self._get_token()}",
        }

    def get_user(self, login: str) -> dict | None:
        r = requests.get(f"{API_BASE}/users", headers=self._headers(),
                          params={"login": login}, timeout=15)
        r.raise_for_status()
        data = r.json()["data"]
        return data[0] if data else None

    def get_vods(self, user_id: str, limit: int = 20) -> list[dict]:
        """Public archived broadcasts (VODs) for a channel, newest first."""
        r = requests.get(f"{API_BASE}/videos", headers=self._headers(), params={
            "user_id": user_id,
            "first": min(limit, 100),
            "type": "archive",
        }, timeout=15)
        r.raise_for_status()
        return r.json()["data"]

    def get_video(self, video_id: str) -> dict | None:
        r = requests.get(f"{API_BASE}/videos", headers=self._headers(),
                          params={"id": video_id}, timeout=15)
        r.raise_for_status()
        data = r.json()["data"]
        return data[0] if data else None
