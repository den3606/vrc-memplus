"""VRChat API client for print upload, listing, and deletion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import vrchatapi
from vrchatapi.api import authentication_api, prints_api
from vrchatapi.exceptions import UnauthorizedException
from vrchatapi.models.two_factor_auth_code import TwoFactorAuthCode
from vrchatapi.models.two_factor_email_code import TwoFactorEmailCode

from .config import AppSettings

API_BASE = "https://api.vrchat.cloud/api/1"
APP_NAME = "VRCMemPlus"
APP_VERSION = "1.0.0"


@dataclass
class PrintInfo:
    id: str
    note: str
    author_name: str
    world_name: str
    timestamp: str
    image_url: str
    created_at: str


@dataclass
class GalleryInfo:
    id: str
    name: str
    image_url: str
    created_at: str
    extension: str
    size_bytes: int


@dataclass
class IconInfo:
    id: str
    name: str
    image_url: str
    profile_url: str
    created_at: str
    extension: str
    size_bytes: int


class VRChatClient:
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self._api_client: vrchatapi.ApiClient | None = None
        self._auth_api: authentication_api.AuthenticationApi | None = None
        self._prints_api: prints_api.PrintsApi | None = None
        self._session = requests.Session()

    @property
    def is_logged_in(self) -> bool:
        if not self.settings.user_id:
            return False
        return bool(self.settings.auth_cookie or self._get_auth_from_jar())

    def _get_auth_from_jar(self) -> str:
        if not self._api_client:
            return ""
        jar = self._api_client.rest_client.cookie_jar
        for cookie in jar:
            if cookie.name == "auth" and cookie.value:
                return cookie.value
        return ""

    def _user_agent(self) -> str:
        email = self.settings.contact_email.strip()
        if not email or "@" not in email or "." not in email.split("@")[-1]:
            raise RuntimeError(
                "VRChat API には連絡先メールが必要です。\n"
                "ログイン画面の「連絡先メール」に有効なメールアドレスを入力してください。\n"
                f"形式例: {APP_NAME}/{APP_VERSION} your@email.com"
            )
        return f"{APP_NAME}/{APP_VERSION} {email}"

    def _configure_api_client(self, configuration: vrchatapi.Configuration) -> None:
        user_agent = self._user_agent()
        if hasattr(configuration, "user_agent"):
            configuration.user_agent = user_agent
        self._api_client = vrchatapi.ApiClient(configuration)
        self._api_client.user_agent = user_agent
        self._auth_api = authentication_api.AuthenticationApi(self._api_client)
        self._prints_api = prints_api.PrintsApi(self._api_client)

    def _extract_auth_value(self, cookie_header: str) -> str:
        cookie_header = cookie_header.strip()
        if not cookie_header:
            return ""
        if cookie_header.startswith("auth="):
            return cookie_header.split("=", 1)[1].split(";", 1)[0].strip()
        return cookie_header

    def _save_cookie(self) -> None:
        if not self._api_client:
            return
        auth_value = self._get_auth_from_jar()
        if not auth_value:
            cookie_header = self._api_client.cookie or ""
            auth_value = self._extract_auth_value(cookie_header)
        if auth_value:
            self.settings.auth_cookie = auth_value
            self.settings.save()

    def _apply_saved_cookie(self, configuration: vrchatapi.Configuration) -> None:
        token = self._extract_auth_value(self.settings.auth_cookie)
        if token:
            configuration.api_key["authCookie"] = f"auth={token}"

    def _ensure_client(self) -> None:
        if self._api_client is not None:
            return

        configuration = vrchatapi.Configuration(
            username=self.settings.username or None,
            password=None,
        )
        self._apply_saved_cookie(configuration)

        self._configure_api_client(configuration)

    def login(
        self,
        username: str,
        password: str,
        two_factor_code: str | None = None,
        email_two_factor_code: str | None = None,
    ) -> str:
        self.settings.username = username
        configuration = vrchatapi.Configuration(username=username, password=password)
        self._apply_saved_cookie(configuration)

        if self._api_client is not None:
            self._api_client.close()
        self._configure_api_client(configuration)

        try:
            user = self._auth_api.get_current_user()
        except UnauthorizedException as exc:
            if exc.status != 200:
                raise RuntimeError(f"ログインに失敗しました: {exc.reason}") from exc

            reason = exc.reason or ""
            if "Email 2 Factor Authentication" in reason:
                if not email_two_factor_code:
                    raise TwoFactorRequired("email")
                self._auth_api.verify2_fa_email_code(
                    two_factor_email_code=TwoFactorEmailCode(email_two_factor_code)
                )
            elif "2 Factor Authentication" in reason:
                if not two_factor_code:
                    raise TwoFactorRequired("totp")
                self._auth_api.verify2_fa(two_factor_auth_code=TwoFactorAuthCode(two_factor_code))
            else:
                raise RuntimeError(f"ログインに失敗しました: {reason}") from exc
            user = self._auth_api.get_current_user()

        self.settings.user_id = user.id
        self.settings.display_name = user.display_name or username
        self._save_cookie()
        self.settings.save()
        return self.settings.display_name

    def restore_session(self) -> str:
        if not self.settings.auth_cookie:
            raise RuntimeError("保存されたセッションがありません")
        self._ensure_client()
        user = self._auth_api.get_current_user()
        self.settings.user_id = user.id
        self.settings.display_name = user.display_name or self.settings.username
        self._save_cookie()
        self.settings.save()
        return self.settings.display_name

    def logout(self) -> None:
        if self._api_client is not None:
            try:
                if self._auth_api is not None:
                    self._auth_api.logout()
            except Exception:
                pass
            self._api_client.close()
        self._api_client = None
        self._auth_api = None
        self._prints_api = None
        self.settings.auth_cookie = ""
        self.settings.user_id = ""
        self.settings.display_name = ""
        self.settings.save()

    def _to_print_info(self, data: dict[str, Any]) -> PrintInfo:
        files = data.get("files") or {}
        return PrintInfo(
            id=data.get("id", ""),
            note=data.get("note") or "",
            author_name=data.get("authorName") or "",
            world_name=data.get("worldName") or "",
            timestamp=data.get("timestamp") or "",
            image_url=files.get("image") or "",
            created_at=data.get("createdAt") or "",
        )

    def list_prints(self) -> list[PrintInfo]:
        self._ensure_client()
        if not self.settings.user_id:
            raise RuntimeError("ユーザーIDがありません。再ログインしてください。")
        prints = self._prints_api.get_user_prints(self.settings.user_id)
        if prints is None:
            return []
        result: list[PrintInfo] = []
        for item in prints:
            if isinstance(item, dict):
                result.append(self._to_print_info(item))
            else:
                result.append(
                    PrintInfo(
                        id=getattr(item, "id", ""),
                        note=getattr(item, "note", "") or "",
                        author_name=getattr(item, "author_name", "") or "",
                        world_name=getattr(item, "world_name", "") or "",
                        timestamp=str(getattr(item, "timestamp", "") or ""),
                        image_url=(getattr(getattr(item, "files", None), "image", "") or ""),
                        created_at=str(getattr(item, "created_at", "") or ""),
                    )
                )
        return result

    def get_print(self, print_id: str) -> PrintInfo:
        self._ensure_client()
        item = self._prints_api.get_print(print_id)
        if isinstance(item, dict):
            return self._to_print_info(item)
        return PrintInfo(
            id=getattr(item, "id", ""),
            note=getattr(item, "note", "") or "",
            author_name=getattr(item, "author_name", "") or "",
            world_name=getattr(item, "world_name", "") or "",
            timestamp=str(getattr(item, "timestamp", "") or ""),
            image_url=(getattr(getattr(item, "files", None), "image", "") or ""),
            created_at=str(getattr(item, "created_at", "") or ""),
        )

    def _format_timestamp(self, ts: datetime) -> str:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def upload_print(
        self,
        image_path: str | Path,
        note: str = "",
        world_name: str = "",
        world_id: str = "",
        timestamp: datetime | None = None,
    ) -> PrintInfo:
        self._ensure_client()
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(str(image_path))

        image_bytes = image_path.read_bytes()
        if not image_bytes:
            raise RuntimeError("画像ファイルが空です")

        ts = timestamp or datetime.now(timezone.utc)
        data: dict[str, str] = {
            "timestamp": self._format_timestamp(ts),
            "note": note or image_path.stem,
            "worldName": world_name or "local",
        }
        if world_id:
            data["worldId"] = world_id

        response = self._session.post(
            f"{API_BASE}/prints",
            data=data,
            files={"image": (image_path.name, image_bytes, "image/png")},
            headers={"User-Agent": self._user_agent()},
            cookies=self._auth_cookies(),
            timeout=120,
        )

        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            raise RuntimeError(f"アップロード失敗 ({response.status_code}): {detail}")

        payload = response.json()
        if isinstance(payload, dict):
            return self._to_print_info(payload)
        raise RuntimeError("アップロード応答の形式が不正です")

    def edit_print(self, print_id: str, image_path: str | Path, note: str = "") -> PrintInfo:
        self._ensure_client()
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(str(image_path))

        image_bytes = image_path.read_bytes()
        if not image_bytes:
            raise RuntimeError("画像ファイルが空です")

        data: dict[str, str] = {}
        if note:
            data["note"] = note

        response = self._session.post(
            f"{API_BASE}/prints/{print_id}",
            data=data,
            files={"image": (image_path.name, image_bytes, "image/png")},
            headers={"User-Agent": self._user_agent()},
            cookies=self._auth_cookies(),
            timeout=120,
        )

        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            raise RuntimeError(f"編集失敗 ({response.status_code}): {detail}")

        payload = response.json()
        if isinstance(payload, dict):
            return self._to_print_info(payload)
        raise RuntimeError("編集応答の形式が不正です")

    def delete_print(self, print_id: str) -> None:
        self._ensure_client()
        self._prints_api.delete_print(print_id)

    def list_gallery_photos(self) -> list[GalleryInfo]:
        self._ensure_client()
        response = self._session.get(
            f"{API_BASE}/files",
            params={"tag": "gallery"},
            headers={"User-Agent": self._user_agent()},
            cookies=self._auth_cookies(),
            timeout=60,
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            raise RuntimeError(f"ギャラリー一覧取得失敗 ({response.status_code}): {detail}")

        payload = response.json()
        if not isinstance(payload, list):
            return []

        items: list[GalleryInfo] = []
        for item in payload:
            if isinstance(item, dict):
                items.append(self._to_gallery_info(item))
        return items

    def upload_gallery_image(self, image_path: str | Path) -> GalleryInfo:
        self._ensure_client()
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(str(image_path))

        image_bytes = image_path.read_bytes()
        if not image_bytes:
            raise RuntimeError("画像ファイルが空です")

        response = self._session.post(
            f"{API_BASE}/gallery",
            files={"file": (image_path.name, image_bytes, "image/png")},
            headers={"User-Agent": self._user_agent()},
            cookies=self._auth_cookies(),
            timeout=120,
        )

        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            raise RuntimeError(f"ギャラリーアップロード失敗 ({response.status_code}): {detail}")

        payload = response.json()
        if isinstance(payload, dict):
            return self._to_gallery_info(payload)
        raise RuntimeError("アップロード応答の形式が不正です")

    def delete_gallery_photo(self, file_id: str) -> None:
        self._delete_file_asset(file_id, "ギャラリー")

    def list_user_icons(self) -> list[IconInfo]:
        self._ensure_client()
        response = self._session.get(
            f"{API_BASE}/files",
            params={"tag": "icon"},
            headers={"User-Agent": self._user_agent()},
            cookies=self._auth_cookies(),
            timeout=60,
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            raise RuntimeError(f"アイコン一覧取得失敗 ({response.status_code}): {detail}")

        payload = response.json()
        if not isinstance(payload, list):
            return []

        return [self._to_icon_info(item) for item in payload if isinstance(item, dict)]

    def upload_user_icon(self, image_path: str | Path) -> IconInfo:
        self._ensure_client()
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(str(image_path))

        image_bytes = image_path.read_bytes()
        if not image_bytes:
            raise RuntimeError("画像ファイルが空です")

        response = self._session.post(
            f"{API_BASE}/icon",
            files={"file": (image_path.name, image_bytes, "image/png")},
            headers={"User-Agent": self._user_agent()},
            cookies=self._auth_cookies(),
            timeout=120,
        )

        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            raise RuntimeError(f"アイコンアップロード失敗 ({response.status_code}): {detail}")

        payload = response.json()
        if isinstance(payload, dict):
            return self._to_icon_info(payload)
        raise RuntimeError("アップロード応答の形式が不正です")

    def delete_user_icon(self, file_id: str) -> None:
        self._delete_file_asset(file_id, "アイコン")

    def get_active_user_icon_url(self) -> str:
        self._ensure_client()
        user = self._auth_api.get_current_user()
        return str(getattr(user, "user_icon", "") or "")

    def set_active_user_icon(self, profile_url: str) -> str:
        self._ensure_client()
        if not self.settings.user_id:
            raise RuntimeError("ユーザーIDがありません。再ログインしてください。")

        response = self._session.put(
            f"{API_BASE}/users/{self.settings.user_id}",
            json={"userIcon": profile_url},
            headers={
                "User-Agent": self._user_agent(),
                "Content-Type": "application/json",
            },
            cookies=self._auth_cookies(),
            timeout=60,
        )

        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            raise RuntimeError(f"アイコン設定失敗 ({response.status_code}): {detail}")

        payload = response.json()
        if isinstance(payload, dict):
            return str(payload.get("userIcon") or profile_url)
        return profile_url

    def _delete_file_asset(self, file_id: str, label: str) -> None:
        self._ensure_client()
        response = self._session.delete(
            f"{API_BASE}/file/{file_id}",
            headers={"User-Agent": self._user_agent()},
            cookies=self._auth_cookies(),
            timeout=60,
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            raise RuntimeError(f"{label}削除失敗 ({response.status_code}): {detail}")

    def _parse_file_record(self, data: dict) -> tuple[str, str, str, int, str]:
        file_id = str(data.get("id", ""))
        versions = data.get("versions") or []
        created_at = ""
        size_bytes = 0
        image_url = f"{API_BASE}/file/{file_id}/1/file" if file_id else ""
        profile_url = f"{API_BASE}/file/{file_id}/1" if file_id else ""

        for version in reversed(versions):
            if not isinstance(version, dict):
                continue
            if version.get("status") != "complete":
                continue
            created_at = str(version.get("created_at") or version.get("createdAt") or created_at)
            file_meta = version.get("file") or {}
            if isinstance(file_meta, dict):
                size_bytes = int(file_meta.get("sizeInBytes") or file_meta.get("size_in_bytes") or size_bytes)
                url = file_meta.get("url")
                if url:
                    image_url = str(url)
            break

        if not created_at and versions:
            first = versions[0] if isinstance(versions[0], dict) else {}
            created_at = str(first.get("created_at") or first.get("createdAt") or "")

        return file_id, image_url, profile_url, created_at, size_bytes

    def _to_gallery_info(self, data: dict) -> GalleryInfo:
        file_id, image_url, _profile_url, created_at, size_bytes = self._parse_file_record(data)
        return GalleryInfo(
            id=file_id,
            name=str(data.get("name") or ""),
            image_url=image_url,
            created_at=created_at,
            extension=str(data.get("extension") or "png"),
            size_bytes=size_bytes,
        )

    def _to_icon_info(self, data: dict) -> IconInfo:
        file_id, image_url, profile_url, created_at, size_bytes = self._parse_file_record(data)
        return IconInfo(
            id=file_id,
            name=str(data.get("name") or ""),
            image_url=image_url,
            profile_url=profile_url,
            created_at=created_at,
            extension=str(data.get("extension") or "png"),
            size_bytes=size_bytes,
        )

    def _auth_cookies(self) -> dict[str, str]:
        self._ensure_client()
        cookies: dict[str, str] = {}
        if self._api_client:
            for cookie in self._api_client.rest_client.cookie_jar:
                cookies[cookie.name] = cookie.value
        token = self._extract_auth_value(self.settings.auth_cookie)
        if token and "auth" not in cookies:
            cookies["auth"] = token
        return cookies

    def _is_image_bytes(self, data: bytes) -> bool:
        if len(data) < 12:
            return False
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return True
        if data[:3] == b"\xff\xd8\xff":
            return True
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"

    def _candidate_image_urls(self, url: str) -> list[str]:
        candidates = [url]
        if url.endswith("/file"):
            candidates.append(url[:-5])
        return candidates

    def download_image(self, url: str, output_path: str | Path) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        headers = {"User-Agent": self._user_agent()}
        cookies = self._auth_cookies()
        last_error: Exception | None = None

        for candidate_url in self._candidate_image_urls(url):
            try:
                response = self._session.get(
                    candidate_url,
                    headers=headers,
                    cookies=cookies,
                    timeout=60,
                )
                response.raise_for_status()
                content = response.content
                content_type = (response.headers.get("Content-Type") or "").lower()

                if "json" in content_type or content[:1] == b"{":
                    raise RuntimeError("API が画像ではなく JSON エラーを返しました")
                if not self._is_image_bytes(content):
                    raise RuntimeError("ダウンロード内容が画像形式ではありません")

                self._write_bytes_atomic(output_path, content)
                return output_path
            except Exception as exc:
                last_error = exc
                continue

        self._safe_unlink(output_path)
        message = str(last_error) if last_error else "不明なエラー"
        raise RuntimeError(f"画像のダウンロードに失敗しました: {message}") from last_error

    def _safe_unlink(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def _write_bytes_atomic(self, path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.part")
        temp_path.write_bytes(content)
        try:
            temp_path.replace(path)
        except OSError:
            if path.exists():
                self._safe_unlink(temp_path)
                return
            path.write_bytes(content)
            self._safe_unlink(temp_path)
        else:
            self._safe_unlink(temp_path)


class TwoFactorRequired(Exception):
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind
