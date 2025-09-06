# app.py
import os, re, sys, json, wave, contextlib, unicodedata
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
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if "first_run_done" not in cfg:
                cfg["first_run_done"] = False
            return cfg
        except Exception:
            pass
    return {"samples_dir": str(default_samples_dir()), "first_run_done": False}

def save_config(cfg: dict):
    if "first_run_done" not in cfg:
        cfg["first_run_done"] = False
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

def strip_accents_lower(s: str) -> str:
    # Para búsqueda robusta (arregla el “tiempo real”)
    nf = unicodedata.normalize("NFD", s or "")
    return "".join(ch for ch in nf if unicodedata.category(ch) != "Mn").lower()

def parse_from_filename(filename: str):
    """
    Ejemplo:
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
    key = (mkey.group(1).upper() if mkey else "").strip()
    key = "—" if (not key or key == "NO") else key
    title = re.sub(r"_KEY_.+", "", tail).replace("_", " ").strip() or base
    return dict(genre=genre, general=general, specifics=specifics, title=title, key=key)

def read_pcm_waveform(path: Path, peaks=WAVE_PEAKS):
    """
    Onda rápida para WAV PCM (sin deps extra).
    Para MP3/FLAC/OGG -> devuelve None (se dibuja línea/“barras” sin fondo).
    """
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

# ----------------- widgets -----------------
class WaveWidget(QtWidgets.QWidget):
    def __init__(self, peaks=None, parent=None):
        super().__init__(parent)
        self._peaks = peaks or []
        self.setMinimumHeight(42)
        # SIN FONDO
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")

    def setPeaks(self, peaks):
        self._peaks = peaks or []
        self.update()

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        r = self.rect()
        fg = QtGui.QColor("#a1a1aa")  # gris claro (solo la onda)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(fg)

        if not self._peaks:
            # línea del medio
            p.setOpacity(0.35)
            pen = QtGui.QPen(fg)
            pen.setWidth(2)
            p.setPen(pen)
            y = r.center().y()
            p.drawLine(0, y, r.width(), y)
            return

        w = r.width()
        h = r.height()
        mid = r.center().y()
        bars = len(self._peaks)
        for i, pk in enumerate(self._peaks):
            barw = max(1, int(w / bars))
            bh = max(1, int(pk * h * 0.95))
            x = int(i * (w / bars))
            y = int(mid - bh / 2)
            p.drawRect(QtCore.QRect(x, y, int(barw * 0.9), bh))

class TagChip(QtWidgets.QLabel):
    def __init__(self, text, tone="blue", parent=None):
        super().__init__(text, parent)
        styles = {
            "blue":   "background:#061e2b;color:#b3e4ff;border:1px solid #123043;",
            "indigo": "background:#0c0e32;color:#c7c9ff;border:1px solid #1d226b;",
            "green":  "background:#0e3b24;color:#d4ffe3;border:1px solid #1b5e3a;",
            "violet": "background:#311251;color:#e7ccff;border:1px solid #52227d;",  # KEY
            "gray":   "background:#2a2a33;color:#d1d5db;border:1px solid #3a3a44;",
        }
        self.setStyleSheet(f"{styles.get(tone,'gray')} border-radius:8px; padding:2px 8px;")
        self.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)

class SampleRow(QtWidgets.QFrame):
    playRequested = QtCore.Signal(object)

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.isPlaying = False

        self.setObjectName("SampleRow")
        self._apply_style()

        self.btn = QtWidgets.QPushButton("▶")
        self.btn.setFixedWidth(40)
        self.btn.clicked.connect(lambda: self.playRequested.emit(self))

        # Chips: género, general, específicos, y KEY como chip violeta
        chip_bar = QtWidgets.QHBoxLayout()
        chip_bar.setContentsMargins(0,0,0,0); chip_bar.setSpacing(6)
        if info["genre"]:
            chip_bar.addWidget(TagChip(info["genre"], "blue"))
        if info["general"]:
            chip_bar.addWidget(TagChip(info["general"], "indigo"))
        for t in info["specifics"]:
            chip_bar.addWidget(TagChip(t, "green"))
        chip_bar.addWidget(TagChip(info["key"] or "—", "violet"))

        chip_wrap = QtWidgets.QWidget()
        chip_wrap.setLayout(chip_bar)

        name = QtWidgets.QLabel(info["title"])
        name.setStyleSheet("color:#e5e7eb;")
        name.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        left = QtWidgets.QHBoxLayout()
        left.setContentsMargins(0,0,0,0); left.setSpacing(8)
        left.addWidget(chip_wrap); left.addWidget(name, 1)
        left_wrap = QtWidgets.QWidget(); left_wrap.setLayout(left)

        self.wave = WaveWidget(info.get("peaks"))

        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(10,10,10,10)
        grid.setHorizontalSpacing(10)
        grid.addWidget(self.btn, 0, 0)
        grid.addWidget(left_wrap, 0, 1)
        grid.addWidget(self.wave, 0, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

    def _apply_style(self):
        # base + seleccionado en azul si está reproduciendo
        if self.isPlaying:
            self.setStyleSheet(
                "#SampleRow { background: rgba(37,99,235,0.18); border:1px solid #3b82f6; border-radius:12px; }"
            )
        else:
            self.setStyleSheet(
                "#SampleRow { background: #1b1b23; border:1px solid #262632; border-radius:12px; }"
            )

    def setPlaying(self, v: bool):
        self.isPlaying = v
        self.btn.setText("■" if v else "▶")
        self._apply_style()

    def setPeaks(self, peaks):
        self.wave.setPeaks(peaks)

# ----------------- Bienvenida (una sola ventana) -----------------
class WelcomeDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bienvenido a Lup Shots")
        self.setModal(True)
        self.setMinimumWidth(520)

        title = QtWidgets.QLabel("<b>Bienvenido a Lup Shots</b>")
        sub   = QtWidgets.QLabel("Selecciona la carpeta donde están (o pondrás) tus shots.")
        sub.setWordWrap(True)

        self.pathEdit = QtWidgets.QLineEdit(str(default_samples_dir()))
        browse = QtWidgets.QPushButton("Examinar…")
        browse.clicked.connect(self._browse)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.pathEdit, 1)
        row.addWidget(browse)

        useBtn = QtWidgets.QPushButton("Usar esta carpeta")
        useBtn.setDefault(True)
        cancel = QtWidgets.QPushButton("Cancelar")
        useBtn.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)

        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(useBtn)

        footer = QtWidgets.QLabel("© 2025 Gabriel Golker")
        footer.setAlignment(QtCore.Qt.AlignHCenter)
        footer.setStyleSheet("color:#9ca3af; padding-top:8px;")

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addLayout(row)
        lay.addLayout(btns)
        lay.addWidget(footer)

    def _browse(self):
        dlg = QtWidgets.QFileDialog(self, "Seleccionar carpeta de samples")
        dlg.setFileMode(QtWidgets.QFileDialog.Directory)
        dlg.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
        dlg.setDirectory(self.pathEdit.text())
        if dlg.exec():
            self.pathEdit.setText(dlg.selectedFiles()[0])

    def selected_path(self) -> Path:
        return Path(self.pathEdit.text().strip() or str(default_samples_dir()))

# ----------------- Ventana principal -----------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, samples_dir: Path):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.samples_dir = samples_dir

        self.player = QtMultimedia.QMediaPlayer()
        self.audio_out = QtMultimedia.QAudioOutput()
        self.audio_out.setVolume(0.9)
        self.player.setAudioOutput(self.audio_out)

        self._build_ui()
        self._load_samples()
        self.search.textChanged.connect(self._apply_filter)

    def _build_ui(self):
        central = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(central)
        v.setContentsMargins(16,16,16,8)
        v.setSpacing(10)

        # Menú simple: cambiar carpeta / salir
        menu = self.menuBar()
        file_menu = menu.addMenu("&Archivo")
        act_change = file_menu.addAction("Cambiar carpeta de &samples…")
        act_change.triggered.connect(self.change_folder)
        file_menu.addSeparator()
        file_menu.addAction("Salir").triggered.connect(self.close)

        # Buscador (en tiempo real)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Buscar (tags, nombre o key)…")
        v.addWidget(self.search)

        # SIN encabezado de columnas (lo quitaste)

        # Lista
        self.scroll = QtWidgets.QScrollArea(); self.scroll.setWidgetResizable(True)
        self.listHost = QtWidgets.QWidget()
        self.listLayout = QtWidgets.QVBoxLayout(self.listHost)
        self.listLayout.setContentsMargins(0,0,0,0)
        self.listLayout.setSpacing(8)
        self.scroll.setWidget(self.listHost)
        v.addWidget(self.scroll, 1)

        # Footer
        footer = QtWidgets.QLabel("© 2025 Gabriel Golker")
        footer.setAlignment(QtCore.Qt.AlignHCenter)
        footer.setStyleSheet("color:#9ca3af; padding: 8px 0;")
        v.addWidget(footer)

        self.setCentralWidget(central)
        self.resize(1120, 720)

    def change_folder(self):
        dlg = QtWidgets.QFileDialog(self, "Seleccionar carpeta de samples")
        dlg.setFileMode(QtWidgets.QFileDialog.Directory)
        dlg.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
        dlg.setDirectory(str(self.samples_dir))
        if dlg.exec():
            self.samples_dir = Path(dlg.selectedFiles()[0])
            cfg = load_config(); cfg["samples_dir"] = str(self.samples_dir); save_config(cfg)
            self._reload()

    # -------- samples --------
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
            haystack = " ".join([
                meta["genre"], meta["general"], " ".join(meta["specifics"]),
                meta["title"], (meta["key"] if meta["key"] != "—" else ""), p.name
            ])
            info = {
                "path": p, "filename": p.name, "duration": duration, "peaks": peaks,
                "genre": meta["genre"], "general": meta["general"], "specifics": meta["specifics"],
                "title": meta["title"], "key": meta["key"],
                "haystack_norm": strip_accents_lower(haystack)
            }
            row = SampleRow(info)
            row.playRequested.connect(self._toggle_play)
            self.rows.append(row)
            self.listLayout.addWidget(row)
        self.listLayout.addStretch(1)

    def _reload(self):
        while self.listLayout.count():
            it = self.listLayout.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        self._load_samples()

    # -------- búsqueda (tiempo real) -----
    def _apply_filter(self, text: str):
        tokens = [strip_accents_lower(t) for t in text.strip().split() if t]
        for row in self.rows:
            if tokens:
                hay = row.info["haystack_norm"]
                show = all(t in hay for t in tokens)
            else:
                show = True
            row.setVisible(show)

    # -------- audio ----------
    def _toggle_play(self, row: SampleRow):
        # Si ya estaba reproduciendo, detén todo
        if row.isPlaying:
            self._stop_all()
            return
        self._stop_all()
        url = QtCore.QUrl.fromLocalFile(str(row.info["path"]))
        self.player.setSource(url)
        self.player.play()
        row.setPlaying(True)
        self.player.mediaStatusChanged.connect(lambda st: self._on_status(st, row))

    def _stop_all(self):
        for r in self.rows:
            if r.isPlaying:
                r.setPlaying(False)
        self.player.stop()

    def _on_status(self, st, row):
        if st in (QtMultimedia.QMediaPlayer.EndOfMedia, QtMultimedia.QMediaPlayer.InvalidMedia):
            row.setPlaying(False)

# ----------------- arranque -----------------
def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyside6"))

    cfg = load_config()
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
    w = MainWindow(samples_dir)
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()



