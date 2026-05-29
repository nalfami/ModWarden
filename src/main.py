"""
ModWarden — main entry point.
Detects broken, incompatible, and outdated mods in any mods/ folder.
"""

import os
import sys
import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

import customtkinter as ctk
from PIL import Image

from mod_parser import scan_folder, ModInfo
from checker import check_mods, find_update, find_update_async, download_update, REQUESTS_OK


def _asset(filename: str) -> str:
    """Return absolute path to an assets file, works both raw and PyInstaller-frozen."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "assets", filename)
    return os.path.join(os.path.dirname(__file__), "..", "assets", filename)

# ── Appearance ────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

BG       = "#0d1117"
SIDEBAR  = "#161b22"
CARD     = "#21262d"
BORDER   = "#30363d"
HOVER    = "#2d333b"
T1       = "#e6edf3"   # primary text
T2       = "#8b949e"   # secondary text
GREEN    = "#3fb950"
GREEN_H  = "#2ea043"
RED      = "#f85149"
YELLOW   = "#d29922"
BLUE     = "#58a6ff"
BLUE_H   = "#1f6feb"

MC_VERSIONS = [
    "1.21.6", "1.21.5", "1.21.4", "1.21.3", "1.21.2",
    "1.21.1", "1.21", "1.20.6", "1.20.4", "1.20.2",
    "1.20.1", "1.19.4", "1.19.2", "1.18.2", "1.17.1",
    "1.16.5", "1.12.2", "1.8.9", "1.7.10",
]

LOADERS = ["Forge", "Fabric", "NeoForge", "Quilt"]


# ── App ───────────────────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ModWarden")
        self.geometry("1060x700")
        self.minsize(900, 620)
        self.configure(fg_color=BG)

        self._mods_folder: str = ""
        self._scan_results: list = []
        self._current_page: str = ""
        self._row_result_map: dict = {}

        self._build_ui()
        self._switch_page("checker")

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._sidebar = self._make_sidebar()
        self._sidebar.pack(side="left", fill="y")

        self._content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self._content.pack(side="right", fill="both", expand=True)

        self._pages: dict[str, ctk.CTkFrame] = {
            "checker": self._build_checker_page(),
            "results": self._build_results_page(),
            "support": self._build_support_page(),
        }

    def _make_sidebar(self) -> ctk.CTkFrame:
        sb = ctk.CTkFrame(self, width=200, fg_color=SIDEBAR, corner_radius=0)
        sb.pack_propagate(False)

        # Logo block
        logo = ctk.CTkFrame(sb, fg_color="transparent")
        logo.pack(pady=(22, 32), padx=16, fill="x")

        try:
            _pil = Image.open(_asset("logo.png"))
            _img = ctk.CTkImage(light_image=_pil, dark_image=_pil, size=(64, 64))
            ctk.CTkLabel(logo, image=_img, text="").pack()
        except Exception:
            ctk.CTkLabel(logo, text="⛏", font=ctk.CTkFont(size=32)).pack()

        ctk.CTkLabel(
            logo, text="ModWarden",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=T1,
        ).pack(pady=(8, 0))
        ctk.CTkLabel(
            logo, text="for Minecraft",
            font=ctk.CTkFont(size=11),
            text_color=T2,
        ).pack()

        # Nav items
        self._nav_btns: dict = {}
        for page_id, icon, label in [
            ("checker", "🔍", "Checker"),
            ("results", "📋", "Results"),
            ("support", "💙", "Support"),
        ]:
            btn = ctk.CTkButton(
                sb,
                text=f"  {icon}  {label}",
                font=ctk.CTkFont(size=13),
                fg_color="transparent",
                hover_color=HOVER,
                text_color=T2,
                anchor="w",
                height=42,
                corner_radius=8,
                command=lambda p=page_id: self._switch_page(p),
            )
            btn.pack(padx=12, pady=2, fill="x")
            self._nav_btns[page_id] = btn

        # Bottom: GitHub + version
        bottom = ctk.CTkFrame(sb, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=12, pady=14)

        ctk.CTkButton(
            bottom,
            text="⌥  github.com/nalfami",
            font=ctk.CTkFont(size=11),
            fg_color="transparent",
            hover_color=HOVER,
            text_color=T2,
            anchor="w",
            height=32,
            corner_radius=6,
            command=lambda: __import__("webbrowser").open("https://github.com/nalfami"),
        ).pack(fill="x")

        ctk.CTkLabel(
            bottom, text="v1.0.0  •  Free / MIT",
            font=ctk.CTkFont(size=10),
            text_color=T2,
        ).pack(pady=(4, 0))

        return sb

    # ── Checker page ──────────────────────────────────────────────────────────

    def _build_checker_page(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self._content, fg_color="transparent")

        ctk.CTkLabel(
            frame, text="ModWarden",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color=T1,
        ).pack(anchor="w")
        ctk.CTkLabel(
            frame,
            text="Scan a mods folder for broken, incompatible and outdated mods",
            font=ctk.CTkFont(size=13),
            text_color=T2,
        ).pack(anchor="w", pady=(4, 22))

        # ── Config card ──
        card = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=12)
        card.pack(fill="x")

        # Folder row
        folder_col = ctk.CTkFrame(card, fg_color="transparent")
        folder_col.pack(padx=20, pady=(20, 14), fill="x")

        ctk.CTkLabel(
            folder_col, text="MODS FOLDER",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=T2,
        ).pack(anchor="w")

        row = ctk.CTkFrame(folder_col, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))

        self._folder_entry = ctk.CTkEntry(
            row,
            placeholder_text="Select your mods folder...",
            fg_color=BG,
            border_color=BORDER,
            text_color=T1,
            font=ctk.CTkFont(size=12),
            height=40,
        )
        self._folder_entry.pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            row, text="Browse",
            width=90, height=40,
            fg_color=GREEN, hover_color=GREEN_H,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._browse_folder,
        ).pack(side="right", padx=(8, 0))

        # Version + Loader row
        sel_row = ctk.CTkFrame(card, fg_color="transparent")
        sel_row.pack(padx=20, pady=(0, 20), fill="x")

        mc_col = ctk.CTkFrame(sel_row, fg_color="transparent")
        mc_col.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkLabel(
            mc_col, text="MINECRAFT VERSION",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=T2,
        ).pack(anchor="w")
        self._mc_var = ctk.StringVar(value="1.21.5")
        ctk.CTkComboBox(
            mc_col,
            values=MC_VERSIONS,
            variable=self._mc_var,
            fg_color=BG,
            border_color=BORDER,
            button_color=BORDER,
            button_hover_color=HOVER,
            dropdown_fg_color=CARD,
            text_color=T1,
            font=ctk.CTkFont(size=12),
            height=40,
        ).pack(fill="x", pady=(6, 0))

        ld_col = ctk.CTkFrame(sel_row, fg_color="transparent")
        ld_col.pack(side="right", fill="x", expand=True, padx=(10, 0))
        ctk.CTkLabel(
            ld_col, text="MOD LOADER",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=T2,
        ).pack(anchor="w")
        self._loader_var = ctk.StringVar(value="Forge")
        ctk.CTkOptionMenu(
            ld_col,
            values=LOADERS,
            variable=self._loader_var,
            fg_color=BG,
            button_color=BORDER,
            button_hover_color=HOVER,
            dropdown_fg_color=CARD,
            text_color=T1,
            font=ctk.CTkFont(size=12),
            height=40,
        ).pack(fill="x", pady=(6, 0))

        # Scan button
        self._scan_btn = ctk.CTkButton(
            frame,
            text="SCAN MODS",
            height=50,
            fg_color=GREEN,
            hover_color=GREEN_H,
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=10,
            command=self._start_scan,
        )
        self._scan_btn.pack(fill="x", pady=(18, 0))

        # Progress bar (hidden by default)
        self._progress = ctk.CTkProgressBar(
            frame, fg_color=BORDER, progress_color=GREEN, height=6, corner_radius=3
        )
        self._progress.set(0)

        self._status_lbl = ctk.CTkLabel(
            frame, text="",
            font=ctk.CTkFont(size=12),
            text_color=T2,
        )
        self._status_lbl.pack(pady=(10, 0))

        return frame

    # ── Results page ──────────────────────────────────────────────────────────

    def _build_results_page(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self._content, fg_color="transparent")

        # Title row
        hdr = ctk.CTkFrame(frame, fg_color="transparent")
        hdr.pack(fill="x")
        ctk.CTkLabel(
            hdr, text="Results",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color=T1,
        ).pack(side="left", anchor="w")

        self._export_btn = ctk.CTkButton(
            hdr,
            text="⬇ Export Report",
            width=140, height=38,
            fg_color=CARD,
            hover_color=HOVER,
            border_width=1,
            border_color=BORDER,
            text_color=T1,
            font=ctk.CTkFont(size=12),
            command=self._export_report,
        )
        self._export_btn.pack(side="right")

        # Stat cards
        stats_row = ctk.CTkFrame(frame, fg_color="transparent")
        stats_row.pack(fill="x", pady=(18, 0))
        self._stat_labels: dict = {}

        for i, (sid, icon, label, color) in enumerate([
            ("total",    "📦", "Total",    BLUE),
            ("ok",       "✅", "OK",       GREEN),
            ("warnings", "⚠️", "Warnings", YELLOW),
            ("errors",   "❌", "Errors",   RED),
        ]):
            sc = ctk.CTkFrame(stats_row, fg_color=CARD, corner_radius=10)
            sc.pack(
                side="left",
                fill="x",
                expand=True,
                padx=(0 if i == 0 else 8, 0),
            )
            ctk.CTkLabel(sc, text=icon, font=ctk.CTkFont(size=22)).pack(pady=(14, 4))
            num = ctk.CTkLabel(
                sc, text="—",
                font=ctk.CTkFont(size=24, weight="bold"),
                text_color=color,
            )
            num.pack()
            ctk.CTkLabel(
                sc, text=label,
                font=ctk.CTkFont(size=11),
                text_color=T2,
            ).pack(pady=(0, 14))
            self._stat_labels[sid] = num

        # Action bar (update / remove)
        self._action_bar = ctk.CTkFrame(frame, fg_color="transparent")
        self._update_btn = ctk.CTkButton(
            self._action_bar,
            text="⬆  Update Selected Mod",
            height=40, width=220,
            fg_color=BLUE, hover_color=BLUE_H,
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=self._update_selected,
        )
        self._update_btn.pack(side="left")
        self._update_status = ctk.CTkLabel(
            self._action_bar, text="",
            font=ctk.CTkFont(size=12),
            text_color=T2,
        )
        self._update_status.pack(side="left", padx=14)

        # Treeview card
        tv_card = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=12)
        tv_card.pack(fill="both", expand=True, pady=(14, 0))

        self._style_treeview()
        cols = ("status", "name", "version", "loader", "mc_range", "issues")
        self._tree = ttk.Treeview(
            tv_card, columns=cols, show="headings",
            style="Mod.Treeview", selectmode="browse",
        )
        for col, heading, width, anchor in [
            ("status",   "Status",        90,  "center"),
            ("name",     "Mod Name",      200, "w"),
            ("version",  "Version",       100, "center"),
            ("loader",   "Loader",        90,  "center"),
            ("mc_range", "MC Range",      150, "center"),
            ("issues",   "Issues / Notes", 340, "w"),
        ]:
            self._tree.heading(col, text=heading)
            self._tree.column(col, width=width, minwidth=60, anchor=anchor)

        sb = ttk.Scrollbar(tv_card, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb.pack(side="right", fill="y", pady=8)

        self._tree.tag_configure("ok",      foreground=GREEN)
        self._tree.tag_configure("warning", foreground=YELLOW)
        self._tree.tag_configure("error",   foreground=RED)
        self._tree.tag_configure("update",  foreground=BLUE)

        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        return frame

    def _style_treeview(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Mod.Treeview",
            background=CARD,
            fieldbackground=CARD,
            foreground=T1,
            rowheight=38,
            borderwidth=0,
            font=("Segoe UI", 11),
        )
        style.configure(
            "Mod.Treeview.Heading",
            background=SIDEBAR,
            foreground=T2,
            font=("Segoe UI", 11, "bold"),
            borderwidth=0,
            relief="flat",
        )
        style.map("Mod.Treeview", background=[("selected", HOVER)])
        style.configure(
            "Vertical.TScrollbar",
            troughcolor=CARD,
            background=BORDER,
            bordercolor=CARD,
            arrowcolor=T2,
        )

    # ── Support page ──────────────────────────────────────────────────────────

    def _build_support_page(self) -> ctk.CTkFrame:
        import webbrowser

        WALLET = "TRZu8DP7mdTUBgmDo22WLkwf4cqbyj5AL1"
        EMAIL  = "blanggglegit@gmail.com"
        GITHUB = "https://github.com/nalfami"

        frame = ctk.CTkFrame(self._content, fg_color="transparent")

        # ── Page title ────────────────────────────────────────────────────────
        ctk.CTkLabel(
            frame, text="Support & About",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color=T1,
        ).pack(anchor="w")
        ctk.CTkLabel(
            frame,
            text="Open source · Free forever · Made with ❤",
            font=ctk.CTkFont(size=13),
            text_color=T2,
        ).pack(anchor="w", pady=(4, 20))

        # ── Row 1: Creator  |  License  (two equal columns) ──────────────────
        row1 = ctk.CTkFrame(frame, fg_color="transparent")
        row1.pack(fill="x")
        row1.columnconfigure(0, weight=1, uniform="col")
        row1.columnconfigure(1, weight=1, uniform="col")

        # Creator card
        cc = ctk.CTkFrame(row1, fg_color=CARD, corner_radius=12)
        cc.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        ctk.CTkLabel(
            cc, text="👤  CREATOR",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=T2,
        ).pack(anchor="w", padx=20, pady=(18, 0))

        ctk.CTkLabel(
            cc, text="nalfami",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=T1,
        ).pack(anchor="w", padx=20, pady=(6, 12))

        ctk.CTkButton(
            cc,
            text="⌥  Open GitHub Profile",
            height=38,
            fg_color=HOVER,
            hover_color=BORDER,
            border_width=1,
            border_color=BORDER,
            text_color=T1,
            font=ctk.CTkFont(size=12),
            anchor="w",
            corner_radius=8,
            command=lambda: webbrowser.open(GITHUB),
        ).pack(fill="x", padx=16, pady=(0, 18))

        # License card
        lc = ctk.CTkFrame(row1, fg_color=CARD, corner_radius=12)
        lc.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        ctk.CTkLabel(
            lc, text="📄  LICENSE",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=T2,
        ).pack(anchor="w", padx=20, pady=(18, 0))

        badge_row = ctk.CTkFrame(lc, fg_color="transparent")
        badge_row.pack(anchor="w", padx=20, pady=(8, 4))

        ctk.CTkLabel(
            badge_row,
            text="FREE",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=BG,
            fg_color=GREEN,
            corner_radius=6,
            width=52, height=24,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            badge_row,
            text="MIT",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=BG,
            fg_color=BLUE,
            corner_radius=6,
            width=40, height=24,
        ).pack(side="left")

        ctk.CTkLabel(
            lc,
            text="Free to use, modify\nand distribute.",
            font=ctk.CTkFont(size=12),
            text_color=T2,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(4, 18))

        # ── Row 2: Donate (full width) ────────────────────────────────────────
        dc = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=12)
        dc.pack(fill="x", pady=(12, 0))

        dc_left = ctk.CTkFrame(dc, fg_color="transparent")
        dc_left.pack(side="left", fill="both", expand=True, padx=20, pady=18)

        ctk.CTkLabel(
            dc_left, text="💙  SUPPORT THE DEVELOPER",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=T2,
        ).pack(anchor="w")
        ctk.CTkLabel(
            dc_left,
            text="If this tool saved your day, a small donation helps keep\nthe project alive and regularly updated.",
            font=ctk.CTkFont(size=12),
            text_color=T1,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        dc_right = ctk.CTkFrame(dc, fg_color="transparent")
        dc_right.pack(side="right", padx=20, pady=18)

        ctk.CTkLabel(
            dc_right,
            text="USDT · TRC20",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=T2,
        ).pack(anchor="e")

        wallet_row = ctk.CTkFrame(dc_right, fg_color=BG, corner_radius=8)
        wallet_row.pack(pady=(6, 0))

        ctk.CTkLabel(
            wallet_row,
            text=WALLET,
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color=T1,
        ).pack(side="left", padx=12, pady=10)

        copy_wallet = ctk.CTkButton(
            wallet_row, text="Copy",
            width=64, height=30,
            fg_color=GREEN, hover_color=GREEN_H,
            font=ctk.CTkFont(size=11, weight="bold"),
        )

        def _copy_wallet():
            self.clipboard_clear()
            self.clipboard_append(WALLET)
            copy_wallet.configure(text="✓ Done")
            self.after(2000, lambda: copy_wallet.configure(text="Copy"))

        copy_wallet.configure(command=_copy_wallet)
        copy_wallet.pack(side="right", padx=8, pady=6)

        # ── Row 3: Contact (full width) ───────────────────────────────────────
        ec = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=12)
        ec.pack(fill="x", pady=(10, 0))

        ec_left = ctk.CTkFrame(ec, fg_color="transparent")
        ec_left.pack(side="left", fill="both", expand=True, padx=20, pady=18)

        ctk.CTkLabel(
            ec_left, text="📧  CONTACT & SUPPORT",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=T2,
        ).pack(anchor="w")
        ctk.CTkLabel(
            ec_left,
            text="Bug reports · Partnership offers · Any questions",
            font=ctk.CTkFont(size=12),
            text_color=T1,
        ).pack(anchor="w", pady=(6, 0))

        ec_right = ctk.CTkFrame(ec, fg_color="transparent")
        ec_right.pack(side="right", padx=20, pady=18)

        email_row = ctk.CTkFrame(ec_right, fg_color=BG, corner_radius=8)
        email_row.pack()

        ctk.CTkLabel(
            email_row,
            text=EMAIL,
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color=T1,
        ).pack(side="left", padx=12, pady=10)

        copy_email = ctk.CTkButton(
            email_row, text="Copy",
            width=64, height=30,
            fg_color=BLUE, hover_color=BLUE_H,
            font=ctk.CTkFont(size=11, weight="bold"),
        )

        def _copy_email():
            self.clipboard_clear()
            self.clipboard_append(EMAIL)
            copy_email.configure(text="✓ Done")
            self.after(2000, lambda: copy_email.configure(text="Copy"))

        copy_email.configure(command=_copy_email)
        copy_email.pack(side="right", padx=8, pady=6)

        return frame

    # ── Navigation ────────────────────────────────────────────────────────────

    def _switch_page(self, page_id: str):
        for f in self._pages.values():
            f.pack_forget()
        self._pages[page_id].pack(fill="both", expand=True, padx=28, pady=28)

        for pid, btn in self._nav_btns.items():
            if pid == page_id:
                btn.configure(fg_color=HOVER, text_color=T1)
            else:
                btn.configure(fg_color="transparent", text_color=T2)

        self._current_page = page_id

    # ── Checker logic ─────────────────────────────────────────────────────────

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select mods folder")
        if folder:
            self._mods_folder = folder
            self._folder_entry.delete(0, "end")
            self._folder_entry.insert(0, folder)

    def _start_scan(self):
        folder = self._folder_entry.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Error", "Please select a valid mods folder.")
            return

        self._mods_folder = folder
        self._scan_btn.configure(state="disabled", text="Scanning…")
        self._status_lbl.configure(text="Reading mod files…", text_color=T2)
        self._progress.set(0)
        self._progress.pack(fill="x", pady=(8, 0))

        for iid in self._tree.get_children():
            self._tree.delete(iid)
        for k in self._stat_labels:
            self._stat_labels[k].configure(text="—")
        self._action_bar.pack_forget()

        threading.Thread(target=self._run_scan, daemon=True).start()

    def _run_scan(self):
        target_mc = self._mc_var.get()
        target_loader = self._loader_var.get()

        mods = scan_folder(self._mods_folder)
        self.after(0, lambda: self._status_lbl.configure(text=f"Checking {len(mods)} mods…"))
        self.after(0, lambda: self._progress.set(0.4))

        results = check_mods(mods, target_mc, target_loader)
        self.after(0, lambda: self._progress.set(0.8))

        self._scan_results = results
        self.after(0, self._show_results)

    def _show_results(self):
        self._progress.set(1.0)
        self.after(600, self._progress.pack_forget)

        results = self._scan_results
        counts = {"total": len(results), "ok": 0, "warnings": 0, "errors": 0}

        self._row_result_map.clear()
        for iid in self._tree.get_children():
            self._tree.delete(iid)

        for r in results:
            mi = r.mod_info
            if r.status == "OK":
                icon = "✓  OK"
                tag = "ok"
                counts["ok"] += 1
            elif r.status == "WARNING":
                icon = "!  WARN"
                tag = "warning"
                counts["warnings"] += 1
            else:
                icon = "✕  ERR"
                tag = "error"
                counts["errors"] += 1

            issues_str = " | ".join(r.issues) if r.issues else "—"

            iid = self._tree.insert(
                "", "end",
                values=(
                    icon,
                    mi.name or mi.file_name,
                    mi.version or "?",
                    mi.loader.capitalize(),
                    mi.mc_version_range or "*",
                    issues_str,
                ),
                tags=(tag,),
            )
            self._row_result_map[iid] = r

        for sid, val in counts.items():
            self._stat_labels[sid].configure(text=str(val))

        self._scan_btn.configure(state="normal", text="SCAN MODS")
        ok_count = counts["ok"]
        issue_count = counts["warnings"] + counts["errors"]
        self._status_lbl.configure(
            text=f"Done — {ok_count} OK, {issue_count} issues found",
            text_color=GREEN if issue_count == 0 else YELLOW,
        )
        self._switch_page("results")

    # ── Results actions ───────────────────────────────────────────────────────

    def _on_tree_select(self, _event=None):
        sel = self._tree.selection()
        if not sel:
            self._action_bar.pack_forget()
            return
        iid = sel[0]
        r = self._row_result_map.get(iid)
        if r is None:
            return

        if not REQUESTS_OK:
            return

        if r.status in ("ERROR", "WARNING") and r.mod_info.is_valid:
            self._action_bar.pack(fill="x", pady=(12, 0))
            self._update_status.configure(text="Select a mod to update via Modrinth", text_color=T2)
        else:
            self._action_bar.pack_forget()

    def _update_selected(self):
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        r = self._row_result_map.get(iid)
        if r is None or not r.mod_info.is_valid:
            return

        self._update_btn.configure(state="disabled", text="Searching…")
        self._update_status.configure(text="Looking for update on Modrinth…", text_color=T2)

        target_mc = self._mc_var.get()
        target_loader = self._loader_var.get().lower()

        def _done(version_info):
            if version_info is None:
                self.after(0, lambda: self._update_btn.configure(
                    state="normal", text="⬆  Update Selected Mod"
                ))
                self.after(0, lambda: self._update_status.configure(
                    text="No compatible update found on Modrinth.", text_color=YELLOW
                ))
                return
            self.after(0, lambda: self._do_download(r, version_info, iid))

        find_update_async(r.mod_info, target_mc, target_loader, _done)

    def _do_download(self, result, version_info: dict, iid: str):
        new_ver = version_info.get("version_number", "?")
        self._update_status.configure(
            text=f"Downloading v{new_ver}…", text_color=BLUE
        )

        def _progress(pct):
            self.after(0, lambda: self._update_status.configure(
                text=f"Downloading v{new_ver}… {pct}%"
            ))

        def _run():
            path = download_update(
                version_info,
                self._mods_folder,
                result.mod_info.file_path,
                _progress,
            )
            self.after(0, lambda: self._download_done(result, path, new_ver, iid))

        threading.Thread(target=_run, daemon=True).start()

    def _download_done(self, result, path: str, new_ver: str, iid: str):
        self._update_btn.configure(state="normal", text="⬆  Update Selected Mod")
        if path:
            self._update_status.configure(
                text=f"✓ Updated to v{new_ver} successfully!", text_color=GREEN
            )
            # Refresh the row
            mi = result.mod_info
            self._tree.item(
                iid,
                values=("✅", mi.name or mi.file_name, new_ver,
                        mi.loader.capitalize(), mi.mc_version_range or "*", "Updated via Modrinth"),
                tags=("ok",),
            )
        else:
            self._update_status.configure(
                text="Download failed. Check your internet connection.", text_color=RED
            )

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_report(self):
        if not self._scan_results:
            messagebox.showinfo("Export", "No scan results to export. Run a scan first.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text file", "*.txt"), ("JSON file", "*.json")],
            initialfile=f"mod_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        )
        if not path:
            return

        if path.endswith(".json"):
            data = []
            for r in self._scan_results:
                mi = r.mod_info
                data.append({
                    "file": mi.file_name,
                    "mod_id": mi.mod_id,
                    "name": mi.name,
                    "version": mi.version,
                    "loader": mi.loader,
                    "mc_range": mi.mc_version_range,
                    "status": r.status,
                    "issues": r.issues,
                })
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        else:
            lines = [
                "ModWarden — Scan Report",
                f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"Folder: {self._mods_folder}",
                f"MC: {self._mc_var.get()}  Loader: {self._loader_var.get()}",
                "=" * 60,
            ]
            for r in self._scan_results:
                mi = r.mod_info
                lines.append(
                    f"[{r.status}] {mi.name or mi.file_name}  v{mi.version}  "
                    f"({mi.loader}) MC:{mi.mc_version_range}"
                )
                for issue in r.issues:
                    lines.append(f"   • {issue}")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))

        messagebox.showinfo("Export", f"Report saved to:\n{path}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
