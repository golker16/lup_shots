# app.py
import os, re, sys, json, wave, contextlib
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets, QtMultimedia
import qdarkstyle

APP_NAME = "Lup Shots"
APP_ORG  = "Lup"
VALID_EXTS = {".wav", ".aiff", ".aif", ".mp3", ".flac", ".ogg"}
WAVE_PEAKS = 140

CONFIG_DIR  = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = CONFIG_DIR / "config.json"

# ----------------- utilidades -----------------
def default_samples_dir() -> Path:
    music = Path(os.path.join(os.environ.get("USERPROFILE", str(Path.home())), "Music"))
    return music / "Lup Samples"

def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Por defecto marcamos que AÚN NO está hecho el primer arranque
    return {"samples_dir": str(default_samples_dir()), "first_run_done": False}

def save_config(cfg: dict):
    # Garantizar que siempre tenga la clave del primer arranque
    if "first_run_done" not in cfg:
        cfg["first_run_done"] = False
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

def parse_from_filename(filename: str):
    """
    GENERO_trap_X_drums_X_clap_snare_X_SQUISH_KEY_NO_.wav
    -> genre=trap, general=drums, specifics=['clap','snare'], title='SQUISH', key='—'
    """
    base = re.sub(r"\.[^.]+$", "", filename)
    parts = base.split("_X_")

    def clean(s):
        return re.sub(r"^GENERO_", "", s or "", flags=re.I).replace("_", " ").strip()

    genre   = clean(parts[0] if len(parts) > 0 else "")
    general = clean(parts[1] if len(parts) > 1 else "")
    specifics = []
    if len(parts) > 2:
        specifics = [t for t in re.split(r"[_\-]", parts[2]) if t]
    tail = "_X_".join(parts[3:]) if len(parts) > 3 else ""
    mkey = re.search(r"_KEY_([^_]+)_?", tail, flags=re.I)
    key = (mkey.group(1).upper() if mkey else "").strip() or "—"
    if key == "NO":
        key = "—"
    title = re.sub(r"_KEY_.+", "", tail).replace("_", " ").strip() or base
    return dict(genre=genre, general=general, specifics=specifics, title=title, key=key)

def read_pcm_waveform(path: Path, peaks=WAVE_PEAKS):
    """Onda rápida para WAV PCM; otros formatos → placeholder."""
    try:
        if path.suffix.lower() not in {".wav"}:
            return None, 0.0
        with contextlib.closing(wave.open(str(path), "rb")) as wf:
            n_channels = wf.getnchannels()
            n_frames   = wf.getnframes()
            framerate  = wf.getframerate()
            sampwidth  = wf.getsampwidth()
            duration   = n_frames / float(framerate) if framerate else 0.0

            blocks = peaks
            step = max(1, n_frames // blocks)
            import struct
            max_val = float(2 ** (8 * sampwidth - 1))
            out = []
            for i in range(blocks):
                wf.setpos(min(i * step, n_frames - 1))
                frames = wf.readframes(min(step, n_frames - i * step))
                fmt_char = {1:"b", 2:"h", 3:None, 4:"i"}[sampwidth]
                if fmt_char is None:  # 24-bit aprox
                    samples = []
                    for j in range(0, len(frames), 3 * n_channels):
                        chunk = frames[j:j+3]
                        if len(chunk) < 3: break
                        b = int.from_bytes(chunk, "little", signed=True)
                        samples.append(b / float(2**23))
                else:
                    fmt = "<" + fmt_char * (len(frames) // sampwidth)
                    ints = struct.unpack(fmt, frames)
                    samples = ints[0::n_channels]
                    samples = [x / (max_val or 1.0) for x in samples]
                peak = max(abs(min(samples)), max(samples)) if samples else 0.0
                out.append(peak)
            mx = max(out) if out else 1.0
            return [p / (mx or 1.0) for p in out], duration
    except Exception:
        return None, 0.0

def seconds_to_time(s):
    m = int(s // 60); ss = int(round(s % 60))
    return f"{m}:{ss:02d}"

def norm(s: str) -> str:
    return QtCore.QCollator().sortKey(s.lower())

# ----------------- widgets -----------------
class WaveWidget(QtWidgets.QWidget):
    def __init__(self, peaks=None, parent=None):
        super().__init__(parent); self._peaks = peaks or []; self.setMinimumHeight(42)
    def setPeaks(self, peaks): self._peaks = peaks or []; self.update()
    def paintEvent(self, e):
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        r = self.rect(); bg = QtGui.QColor("#0f172a"); fg = QtGui.QColor("#a1a1aa")
        p.fillRect(r, bg)
        if not self._peaks:
            p.setOpacity(0.25); y = r.center().y(); p.fillRect(QtCore.QRect(0, y-1, r.width(), 2), fg); return
        w, h, mid, bars = r.width(), r.height(), r.center().y(), len(self._peaks)
        for i, pk in enumerate(self._peaks):
            barw = max(1, int(w / bars)); bh = max(1, int(pk * h * .95))
            x = int(i * (w / bars)); y = int(mid - bh/2)
            p.fillRect(QtCore.QRect(x, y, int(barw * .9), bh), fg)

class TagChip(QtWidgets.QLabel):
    def __init__(self, text, tone, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet({
            "blue":   "background:#061e2b;color:#b3e4ff;border:1px solid #123043;border-radius:8px;padding:2px 8px;",
            "indigo": "background:#0c0e32;color:#c7c9ff;border:1px solid #1d226b;border-radius:8px;padding:2px 8px;",
            "green":  "background:#0e3b24;color:#d4ffe3;border:1px solid #1b5e3a;border-radius:8px;padding:2px 8px;",
        }[tone])
        self.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)

class SampleRow(QtWidgets.QWidget):
    playRequested = QtCore.Signal(object)
    def __init__(self, info, parent=None):
        super().__init__(parent); self.info = info; self.isPlaying = False
        self.btn = QtWidgets.QPushButton("▶"); self.btn.setFixedWidth(40)
        self.btn.clicked.connect(lambda: self.playRequested.emit(self))
        chips = []
        if info["genre"]:   chips.append(TagChip(info["genre"], "blue"))
        if info["general"]: chips.append(TagChip(info["general"], "indigo"))
        for t in info["specifics"]: chips.append(TagChip(t, "green"))
        tagsW = QtWidgets.QWidget(); h = QtWidgets.QHBoxLayout(tagsW); h.setContentsMargins(0,0,0,0); h.setSpacing(6)
        for c in chips: h.addWidget(c)
        name = QtWidgets.QLabel(info["title"]); name.setStyleSheet("color:#e5e7eb;"); name.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        row = QtWidgets.QHBoxLayout(); row.setContentsMargins(0,0,0,0); row.setSpacing(8)
        row.addWidget(tagsW); row.addWidget(name, 1); tagsWrap = QtWidgets.QWidget(); tagsWrap.setLayout(row)
        self.keyLbl = QtWidgets.QLabel(info["key"] or "—"); self.keyLbl.setAlignment(QtCore.Qt.AlignCenter)
        self.wave = WaveWidget(info.get("peaks"))
        grid = QtWidgets.QGridLayout(self); grid.setContentsMargins(10,10,10,10); grid.setHorizontalSpacing(10)
        grid.addWidget(self.btn, 0, 0); grid.addWidget(tagsWrap, 0, 1); grid.addWidget(self.keyLbl, 0, 2); grid.addWidget(self.wave, 0, 3)
        grid.setColumnStretch(1, 1); grid.setColumnStretch(3, 1)
    def setPlaying(self, v): self.isPlaying = v; self.btn.setText("■" if v else "▶")
    def setPeaks(self, peaks): self.wave.setPeaks(peaks)

# ----------------- Bienvenida (una sola ventana) -----------------
class WelcomeDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bienvenido a Lup Shots")
        self.setModal(True); self.setMinimumWidth(520)
        title = QtWidgets.QLabel("<b>Bienvenido a Lup Shots</b>")
        sub   = QtWidgets.QLabel("Selecciona la carpeta donde están (o pondrás) tus shots.")
        sub.setWordWrap(True)
        self.pathEdit = QtWidgets.QLineEdit(str(default_samples_dir()))
        browse = QtWidgets.QPushButton("Examinar…"); browse.clicked.connect(self._browse)
        row = QtWidgets.QHBoxLayout(); row.addWidget(self.pathEdit, 1); row.addWidget(browse)
        useBtn = QtWidgets.QPushButton("Usar esta carpeta"); useBtn.setDefault(True)
        cancel = QtWidgets.QPushButton("Cancelar")
        useBtn.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        btns = QtWidgets.QHBoxLayout(); btns.addStretch(1); btns.addWidget(cancel); btns.addWidget(useBtn)
        footer = QtWidgets.QLabel("© 2025 Gabriel Golker"); footer.setAlignment(QtCore.Qt.AlignHCenter); footer.setStyleSheet("color:#9ca3af; padding-top:8px;")
        lay = QtWidgets.QVBoxLayout(self); lay.addWidget(title); lay.addWidget(sub); lay.addLayout(row); lay.addLayout(btns); lay.addWidget(footer)
    def _browse(self):
        dlg = QtWidgets.QFileDialog(self, "Seleccionar carpeta de samples")
        dlg.setFileMode(QtWidgets.QFileDialog.Directory); dlg.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
        dlg.setDirectory(self.pathEdit.text())
        if dlg.exec(): self.pathEdit.setText(dlg.selectedFiles()[0])
    def selected_path(self) -> Path: return Path(self.pathEdit.text().strip() or str(default_samples_dir()))

# ----------------- Ventana principal (con bandeja del sistema) -----------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, samples_dir: Path):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.samples_dir = samples_dir
        # Audio
        self.player = QtMultimedia.QMediaPlayer()
        self.audio_out = QtMultimedia.QAudioOutput(); self.audio_out.setVolume(0.9)
        self.player.setAudioOutput(self.audio_out)
        # UI
        self._build_ui()
        self._init_tray()     # <— bandeja del sistema
        self._load_samples()
        self.search.textChanged.connect(self._apply_filter)

    # ---- Bandeja ----
    def _init_tray(self):
        # Ícono (fallback: icono estándar si no tienes .ico)
        icon = self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay)
        self.tray = QtWidgets.QSystemTrayIcon(icon, self)
        menu = QtWidgets.QMenu()
        act_show = menu.addAction("Mostrar Lup Shots"); act_show.triggered.connect(self._show_from_tray)
        act_change = menu.addAction("Cambiar carpeta de samples…"); act_change.triggered.connect(self.change_folder)
        menu.addSeparator()
        act_exit = menu.addAction("Salir"); act_exit.triggered.connect(self._exit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self._trayTipShown = False

    def _show_from_tray(self):
        self.showNormal(); self.activateWindow(); self.raise_()

    def _tray_activated(self, reason):
        if reason in (QtWidgets.QSystemTrayIcon.Trigger, QtWidgets.QSystemTrayIcon.DoubleClick):
            self._show_from_tray()

    def _exit_app(self):
        # Cerrar de verdad
        self.tray.hide()
        QtWidgets.QApplication.quit()

    def closeEvent(self, e: QtGui.QCloseEvent):
        # Ocultar a bandeja en lugar de salir
        e.ignore()
        self.hide()
        if not self._trayTipShown:
            self.tray.showMessage("Lup Shots", "Sigo ejecutándome en la bandeja. Doble clic para abrir.", QtWidgets.QSystemTrayIcon.Information, 4000)
            self._trayTipShown = True

    # ---- UI ----
    def _build_ui(self):
        central = QtWidgets.QWidget(); v = QtWidgets.QVBoxLayout(central)
        v.setContentsMargins(16,16,16,8); v.setSpacing(10)
        # Menú
        menu = self.menuBar(); file_menu = menu.addMenu("&Archivo")
        file_menu.addAction("Cambiar carpeta de &samples…").triggered.connect(self.change_folder)
        file_menu.addSeparator(); file_menu.addAction("Salir").triggered.connect(self._exit_app)
        # Buscador
        self.search = QtWidgets.QLineEdit(); self.search.setPlaceholderText("Buscar (tags, nombre o key)…"); v.addWidget(self.search)
        # Encabezado
        head = QtWidgets.QGridLayout(); head.setHorizontalSpacing(10)
        def muted(t): lab = QtWidgets.QLabel(t); lab.setStyleSheet("color:#9ca3af; text-transform:uppercase; letter-spacing:.08em; font-size:12px;"); return lab
        head.addWidget(muted(""), 0, 0); head.addWidget(muted("Etiquetas & Nombre"), 0, 1); head.addWidget(muted("Key"), 0, 2); head.addWidget(muted("Wave"), 0, 3)
        hw = QtWidgets.QWidget(); hw.setLayout(head); v.addWidget(hw)
        # Lista
        self.scroll = QtWidgets.QScrollArea(); self.scroll.setWidgetResizable(True)
        self.listHost = QtWidgets.QWidget(); self.listLayout = QtWidgets.QVBoxLayout(self.listHost)
        self.listLayout.setContentsMargins(0,0,0,0); self.listLayout.setSpacing(8)
        self.scroll.setWidget(self.listHost); v.addWidget(self.scroll, 1)
        # Footer
        footer = QtWidgets.QLabel("© 2025 Gabriel Golker"); footer.setAlignment(QtCore.Qt.AlignHCenter); footer.setStyleSheet("color:#9ca3af; padding: 8px 0;")
        v.addWidget(footer)
        self.setCentralWidget(central); self.resize(1120, 720)

    # ---- carpeta / recarga ----
    def change_folder(self):
        dlg = QtWidgets.QFileDialog(self, "Seleccionar carpeta de samples")
        dlg.setFileMode(QtWidgets.QFileDialog.Directory); dlg.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
        dlg.setDirectory(str(self.samples_dir))
        if dlg.exec():
            self.samples_dir = Path(dlg.selectedFiles()[0])
            cfg = load_config(); cfg["samples_dir"] = str(self.samples_dir); save_config(cfg)
            self._reload()

    def _collect_files(self):
        files = []
        for root, _, names in os.walk(self.samples_dir):
            for n in names:
                p = Path(root) / n
                if p.suffix.lower() in VALID_EXTS:
                    files.append(p)
        return sorted(files)

    def _load_samples(self):
        self.rows = []
        for p in self._collect_files():
            meta = parse_from_filename(p.name)
            peaks, duration = read_pcm_waveform(p)
            info = {
                "path": p, "filename": p.name, "duration": duration, "peaks": peaks,
                "genre": meta["genre"], "general": meta["general"], "specifics": meta["specifics"],
                "title": meta["title"], "key": meta["key"],
                "haystack": norm(" ".join([meta["genre"], meta["general"], " ".join(meta["specifics"]), meta["title"], (meta["key"] if meta["key"] != "—" else ""), p.name]))
            }
            row = SampleRow(info); row.playRequested.connect(self._toggle_play)
            self.rows.append(row); self.listLayout.addWidget(row)
        self.listLayout.addStretch(1)

    def _reload(self):
        while self.listLayout.count():
            it = self.listLayout.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        self._load_samples()

    # ---- búsqueda ----
    def _apply_filter(self, text: str):
        tokens = [t for t in text.strip().lower().split() if t]
        for row in self.rows:
            show = True
            if tokens: show = all(t in row.info["haystack"] for t in tokens)
            row.setVisible(show)

    # ---- audio ----
    def _toggle_play(self, row: SampleRow):
        if row.isPlaying:
            self._stop_all(); return
        self._stop_all()
        url = QtCore.QUrl.fromLocalFile(str(row.info["path"]))
        self.player.setSource(url); self.player.play(); row.setPlaying(True)
        self.player.mediaStatusChanged.connect(lambda st: self._on_status(st, row))
    def _stop_all(self):
        for r in self.rows:
            if r.isPlaying: r.setPlaying(False)
        self.player.stop()
    def _on_status(self, st, row):
        if st in (QtMultimedia.QMediaPlayer.EndOfMedia, QtMultimedia.QMediaPlayer.InvalidMedia): row.setPlaying(False)

# ----------------- arranque -----------------
def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # <— necesario para que el app siga vivo en bandeja
    app.setApplicationName(APP_NAME); app.setOrganizationName(APP_ORG)
    app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyside6"))

    cfg = load_config()
    # Mostrar SIEMPRE bienvenida si first_run_done es False, o si la carpeta no existe
    need_setup = (not cfg.get("first_run_done", False)) or (not Path(cfg.get("samples_dir", "")).exists())
    if need_setup:
        dlg = WelcomeDialog()
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            chosen = dlg.selected_path()
            if not chosen.exists():
                chosen.mkdir(parents=True, exist_ok=True)
            cfg["samples_dir"] = str(chosen)
            cfg["first_run_done"] = True
            save_config(cfg)
        else:
            sys.exit(0)

    samples_dir = Path(cfg["samples_dir"])
    w = MainWindow(samples_dir); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()



