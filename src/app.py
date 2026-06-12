"""VRCMem+ - manage VRChat Photo Gallery and Prints."""

from __future__ import annotations

APP_DISPLAY_NAME = "VRCMem+"

import hashlib
import io
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk
from PIL import Image

from .config import AppSettings, app_data_dir
from .paths import app_icon_path
from .gallery_prepare import prepare_gallery_image
from .icon_prepare import prepare_icon_image
from .vrchat_client import GalleryInfo, IconInfo, PrintInfo, TwoFactorRequired, VRChatClient
from .print_converter import (
    ORIG_H,
    ORIG_W,
    PORT_H,
    PORT_W,
    prepare_print_for_upload,
)

ORIENTATION_UI = {"横": "landscape", "縦": "portrait"}
ORIENTATION_UI_REV = {value: label for label, value in ORIENTATION_UI.items()}
CROP_UI = {"クロップ": "cover", "全体": "contain"}
CROP_UI_REV = {value: label for label, value in CROP_UI.items()}
LOGIN_PLACEHOLDERS = {
    "username": "VRChat ユーザー名",
    "password": "パスワード",
    "contact_email": "your@email.com",
    "two_factor": "6桁の認証コード（必要時）",
    "email_two_factor": "メールの認証コード（必要時）",
}
PREVIEW_FALLBACK_WIDTH = 520
PREVIEW_AREA_MINSIZE = 280
CARD_FG = ("gray95", "gray18")
CARD_BORDER = ("gray70", "gray40")
PANEL_FG = ("gray90", "gray20")
PANEL_BORDER = ("gray55", "#666666")
INFO_WRAP = 360

PAGE_DESCRIPTIONS = {
    "login": (
        "VRCMem+ にログインして、VRChat の Photo Gallery と Print を管理します。\n"
        "セッションは保存されるので、次回は「セッション復元」から再開できます。"
    ),
    "gallery": (
        "プロフィールや写真メニューに表示する Photo Gallery 用の画像を管理します。\n"
        "写真をドロップすると PNG に変換（各辺 2047px 以下）してアップロードします。\n"
        "一覧の確認・プレビュー・ダウンロード・削除ができます。"
    ),
    "print": (
        "ワールド内に配置する Print（ポラロイド風の写真）を管理します。\n"
        "写真をドロップすると Print 用サイズ（横 2048×1440 / 縦 1440×2048）にリサイズ・クロップしてアップロードします（枠は VRChat 側で表示）。\n"
        "メモの編集・一覧・ダウンロード・削除ができます。アップロードには VRC+ が必要です。"
    ),
    "icon": (
        "ネームプレートなどに表示するユーザーアイコンを管理します。\n"
        "写真をドロップすると正方形にクロップ（最大 2048×2048）してアップロードします。\n"
        "一覧からプロフィールに設定・ダウンロード・削除ができます。VRC+ が必要です。"
    ),
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
IMAGE_FILETYPES = [
    ("画像ファイル", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff"),
    ("すべてのファイル", "*.*"),
]

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False


class VRCMemApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        if DND_AVAILABLE:
            try:
                TkinterDnD._require(self)
            except Exception:
                pass

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(APP_DISPLAY_NAME)
        self.geometry("1100x760")
        self.minsize(960, 640)
        self._set_window_icon()

        self.settings = AppSettings.load()
        if not self.settings.default_world_name:
            self.settings.default_world_name = "local"
        self.client = VRChatClient(self.settings)
        self._active_page = "login"
        self._preview_photo: ctk.CTkImage | None = None
        self._gallery_preview_photo: ctk.CTkImage | None = None
        self._thumb_cache: dict[str, ctk.CTkImage] = {}
        self._gallery_thumb_cache: dict[str, ctk.CTkImage] = {}
        self._gallery_list_gen = 0
        self._print_list_gen = 0
        self._print_rows: list[PrintInfo] = []
        self._selected_print_ids: set[str] = set()
        self._selected_print: PrintInfo | None = None
        self._gallery_rows: list[GalleryInfo] = []
        self._selected_gallery_ids: set[str] = set()
        self._selected_gallery: GalleryInfo | None = None
        self._icon_list_gen = 0
        self._icon_rows: list[IconInfo] = []
        self._selected_icon_ids: set[str] = set()
        self._selected_icon: IconInfo | None = None
        self._icon_thumb_cache: dict[str, ctk.CTkImage] = {}
        self._icon_preview_photo: ctk.CTkImage | None = None
        self._active_icon_photo: ctk.CTkImage | None = None
        self._active_user_icon_url = ""
        self._upload_busy = False
        self._cache_locks: dict[str, threading.Lock] = {}
        self._cache_locks_guard = threading.Lock()

        self._build_layout()
        self._load_settings_into_ui()
        self._try_restore_session()
        if self.client.is_logged_in:
            self._show_page("gallery", auto_load=True)
        else:
            self._show_page("login")

    def _set_window_icon(self) -> None:
        icon_path = app_icon_path()
        if not icon_path.exists():
            return
        try:
            self.iconbitmap(default=str(icon_path))
        except Exception:
            pass

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(5, weight=1)

        ctk.CTkLabel(self.sidebar, text=APP_DISPLAY_NAME, font=ctk.CTkFont(size=22, weight="bold")).grid(
            row=0, column=0, padx=20, pady=(24, 20), sticky="w"
        )

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for idx, (key, label) in enumerate(
            [
                ("login", "ログイン"),
                ("gallery", "PhotoGallery"),
                ("print", "Print"),
                ("icon", "ユーザーアイコン"),
            ],
            start=1,
        ):
            btn = ctk.CTkButton(
                self.sidebar,
                text=label,
                anchor="w",
                command=lambda k=key: self._show_page(k, auto_load=k in ("gallery", "print", "icon")),
            )
            btn.grid(row=idx, column=0, padx=16, pady=6, sticky="ew")
            self.nav_buttons[key] = btn

        self.status_label = ctk.CTkLabel(self.sidebar, text="未ログイン", text_color="gray70", wraplength=180)
        self.status_label.grid(row=6, column=0, padx=16, pady=16, sticky="sw")

        self.content = ctk.CTkFrame(self, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.pages: dict[str, ctk.CTkFrame] = {
            "login": self._build_login_page(),
            "gallery": self._build_gallery_page(),
            "print": self._build_print_page(),
            "icon": self._build_icon_page(),
        }
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

        self.progress = ctk.CTkProgressBar(self.content)
        self.progress.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 16))
        self.progress.set(0)
        self.progress.grid_remove()

    def _show_page(self, key: str, auto_load: bool = False) -> None:
        self._active_page = key
        for name, page in self.pages.items():
            page.grid() if name == key else page.grid_remove()
        for name, btn in self.nav_buttons.items():
            btn.configure(fg_color=("gray75", "gray25") if name == key else "transparent")
        if auto_load and self.client.is_logged_in:
            if key == "gallery":
                self._refresh_gallery()
            elif key == "print":
                self._refresh_prints()
            elif key == "icon":
                self._refresh_icons()

    def _build_login_page(self) -> ctk.CTkScrollableFrame:
        page = ctk.CTkScrollableFrame(self.content)
        page.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(page, text="VRChat ログイン", font=ctk.CTkFont(size=24, weight="bold")).grid(
            row=0, column=0, padx=24, pady=(24, 8), sticky="w"
        )
        ctk.CTkLabel(
            page,
            text=PAGE_DESCRIPTIONS["login"],
            font=ctk.CTkFont(size=12),
            text_color="gray70",
            wraplength=720,
            justify="left",
        ).grid(row=1, column=0, padx=24, pady=(0, 16), sticky="w")

        form = ctk.CTkFrame(page)
        form.grid(row=2, column=0, padx=24, pady=8, sticky="ew")
        form.grid_columnconfigure(1, weight=1)

        fields = [
            ("username", "ユーザー名"),
            ("password", "パスワード"),
            ("contact_email", "連絡先メール (必須)"),
            ("two_factor", "2FAコード (必要時)"),
            ("email_two_factor", "メール2FAコード (必要時)"),
        ]
        self.login_entries: dict[str, ctk.CTkEntry] = {}
        for row, (key, label) in enumerate(fields):
            ctk.CTkLabel(form, text=label).grid(row=row, column=0, padx=12, pady=8, sticky="w")
            entry_kwargs: dict = {"placeholder_text": LOGIN_PLACEHOLDERS[key]}
            if "password" in key or "factor" in key:
                entry_kwargs["show"] = "*"
            entry = ctk.CTkEntry(form, **entry_kwargs)
            entry.grid(row=row, column=1, padx=12, pady=8, sticky="ew")
            self.login_entries[key] = entry

        btns = ctk.CTkFrame(page, fg_color="transparent")
        btns.grid(row=3, column=0, padx=24, pady=16, sticky="w")
        ctk.CTkButton(btns, text="ログイン", command=self._login).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="セッション復元", command=self._restore_session).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="ログアウト", fg_color="gray30", command=self._logout).pack(side="left")
        return page

    def _build_page_header(self, page: ctk.CTkFrame, title: str, description: str, content_row: int) -> None:
        page.grid_columnconfigure(0, weight=2)
        page.grid_columnconfigure(1, weight=3)
        page.grid_rowconfigure(content_row, weight=1)

        ctk.CTkLabel(page, text=title, font=ctk.CTkFont(size=24, weight="bold")).grid(
            row=0, column=0, columnspan=2, padx=24, pady=(24, 4), sticky="w"
        )
        desc = ctk.CTkLabel(
            page,
            text=description,
            font=ctk.CTkFont(size=12),
            text_color="gray70",
            wraplength=720,
            justify="left",
            anchor="w",
        )
        desc.grid(row=1, column=0, columnspan=2, padx=24, pady=(0, 12), sticky="ew")

        def on_resize(event) -> None:
            if self._widget_alive(desc):
                desc.configure(wraplength=max(320, event.width - 56))

        page.bind("<Configure>", on_resize)

    def _build_upload_card(
        self,
        parent: ctk.CTkFrame,
        row: int,
        *,
        title: str,
        drop_text: str,
        on_drop: Callable,
        on_pick: Callable,
        status_attr: str,
        build_settings: Callable[[ctk.CTkFrame], None] | None = None,
    ) -> tk.Label:
        card = ctk.CTkFrame(
            parent,
            fg_color=CARD_FG,
            border_width=1,
            border_color=CARD_BORDER,
            corner_radius=8,
        )
        card.grid(row=row, column=0, columnspan=2, padx=24, pady=(0, 6), sticky="ew")
        card.grid_columnconfigure(0, weight=1)

        body_row = 0
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.grid(row=body_row, column=0, padx=12, pady=(8, 6), sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text=title, font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, sticky="w"
        )
        status_label = ctk.CTkLabel(
            header,
            text="写真をドロップすると自動アップロードします",
            text_color="gray70",
            font=ctk.CTkFont(size=11),
            anchor="e",
        )
        status_label.grid(row=0, column=1, sticky="e", padx=(8, 0))
        setattr(self, status_attr, status_label)
        body_row += 1

        if build_settings is not None:
            settings = ctk.CTkFrame(card, fg_color="transparent")
            settings.grid(row=body_row, column=0, padx=12, pady=(0, 6), sticky="ew")
            build_settings(settings)
            body_row += 1

        drop_row = ctk.CTkFrame(card, fg_color="transparent")
        drop_row.grid(row=body_row, column=0, padx=12, pady=(0, 8), sticky="ew")
        drop_row.grid_columnconfigure(0, weight=1)

        drop_zone = ctk.CTkFrame(drop_row, height=44, fg_color=("gray85", "gray25"), corner_radius=8)
        drop_zone.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        drop_zone.grid_propagate(False)
        drop_zone.grid_columnconfigure(0, weight=1)
        drop_zone.grid_rowconfigure(0, weight=1)

        if not DND_AVAILABLE:
            drop_text += "（クリックでも選択）"
        drop_target = tk.Label(
            drop_zone,
            text=drop_text,
            bg="#2b2b2b",
            fg="#aaaaaa",
            font=("Segoe UI", 11),
            justify="center",
            cursor="hand2",
        )
        drop_target.place(relx=0, rely=0, relwidth=1, relheight=1)
        drop_target.bind("<Button-1>", lambda _e: on_pick())
        self._setup_drop_target(drop_target, on_drop)

        ctk.CTkButton(
            drop_row,
            text="選択",
            width=72,
            height=44,
            command=on_pick,
        ).grid(row=0, column=1)

        return drop_target

    def _build_list_toolbar(
        self,
        parent: ctk.CTkFrame,
        row: int,
        *,
        count_attr: str,
        on_refresh: Callable[[], None],
        on_delete: Callable[[], None],
        on_download: Callable[[], None],
        extra_label: str = "",
        on_extra: Callable[[], None] | None = None,
    ) -> None:
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.grid(row=row, column=0, columnspan=2, padx=24, pady=(0, 4), sticky="w")
        count_label = ctk.CTkLabel(toolbar, text="", text_color="gray70")
        count_label.pack(side="left", padx=(0, 12))
        setattr(self, count_attr, count_label)
        if on_extra and extra_label:
            ctk.CTkButton(toolbar, text=extra_label, command=on_extra).pack(side="left", padx=4)
        ctk.CTkButton(toolbar, text="選択をダウンロード", command=on_download).pack(side="left", padx=4)
        ctk.CTkButton(toolbar, text="選択を削除", fg_color="#8b1e1e", command=on_delete).pack(side="left", padx=4)
        ctk.CTkButton(toolbar, text="一覧を更新", command=on_refresh).pack(side="left", padx=4)

    def _bind_info_wrap(self, container: ctk.CTkFrame, labels: list[ctk.CTkLabel]) -> None:
        def on_configure(event) -> None:
            wrap = max(120, event.width - 8)
            for label in labels:
                if self._widget_alive(label):
                    label.configure(wraplength=wrap)

        container.bind("<Configure>", on_configure)

    def _build_detail_panel(
        self,
        parent: ctk.CTkFrame,
        *,
        placeholder: str,
        build_info: Callable[[ctk.CTkFrame, list[ctk.CTkLabel]], None],
    ) -> tuple[ctk.CTkFrame, ctk.CTkScrollableFrame, ctk.CTkLabel]:
        parent.grid_rowconfigure(0, weight=0)
        parent.grid_rowconfigure(1, weight=1, minsize=PREVIEW_AREA_MINSIZE)
        parent.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(parent, text="詳細", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, padx=12, pady=(12, 8), sticky="w"
        )

        detail_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent", label_text="")
        detail_scroll.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")
        detail_scroll.grid_columnconfigure(0, weight=1)

        preview_body = ctk.CTkFrame(
            detail_scroll,
            fg_color=PANEL_FG,
            border_width=2,
            border_color=PANEL_BORDER,
            corner_radius=10,
        )
        preview_body.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            preview_body,
            text="プレビュー",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="gray80",
        ).pack(anchor="w", padx=12, pady=(10, 4))

        image_label = ctk.CTkLabel(preview_body, text=placeholder, anchor="n", justify="center")
        image_label.pack(anchor="n", padx=12, pady=(0, 12))

        info_pane = ctk.CTkFrame(
            detail_scroll,
            fg_color=PANEL_FG,
            border_width=2,
            border_color=PANEL_BORDER,
            corner_radius=10,
        )
        info_pane.pack(fill="x")
        info_pane.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            info_pane,
            text="情報",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="gray80",
        ).grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 6), sticky="w")

        info_content = ctk.CTkFrame(info_pane, fg_color="transparent")
        info_content.grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="ew")
        info_content.grid_columnconfigure(1, weight=1)
        wrap_labels: list[ctk.CTkLabel] = []
        build_info(info_content, wrap_labels)
        self._bind_info_wrap(info_content, wrap_labels)

        return preview_body, detail_scroll, image_label

    def _get_preview_max_width(self, detail_scroll: ctk.CTkScrollableFrame) -> int:
        detail_scroll.update_idletasks()
        width = detail_scroll.winfo_width()
        if width <= 1:
            return PREVIEW_FALLBACK_WIDTH
        return max(280, width - 40)

    def _build_gallery_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.content)
        self._build_page_header(page, "PhotoGallery", PAGE_DESCRIPTIONS["gallery"], content_row=4)

        self._gallery_drop_target = self._build_upload_card(
            page,
            row=2,
            title="アップロード",
            drop_text="写真をドロップ（PNG に変換してアップロード）",
            on_drop=self._on_gallery_drop,
            on_pick=self._pick_gallery_files_to_upload,
            status_attr="gallery_upload_status_label",
        )
        self._build_list_toolbar(
            page,
            row=3,
            count_attr="gallery_status_label",
            on_refresh=self._refresh_gallery,
            on_delete=self._delete_selected_gallery,
            on_download=self._download_selected_gallery,
        )

        self.gallery_scroll = ctk.CTkScrollableFrame(page, label_text="アップロード済み Photo Gallery")
        self.gallery_scroll.grid(row=4, column=0, padx=(24, 8), pady=8, sticky="nsew")

        preview_frame = ctk.CTkFrame(page)
        preview_frame.grid(row=4, column=1, padx=(8, 24), pady=8, sticky="nsew")

        def build_gallery_info(info: ctk.CTkFrame, wrap_labels: list[ctk.CTkLabel]) -> None:
            info.grid_columnconfigure(1, weight=1)
            fields = [
                ("名前", "gallery_preview_name_label", "-"),
                ("ID", "gallery_preview_id_label", "-"),
                ("作成日時", "gallery_preview_created_label", "-"),
                ("サイズ", "gallery_preview_size_label", "-"),
            ]
            for row, (label, attr, default) in enumerate(fields):
                ctk.CTkLabel(info, text=label, text_color="gray70", anchor="w", width=72).grid(
                    row=row, column=0, sticky="nw", padx=(0, 12), pady=4
                )
                value = ctk.CTkLabel(
                    info,
                    text=default,
                    anchor="w",
                    justify="left",
                    wraplength=INFO_WRAP,
                )
                value.grid(row=row, column=1, sticky="ew", pady=4)
                setattr(self, attr, value)
                wrap_labels.append(value)

        (
            self.gallery_preview_body,
            self.gallery_preview_scroll,
            self.gallery_preview_label,
        ) = self._build_detail_panel(
            preview_frame,
            placeholder="画像を選択してください",
            build_info=build_gallery_info,
        )
        return page

    def _build_icon_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.content)
        self._build_page_header(page, "ユーザーアイコン", PAGE_DESCRIPTIONS["icon"], content_row=4)

        def build_icon_settings(settings: ctk.CTkFrame) -> None:
            self.upload_set_icon_var = tk.BooleanVar(value=True)
            ctk.CTkCheckBox(
                settings,
                text="アップロード後にプロフィールに設定",
                variable=self.upload_set_icon_var,
            ).pack(anchor="w")

        self._icon_drop_target = self._build_upload_card(
            page,
            row=2,
            title="アップロード",
            drop_text="写真をドロップ（正方形にクロップしてアップロード）",
            on_drop=self._on_icon_drop,
            on_pick=self._pick_icon_files_to_upload,
            status_attr="icon_upload_status_label",
            build_settings=build_icon_settings,
        )
        self._build_list_toolbar(
            page,
            row=3,
            count_attr="icon_status_label",
            on_refresh=self._refresh_icons,
            on_delete=self._delete_selected_icons,
            on_download=self._download_selected_icons,
            extra_label="選択をプロフィールに設定",
            on_extra=self._set_selected_icon_active,
        )

        self.icon_scroll = ctk.CTkScrollableFrame(page, label_text="アップロード済みユーザーアイコン")
        self.icon_scroll.grid(row=4, column=0, padx=(24, 8), pady=8, sticky="nsew")

        preview_frame = ctk.CTkFrame(page)
        preview_frame.grid(row=4, column=1, padx=(8, 24), pady=8, sticky="nsew")

        active_frame = ctk.CTkFrame(
            preview_frame,
            fg_color=PANEL_FG,
            border_width=2,
            border_color=PANEL_BORDER,
            corner_radius=10,
        )
        active_frame.grid(row=0, column=0, padx=12, pady=(12, 8), sticky="ew")
        ctk.CTkLabel(
            active_frame,
            text="現在のプロフィールアイコン",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="gray80",
        ).pack(anchor="w", padx=12, pady=(10, 4))
        self.active_icon_label = ctk.CTkLabel(active_frame, text="未設定", anchor="n", justify="center")
        self.active_icon_label.pack(anchor="n", padx=12, pady=(0, 12))

        detail_host = ctk.CTkFrame(preview_frame, fg_color="transparent")
        detail_host.grid(row=1, column=0, sticky="nsew")
        preview_frame.grid_rowconfigure(1, weight=1, minsize=PREVIEW_AREA_MINSIZE)
        preview_frame.grid_columnconfigure(0, weight=1)
        detail_host.grid_columnconfigure(0, weight=1)
        detail_host.grid_rowconfigure(0, weight=1)

        def build_icon_info(info: ctk.CTkFrame, wrap_labels: list[ctk.CTkLabel]) -> None:
            info.grid_columnconfigure(1, weight=1)
            fields = [
                ("名前", "icon_preview_name_label", "-"),
                ("ID", "icon_preview_id_label", "-"),
                ("作成日時", "icon_preview_created_label", "-"),
                ("サイズ", "icon_preview_size_label", "-"),
                ("状態", "icon_preview_status_label", "-"),
            ]
            for row, (label, attr, default) in enumerate(fields):
                ctk.CTkLabel(info, text=label, text_color="gray70", anchor="w", width=72).grid(
                    row=row, column=0, sticky="nw", padx=(0, 12), pady=4
                )
                value = ctk.CTkLabel(
                    info,
                    text=default,
                    anchor="w",
                    justify="left",
                    wraplength=INFO_WRAP,
                )
                value.grid(row=row, column=1, sticky="ew", pady=4)
                setattr(self, attr, value)
                wrap_labels.append(value)

            self.icon_apply_btn = ctk.CTkButton(
                info,
                text="プロフィールに設定",
                command=self._set_preview_icon_active,
                state="disabled",
            )
            self.icon_apply_btn.grid(row=len(fields), column=0, columnspan=2, sticky="ew", pady=(10, 0))

        (
            self.icon_preview_body,
            self.icon_preview_scroll,
            self.icon_preview_label,
        ) = self._build_detail_panel(
            detail_host,
            placeholder="アイコンを選択してください",
            build_info=build_icon_info,
        )
        return page

    def _build_print_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.content)
        self._build_page_header(page, "Print", PAGE_DESCRIPTIONS["print"], content_row=4)

        def build_print_settings(settings: ctk.CTkFrame) -> None:
            settings.grid_columnconfigure(0, weight=2)
            settings.grid_columnconfigure(1, weight=2)
            settings.grid_columnconfigure(2, weight=1)
            settings.grid_columnconfigure(3, weight=2)
            compact = {"height": 28}
            self.upload_note_entry = ctk.CTkEntry(
                settings, placeholder_text="メモ（空欄ならファイル名）", **compact
            )
            self.upload_world_entry = ctk.CTkEntry(
                settings, placeholder_text="ワールド名（例: local）", **compact
            )
            self.upload_orientation = ctk.CTkSegmentedButton(
                settings, values=list(ORIENTATION_UI.keys()), height=28
            )
            self.upload_orientation.set("横")
            self.upload_crop = ctk.CTkSegmentedButton(
                settings, values=list(CROP_UI.keys()), height=28
            )
            self.upload_crop.set("クロップ")
            widgets = [
                self.upload_note_entry,
                self.upload_world_entry,
                self.upload_orientation,
                self.upload_crop,
            ]
            for col, widget in enumerate(widgets):
                widget.grid(row=0, column=col, padx=(0 if col == 0 else 6, 0), sticky="ew")

        self._print_drop_target = self._build_upload_card(
            page,
            row=2,
            title="アップロード",
            drop_text="写真をドロップ（リサイズ・クロップしてアップロード）",
            on_drop=self._on_print_drop,
            on_pick=self._pick_print_files_to_upload,
            status_attr="print_upload_status_label",
            build_settings=build_print_settings,
        )
        self._build_list_toolbar(
            page,
            row=3,
            count_attr="prints_status_label",
            on_refresh=self._refresh_prints,
            on_delete=self._delete_selected_prints,
            on_download=self._download_selected_prints,
        )

        self.prints_scroll = ctk.CTkScrollableFrame(page, label_text="アップロード済み Print")
        self.prints_scroll.grid(row=4, column=0, padx=(24, 8), pady=8, sticky="nsew")

        preview_frame = ctk.CTkFrame(page)
        preview_frame.grid(row=4, column=1, padx=(8, 24), pady=8, sticky="nsew")

        def build_print_info(info: ctk.CTkFrame, wrap_labels: list[ctk.CTkLabel]) -> None:
            info.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(info, text="ID", text_color="gray70", anchor="w", width=72).grid(
                row=0, column=0, sticky="nw", padx=(0, 12), pady=4
            )
            self.preview_id_label = ctk.CTkLabel(info, text="-", anchor="w", justify="left", wraplength=INFO_WRAP)
            self.preview_id_label.grid(row=0, column=1, sticky="ew", pady=4)
            wrap_labels.append(self.preview_id_label)

            ctk.CTkLabel(info, text="メモ", text_color="gray70", anchor="w", width=72).grid(
                row=1, column=0, sticky="w", padx=(0, 12), pady=4
            )
            self.preview_note_entry = ctk.CTkEntry(info, placeholder_text="Print に表示するメモ")
            self.preview_note_entry.grid(row=1, column=1, sticky="ew", pady=4)

            ctk.CTkLabel(info, text="ワールド", text_color="gray70", anchor="w", width=72).grid(
                row=2, column=0, sticky="w", padx=(0, 12), pady=4
            )
            self.preview_world_label = ctk.CTkLabel(
                info,
                text="-",
                anchor="w",
                justify="left",
                wraplength=INFO_WRAP,
                text_color="gray70",
            )
            self.preview_world_label.grid(row=2, column=1, sticky="ew", pady=4)
            wrap_labels.append(self.preview_world_label)

            meta_fields = [
                ("作者", "preview_author_label"),
                ("撮影日時", "preview_timestamp_label"),
                ("作成日時", "preview_created_label"),
            ]
            for row, (label, attr) in enumerate(meta_fields, start=3):
                ctk.CTkLabel(info, text=label, text_color="gray70", anchor="w", width=72).grid(
                    row=row, column=0, sticky="nw", padx=(0, 12), pady=4
                )
                value = ctk.CTkLabel(info, text="-", anchor="w", justify="left", wraplength=INFO_WRAP)
                value.grid(row=row, column=1, sticky="ew", pady=4)
                setattr(self, attr, value)
                wrap_labels.append(value)

            self.preview_save_btn = ctk.CTkButton(
                info,
                text="変更を保存",
                command=self._save_print_edits,
                state="disabled",
            )
            self.preview_save_btn.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        (
            self.print_preview_body,
            self.print_preview_scroll,
            self.preview_label,
        ) = self._build_detail_panel(
            preview_frame,
            placeholder="Print を選択してください",
            build_info=build_print_info,
        )
        return page

    def _setup_drop_target(self, target: tk.Label, handler: Callable) -> None:
        if not DND_AVAILABLE:
            return
        target.drop_target_register(DND_FILES)
        target.dnd_bind("<<Drop>>", handler)

    def _on_gallery_drop(self, event) -> None:
        paths = self._parse_dropped_paths(event.data)
        if paths:
            self._upload_gallery_images(paths)

    def _on_print_drop(self, event) -> None:
        paths = self._parse_dropped_paths(event.data)
        if paths:
            self._upload_print_images(paths)

    def _on_icon_drop(self, event) -> None:
        paths = self._parse_dropped_paths(event.data)
        if paths:
            self._upload_icon_images(paths)

    def _parse_dropped_paths(self, data: str) -> list[Path]:
        data = data.strip()
        raw_paths = re.findall(r"\{([^}]+)\}", data) if "{" in data else data.split()
        result: list[Path] = []
        for raw in raw_paths:
            path = Path(raw)
            if path.suffix.lower() in IMAGE_EXTENSIONS and path.exists():
                result.append(path)
        return result

    def _pick_gallery_files_to_upload(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=IMAGE_FILETYPES)
        if paths:
            self._upload_gallery_images([Path(p) for p in paths])

    def _pick_print_files_to_upload(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=IMAGE_FILETYPES)
        if paths:
            self._upload_print_images([Path(p) for p in paths])

    def _pick_icon_files_to_upload(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=IMAGE_FILETYPES)
        if paths:
            self._upload_icon_images([Path(p) for p in paths])

    def _load_settings_into_ui(self) -> None:
        self.login_entries["username"].insert(0, self.settings.username)
        self.login_entries["contact_email"].insert(0, self.settings.contact_email)
        self.upload_note_entry.insert(0, self.settings.default_note)
        self.upload_world_entry.insert(0, self.settings.default_world_name or "local")
        self.upload_orientation.set(
            ORIENTATION_UI_REV.get(self.settings.default_orientation, "横")
        )
        self.upload_crop.set(CROP_UI_REV.get(self.settings.default_crop_mode, "クロップ"))
        if hasattr(self, "upload_set_icon_var"):
            self.upload_set_icon_var.set(self.settings.default_set_icon_on_upload)
        self._update_status()

    def _save_upload_settings(self) -> None:
        self.settings.default_note = self.upload_note_entry.get().strip()
        self.settings.default_world_name = self.upload_world_entry.get().strip() or "local"
        self.settings.default_orientation = ORIENTATION_UI.get(self.upload_orientation.get(), "landscape")
        self.settings.default_crop_mode = CROP_UI.get(self.upload_crop.get(), "cover")
        self.settings.save()

    def _collect_upload_settings(self) -> tuple[str, str, str, str]:
        self._save_upload_settings()
        common_note = self.upload_note_entry.get().strip()
        world_name = self.upload_world_entry.get().strip() or "local"
        orientation = ORIENTATION_UI.get(self.upload_orientation.get(), "landscape")
        crop_mode = CROP_UI.get(self.upload_crop.get(), "cover")
        return common_note, world_name, orientation, crop_mode

    def _set_gallery_upload_status(self, text: str) -> None:
        if hasattr(self, "gallery_upload_status_label"):
            self.gallery_upload_status_label.configure(text=text)

    def _set_print_upload_status(self, text: str) -> None:
        if hasattr(self, "print_upload_status_label"):
            self.print_upload_status_label.configure(text=text)

    def _set_icon_upload_status(self, text: str) -> None:
        if hasattr(self, "icon_upload_status_label"):
            self.icon_upload_status_label.configure(text=text)

    def _save_icon_upload_settings(self) -> None:
        if hasattr(self, "upload_set_icon_var"):
            self.settings.default_set_icon_on_upload = bool(self.upload_set_icon_var.get())
            self.settings.save()

    def _upload_gallery_images(self, paths: list[Path]) -> None:
        if self._upload_busy:
            messagebox.showinfo("処理中", "アップロード処理が完了するまでお待ちください。")
            return
        if not self.client.is_logged_in:
            messagebox.showwarning("未ログイン", "先にログインしてください。")
            self._show_page("login")
            return
        if not paths:
            return

        temp_dir = app_data_dir() / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        def worker() -> tuple[int, list[str]]:
            uploaded = 0
            errors: list[str] = []
            total = len(paths)
            for idx, src in enumerate(paths, start=1):
                try:
                    safe_id = hashlib.md5(src.name.encode("utf-8")).hexdigest()[:12]
                    upload_path = temp_dir / f"{safe_id}_gallery.png"
                    prepare_gallery_image(src, upload_path)
                    self.client.upload_gallery_image(upload_path)
                    uploaded += 1
                except Exception as exc:
                    errors.append(f"{src.name}: {exc}")
                self.after(0, lambda v=idx / total: self._set_progress(v))
            return uploaded, errors

        self._upload_busy = True
        self._set_gallery_upload_status(f"{len(paths)} 件を処理中...")

        def on_success(result: tuple[int, list[str]]) -> None:
            self._upload_busy = False
            uploaded, errors = result
            if errors:
                self._set_gallery_upload_status(f"完了: {uploaded} 件成功 / {len(errors)} 件失敗")
                messagebox.showwarning(
                    "一部失敗",
                    f"成功: {uploaded} 件\n失敗: {len(errors)} 件\n\n" + "\n".join(errors[:5]),
                )
            else:
                self._set_gallery_upload_status(f"{uploaded} 件をアップロードしました")
            self._refresh_gallery()

        def on_finish() -> None:
            self._upload_busy = False

        self._run_async(worker, on_success=on_success, on_finish=on_finish)

    def _upload_print_images(self, paths: list[Path]) -> None:
        if self._upload_busy:
            messagebox.showinfo("処理中", "アップロード処理が完了するまでお待ちください。")
            return
        if not self.client.is_logged_in:
            messagebox.showwarning("未ログイン", "先にログインしてください。")
            self._show_page("login")
            return
        if not paths:
            return

        common_note, world_name, orientation, crop_mode = self._collect_upload_settings()
        temp_dir = app_data_dir() / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        def worker() -> tuple[int, list[str]]:
            uploaded = 0
            errors: list[str] = []
            total = len(paths)
            for idx, src in enumerate(paths, start=1):
                note = common_note or src.stem
                try:
                    safe_id = hashlib.md5(src.name.encode("utf-8")).hexdigest()[:12]
                    upload_path = temp_dir / f"{safe_id}_print.png"
                    upload_path, _used_orientation = prepare_print_for_upload(
                        src,
                        upload_path,
                        orientation=orientation,
                        crop_mode=crop_mode,
                    )
                    self.client.upload_print(
                        image_path=upload_path,
                        note=note,
                        world_name=world_name,
                    )
                    uploaded += 1
                except Exception as exc:
                    errors.append(f"{src.name}: {exc}")
                self.after(0, lambda v=idx / total: self._set_progress(v))
            return uploaded, errors

        self._upload_busy = True
        self._set_print_upload_status(f"{len(paths)} 件を処理中...")

        def on_success(result: tuple[int, list[str]]) -> None:
            self._upload_busy = False
            uploaded, errors = result
            if errors:
                self._set_print_upload_status(f"完了: {uploaded} 件成功 / {len(errors)} 件失敗")
                messagebox.showwarning(
                    "一部失敗",
                    f"成功: {uploaded} 件\n失敗: {len(errors)} 件\n\n" + "\n".join(errors[:5]),
                )
            else:
                self._set_print_upload_status(f"{uploaded} 件をアップロードしました")
            self._refresh_prints()

        def on_finish() -> None:
            self._upload_busy = False

        self._run_async(worker, on_success=on_success, on_finish=on_finish)

    def _upload_icon_images(self, paths: list[Path]) -> None:
        if self._upload_busy:
            messagebox.showinfo("処理中", "アップロード処理が完了するまでお待ちください。")
            return
        if not self.client.is_logged_in:
            messagebox.showwarning("未ログイン", "先にログインしてください。")
            self._show_page("login")
            return
        if not paths:
            return

        self._save_icon_upload_settings()
        set_on_upload = bool(self.upload_set_icon_var.get())
        temp_dir = app_data_dir() / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        def worker() -> tuple[int, list[str]]:
            uploaded = 0
            errors: list[str] = []
            total = len(paths)
            for idx, src in enumerate(paths, start=1):
                try:
                    safe_id = hashlib.md5(src.name.encode("utf-8")).hexdigest()[:12]
                    upload_path = temp_dir / f"{safe_id}_icon.png"
                    prepare_icon_image(src, upload_path)
                    icon = self.client.upload_user_icon(upload_path)
                    if set_on_upload and icon.profile_url:
                        self.client.set_active_user_icon(icon.profile_url)
                    uploaded += 1
                except Exception as exc:
                    errors.append(f"{src.name}: {exc}")
                self.after(0, lambda v=idx / total: self._set_progress(v))
            return uploaded, errors

        self._upload_busy = True
        self._set_icon_upload_status(f"{len(paths)} 件を処理中...")

        def on_success(result: tuple[int, list[str]]) -> None:
            self._upload_busy = False
            uploaded, errors = result
            if errors:
                self._set_icon_upload_status(f"完了: {uploaded} 件成功 / {len(errors)} 件失敗")
                messagebox.showwarning(
                    "一部失敗",
                    f"成功: {uploaded} 件\n失敗: {len(errors)} 件\n\n" + "\n".join(errors[:5]),
                )
            else:
                suffix = "（プロフィールに設定済み）" if set_on_upload else ""
                self._set_icon_upload_status(f"{uploaded} 件をアップロードしました{suffix}")
            self._refresh_icons()

        def on_finish() -> None:
            self._upload_busy = False

        self._run_async(worker, on_success=on_success, on_finish=on_finish)

    def _update_status(self) -> None:
        if self.client.is_logged_in:
            self.status_label.configure(text=f"ログイン中\n{self.settings.display_name}")
        else:
            self.status_label.configure(text="未ログイン")

    def _try_restore_session(self) -> None:
        if not self.settings.auth_cookie or not self.settings.contact_email.strip():
            return
        self._run_async(self._restore_session_worker, on_success=lambda _: self._show_page("gallery", auto_load=True), show_progress=False)

    def _login(self) -> None:
        username = self.login_entries["username"].get().strip()
        password = self.login_entries["password"].get()
        if not username or not password:
            messagebox.showwarning("入力不足", "ユーザー名とパスワードを入力してください。")
            return
        contact_email = self.login_entries["contact_email"].get().strip()
        if not contact_email or "@" not in contact_email:
            messagebox.showwarning("入力不足", "有効な連絡先メールを入力してください。")
            return
        self.settings.contact_email = contact_email
        self.settings.save()

        def worker() -> str:
            return self.client.login(
                username=username,
                password=password,
                two_factor_code=self.login_entries["two_factor"].get().strip() or None,
                email_two_factor_code=self.login_entries["email_two_factor"].get().strip() or None,
            )

        def on_success(name: str) -> None:
            messagebox.showinfo("ログイン成功", f"{name} としてログインしました。")
            self._show_page("gallery", auto_load=True)

        self._run_async(worker, on_success=on_success)

    def _restore_session(self) -> None:
        contact_email = self.login_entries["contact_email"].get().strip()
        if not contact_email or "@" not in contact_email:
            messagebox.showwarning("入力不足", "セッション復元にも連絡先メールが必要です。")
            return
        self.settings.contact_email = contact_email
        self.settings.save()

        def on_success(name: str) -> None:
            messagebox.showinfo("復元成功", f"{name} のセッションを復元しました。")
            self._show_page("gallery", auto_load=True)

        self._run_async(self._restore_session_worker, on_success=on_success)

    def _restore_session_worker(self) -> str:
        name = self.client.restore_session()
        self.after(0, self._update_status)
        return name

    def _logout(self) -> None:
        self.client.logout()
        self._update_status()
        self._show_page("login")
        messagebox.showinfo("ログアウト", "ログアウトしました。")

    def _format_bytes(self, size: int) -> str:
        if size <= 0:
            return "-"
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    def _refresh_gallery(self) -> None:
        if not self.client.is_logged_in:
            return
        self.gallery_status_label.configure(text="読み込み中...")
        self._run_async(lambda: self.client.list_gallery_photos(), on_success=self._render_gallery_list)

    def _refresh_icons(self) -> None:
        if not self.client.is_logged_in:
            return
        self.icon_status_label.configure(text="読み込み中...")

        def worker() -> tuple[list[IconInfo], str]:
            icons = self.client.list_user_icons()
            active_url = self.client.get_active_user_icon_url()
            return icons, active_url

        def on_success(result: tuple[list[IconInfo], str]) -> None:
            icons, active_url = result
            self._active_user_icon_url = active_url
            self._render_icon_list(icons)
            self._show_active_icon_preview(active_url)

        self._run_async(worker, on_success=on_success)

    def _normalize_icon_url(self, url: str) -> str:
        normalized = url.strip().rstrip("/")
        if normalized.endswith("/file"):
            normalized = normalized[:-5]
        return normalized

    def _icon_display_url(self, profile_url: str) -> str:
        url = profile_url.strip()
        if not url:
            return ""
        if url.endswith("/file"):
            return url
        return f"{url}/file"

    def _is_active_icon(self, item: IconInfo) -> bool:
        if not self._active_user_icon_url:
            return False
        return self._normalize_icon_url(item.profile_url) == self._normalize_icon_url(self._active_user_icon_url)

    def _show_active_icon_preview(self, profile_url: str) -> None:
        if not profile_url:
            self.active_icon_label.configure(image=None, text="未設定")
            return

        display_url = self._icon_display_url(profile_url)
        cache_name = f"active_icon_{hashlib.md5(profile_url.encode('utf-8')).hexdigest()[:12]}.png"

        def worker() -> ctk.CTkImage | None:
            return self._load_item_image(display_url, cache_name, (96, 96))

        def on_success(photo: ctk.CTkImage | None) -> None:
            if not self._widget_alive(self.active_icon_label):
                return
            if photo is None:
                self.active_icon_label.configure(image=None, text="読み込み失敗")
                return
            self._active_icon_photo = photo
            self.active_icon_label.configure(image=photo, text="")

        self._run_async(worker, on_success=on_success, show_progress=False)

    def _render_icon_list(self, items: list[IconInfo]) -> None:
        self._icon_list_gen += 1
        list_gen = self._icon_list_gen
        self._icon_rows = items
        self._selected_icon_ids.clear()
        self._icon_thumb_cache.clear()
        for child in self.icon_scroll.winfo_children():
            child.destroy()

        self.icon_status_label.configure(text=f"{len(items)} 件")

        if not items:
            self._clear_icon_preview()
            ctk.CTkLabel(
                self.icon_scroll,
                text="まだユーザーアイコンがありません。\n上のエリアに写真をドロップしてアップロードしてください。",
                justify="left",
            ).pack(fill="x", padx=8, pady=8)
            return

        for item in items:
            row = ctk.CTkFrame(self.icon_scroll)
            row.pack(fill="x", padx=4, pady=4)

            var = tk.BooleanVar(value=False)

            def toggle(iid: str = item.id, v: tk.BooleanVar = var) -> None:
                if v.get():
                    self._selected_icon_ids.add(iid)
                else:
                    self._selected_icon_ids.discard(iid)

            ctk.CTkCheckBox(row, text="", variable=var, width=24, command=toggle).pack(side="left", padx=4)

            thumb_label = ctk.CTkLabel(row, text="...")
            thumb_label.pack(side="left", padx=4)
            self._load_icon_thumbnail_async(item, thumb_label, list_gen)

            label = item.name or "(名前なし)"
            status = " [設定中]" if self._is_active_icon(item) else ""
            text = f"{label}{status}\n{item.id}"
            ctk.CTkButton(
                row,
                text=text,
                anchor="w",
                fg_color="transparent",
                hover_color=("gray85", "gray20"),
                command=lambda icon=item: self._show_icon_preview(icon),
            ).pack(side="left", fill="x", expand=True, padx=4)

    def _load_icon_thumbnail_async(self, item: IconInfo, label: ctk.CTkLabel, list_gen: int) -> None:
        if not item.image_url:
            if self._widget_alive(label):
                label.configure(text="NoImg")
            return

        def worker() -> ctk.CTkImage | None:
            return self._load_item_image(item.image_url, f"icon_{item.id}.png", (72, 72))

        def on_success(photo: ctk.CTkImage | None) -> None:
            if list_gen != self._icon_list_gen or not self._widget_alive(label):
                return
            if photo is None:
                label.configure(text="読込失敗")
                return
            self._icon_thumb_cache[item.id] = photo
            label.configure(image=photo, text="")

        self._run_async(worker, on_success=on_success, show_progress=False)

    def _clear_icon_preview(self) -> None:
        self._selected_icon = None
        self.icon_preview_label.configure(image=None, text="アイコンを選択してください")
        self.icon_preview_id_label.configure(text="-")
        self.icon_preview_name_label.configure(text="-")
        self.icon_preview_created_label.configure(text="-")
        self.icon_preview_size_label.configure(text="-")
        self.icon_preview_status_label.configure(text="-")
        self.icon_apply_btn.configure(state="disabled")

    def _show_icon_preview(self, item: IconInfo) -> None:
        self._selected_icon = item
        self.icon_preview_id_label.configure(text=item.id)
        self.icon_preview_name_label.configure(text=item.name or "-")
        self.icon_preview_created_label.configure(text=item.created_at or "-")
        self.icon_preview_size_label.configure(text=self._format_bytes(item.size_bytes))
        if self._is_active_icon(item):
            self.icon_preview_status_label.configure(text="プロフィールに設定中")
            self.icon_apply_btn.configure(state="disabled")
        else:
            self.icon_preview_status_label.configure(text="-")
            self.icon_apply_btn.configure(state="normal")

        if not item.image_url:
            self.icon_preview_label.configure(image=None, text="画像URLがありません")
            return

        max_width = self._get_preview_max_width(self.icon_preview_scroll)
        preview_item_id = item.id

        def worker() -> ctk.CTkImage | None:
            return self._load_preview_photo(item.image_url, f"icon_{item.id}_full.png", max_width)

        def on_success(photo: ctk.CTkImage | None) -> None:
            if self._selected_icon is None or self._selected_icon.id != preview_item_id:
                return
            if not self._widget_alive(self.icon_preview_label):
                return
            if photo is None:
                self.icon_preview_label.configure(image=None, text="画像の読み込みに失敗しました")
                return
            self._icon_preview_photo = photo
            self.icon_preview_label.configure(image=photo, text="")
            self._reset_preview_scroll(self.icon_preview_scroll)

        self._run_async(worker, on_success=on_success, show_progress=False)

    def _resolve_icon_for_apply(self) -> IconInfo | None:
        if len(self._selected_icon_ids) == 1:
            icon_id = next(iter(self._selected_icon_ids))
            for item in self._icon_rows:
                if item.id == icon_id:
                    return item
        if self._selected_icon is not None:
            return self._selected_icon
        return None

    def _apply_icon_to_profile(self, item: IconInfo) -> None:
        if not item.profile_url:
            messagebox.showwarning("設定不可", "このアイコンの URL を取得できません。")
            return

        def worker() -> str:
            return self.client.set_active_user_icon(item.profile_url)

        def on_success(active_url: str) -> None:
            self._active_user_icon_url = active_url
            messagebox.showinfo("設定完了", "プロフィールアイコンを更新しました。")
            self._refresh_icons()
            self._show_icon_preview(item)

        self._run_async(worker, on_success=on_success)

    def _set_preview_icon_active(self) -> None:
        if not self._selected_icon:
            return
        self._apply_icon_to_profile(self._selected_icon)

    def _set_selected_icon_active(self) -> None:
        item = self._resolve_icon_for_apply()
        if item is None:
            messagebox.showwarning("未選択", "プロフィールに設定するアイコンを1つ選択してください。")
            return
        if len(self._selected_icon_ids) > 1:
            messagebox.showwarning("選択エラー", "一度に設定できるのは1つだけです。")
            return
        self._apply_icon_to_profile(item)

    def _delete_selected_icons(self) -> None:
        if not self._selected_icon_ids:
            messagebox.showwarning("未選択", "削除するアイコンを選択してください。")
            return
        if not messagebox.askyesno("確認", f"{len(self._selected_icon_ids)} 件を削除しますか？"):
            return
        ids = list(self._selected_icon_ids)

        def worker() -> int:
            total = len(ids)
            for idx, file_id in enumerate(ids, start=1):
                self.client.delete_user_icon(file_id)
                self.after(0, lambda v=idx / total: self._set_progress(v))
            return total

        def on_delete_success(count: int) -> None:
            messagebox.showinfo("削除完了", f"{count} 件を削除しました。")
            self._refresh_icons()

        self._run_async(worker, on_success=on_delete_success)

    def _download_selected_icons(self) -> None:
        if not self._selected_icon_ids:
            messagebox.showwarning("未選択", "ダウンロードするアイコンを選択してください。")
            return
        output_dir = filedialog.askdirectory()
        if not output_dir:
            return
        selected = [icon for icon in self._icon_rows if icon.id in self._selected_icon_ids]

        def worker() -> int:
            total = len(selected)
            for idx, item in enumerate(selected, start=1):
                if item.image_url:
                    name = item.name or item.id
                    self.client.download_image(item.image_url, Path(output_dir) / f"{name}.png")
                self.after(0, lambda v=idx / total: self._set_progress(v))
            return total

        self._run_async(worker, on_success=lambda count: messagebox.showinfo("ダウンロード完了", f"{count} 件を保存しました。"))

    def _widget_alive(self, widget: tk.Misc) -> bool:
        try:
            return bool(widget.winfo_exists())
        except Exception:
            return False

    def _bytes_to_ctk_image(
        self,
        data: bytes,
        *,
        thumb_size: tuple[int, int] | None = None,
        max_width: int | None = None,
    ) -> ctk.CTkImage | None:
        try:
            with Image.open(io.BytesIO(data)) as img:
                if max_width is not None and img.width > max_width:
                    ratio = max_width / img.width
                    img = img.resize((max_width, max(1, int(img.height * ratio))), Image.Resampling.LANCZOS)
                elif thumb_size is not None:
                    img = img.copy()
                    img.thumbnail(thumb_size, Image.Resampling.LANCZOS)
                else:
                    img = img.copy()
                pil = img
            return ctk.CTkImage(light_image=pil, dark_image=pil, size=(pil.width, pil.height))
        except Exception:
            return None

    def _render_gallery_list(self, items: list[GalleryInfo]) -> None:
        self._gallery_list_gen += 1
        list_gen = self._gallery_list_gen
        self._gallery_rows = items
        self._selected_gallery_ids.clear()
        self._gallery_thumb_cache.clear()
        for child in self.gallery_scroll.winfo_children():
            child.destroy()

        self.gallery_status_label.configure(text=f"{len(items)} 件")

        if not items:
            self._clear_gallery_preview()
            ctk.CTkLabel(
                self.gallery_scroll,
                text="まだ Photo Gallery の画像がありません。\n上のエリアに写真をドロップしてアップロードしてください。",
                justify="left",
            ).pack(fill="x", padx=8, pady=8)
            return

        for item in items:
            row = ctk.CTkFrame(self.gallery_scroll)
            row.pack(fill="x", padx=4, pady=4)

            var = tk.BooleanVar(value=False)

            def toggle(gid: str = item.id, v: tk.BooleanVar = var) -> None:
                if v.get():
                    self._selected_gallery_ids.add(gid)
                else:
                    self._selected_gallery_ids.discard(gid)

            ctk.CTkCheckBox(row, text="", variable=var, width=24, command=toggle).pack(side="left", padx=4)

            thumb_label = ctk.CTkLabel(row, text="...")
            thumb_label.pack(side="left", padx=4)
            self._load_gallery_thumbnail_async(item, thumb_label, list_gen)

            label = item.name or "(名前なし)"
            text = f"{label}\n{item.id}"
            ctk.CTkButton(
                row,
                text=text,
                anchor="w",
                fg_color="transparent",
                hover_color=("gray85", "gray20"),
                command=lambda g=item: self._show_gallery_preview(g),
            ).pack(side="left", fill="x", expand=True, padx=4)

    def _cache_lock_for(self, cache_name: str) -> threading.Lock:
        with self._cache_locks_guard:
            if cache_name not in self._cache_locks:
                self._cache_locks[cache_name] = threading.Lock()
            return self._cache_locks[cache_name]

    def _reset_preview_scroll(self, scroll_frame: ctk.CTkScrollableFrame) -> None:
        try:
            scroll_frame._parent_canvas.yview_moveto(0)
            scroll_frame._parent_canvas.xview_moveto(0)
        except Exception:
            pass

    def _load_preview_photo(
        self, image_url: str, cache_name: str, max_width: int
    ) -> ctk.CTkImage | None:
        if not image_url:
            return None
        cache_dir = app_data_dir() / "cache"
        cache_dir.mkdir(exist_ok=True)
        cache_path = cache_dir / cache_name
        with self._cache_lock_for(cache_name):
            try:
                data = self._read_cached_image_bytes(cache_path, image_url)
                if data is None:
                    return None
                return self._bytes_to_ctk_image(data, max_width=max_width)
            except Exception:
                return None

    def _read_cached_image_bytes(self, cache_path: Path, image_url: str) -> bytes | None:
        if cache_path.exists():
            try:
                data = cache_path.read_bytes()
                if self.client._is_image_bytes(data):
                    return data
            except OSError:
                pass

        self.client.download_image(image_url, cache_path)
        data = cache_path.read_bytes()
        return data if self.client._is_image_bytes(data) else None

    def _load_item_image(
        self, image_url: str, cache_name: str, size: tuple[int, int]
    ) -> ctk.CTkImage | None:
        if not image_url:
            return None
        cache_dir = app_data_dir() / "cache"
        cache_dir.mkdir(exist_ok=True)
        cache_path = cache_dir / cache_name
        with self._cache_lock_for(cache_name):
            try:
                data = self._read_cached_image_bytes(cache_path, image_url)
                if data is None:
                    return None
                return self._bytes_to_ctk_image(data, thumb_size=size)
            except Exception:
                return None

    def _load_gallery_thumbnail_async(
        self, item: GalleryInfo, label: ctk.CTkLabel, list_gen: int
    ) -> None:
        if not item.image_url:
            if self._widget_alive(label):
                label.configure(text="NoImg")
            return

        def worker() -> ctk.CTkImage | None:
            return self._load_item_image(item.image_url, f"gallery_{item.id}.png", (72, 72))

        def on_success(photo: ctk.CTkImage | None) -> None:
            if list_gen != self._gallery_list_gen or not self._widget_alive(label):
                return
            if photo is None:
                label.configure(text="読込失敗")
                return
            self._gallery_thumb_cache[item.id] = photo
            label.configure(image=photo, text="")

        self._run_async(worker, on_success=on_success, show_progress=False)

    def _clear_gallery_preview(self) -> None:
        self._selected_gallery = None
        self.gallery_preview_label.configure(image=None, text="画像を選択してください")
        self.gallery_preview_id_label.configure(text="-")
        self.gallery_preview_name_label.configure(text="-")
        self.gallery_preview_created_label.configure(text="-")
        self.gallery_preview_size_label.configure(text="-")

    def _show_gallery_preview(self, item: GalleryInfo) -> None:
        self._selected_gallery = item
        self.gallery_preview_id_label.configure(text=item.id)
        self.gallery_preview_name_label.configure(text=item.name or "-")
        self.gallery_preview_created_label.configure(text=item.created_at or "-")
        self.gallery_preview_size_label.configure(text=self._format_bytes(item.size_bytes))

        if not item.image_url:
            self.gallery_preview_label.configure(image=None, text="画像URLがありません")
            return

        max_width = self._get_preview_max_width(self.gallery_preview_scroll)

        preview_item_id = item.id

        def worker() -> ctk.CTkImage | None:
            return self._load_preview_photo(item.image_url, f"gallery_{item.id}_full.png", max_width)

        def on_success(photo: ctk.CTkImage | None) -> None:
            if self._selected_gallery is None or self._selected_gallery.id != preview_item_id:
                return
            if not self._widget_alive(self.gallery_preview_label):
                return
            if photo is None:
                self.gallery_preview_label.configure(image=None, text="画像の読み込みに失敗しました")
                return
            self._gallery_preview_photo = photo
            self.gallery_preview_label.configure(image=photo, text="")
            self._reset_preview_scroll(self.gallery_preview_scroll)

        self._run_async(worker, on_success=on_success, show_progress=False)

    def _delete_selected_gallery(self) -> None:
        if not self._selected_gallery_ids:
            messagebox.showwarning("未選択", "削除する画像を選択してください。")
            return
        if not messagebox.askyesno("確認", f"{len(self._selected_gallery_ids)} 件を削除しますか？"):
            return
        ids = list(self._selected_gallery_ids)

        def worker() -> int:
            total = len(ids)
            for idx, file_id in enumerate(ids, start=1):
                self.client.delete_gallery_photo(file_id)
                self.after(0, lambda v=idx / total: self._set_progress(v))
            return total

        def on_delete_success(count: int) -> None:
            messagebox.showinfo("削除完了", f"{count} 件を削除しました。")
            self._refresh_gallery()

        self._run_async(worker, on_success=on_delete_success)

    def _download_selected_gallery(self) -> None:
        if not self._selected_gallery_ids:
            messagebox.showwarning("未選択", "ダウンロードする画像を選択してください。")
            return
        output_dir = filedialog.askdirectory()
        if not output_dir:
            return
        selected = [g for g in self._gallery_rows if g.id in self._selected_gallery_ids]

        def worker() -> int:
            total = len(selected)
            for idx, item in enumerate(selected, start=1):
                if item.image_url:
                    name = item.name or item.id
                    self.client.download_image(item.image_url, Path(output_dir) / f"{name}.png")
                self.after(0, lambda v=idx / total: self._set_progress(v))
            return total

        self._run_async(worker, on_success=lambda count: messagebox.showinfo("ダウンロード完了", f"{count} 件を保存しました。"))

    def _refresh_prints(self) -> None:
        if not self.client.is_logged_in:
            return
        self.prints_status_label.configure(text="読み込み中...")
        self._run_async(lambda: self.client.list_prints(), on_success=self._render_print_list)

    def _render_print_list(self, prints: list[PrintInfo]) -> None:
        self._print_list_gen += 1
        list_gen = self._print_list_gen
        self._print_rows = prints
        self._selected_print_ids.clear()
        self._thumb_cache.clear()
        for child in self.prints_scroll.winfo_children():
            child.destroy()

        self.prints_status_label.configure(text=f"{len(prints)} 件")

        if not prints:
            self._clear_print_preview()
            ctk.CTkLabel(
                self.prints_scroll,
                text="まだ Print がありません。\n上のエリアに写真をドロップしてアップロードしてください。",
                justify="left",
            ).pack(fill="x", padx=8, pady=8)
            return

        for item in prints:
            row = ctk.CTkFrame(self.prints_scroll)
            row.pack(fill="x", padx=4, pady=4)

            var = tk.BooleanVar(value=False)

            def toggle(pid: str = item.id, v: tk.BooleanVar = var) -> None:
                if v.get():
                    self._selected_print_ids.add(pid)
                else:
                    self._selected_print_ids.discard(pid)

            ctk.CTkCheckBox(row, text="", variable=var, width=24, command=toggle).pack(side="left", padx=4)

            thumb_label = ctk.CTkLabel(row, text="...")
            thumb_label.pack(side="left", padx=4)
            self._load_thumbnail_async(item, thumb_label, list_gen)

            text = f"{item.note or '(メモなし)'}\n{item.id}"
            ctk.CTkButton(
                row,
                text=text,
                anchor="w",
                fg_color="transparent",
                hover_color=("gray85", "gray20"),
                command=lambda p=item: self._show_print_preview(p),
            ).pack(side="left", fill="x", expand=True, padx=4)

    def _load_thumbnail_async(self, item: PrintInfo, label: ctk.CTkLabel, list_gen: int) -> None:
        if not item.image_url:
            if self._widget_alive(label):
                label.configure(text="NoImg")
            return

        def worker() -> ctk.CTkImage | None:
            return self._load_item_image(item.image_url, f"{item.id}.png", (72, 72))

        def on_success(photo: ctk.CTkImage | None) -> None:
            if list_gen != self._print_list_gen or not self._widget_alive(label):
                return
            if photo is None:
                label.configure(text="読込失敗")
                return
            self._thumb_cache[item.id] = photo
            label.configure(image=photo, text="")

        self._run_async(worker, on_success=on_success, show_progress=False)

    def _clear_print_preview(self) -> None:
        self._selected_print = None
        self.preview_label.configure(image=None, text="Print を選択してください")
        self.preview_id_label.configure(text="-")
        self.preview_note_entry.delete(0, "end")
        self.preview_author_label.configure(text="-")
        self.preview_world_label.configure(text="-")
        self.preview_timestamp_label.configure(text="-")
        self.preview_created_label.configure(text="-")
        self.preview_save_btn.configure(state="disabled")

    def _show_print_preview(self, item: PrintInfo) -> None:
        self._selected_print = item
        self.preview_id_label.configure(text=item.id)
        self.preview_note_entry.delete(0, "end")
        self.preview_note_entry.insert(0, item.note or "")
        self.preview_author_label.configure(text=item.author_name or "-")
        self.preview_world_label.configure(text=item.world_name or "-")
        self.preview_timestamp_label.configure(text=item.timestamp or "-")
        self.preview_created_label.configure(text=item.created_at or "-")
        self.preview_save_btn.configure(state="normal")

        if not item.image_url:
            self.preview_label.configure(image=None, text="画像URLがありません")
            return

        max_width = self._get_preview_max_width(self.print_preview_scroll)

        preview_item_id = item.id

        def worker() -> ctk.CTkImage | None:
            return self._load_preview_photo(item.image_url, f"{item.id}_full.png", max_width)

        def on_success(photo: ctk.CTkImage | None) -> None:
            if self._selected_print is None or self._selected_print.id != preview_item_id:
                return
            if not self._widget_alive(self.preview_label):
                return
            if photo is None:
                self.preview_label.configure(image=None, text="画像の読み込みに失敗しました")
                return
            self._preview_photo = photo
            self.preview_label.configure(image=photo, text="")
            self._reset_preview_scroll(self.print_preview_scroll)

        self._run_async(worker, on_success=on_success, show_progress=False)

    def _get_print_cache_path(self, item: PrintInfo) -> Path:
        return app_data_dir() / "cache" / f"{item.id}_full.png"

    def _save_print_edits(self) -> None:
        if not self._selected_print:
            return
        if not self.client.is_logged_in:
            messagebox.showwarning("未ログイン", "先にログインしてください。")
            return

        item = self._selected_print
        new_note = self.preview_note_entry.get().strip()
        if new_note == (item.note or "").strip():
            messagebox.showinfo("変更なし", "メモに変更がありません。")
            return

        cache_path = self._get_print_cache_path(item)

        def worker() -> PrintInfo:
            if not cache_path.exists():
                if not item.image_url:
                    raise RuntimeError("画像を取得できません")
                self.client.download_image(item.image_url, cache_path)

            temp_path = app_data_dir() / "temp" / f"{item.id}_edit.png"
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(cache_path) as img:
                img.save(temp_path, format="PNG")

            updated = self.client.edit_print(item.id, temp_path, note=new_note)
            cache_path.write_bytes(temp_path.read_bytes())
            if (app_data_dir() / "cache" / f"{item.id}.png").exists():
                with Image.open(cache_path) as img:
                    thumb = img.copy()
                    thumb.thumbnail((72, 72))
                    thumb.save(app_data_dir() / "cache" / f"{item.id}.png", format="PNG")
            return updated

        def on_success(updated: PrintInfo) -> None:
            messagebox.showinfo("保存完了", "メモを更新しました。")
            for idx, row in enumerate(self._print_rows):
                if row.id == updated.id:
                    self._print_rows[idx] = updated
                    break
            self._show_print_preview(updated)
            self._refresh_prints()

        self._run_async(worker, on_success=on_success)

    def _delete_selected_prints(self) -> None:
        if not self._selected_print_ids:
            messagebox.showwarning("未選択", "削除する Print を選択してください。")
            return
        if not messagebox.askyesno("確認", f"{len(self._selected_print_ids)} 件を削除しますか？"):
            return
        ids = list(self._selected_print_ids)

        def worker() -> int:
            total = len(ids)
            for idx, print_id in enumerate(ids, start=1):
                self.client.delete_print(print_id)
                self.after(0, lambda v=idx / total: self._set_progress(v))
            return total

        def on_delete_success(count: int) -> None:
            messagebox.showinfo("削除完了", f"{count} 件を削除しました。")
            self._refresh_prints()

        self._run_async(worker, on_success=on_delete_success)

    def _download_selected_prints(self) -> None:
        if not self._selected_print_ids:
            messagebox.showwarning("未選択", "ダウンロードする Print を選択してください。")
            return
        output_dir = filedialog.askdirectory()
        if not output_dir:
            return
        selected = [p for p in self._print_rows if p.id in self._selected_print_ids]

        def worker() -> int:
            total = len(selected)
            for idx, item in enumerate(selected, start=1):
                if item.image_url:
                    self.client.download_image(item.image_url, Path(output_dir) / f"{item.id}.png")
                self.after(0, lambda v=idx / total: self._set_progress(v))
            return total

        self._run_async(worker, on_success=lambda count: messagebox.showinfo("ダウンロード完了", f"{count} 件を保存しました。"))

    def _set_progress(self, value: float) -> None:
        self.progress.set(max(0.0, min(1.0, value)))

    def _run_async(
        self,
        worker: Callable[[], object],
        on_success: Callable[[object], None] | None = None,
        on_finish: Callable[[], None] | None = None,
        show_progress: bool = True,
    ) -> None:
        if show_progress:
            self.progress.grid()
            self.progress.set(0)
            self.progress.start()

        def target() -> None:
            try:
                result = worker()
            except TwoFactorRequired as exc:
                kind = exc.kind
                self.after(0, lambda k=kind: messagebox.showwarning("2FAが必要", f"{k} の2FAコードを入力して再試行してください。"))
            except Exception as exc:
                message = str(exc)
                self.after(0, lambda msg=message: messagebox.showerror("エラー", msg))
                if self._active_page == "gallery" and hasattr(self, "gallery_status_label"):
                    self.after(0, lambda: self.gallery_status_label.configure(text="取得失敗"))
                elif self._active_page == "print" and hasattr(self, "prints_status_label"):
                    self.after(0, lambda: self.prints_status_label.configure(text="取得失敗"))
                elif self._active_page == "icon" and hasattr(self, "icon_status_label"):
                    self.after(0, lambda: self.icon_status_label.configure(text="取得失敗"))
            else:
                if on_success:
                    success_result = result
                    self.after(0, lambda r=success_result: on_success(r))
                self.after(0, self._update_status)
            finally:
                if on_finish:
                    self.after(0, on_finish)
                if show_progress:
                    self.after(0, self._stop_progress)

        threading.Thread(target=target, daemon=True).start()

    def _stop_progress(self) -> None:
        self.progress.stop()
        self.progress.set(0)
        self.progress.grid_remove()


def main() -> None:
    app = VRCMemApp()
    app.mainloop()


if __name__ == "__main__":
    main()
