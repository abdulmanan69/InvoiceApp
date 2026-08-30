"""Minimal Supabase client using only the Python standard library (urllib) - no extra dependency.

Talks to Supabase REST (PostgREST) and Auth (GoTrue) over HTTPS. Every call has a timeout and
raises CloudError with a friendly message on failure, so the UI can stay responsive and offline-safe.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request


class CloudError(Exception):
    """A user-facing cloud problem (network down, wrong key, auth failed, ...)."""


def key_role(key: str) -> str:
    """Best-effort role baked into a Supabase API key: 'anon', 'service_role' or '' if unknown.
    Lets the UI catch the classic mistake of pasting the secret key where the anon key goes."""
    k = (key or "").strip()
    if k.startswith("sb_publishable_"):
        return "anon"
    if k.startswith("sb_secret_"):
        return "service_role"
    parts = k.split(".")
    if len(parts) == 3:
        try:
            import base64
            pad = parts[1] + "=" * (-len(parts[1]) % 4)
            return json.loads(base64.urlsafe_b64decode(pad)).get("role", "")
        except Exception:
            return ""
    return ""


def _request(method: str, url: str, headers: dict, body=None, timeout: float = 15.0):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
        return status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8")
        except Exception:
            pass
        msg = raw
        try:
            j = json.loads(raw)
            msg = j.get("msg") or j.get("message") or j.get("error_description") or j.get("error") or raw
        except Exception:
            pass
        raise CloudError(f"{e.code}: {msg or e.reason}")
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        reason = getattr(e, "reason", e)
        raise CloudError(f"Could not reach the server ({reason}). Check the URL and your internet.")
    except Exception as e:  # pragma: no cover - defensive
        raise CloudError(str(e))


class Supabase:
    def __init__(self, url: str, anon_key: str):
        self.url = (url or "").rstrip("/")
        self.anon = anon_key or ""

    # ------------------------------------------------------------------ headers
    def _auth_headers(self, token: str | None = None, extra: dict | None = None) -> dict:
        h = {"apikey": self.anon, "Authorization": f"Bearer {token or self.anon}", "Content-Type": "application/json"}
        if extra:
            h.update(extra)
        return h

    def _service_headers(self, service_key: str, extra: dict | None = None) -> dict:
        h = {"apikey": service_key, "Authorization": f"Bearer {service_key}", "Content-Type": "application/json"}
        if extra:
            h.update(extra)
        return h

    # ------------------------------------------------------------------ auth
    def test_connection(self) -> bool:
        if not self.url or not self.anon:
            raise CloudError("Enter the Project URL and the anon key first.")
        _request("GET", f"{self.url}/auth/v1/settings", {"apikey": self.anon}, timeout=12)
        return True

    def sign_in(self, email: str, password: str) -> dict:
        _, data = _request("POST", f"{self.url}/auth/v1/token?grant_type=password",
                           {"apikey": self.anon, "Content-Type": "application/json"},
                           {"email": email, "password": password})
        if not data or "access_token" not in data:
            raise CloudError("Sign in failed - wrong email or password.")
        return data

    def sign_up(self, email: str, password: str, metadata: dict | None = None) -> dict:
        """Create a new auth account. Returns a session dict if the project auto-confirms emails,
        otherwise a bare user record (the person must click the confirmation email first)."""
        _, data = _request("POST", f"{self.url}/auth/v1/signup",
                           {"apikey": self.anon, "Content-Type": "application/json"},
                           {"email": email, "password": password, "data": metadata or {}})
        return data or {}

    def db_ready(self) -> bool:
        """True when SUPABASE_SETUP.sql has been run (the shops table answers)."""
        try:
            _request("GET", f"{self.url}/rest/v1/shops?select=id&limit=1",
                     {"apikey": self.anon, "Authorization": f"Bearer {self.anon}"})
            return True
        except CloudError as e:
            m = str(e)
            if "PGRST205" in m or "does not exist" in m or "Could not find the table" in m or m.startswith("404"):
                return False
            raise

    def refresh(self, refresh_token: str) -> dict:
        _, data = _request("POST", f"{self.url}/auth/v1/token?grant_type=refresh_token",
                           {"apikey": self.anon, "Content-Type": "application/json"},
                           {"refresh_token": refresh_token})
        return data or {}

    def get_user(self, token: str) -> dict:
        _, data = _request("GET", f"{self.url}/auth/v1/user", self._auth_headers(token))
        return data or {}

    # ------------------------------------------------------------------ admin (service_role key; owner machine only)
    def admin_create_user(self, service_key: str, email: str, password: str, metadata: dict | None = None) -> dict:
        _, data = _request("POST", f"{self.url}/auth/v1/admin/users",
                           self._service_headers(service_key),
                           {"email": email, "password": password, "email_confirm": True,
                            "user_metadata": metadata or {}})
        if not data or "id" not in data:
            raise CloudError("Could not create the user (is the service key correct?).")
        return data

    def admin_list_users(self, service_key: str) -> list[dict]:
        _, data = _request("GET", f"{self.url}/auth/v1/admin/users?per_page=200", self._service_headers(service_key))
        if isinstance(data, dict):
            return data.get("users", [])
        return data or []

    def admin_delete_user(self, service_key: str, user_id: str) -> None:
        _request("DELETE", f"{self.url}/auth/v1/admin/users/{user_id}", self._service_headers(service_key))

    def admin_update_user(self, service_key: str, user_id: str, attrs: dict) -> dict:
        _, data = _request("PUT", f"{self.url}/auth/v1/admin/users/{user_id}",
                           self._service_headers(service_key), attrs)
        return data or {}

    def admin_find_user(self, service_key: str, email: str) -> dict | None:
        email = (email or "").lower()
        for u in self.admin_list_users(service_key):
            if (u.get("email") or "").lower() == email:
                return u
        return None

    # ------------------------------------------------------------------ REST (PostgREST) - used from Phase B on
    def select(self, table: str, token: str, params: dict | None = None) -> list[dict]:
        q = ("?" + urllib.parse.urlencode(params)) if params else ""
        _, data = _request("GET", f"{self.url}/rest/v1/{table}{q}", self._auth_headers(token))
        return data or []

    def upsert(self, table: str, token: str, rows: list[dict], on_conflict: str = "id") -> list[dict]:
        headers = self._auth_headers(token, {"Prefer": "resolution=merge-duplicates,return=representation"})
        url = f"{self.url}/rest/v1/{table}?on_conflict={on_conflict}"
        _, data = _request("POST", url, headers, rows)
        return data or []

    def insert(self, table: str, token: str, rows: list[dict]) -> list[dict]:
        headers = self._auth_headers(token, {"Prefer": "return=representation"})
        _, data = _request("POST", f"{self.url}/rest/v1/{table}", headers, rows)
        return data or []

    def rpc(self, fn: str, token: str, params: dict | None = None):
        _, data = _request("POST", f"{self.url}/rest/v1/rpc/{fn}", self._auth_headers(token), params or {})
        return data
