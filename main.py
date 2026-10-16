from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QPlainTextEdit, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QCheckBox, QLineEdit
)
from PySide6.QtGui import QColor, QBrush
from PySide6.QtCore import Qt
import sys, os, json, shutil, subprocess, fnmatch
from datetime import datetime

# -------------------- ユーティリティ --------------------
def app_dir() -> str:
    """実行中アプリのディレクトリ（exe化対応）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(app_dir(), "config.json")
UNDO_FILE   = os.path.join(app_dir(), "undo.json")

def detect_windows_light_theme() -> bool:
    """Windowsの“アプリ テーマ”がライトならTrue、ダークならFalse。非WindowsはTrue。"""
    try:
        if sys.platform != "win32":
            return True
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            val, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")  # 1=Light, 0=Dark
            return bool(val)
    except Exception:
        return True

def load_config() -> dict:
    defaults = {
        "theme_mode": "System",  # System / Light / Dark
        "recursive": True,
        "date_folder": False,
        "exclude_patterns": ["*.iso", ".git", "node_modules/*"],
        "last_folder": ""
    }
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {**defaults, **data}
    except Exception:
        pass
    return defaults

def save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# -------------------- 仕分けルール＆色 --------------------
RULES = {
    "Images":  {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"},
    "Audio":   {".wav", ".mp3", ".ogg", ".flac", ".m4a"},
    "Videos":  {".mp4", ".mkv", ".mov", ".webm", ".avi"},
    "Docs":    {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".csv", ".rtf"},
    "Archives":{".zip", ".7z", ".rar", ".tar", ".gz"},
}
DEFAULT_BUCKET = "Others"

BUCKET_COLORS_LIGHT = {
    "Images":  QColor(230, 245, 255),
    "Audio":   QColor(240, 235, 255),
    "Videos":  QColor(255, 240, 230),
    "Docs":    QColor(235, 255, 235),
    "Archives":QColor(255, 245, 230),
    "Others":  QColor(245, 245, 245),
}
BUCKET_COLORS_DARK = {
    "Images":  QColor(40, 70, 95),
    "Audio":   QColor(55, 45, 85),
    "Videos":  QColor(90, 60, 35),
    "Docs":    QColor(40, 75, 45),
    "Archives":QColor(90, 70, 40),
    "Others":  QColor(50, 50, 50),
}

def decide_bucket(ext: str) -> str:
    for name, exts in RULES.items():
        if ext.lower() in exts:
            return name
    return DEFAULT_BUCKET

def unique_path(path: str) -> str:
    """同名があれば (1),(2)… を付けて衝突回避。"""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while True:
        cand = f"{base} ({i}){ext}"
        if not os.path.exists(cand):
            return cand
        i += 1

def reveal_in_explorer(path: str):
    if not os.path.exists(path):
        return
    if sys.platform == "win32":
        subprocess.run(["explorer", "/select,", os.path.normpath(path)])
    else:
        folder = os.path.dirname(path)
        subprocess.Popen(["xdg-open" if sys.platform.startswith("linux") else "open", folder])

def path_is_excluded(root: str, path: str, patterns: list[str]) -> bool:
    """
    除外パターン（glob）にマッチしたらTrue。
    - `.png` のようにドットから始まる指定は `*.png` に自動補正
    - 大文字小文字は無視
    - 相対パス／ベース名のどちらにもマッチすれば除外
    """
    rel = os.path.relpath(path, root).replace("\\", "/")
    base = os.path.basename(path)
    rel_l, base_l = rel.lower(), base.lower()

    fixed = []
    for p in patterns:
        p = p.strip()
        if not p:
            continue
        if p.startswith("."):          # 例: .png → *.png
            p = "*" + p
        fixed.append(p.lower())

    for p in fixed:
        if fnmatch.fnmatch(rel_l, p) or fnmatch.fnmatch(base_l, p):
            return True
    return False

def date_folder_for(path: str) -> str:
    """ファイルの更新日から YYYY-MM-DD を返す。"""
    try:
        t = os.path.getmtime(path)
        return datetime.fromtimestamp(t).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")

def looks_like_unity_project(folder: str) -> bool:
    if (
        os.path.isdir(os.path.join(folder, "Assets"))
        and os. path.isdir(os.path.join(folder, "ProjectSettings"))
    ):
        return True

    
    return False

# -------------------- メインUI --------------------
class FileSeirikun(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.setWindowTitle("ファイル整理くん")
        self.resize(1040, 640)

        # 状態
        self.target_folder: str | None = self.cfg.get("last_folder") or None
        self.plan: list[tuple[str, str, str]] = []  # (src, bucket, dst)
        self.theme_mode = self.cfg.get("theme_mode", "System")
        self.is_light = detect_windows_light_theme() if self.theme_mode == "System" else (self.theme_mode == "Light")

        # --- 上段：フォルダラベル＆ボタン ---
        self.folder_label = QLabel(f"整理するフォルダ：{self.target_folder or '未選択'}")
        self.folder_label.setStyleSheet("font-size:14px;")

        self.btn_select = QPushButton("フォルダ選択")
        self.btn_dryrun = QPushButton("試し整理")
        self.btn_run    = QPushButton("実行")
        self.btn_undo   = QPushButton("元に戻す")

        # --- オプション行 ---
        self.chk_recursive = QCheckBox("サブフォルダも対象（再帰）")
        self.chk_recursive.setChecked(bool(self.cfg.get("recursive", True)))
        self.chk_date = QCheckBox("日付別フォルダ（YYYY-MM-DD）")
        self.chk_date.setChecked(bool(self.cfg.get("date_folder", False)))

        self.exclude_edit = QLineEdit(", ".join(self.cfg.get("exclude_patterns", [])))
        self.exclude_edit.setPlaceholderText("除外パターン（カンマ区切り）例: *.png, *.jpg, .git, node_modules/*")
        self.exclude_edit.setClearButtonEnabled(True)

        # テーマ切替
        self.theme_box = QComboBox()
        self.theme_box.addItems(["Windowsに合わせる", "ライト", "ダーク"])
        self.theme_box.setCurrentIndex({"System":0,"Light":1,"Dark":2}[self.theme_mode])

        # --- サマリ & 表 ---
        self.summary_label = QLabel("—")
        self.summary_label.setStyleSheet("color:#888;")

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ファイル名", "カテゴリ", "移動先（相対パス）", "元の相対パス"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.doubleClicked.connect(self.on_table_double_clicked)

        # --- ログ ---
        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setPlaceholderText("ここに実行ログが表示されます。")

        # --- レイアウト ---
        row_btns = QHBoxLayout()
        row_btns.addWidget(self.btn_select)
        row_btns.addWidget(self.btn_dryrun)
        row_btns.addWidget(self.btn_run)
        row_btns.addWidget(self.btn_undo)
        row_btns.addStretch(1)
        row_btns.addWidget(QLabel("テーマ："))
        row_btns.addWidget(self.theme_box)

        row_opts = QHBoxLayout()
        row_opts.addWidget(self.chk_recursive)
        row_opts.addWidget(self.chk_date)
        row_opts.addStretch(1)

        row_excl = QHBoxLayout()
        row_excl.addWidget(QLabel("除外:"))
        row_excl.addWidget(self.exclude_edit)

        root = QVBoxLayout(self)
        root.addWidget(self.folder_label)
        root.addLayout(row_btns)
        root.addLayout(row_opts)
        root.addLayout(row_excl)
        root.addWidget(self.summary_label)
        root.addWidget(self.table, stretch=1)
        root.addWidget(self.log_area, stretch=1)

        # --- イベント ---
        self.btn_select.clicked.connect(self.select_folder)
        self.btn_dryrun.clicked.connect(self.do_dryrun)
        self.btn_run.clicked.connect(self.do_run)
        self.btn_undo.clicked.connect(self.do_undo)
        self.theme_box.currentIndexChanged.connect(self.on_theme_changed)
        self.chk_recursive.stateChanged.connect(self.on_option_changed)
        self.chk_date.stateChanged.connect(self.on_option_changed)
        self.exclude_edit.editingFinished.connect(self.on_option_changed)

        # テーマ反映
        self.apply_theme()

    # -------------------- テーマ --------------------
    def on_theme_changed(self):
        self.theme_mode = ["System", "Light", "Dark"][self.theme_box.currentIndex()]
        self.cfg["theme_mode"] = self.theme_mode
        save_config(self.cfg)
        self.apply_theme()

    def apply_theme(self):
        if self.theme_mode == "System":
            self.is_light = detect_windows_light_theme()
        else:
            self.is_light = (self.theme_mode == "Light")

        if self.is_light:
            self.setStyleSheet("""
                QWidget { background-color: #fefefe; color: #202020; font-size: 13px; }
                QTableWidget { gridline-color: #ccc; alternate-background-color: #f9f9f9;
                               selection-background-color: #cce5ff; selection-color: #000; }
                QHeaderView::section { background-color: #e8e8e8; padding: 4px; border: 1px solid #ccc; }
                QPlainTextEdit, QLineEdit { background-color: #ffffff; color: #000000; border: 1px solid #cfcfcf; border-radius: 4px; }
                QPushButton { padding: 6px 10px; }

                /* ▼ チェックボックス（ライト） */
                QCheckBox::indicator {
                    width: 16px; height: 16px;
                    border: 1px solid #9aa0a6; border-radius: 3px;
                    background: #ffffff;
                }
                QCheckBox::indicator:hover { border-color: #5f6368; }
                QCheckBox::indicator:checked {
                    background: #2b6cb0; border-color: #2b6cb0; image: url();
                }
                QCheckBox::indicator:checked::before {
                    content: "✔"; color: #ffffff; font-weight: 800; margin-left: 2px;
                }
                QCheckBox::indicator:disabled { background: #f1f3f4; border-color: #d2d6da; }
                QCheckBox::indicator:checked:disabled { background: #9bb7d9; border-color: #9bb7d9; }
            """)
        else:
            self.setStyleSheet("""
                QWidget { background-color: #121212; color: #eaeaea; font-size: 13px; }
                QTableWidget { gridline-color: #333; alternate-background-color: #1b1b1b;
                               selection-background-color: #2a4b7c; selection-color: #ffffff; }
                QHeaderView::section { background-color: #1e1e1e; padding: 4px; border: 1px solid #333; }
                QPlainTextEdit, QLineEdit { background-color: #1a1a1a; color: #eaeaea; border: 1px solid #333; border-radius: 4px; }
                QPushButton { padding: 6px 10px; }

                /* ▼ チェックボックス（ダーク） */
                QCheckBox::indicator {
                    width: 16px; height: 16px;
                    border: 1px solid #555; border-radius: 3px;
                    background: #1a1a1a;
                }
                QCheckBox::indicator:hover { border-color: #888; }
                QCheckBox::indicator:checked {
                    background: #4aa3ff; border-color: #4aa3ff; image: url();
                }
                QCheckBox::indicator:checked::before {
                    content: "✔"; color: #0c0c0c; font-weight: 900; margin-left: 2px;
                }
                QCheckBox::indicator:disabled { background: #202020; border-color: #2a2a2a; }
                QCheckBox::indicator:checked:disabled { background: #2f5f85; border-color: #2f5f85; }
            """)
        self.recolor_table_rows()

    def current_bucket_colors(self):
        return BUCKET_COLORS_LIGHT if self.is_light else BUCKET_COLORS_DARK

    def recolor_table_rows(self):
        colors = self.current_bucket_colors()
        for row in range(self.table.rowCount()):
            bucket = self.table.item(row, 1).text()
            bg = colors.get(bucket, colors["Others"])
            for col in range(self.table.columnCount()):
                it = self.table.item(row, col)
                if it:
                    it.setBackground(QBrush(bg))

    # -------------------- UIヘルパ --------------------
    def log(self, msg: str):
        self.log_area.appendPlainText(msg)

    def clear_preview(self):
        self.table.setRowCount(0)
        self.summary_label.setText("—")

    def add_preview_row(self, src: str, bucket: str, dst: str):
        row = self.table.rowCount()
        self.table.insertRow(row)

        rel_dst = os.path.relpath(dst, self.target_folder) if self.target_folder else dst
        rel_src = os.path.relpath(src, self.target_folder) if self.target_folder else src

        it_name   = QTableWidgetItem(os.path.basename(src))
        it_bucket = QTableWidgetItem(bucket)
        it_rel    = QTableWidgetItem(rel_dst)
        it_src    = QTableWidgetItem(rel_src)

        bg = self.current_bucket_colors().get(bucket, self.current_bucket_colors()["Others"])
        for it in (it_name, it_bucket, it_rel, it_src):
            it.setBackground(QBrush(bg))

        f = it_bucket.font(); f.setBold(True); it_bucket.setFont(f)

        self.table.setItem(row, 0, it_name)
        self.table.setItem(row, 1, it_bucket)
        self.table.setItem(row, 2, it_rel)
        self.table.setItem(row, 3, it_src)
        self.table.setRowHeight(row, 22)

    def on_table_double_clicked(self):
        row = self.table.currentRow()
        if row < 0 or not self.target_folder:
            return
        src_rel = self.table.item(row, 3).text()
        reveal_in_explorer(os.path.join(self.target_folder, src_rel))

    # -------------------- 設定変更 --------------------
    def on_option_changed(self):
        self.cfg["recursive"]   = self.chk_recursive.isChecked()
        self.cfg["date_folder"] = self.chk_date.isChecked()

        # 入力正規化：.png → *.png、空は捨てる
        patterns = []
        for p in self.exclude_edit.text().split(","):
            p = p.strip()
            if not p:
                continue
            if p.startswith("."):
                p = "*" + p
            patterns.append(p)
        self.cfg["exclude_patterns"] = patterns

        # 表示も正規化して反映
        self.exclude_edit.setText(", ".join(patterns))
        save_config(self.cfg)

    # -------------------- 計画生成 --------------------
    def iter_files(self, root: str, recursive: bool):
        if not recursive:
            for name in os.listdir(root):
                p = os.path.join(root, name)
                if os.path.isfile(p):
                    yield p
            return
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if d not in {".git", "node_modules"}
            ]

            for fname in filenames:
                yield os.path.join(dirpath, fname)

    def build_plan(self):
        self.plan = []
        if not self.target_folder:
            return

        recursive   = self.chk_recursive.isChecked()
        date_folder = self.chk_date.isChecked()
        patterns    = [p.strip() for p in self.exclude_edit.text().split(",") if p.strip()]

        files = []
        for p in self.iter_files(self.target_folder, recursive):
            if path_is_excluded(self.target_folder, p, patterns):
                continue
            files.append(p)

        for src in files:
            ext = os.path.splitext(src)[1]
            bucket = decide_bucket(ext)

            dest_dir = os.path.join(self.target_folder, bucket)
            if date_folder:
                dest_dir = os.path.join(dest_dir, date_folder_for(src))
            dest = os.path.join(dest_dir, os.path.basename(src))

            same = os.path.abspath(src) == os.path.abspath(dest)
            under_dest_root = os.path.commonpath(
                [os.path.abspath(src), os.path.abspath(os.path.join(self.target_folder, bucket))]
            ) == os.path.abspath(os.path.join(self.target_folder, bucket))

            if same or under_dest_root:
                continue

            self.plan.append((src, bucket, dest))

    # -------------------- 操作 --------------------
    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "フォルダを選択")
        if folder:
            self.target_folder = folder
            self.cfg["last_folder"] = folder
            save_config(self.cfg)
            self.folder_label.setText(f"整理するフォルダ：{folder}")
            self.log(f"[選択] {folder}")
            self.clear_preview()
            self.plan = []
        else:
            self.log("[選択] キャンセル")

    def do_dryrun(self):
        if not self.target_folder:
            QMessageBox.warning(self, "未選択", "先にフォルダを選んでください。")
            return

        self.build_plan()
        self.clear_preview()

        if not self.plan:
            self.summary_label.setText("移動対象なし")
            self.log("[試し整理] 移動対象はありません。")
            return

        by_bucket = {}
        for src, bucket, dst in self.plan:
            self.add_preview_row(src, bucket, dst)
            by_bucket[bucket] = by_bucket.get(bucket, 0) + 1

        summary = " / ".join(f"{k}: {v}件" for k, v in sorted(by_bucket.items()))
        self.summary_label.setText(f"計 {len(self.plan)}件　|　{summary}")
        self.log(f"[試し整理] {len(self.plan)} 件をプレビューしました。")

    def do_run(self):
        if not self.target_folder:
            QMessageBox.warning(self, "未選択", "先にフォルダを選んでください。")
            return

        if not self.plan:
            self.build_plan()
        if not self.plan:
            self.log("[実行] 移動対象はありません。")
            self.summary_label.setText("移動対象なし")
            return

        moves_done: list[tuple[str, str]] = []
        errors = 0

        for src, _, dst in self.plan:
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                dst_u = unique_path(dst)
                shutil.move(src, dst_u)
                moves_done.append((src, dst_u))
                self.log(f"[移動] {os.path.basename(src)} -> {os.path.relpath(dst_u, self.target_folder)}")
            except Exception as e:
                errors += 1
                self.log(f"[失敗] {src} : {e}")

        if moves_done:
            undo = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "root": self.target_folder,
                "moves": [{"from": s, "to": d} for s, d in moves_done]
            }
            try:
                with open(UNDO_FILE, "w", encoding="utf-8") as f:
                    json.dump(undo, f, ensure_ascii=False, indent=2)
                self.log(f"[保存] Undo情報を {os.path.basename(UNDO_FILE)} に保存（{len(moves_done)} 件）")
            except Exception as e:
                self.log(f"[警告] Undo保存失敗: {e}")

        self.do_dryrun()
        self.log(f"[完了] 実行: {len(moves_done)} 件、失敗: {errors} 件")

    def do_undo(self):
        if not os.path.exists(UNDO_FILE):
            self.log("[元に戻す] Undo情報が見つかりません。")
            return

        try:
            with open(UNDO_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.log(f"[元に戻す] Undo情報の読み込みに失敗: {e}")
            return

        root = data.get("root")
        moves = data.get("moves", [])
        if not root or not moves:
            self.log("[元に戻す] 内容が不正です。")
            return

        restored, errors = 0, 0
        for rec in reversed(moves):  # 逆順で戻す
            src_now = rec["to"]
            dst_back = rec["from"]
            try:
                if os.path.exists(dst_back):
                    base, ext = os.path.splitext(dst_back)
                    dst_back = unique_path(base + " (restore)" + ext)
                os.makedirs(os.path.dirname(dst_back), exist_ok=True)
                shutil.move(src_now, dst_back)
                restored += 1
                self.log(f"[戻す] {os.path.basename(src_now)} -> {os.path.relpath(dst_back, root)}")
            except Exception as e:
                errors += 1
                self.log(f"[戻し失敗] {src_now} : {e}")

        if restored and errors == 0:
            try:
                os.remove(UNDO_FILE)
                self.log(f"[片付け] {os.path.basename(UNDO_FILE)} を削除しました。")
            except Exception as e:
                self.log(f"[警告] Undoファイル削除失敗: {e}")

        self.do_dryrun()
        self.log(f"[完了] 戻し: {restored} 件、失敗: {errors} 件")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = FileSeirikun()
    w.show()
    sys.exit(app.exec())
