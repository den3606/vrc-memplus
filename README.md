# VRCPrint Desktop

写真をドロップするだけで VRChat Print に変換・アップロードできる Windows 向けデスクトップアプリです。

![VRCPrint Desktop のスクリーンショット](./assets/image.png)

## 機能

- **ドラッグ＆ドロップ** — 管理画面に写真をドロップすると自動で VRCPrint 変換 → アップロード
- **Print 管理** — 一覧表示、プレビュー、ダウンロード、一括削除
- **ログイン** — VRChat API 認証（2FA 対応）、セッション保存

## 必要環境

- Windows 10/11
- Python 3.10+

## セットアップ

```powershell
cd C:\Users\den36\Projects\vrcprint-desktop
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 起動

```powershell
python main.py
```

## 使い方

1. **ログイン** — ユーザー名・パスワード・連絡先メールを入力してログイン
2. **管理** — 上部のエリアに写真を **ドロップ**（またはクリックして選択）
3. 自動で VRCPrint 形式に変換され、VRChat にアップロードされます
4. 下の一覧から Print の確認・削除・ダウンロードができます

### デフォルト設定

- ワールド名: `local`
- メモ: ファイル名
- 向き: 横 (landscape)
- フレーム: 白 (light)

## 注意

- Print のアップロードには **VRChat Plus (VRC+)** が必要です
- 連絡先メールは VRChat API の User-Agent 要件のため必須です
