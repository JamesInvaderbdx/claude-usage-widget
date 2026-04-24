import tkinter as tk
import customtkinter as ctk
import threading
import json
import os
from datetime import datetime

CACHE_FILE  = os.path.expanduser("~/.claudus_cache.json")
COOKIE_FILE = os.path.expanduser("~/.claudus_cookie.json")
REFRESH_INTERVAL = 900  # 15 min

# ── cookie storage ────────────────────────────────────────────────────────────

def save_cookies(session_key, cf_clearance):
    with open(COOKIE_FILE, "w") as f:
        json.dump({"sessionKey": session_key, "cf_clearance": cf_clearance}, f)

def load_cookies():
    try:
        with open(COOKIE_FILE) as f:
            d = json.load(f)
            return d.get("sessionKey", ""), d.get("cf_clearance", "")
    except Exception:
        return "", ""

# ── helpers ───────────────────────────────────────────────────────────────────

def bar(pct, width=10):
    n = round(pct / 100 * width)
    return "▓" * n + "░" * (width - n)

def save_cache(data):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

def load_cache():
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return None

def _fmt_reset(iso):
    """ISO timestamp → 'jj/mm HH:MM' en heure locale."""
    try:
        dt = datetime.fromisoformat(iso).astimezone(tz=None)
        return dt.strftime("%d/%m %H:%M")
    except Exception:
        return iso[:16]

def _countdown(iso):
    """ISO timestamp → 'dans Xh Ym' ou 'expiré'."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso).astimezone(tz=None)
        diff = dt - datetime.now().astimezone()
        secs = diff.total_seconds()
        if secs <= 0:
            return "expiré"
        total_min = int(secs // 60)
        h, m = divmod(total_min, 60)
        return f"dans {h}h{m:02d}m" if h else f"dans {m}m"
    except Exception:
        return ""

# ── scraper ───────────────────────────────────────────────────────────────────

def fetch_usage(session_key, cf_clearance):
    from curl_cffi import requests as curl

    s = curl.Session(impersonate="chrome")
    s.cookies.set("sessionKey",   session_key,  domain="claude.ai")
    s.cookies.set("cf_clearance", cf_clearance, domain="claude.ai")

    result = {
        "plan": "—",
        "five_hour_pct": None, "reset_5h": "—", "reset_5h_iso": "",
        "seven_day_pct": None, "reset_7d": "—", "reset_7d_iso": "",
        "add_on_pct":    None, "reset_add_on": "—", "reset_add_on_iso": "",
        "add_on_used": None, "add_on_limit": None, "add_on_currency": "",
    }

    # 1. account → plan + org uuid
    org_uuid = None
    try:
        r = s.get("https://claude.ai/api/account", timeout=15)
        r.raise_for_status()
        acc = r.json()
        memberships = acc.get("memberships", [])
        if memberships:
            org = memberships[0].get("organization", {})
            caps = org.get("capabilities", [])
            if "claude_pro" in caps:
                result["plan"] = "Pro"
            elif "claude_max_5x" in caps:
                result["plan"] = "Max 5×"
            elif "claude_max_20x" in caps:
                result["plan"] = "Max 20×"
            else:
                result["plan"] = caps[0] if caps else "—"
            org_uuid = org.get("uuid")
    except Exception:
        pass

    # 2. usage
    if org_uuid:
        try:
            r = s.get(f"https://claude.ai/api/organizations/{org_uuid}/usage", timeout=15)
            r.raise_for_status()
            data = r.json()

            fh = data.get("five_hour") or {}
            sd = data.get("seven_day") or {}

            result["five_hour_pct"] = fh.get("utilization")
            result["seven_day_pct"] = sd.get("utilization")

            if fh.get("resets_at"):
                result["reset_5h"]     = _fmt_reset(fh["resets_at"])
                result["reset_5h_iso"] = fh["resets_at"]
            if sd.get("resets_at"):
                result["reset_7d"]     = _fmt_reset(sd["resets_at"])
                result["reset_7d_iso"] = sd["resets_at"]

            # extra_usage (crédits supplémentaires en €)
            eu = data.get("extra_usage")
            if eu and eu.get("is_enabled"):
                result["add_on_pct"]      = eu.get("utilization")
                result["add_on_used"]     = eu.get("used_credits")
                result["add_on_limit"]    = eu.get("monthly_limit")
                result["add_on_currency"] = eu.get("currency", "")
                result["add_on_renewable"] = eu.get("resets_at") is not None
                if eu.get("resets_at"):
                    result["reset_add_on"]     = _fmt_reset(eu["resets_at"])
                    result["reset_add_on_iso"] = eu["resets_at"]

                # compteur de recharges : détecte si used_credits a baissé
                prev = load_cache()
                prev_used  = (prev or {}).get("add_on_used", 0) or 0
                prev_month = (prev or {}).get("add_on_recharge_month", "")
                cur_month  = datetime.now().strftime("%Y-%m")
                prev_count = (prev or {}).get("add_on_recharge_count", 0) if prev_month == cur_month else 0
                cur_used   = eu.get("used_credits") or 0
                if prev_month == cur_month and cur_used < prev_used - 1:
                    prev_count += 1
                result["add_on_recharge_count"] = prev_count
                result["add_on_recharge_month"] = cur_month

        except Exception as e:
            result["error"] = str(e)

    result["updated"] = datetime.now().strftime("%d/%m %H:%M")
    save_cache(result)
    return result

# ── setup dialog ──────────────────────────────────────────────────────────────

INSTRUCTIONS = """\
Dans Chrome, ouvre claude.ai → F12 → Application → Cookies → https://claude.ai

Copie la valeur de ces deux cookies :
  • sessionKey
  • cf_clearance
"""

class SetupDialog:
    def __init__(self):
        self.session_key   = ""
        self.cf_clearance  = ""
        self.root = tk.Tk()
        self.root.title("Claud'Us – Setup")
        self.root.configure(bg="#0a0a14")
        self.root.resizable(False, False)
        self._build()
        self.root.mainloop()

    def _build(self):
        BG, FG, ACC = "#0a0a14", "#ccccee", "#5555ff"
        F  = ("Courier New", 10)
        FB = ("Courier New", 10, "bold")

        tk.Label(self.root, text=INSTRUCTIONS, bg=BG, fg=FG,
                 font=F, justify="left", padx=16, pady=10).pack()

        for label, attr in [("sessionKey :", "e_sk"), ("cf_clearance :", "e_cf")]:
            tk.Label(self.root, text=label, bg=BG, fg=ACC, font=FB,
                     anchor="w", padx=16).pack(fill="x")
            e = tk.Entry(self.root, bg="#12122a", fg=FG, font=F,
                         insertbackground=FG, width=72, relief="flat", bd=4)
            e.pack(padx=16, pady=(0, 8))
            setattr(self, attr, e)

        self.e_sk.focus()
        tk.Button(self.root, text="VALIDER", bg=ACC, fg="white",
                  font=FB, relief="flat", padx=12, pady=4,
                  command=self._ok).pack(pady=(0, 12))
        self.root.bind("<Return>", lambda _: self._ok())

    def _ok(self):
        sk = self.e_sk.get().strip()
        cf = self.e_cf.get().strip()
        if sk and cf:
            save_cookies(sk, cf)
            self.session_key  = sk
            self.cf_clearance = cf
        self.root.destroy()

# ── widget UI ─────────────────────────────────────────────────────────────────

class ClaudeWidget:
    BG     = "#0a0a14"
    BG2    = "#12122a"
    BORDER = "#2a2a5c"
    ACCENT = "#5555ff"
    GREEN  = "#44ff88"
    CYAN   = "#44ccff"
    ORANGE = "#ffaa44"
    DIM    = "#444466"
    WHITE  = "#ccccee"
    F      = ("Courier New", 10)
    FSM    = ("Courier New", 9)
    FH     = ("Courier New", 11, "bold")

    def __init__(self, session_key, cf_clearance):
        self.session_key  = session_key
        self.cf_clearance = cf_clearance
        self._tray = None
        self._iso_5h     = ""
        self._iso_7d     = ""
        self._iso_add_on = ""
        ctk.set_appearance_mode("dark")
        self.root = ctk.CTk()
        self.root.title("")
        self.root.geometry("300+40+40")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.93)
        self.root.overrideredirect(True)
        self.root.configure(fg_color=self.BG)
        self._dx = self._dy = 0
        self._build()
        self._position_bottom_right()
        self._start_tray()
        self._refresh_async()
        self._tick()

    def _position_bottom_right(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w  = self.root.winfo_width()
        h  = self.root.winfo_height()
        x = sw - w - 200
        y = sh - h - 220
        self.root.geometry(f"+{x}+{y}")

    def _start_drag(self, e): self._dx, self._dy = e.x, e.y
    def _drag(self, e):
        x = self.root.winfo_x() + e.x - self._dx
        y = self.root.winfo_y() + e.y - self._dy
        self.root.geometry(f"+{x}+{y}")

    def _bind_drag(self, *widgets):
        for w in widgets:
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>",     self._drag)

    def _build(self):
        outer = tk.Frame(self.root, bg=self.BORDER, bd=1)
        outer.pack(fill="both", expand=True, padx=1, pady=1)
        inner = tk.Frame(outer, bg=self.BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        hdr = tk.Frame(inner, bg=self.BG2, height=26)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        self._bind_drag(hdr)

        tk.Label(hdr, text="◈ CLAUDE USAGE", bg=self.BG2,
                 fg=self.ACCENT, font=self.FH).pack(side="left", padx=8)
        tk.Button(hdr, text="×", bg=self.BG2, fg=self.DIM,
                  font=("Courier New", 13, "bold"), relief="flat",
                  activebackground="#555577", activeforeground="white",
                  bd=0, padx=4, command=self._hide).pack(side="right")
        tk.Button(hdr, text="⚙", bg=self.BG2, fg=self.DIM,
                  font=("Courier New", 11), relief="flat", bd=0, padx=4,
                  activebackground=self.BORDER, activeforeground=self.WHITE,
                  command=self._reconfig).pack(side="right")

        body = tk.Frame(inner, bg=self.BG, padx=12, pady=8)
        body.pack(fill="both", expand=True)
        self._bind_drag(inner, body)
        self._body = body

        self.lbl_plan    = tk.Label(body, text="PLAN     : —",               bg=self.BG, fg=self.WHITE, font=self.F,   anchor="w")
        self.lbl_5h      = tk.Label(body, text="5H       : ░░░░░░░░░░  —%", bg=self.BG, fg=self.GREEN, font=self.F,   anchor="w")
        self.lbl_rst_5h  = tk.Label(body, text="  reset  : —",              bg=self.BG, fg=self.DIM,   font=self.FSM, anchor="w")
        self.lbl_7d      = tk.Label(body, text="7 JOURS  : ░░░░░░░░░░  —%", bg=self.BG, fg=self.CYAN,  font=self.F,   anchor="w")
        self.lbl_rst_7d  = tk.Label(body, text="  reset  : —",              bg=self.BG, fg=self.DIM,   font=self.FSM, anchor="w")
        self.lbl_add_on     = tk.Label(body, text="ADD-ON   : ░░░░░░░░░░  —%", bg=self.BG, fg=self.ORANGE, font=self.F,   anchor="w")
        self.lbl_rst_add_on = tk.Label(body, text="  reset  : —",              bg=self.BG, fg=self.DIM,    font=self.FSM, anchor="w")
        self.lbl_updated = tk.Label(body, text="UPDATED  : —",              bg=self.BG, fg=self.DIM,   font=self.FSM, anchor="w")

        for w in (self.lbl_plan, self.lbl_5h, self.lbl_rst_5h,
                  self.lbl_7d, self.lbl_rst_7d,
                  self.lbl_add_on, self.lbl_rst_add_on):
            w.pack(fill="x", pady=1)

        # add-on masqué par défaut
        self.lbl_add_on.pack_forget()
        self.lbl_rst_add_on.pack_forget()

        tk.Frame(body, bg=self.BORDER, height=1).pack(fill="x", pady=(6, 4))

        self.lbl_updated.pack(fill="x", pady=(0, 4))

        row = tk.Frame(body, bg=self.BG); row.pack(fill="x")
        self.btn_refresh = tk.Button(row, text="⟳ REFRESH", bg=self.BG2,
                                     fg=self.ACCENT, font=self.FSM, relief="flat",
                                     bd=0, padx=6, pady=2,
                                     activebackground=self.BORDER,
                                     command=self._force_refresh)
        self.btn_refresh.pack(side="left")
        self.lbl_status = tk.Label(row, text="", bg=self.BG, fg=self.DIM, font=self.FSM)
        self.lbl_status.pack(side="right")

    def _reset_label(self, iso, fmt_date):
        """Compose 'dd/mm HH:MM · dans Xh Ym'."""
        cd = _countdown(iso)
        return f"  reset  : {fmt_date}  {cd}" if cd else f"  reset  : {fmt_date}"

    def _set_add_on_visible(self, visible):
        self.lbl_add_on.pack_forget()
        self.lbl_rst_add_on.pack_forget()
        if visible:
            self.lbl_add_on.pack(fill="x", pady=1, after=self.lbl_rst_7d)
            self.lbl_rst_add_on.pack(fill="x", pady=1, after=self.lbl_add_on)

    def _tick(self):
        """Met à jour les comptes à rebours toutes les 30s sans appel réseau."""
        if self._iso_5h:
            cd = _countdown(self._iso_5h)
            t  = _fmt_reset(self._iso_5h)
            self.lbl_rst_5h.config(text=f"  reset  : {t}  {cd}" if cd else f"  reset  : {t}")
        if self._iso_7d:
            cd = _countdown(self._iso_7d)
            t  = _fmt_reset(self._iso_7d)
            self.lbl_rst_7d.config(text=f"  reset  : {t}  {cd}" if cd else f"  reset  : {t}")
        if self._iso_add_on:
            cd = _countdown(self._iso_add_on)
            t  = _fmt_reset(self._iso_add_on)
            self.lbl_rst_add_on.config(text=f"  reset  : {t}  {cd}" if cd else f"  reset  : {t}")
        self.root.after(30_000, self._tick)

    def _apply(self, data):
        self.lbl_plan.config(text=f"PLAN     : {data.get('plan','—').upper()}")

        fh = data.get("five_hour_pct")
        self.lbl_5h.config(
            text=f"5H       : {bar(fh)}  {fh:.0f}%" if fh is not None else "5H       : —")
        self._iso_5h = data.get("reset_5h_iso", "")
        self.lbl_rst_5h.config(text=self._reset_label(self._iso_5h, data.get("reset_5h", "—")))

        sd = data.get("seven_day_pct")
        self.lbl_7d.config(
            text=f"7 JOURS  : {bar(sd)}  {sd:.0f}%" if sd is not None else "7 JOURS  : —")
        self._iso_7d = data.get("reset_7d_iso", "")
        self.lbl_rst_7d.config(text=self._reset_label(self._iso_7d, data.get("reset_7d", "—")))

        ao = data.get("add_on_pct")
        if ao is not None:
            used  = data.get("add_on_used")
            limit = data.get("add_on_limit")
            cur   = data.get("add_on_currency", "")
            if used is not None and limit:
                used_e  = used  / 200
                limit_e = limit / 200
                detail = f"  {used_e:.2f}/{limit_e:.0f}{cur}"
            else:
                detail = f"  {ao:.0f}%"
            self.lbl_add_on.config(text=f"EXTRA    : {bar(ao)}{detail}")
            self._iso_add_on = data.get("reset_add_on_iso", "")
            rst_txt = self._reset_label(self._iso_add_on, data.get("reset_add_on", "—"))
            renewable = data.get("add_on_renewable", False)
            count     = data.get("add_on_recharge_count", 0)
            limit_e   = (data.get("add_on_limit") or 0) / 200
            cur       = data.get("add_on_currency", "")
            if renewable:
                cd  = _countdown(self._iso_add_on) if self._iso_add_on else ""
                txt = f"  auto-recharge {limit_e:.0f}{cur}"
                if count:
                    txt += f" · {count}× ce mois"
                if cd:
                    txt += f" · cap dans {cd}"
                self.lbl_rst_add_on.config(text=txt)
            else:
                self.lbl_rst_add_on.config(text="  non renouvelable")
            self._set_add_on_visible(True)
        else:
            self._iso_add_on = ""
            self._set_add_on_visible(False)

        self.lbl_updated.config(text=f"UPDATED  : {data.get('updated','—')}")
        self.lbl_status.config(text="ok", fg=self.GREEN)

    def _show_error(self, msg):
        self.lbl_status.config(text=f"err: {msg[:30]}", fg="#ff4444")

    def _force_refresh(self):
        self.btn_refresh.config(state="disabled")
        self.lbl_status.config(text="chargement…", fg=self.CYAN)
        threading.Thread(target=self._worker, daemon=True).start()

    def _refresh_async(self):
        cached = load_cache()
        if cached:
            self._apply(cached)
        self._force_refresh()
        self.root.after(REFRESH_INTERVAL * 1000, self._refresh_async)

    def _worker(self):
        try:
            data = fetch_usage(self.session_key, self.cf_clearance)
            self.root.after(0, lambda: self._apply(data))
        except Exception as e:
            self.root.after(0, lambda: self._show_error(str(e)))
        finally:
            self.root.after(0, lambda: self.btn_refresh.config(state="normal"))

    def _hide(self):
        self.root.withdraw()

    def _show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)

    def _quit(self):
        if self._tray:
            self._tray.stop()
        self.root.destroy()

    def _start_tray(self):
        import pystray
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle([4, 4, 27, 27], fill="#0a0a14", outline="#5555ff", width=2)
        d.text((9, 8), "C", fill="#5555ff")

        menu = pystray.Menu(
            pystray.MenuItem("Afficher",  lambda: self.root.after(0, self._show), default=True),
            pystray.MenuItem("Masquer",   lambda: self.root.after(0, self._hide)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⚙ Reconfigurer", lambda: self.root.after(0, self._reconfig)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter",   lambda: self.root.after(0, self._quit)),
        )
        self._tray = pystray.Icon("claude-usage", img, "Claude Usage", menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _reconfig(self):
        self.root.withdraw()
        dlg = SetupDialog()
        if dlg.session_key:
            self.session_key  = dlg.session_key
            self.cf_clearance = dlg.cf_clearance
        self.root.deiconify()
        self._force_refresh()

    def run(self):
        self.root.mainloop()

# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sk, cf = load_cookies()
    if not sk or not cf:
        dlg = SetupDialog()
        sk, cf = dlg.session_key, dlg.cf_clearance
        if not sk:
            raise SystemExit("Aucune clé fournie.")
    ClaudeWidget(sk, cf).run()
