# app.py
import os
import re
import sys
import json
import wave
import contextlib
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets, QtMultimedia
import qdarkstyle

APP_NAME = "Lup Shots"
APP_ORG = "Lup"
CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = CONFIG_DIR / "config.json"

VALID_EXTS = {".wav", ".aiff", ".aif", ".mp3", ".flac", ".ogg"}
WAVE_PEAKS = 140  # barras mini-waveform


# ----------------- utils -----------------
def default_samples_dir() -> Path:
    # %USERPROFILE%\Music\Lup Samples
    music = Path(os.path.join(os.environ.get("USERPROFILE", str(Path.home())), "Music"))
    return music / "Lup Samples"

def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"samples_dir": str(default_samples_dir())}

def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

def choose_samples_dir(parent, starting: Path) -> Path:
    dlg = QtWidgets.QFileDialog(parent, "Seleccionar carpeta de samples")
    dlg.setFileMode(QtWidgets.QFileDialog.Directory)
    dlg.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
    dlg.setDirectory(str(starting))
    if dlg.exec():
        dirs = dlg.selectedFiles()
        if dirs:
            return Path(dirs[0])
    return starting

def parse_from_filename(filename: str):
    """
    Formato: GENERO_trap_X_drums_X_clap_snare_X_SQUISH_KEY_NO_.wav
    Devuelve: dict(genre, general, specifics[], title, key)
    """
    base = re.sub(r"\.[^.]+$", "", filename)
    parts = base.split("_X_")

    def clean(s):
        return re.sub(r"^GENERO_", "", s or "", flags=re.I).replace("_", " ").strip()

    genre = clean(parts[0] if len(parts) > 0 else "")
    general = clean(parts[1] if len(parts) > 1 else "")
    specifics = []
    if len(parts) > 2:
        specifics = [t for t in re.split(r"[_\-]", parts[2]) if t]
    tail = "_X_".join(parts[3:]) if len(parts) > 3 else ""
    key_match = re.search(r"_KEY_([^_]+)_?", tail, flags=re.I)
    key = (key_match.group(1).upper() if key_match else "").strip() or "—"
    if key == "NO":
        key = "—"
    title = re.sub(r"_KEY_.+", "", tail).replace("_", " ").strip() or base
    return dict(genre=genre, general=general, specifics=specifics, title=title, key=key)

def seconds_to_time(s):
    m = int(s // 60)
    ss = int(round(s % 60))
    return f"{m}:{ss:02d}"

def read_pcm_waveform(path: Path, peaks=WAVE_PEAKS):
    """
    Onda rápida para WAV PCM. Para otros formatos mostramos placeholder.
    """
    try:
        if path.suffix.lower() not in {".wav"}:
            return None, 0.0
        with contextlib.closing(wave.open(str(path), "rb")) as wf:
            n_channels = wf.getnchannels()
            n_frames = wf.getnframes()
            framerate = wf.getframerate()
            sampwidth = wf.getsampwidth()
            duration = n_frames / float(framerate) if framerate else 0.0

            blocks = peaks
            step = max(1, n_frames // blocks)
            import struct
            max_val = float(2 ** (8 * sampwidth - 1))
            out = []
            for i in range(blocks):
                wf.setpos(min(i * step, n_frames - 1))
                frames = wf.readframes(min(step, n_frames - i * step))
                fmt_char = {1: "b", 2: "h", 3: None, 4: "i"}[sampwidth]
                if fmt_char is None:  # 24-bit (aprox)
                    samples = []
                    for j in range(0, len(frames), 3 * n_channels):
                        chunk = frames[j : j + 3]
                        if len(chunk) < 3:
                            break
                        b = int.from_bytes(chunk, byteorder="little", signed=True)
                        samples.append(b / float(2 ** 23))
                else:
                    fmt = "<" + fmt_char * (len(frames) // sampwidth)
                    ints = struct.unpack(fmt, frames)
                    samples = ints[0::n_channels]
                    samples = [x / (max_val or 1.0) for x in samples]
                peak = max(abs(min(samples)), max(samples)) if samples else 0.0
                out.append(peak)
            mx = max(out) if out else 1.0
            out = [p / (mx or 1.0) for p in out]
            return out, duration
    except Exception:
        return None, 0.0

def norm(s: str) -> str:
    return QtCore.QCollator().sortKey(s.lower())


# ----------------- widgets -----------------
class WaveWidget(QtWidgets.QWidget):
    def __init__(self, peaks=None, parent=None):
        super().__init__(parent)
        self._peaks = peaks or []
        self.setMinimumHeight(42)

    def setPeaks(self, peaks):
        self._peaks = peaks or []
        self.update()

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        r = self.rect()
        bg = QtGui.QColor("#0f172a")
        fg = QtGui.QColor("#a1a1aa")
        p.fillRect(r, bg)
        if not self._peaks:
            p.setOpacity(0.25)
            y = r.center().y()
            p.fillRect(QtCore.QRect(0, y - 1, r.width(), 2), fg)
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
            p.fillRect(QtCore.QRect(x, y, int(barw * 0.9), bh), fg)

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
    playRequested = QtCore.Signal(object)  # self

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.isPlaying = False

        self.btn = QtWidgets.QPushButton("▶")
        self.btn.setFixedWidth(40)
        self.btn.clicked.connect(lambda: self.playRequested.emit(self))

        chips = []
        if info["genre"]:
            chips.append(TagChip(info["genre"], "blue"))
        if info["general"]:
            chips.append(TagChip(info["general"], "indigo"))
        for t in info["specifics"]:
            chips.append(TagChip(t, "green"))
        self.tagsW = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(self.tagsW); h.setContentsMargins(0,0,0,0); h.setSpacing(6)
        for c in chips: h.addWidget(c)

        self.nameLbl = QtWidgets.QLabel(info["title"])
        self.nameLbl.setStyleSheet("color:#e5e7eb;")
        self.nameLbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        tagsLine = QtWidgets.QHBoxLayout()
        tagsLine.setContentsMargins(0,0,0,0)
        tagsLine.setSpacing(8)
        tagsLine.addWidget(self.tagsW)
        tagsLine.addWidget(self.nameLbl, 1)
        tagsWrap = QtWidgets.QWidget(); tagsWrap.setLayout(tagsLine)

        self.keyLbl = QtWidgets.QLabel(info["key"] or "—")
        self.keyLbl.setAlignment(QtCore.Qt.AlignCenter)

        self.wave = WaveWidget(info.get("peaks"))

        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(10,10,10,10)
        grid.setHorizontalSpacing(10)
        grid.addWidget(self.btn, 0, 0)
        grid.addWidget(tagsWrap, 0, 1)
        grid.addWidget(self.keyLbl, 0, 2)
        grid.addWidget(self.wave, 0, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

    def setPlaying(self, playing: bool):
        self.isPlaying = playing
        self.btn.setText("■" if playing else "▶")

    def setPeaks(self, peaks):
        self.wave.setPeaks(peaks)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.player = QtMultimedia.QMediaPlayer()
        self.audio_out = QtMultimedia.QAudioOutput()
        self.audio_out.setVolume(0.9)
        self.player.setAudioOutput(self.audio_out)

        # config & samples dir (primer arranque pide carpeta)
        self.cfg = load_config()
        self.samples_dir = Path(self.cfg.get("samples_dir", default_samples_dir()))
        if not self.samples_dir.exists():
            self.samples_dir = default_samples_dir()
        self.ensure_samples_dir()

        # UI
        self._build_ui()
        self._load_samples()
        self.search.textChanged.connect(self._apply_filter)

    # ----- UI -----
    def _build_ui(self):
        central = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(central)
        v.setContentsMargins(16,16,16,8)
        v.setSpacing(10)

        # Menú
        menu = self.menuBar()
        file_menu = menu.addMenu("&Archivo")
        act_change = file_menu.addAction("Cambiar carpeta de &samples…")
        act_change.triggered.connect(self.change_folder)
        file_menu.addSeparator()
        file_menu.addAction("Salir").triggered.connect(self.close)

        # buscador
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Buscar (tags, nombre o key)…")
        v.addWidget(self.search)

        # encabezado
        head = QtWidgets.QGridLayout()
        head.setHorizontalSpacing(10)
        head.addWidget(self._muted(""), 0, 0)
        head.addWidget(self._muted("Etiquetas & Nombre"), 0, 1)
        head.addWidget(self._muted("Key"), 0, 2)
        head.addWidget(self._muted("Wave"), 0, 3)
        headW = QtWidgets.QWidget(); headW.setLayout(head)
        v.addWidget(headW)

        # lista
        self.scroll = QtWidgets.QScrollArea(); self.scroll.setWidgetResizable(True)
        self.listHost = QtWidgets.QWidget()
        self.listLayout = QtWidgets.QVBoxLayout(self.listHost)
        self.listLayout.setContentsMargins(0,0,0,0)
        self.listLayout.setSpacing(8)
        self.scroll.setWidget(self.listHost)
        v.addWidget(self.scroll, 1)

        # footer
        footer = QtWidgets.QLabel("© 2025 Gabriel Golker")
        footer.setAlignment(QtCore.Qt.AlignHCenter)
        footer.setStyleSheet("color:#9ca3af; padding: 8px 0;")
        v.addWidget(footer)

        self.setCentralWidget(central)
        self.resize(1120, 720)

    def _muted(self, txt):
        lab = QtWidgets.QLabel(txt)
        lab.setStyleSheet("color:#9ca3af; text-transform:uppercase; letter-spacing:.08em; font-size:12px;")
        return lab

    # ----- samples -----
    def ensure_samples_dir(self):
        # Primer arranque: preguntar y crear por defecto si no existe
        if not self.samples_dir.exists():
            self.samples_dir = default_samples_dir()
        if not self.samples_dir.exists():
            self.samples_dir.mkdir(parents=True, exist_ok=True)

        # Si no hay config guardada, ofrezco seleccionar (con default sugerida)
        first_run = not CONFIG_PATH.exists()
        if first_run:
            chosen = choose_samples_dir(self, self.samples_dir)
            self.samples_dir = chosen
            self.cfg["samples_dir"] = str(self.samples_dir)
            save_config(self.cfg)

    def change_folder(self):
        chosen = choose_samples_dir(self, self.samples_dir)
        self.samples_dir = chosen
        self.cfg["samples_dir"] = str(self.samples_dir)
        save_config(self.cfg)
        self._reload_samples()

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
        files = self._collect_files()
        for p in files:
            meta = parse_from_filename(p.name)
            peaks, duration = read_pcm_waveform(p)
            info = {
                "path": p,
                "filename": p.name,
                "genre": meta["genre"],
                "general": meta["general"],
                "specifics": meta["specifics"],
                "title": meta["title"],
                "key": meta["key"],
                "duration": duration,
                "peaks": peaks,
                "haystack": norm(
                    " ".join([meta["genre"], meta["general"], " ".join(meta["specifics"]), meta["title"], meta["key"] if meta["key"] != "—" else "", p.name])
                ),
            }
            row = SampleRow(info)
            row.playRequested.connect(self._toggle_play)
            self.rows.append(row)
            self.listLayout.addWidget(row)
        self.listLayout.addStretch(1)

    def _reload_samples(self):
        while self.listLayout.count():
            it = self.listLayout.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        self._load_samples()

    # ----- búsqueda -----
    def _apply_filter(self, text: str):
        tokens = [t for t in text.strip().lower().split() if t]
        for row in self.rows:
            show = True
            if tokens:
                show = all(t in row.info["haystack"] for t in tokens)
            row.setVisible(show)

    # ----- audio -----
    def _toggle_play(self, row: 'SampleRow'):
        # si ya estaba sonando, detener
        if row.isPlaying:
            self.player.stop()
            row.setPlaying(False)
            return
        # parar otros
        for r in self.rows:
            if r.isPlaying:
                r.setPlaying(False)
        # reproducir
        url = QtCore.QUrl.fromLocalFile(str(row.info["path"]))
        self.player.setSource(url)
        self.player.play()
        row.setPlaying(True)
        self.player.mediaStatusChanged.connect(lambda st: self._on_status(st, row))

    def _on_status(self, status, row):
        if status in (QtMultimedia.QMediaPlayer.EndOfMedia, QtMultimedia.QMediaPlayer.InvalidMedia):
            row.setPlaying(False)


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyside6"))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
