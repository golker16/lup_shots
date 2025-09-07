# app.py — Lup Shots (escala 5k+)
import os, re, sys, json, wave, contextlib, unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

from PySide6 import QtCore, QtGui, QtWidgets, QtMultimedia
import qdarkstyle

APP_NAME = "Lup Shots"
APP_ORG  = "Lup"
VALID_EXTS = {".wav", ".aiff", ".aif", ".mp3", ".flac", ".ogg"}
WAVE_BARS = 160

CONFIG_DIR  = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = CONFIG_DIR / "config.json"

def default_samples_dir() -> Path:
    music = Path(os.path.join(os.environ.get("USERPROFILE", str(Path.home())), "Music"))
    return music / "Lup Samples"

def load_config():
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.setdefault("first_run_done", False)
            cfg.setdefault("favorites", [])
            return cfg
        except Exception:
            pass
    return {"samples_dir": str(default_samples_dir()), "first_run_done": False, "favorites": []}

def save_config(cfg: dict):
    cfg.setdefault("first_run_done", False)
    cfg.setdefault("favorites", [])
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

def strip_accents_lower(s: str) -> str:
    import unicodedata
    nf = unicodedata.normalize("NFD", s or "")
    return "".join(ch for ch in nf if unicodedata.category(ch) != "Mn").lower()

def parse_from_filename(filename: str):
    base = re.sub(r"\.[^.]+$", "", filename)
    parts = base.split("_X_")
    def clean(s): return (s or "").strip()
    graw = clean(parts[0] if len(parts)>0 else "")
    genres = [t for t in re.sub(r"^GENERO_", "", graw, flags=re.I).split("_") if t]
    generals = [t for t in clean(parts[1] if len(parts)>1 else "").split("_") if t]
    specifics = [t for t in clean(parts[2] if len(parts)>2 else "").split("_") if t]
    tail = "_X_".join(parts[3:]) if len(parts) > 3 else ""
    title = re.sub(r"_KEY_.+", "", tail).replace("_", " ").strip() or base
    mkey = re.search(r"_KEY_([^_]+)_?", tail, flags=re.I)
    key = (mkey.group(1).upper() if mkey else "").strip()
    key = None if (not key or key == "NO") else key
    return dict(genres=genres, generals=generals, specifics=specifics, title=title, key=key)

def read_wav_meta_and_peaks(path: Path, bars=WAVE_BARS):
    """Solo WAV (rápido y sin deps). Otros formatos => meta mínima."""
    if path.suffix.lower() != ".wav":
        return None, None, None, None, None  # duration, sr, bitdepth, peaks, channels
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as wf:
            ch = wf.getnchannels(); n = wf.getnframes(); sr = wf.getframerate()
            sw = wf.getsampwidth(); bd = sw * 8
            dur = n / float(sr) if sr else 0.0
            step = max(1, n // bars)
            import struct
            fmt_char = {1:"b", 2:"h", 3:None, 4:"i"}[sw]
            peaks = []
            maxv = float(2 ** (8*sw - 1))
            for i in range(bars):
                wf.setpos(min(i*step, n-1))
                frames = wf.readframes(min(step, n - i*step))
                if fmt_char is None:  # 24-bit
                    vals = []
                    frame_size = ch * 3
                    for j in range(0, len(frames) - (frame_size - 1), frame_size):
                        v = int.from_bytes(frames[j:j+3], "little", signed=True)
                        vals.append(v / float(2**23))
                else:
                    fmt = "<" + fmt_char * (len(frames)//sw)
                    ints = struct.unpack(fmt, frames) if frames else ()
                    vals = ints[0::ch]
                    vals = [v/(maxv or 1.0) for v in vals]
                peak = max(abs(min(vals)), max(vals)) if vals else 0.0
                peaks.append(peak)
            mx = max(peaks) if peaks else 1.0
            peaks = [p / (mx or 1.0) for p in peaks]
            return dur, sr, bd, peaks, ch
    except Exception:
        return None, None, None, None, None

def fmt_khz(sr: Optional[int]):
    if not sr: return "—"
    khz = sr/1000.0
    return f"{khz:.0f} kHz" if abs(khz-round(khz))<1e-6 else f"{khz:.1f} kHz"

def fmt_dur(s: Optional[float]):
    return f"{(s or 0.0):.2f}s"
# ------------------------------------------------------------------------------------

@dataclass
class SampleEntry:
    path: Path
    title: str
    genres: List[str]
    generals: List[str]
    specifics: List[str]
    key: Optional[str]
    tagset: Set[str]
    haystack: str
    favorite: bool = False

    # lazy meta
    duration: Optional[float] = None
    samplerate: Optional[int] = None
    bitdepth: Optional[int] = None
    channels: Optional[int] = None
    peaks: Optional[List[float]] = None

# ------------------------- Modelo -------------------------
class SampleModel(QtCore.QAbstractListModel):
    Roles = {
        "PathRole": QtCore.Qt.UserRole + 1,
        "TitleRole": QtCore.Qt.UserRole + 2,
        "TagsRole": QtCore.Qt.UserRole + 3,
        "KeyRole": QtCore.Qt.UserRole + 4,
        "FavRole": QtCore.Qt.UserRole + 5,
        "PeaksRole": QtCore.Qt.UserRole + 6,
        "DurRole": QtCore.Qt.UserRole + 7,
        "SRRole": QtCore.Qt.UserRole + 8,
        "BDRole": QtCore.Qt.UserRole + 9,
        "TagsetRole": QtCore.Qt.UserRole + 10,
        "HayRole": QtCore.Qt.UserRole + 11,
    }
    def __init__(self):
        super().__init__()
        self.items: List[SampleEntry] = []

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, idx, role=QtCore.Qt.DisplayRole):
        if not idx.isValid(): return None
        s = self.items[idx.row()]
        if role == self.Roles["PathRole"]:  return str(s.path)
        if role == self.Roles["TitleRole"]: return s.title
        if role == self.Roles["TagsRole"]:  return (s.genres, s.generals, s.specifics)
        if role == self.Roles["KeyRole"]:   return s.key
        if role == self.Roles["FavRole"]:   return s.favorite
        if role == self.Roles["PeaksRole"]: return s.peaks
        if role == self.Roles["DurRole"]:   return s.duration
        if role == self.Roles["SRRole"]:    return s.samplerate
        if role == self.Roles["BDRole"]:    return s.bitdepth
        if role == self.Roles["TagsetRole"]:return s.tagset
        if role == self.Roles["HayRole"]:   return s.haystack
        if role == QtCore.Qt.DisplayRole:   return s.title
        return None

    def flags(self, idx):
        return QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable

    def add_item(self, ent: SampleEntry):
        self.beginInsertRows(QtCore.QModelIndex(), len(self.items), len(self.items))
        self.items.append(ent)
        self.endInsertRows()

    def set_favorite(self, row: int, fav: bool):
        self.items[row].favorite = fav
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [self.Roles["FavRole"]])

    def set_meta(self, row: int, duration, sr, bd, peaks, ch):
        s = self.items[row]
        s.duration, s.samplerate, s.bitdepth, s.peaks, s.channels = duration, sr, bd, peaks, ch
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [self.Roles["PeaksRole"], self.Roles["DurRole"], self.Roles["SRRole"], self.Roles["BDRole"]])

# ------------------- Proxy (búsqueda / orden) -------------------
class SampleProxy(QtCore.QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.tokens: List[str] = []
        self.setDynamicSortFilter(True)

    def set_search(self, text: str):
        self.tokens = [strip_accents_lower(t) for t in text.strip().split() if t]
        self.invalidateFilter()

    def filterAcceptsRow(self, src_row, src_parent):
        m: SampleModel = self.sourceModel()  # type: ignore
        idx = m.index(src_row)
        hay = m.data(idx, m.Roles["HayRole"]) or ""
        for t in self.tokens:
            if t not in hay: return False
        return True

    def lessThan(self, left, right):
        m: SampleModel = self.sourceModel()  # type: ignore
        favL = bool(m.data(left,  m.Roles["FavRole"]))
        favR = bool(m.data(right, m.Roles["FavRole"]))
        if favL != favR: return favR  # fav primero
        a = strip_accents_lower(m.data(left,  m.Roles["TitleRole"]) or "")
        b = strip_accents_lower(m.data(right, m.Roles["TitleRole"]) or "")
        return a < b

# ------------------- Scanner en background -------------------
class Scanner(QtCore.QThread):
    found = QtCore.Signal(object)  # SampleEntry
    done  = QtCore.Signal()
    def __init__(self, root: Path, favorites: Set[str]):
        super().__init__()
        self.root = root
        self.favorites = favorites
    def run(self):
        for r, _, files in os.walk(self.root):
            for n in files:
                p = Path(r) / n
                if p.suffix.lower() not in VALID_EXTS: continue
                meta = parse_from_filename(p.name)
                tags = meta["genres"] + meta["generals"] + meta["specifics"]
                if meta["key"]: tags.append(meta["key"])
                hay = strip_accents_lower(" ".join([*tags, meta["title"], p.name]))
                ent = SampleEntry(
                    path=p, title=meta["title"], genres=meta["genres"],
                    generals=meta["generals"], specifics=meta["specifics"],
                    key=meta["key"], tagset=set(tags), haystack=hay,
                    favorite=(p.name in self.favorites)
                )
                self.found.emit(ent)
        self.done.emit()

# -------- Worker de meta/peaks (lazy al seleccionar) ----------
class MetaWorker(QtCore.QThread):
    ready = QtCore.Signal(int, float, int, int, list, int)  # row, dur, sr, bd, peaks, ch
    def __init__(self, model: SampleModel, row: int):
        super().__init__()
        self.model = model; self.row = row
    def run(self):
        s = self.model.items[self.row]
        dur, sr, bd, peaks, ch = read_wav_meta_and_peaks(s.path)
        self.ready.emit(self.row, dur or 0.0, sr or 0, bd or 0, peaks or [], ch or 0)

# ------------------- Delegate (pinta filas + waveform) -------------------
class RowDelegate(QtWidgets.QStyledItemDelegate):
    ROW_H = 48
    WAVE_H = 78
    PADDING = 10

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex):
        painter.save()
        r = option.rect
        hovered = option.state & QtWidgets.QStyle.State_MouseOver
        selected = option.state & QtWidgets.QStyle.State_Selected

        # fondo
        bg = QtGui.QColor("#19191d")
        border = QtGui.QColor("#303039")
        if selected:
            bg = QtGui.QColor(37,99,235,46)
            border = QtGui.QColor("#3b82f6")
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        path = QtGui.QPainterPath()
        path.addRoundedRect(r.adjusted(3,3,-3,-3), 10, 10)
        painter.fillPath(path, bg)
        pen = QtGui.QPen(border); pen.setWidth(1); painter.setPen(pen); painter.drawPath(path)

        # áreas
        playRect = QtCore.QRect(r.left()+14, r.top()+12, 24, 24)
        starRect = QtCore.QRect(r.right()-34, r.top()+12, 20, 20)
        chipsX = playRect.right()+12
        chipsMaxX = starRect.left()-12

        # chips (género/ general/ específicos / key)
        def draw_chip(x, y, text, color):
            fm = option.fontMetrics
            w = fm.horizontalAdvance(text) + 16
            rect = QtCore.QRect(x, y, w, 22)
            painter.fillRect(rect, QtGui.QColor(color))
            painter.setPen(QtGui.QPen(QtGui.QColor("#e5e7eb")))
            painter.drawText(rect.adjusted(8,0,-8,0), QtCore.Qt.AlignVCenter|QtCore.Qt.AlignLeft, text)
            return rect.right()+6

        genres, generals, specifics = index.data(SampleModel.Roles["TagsRole"])
        x = chipsX; y = r.top()+12
        for t in genres:   x = draw_chip(x,y,t,"#0b2530")
        for t in generals: x = draw_chip(x,y,t,"#12183c")
        for t in specifics: 
            if x+60 < chipsMaxX: x = draw_chip(x,y,t,"#0f3d28")

        # título
        painter.setPen(QtGui.QColor("#e5e7eb"))
        title = index.data(SampleModel.Roles["TitleRole"]) or ""
        painter.drawText(QtCore.QRect(x, y, max(0, chipsMaxX-x), 22), QtCore.Qt.AlignVCenter|QtCore.Qt.AlignLeft, title)

        # estrella
        fav = bool(index.data(SampleModel.Roles["FavRole"]))
        painter.setPen(QtGui.QColor("#facc15" if fav else "#9ca3af"))
        painter.drawText(starRect, QtCore.Qt.AlignCenter, "★" if fav else "☆")

        # si está seleccionado, dibujar waveform y pills
        if selected:
            y0 = r.top() + self.ROW_H
            waveRect = QtCore.QRect(r.left()+16, y0+6, r.width()-32, self.WAVE_H-16)
            peaks = index.data(SampleModel.Roles["PeaksRole"]) or []
            # barras
            painter.setPen(QtCore.Qt.NoPen)
            if peaks:
                painter.setBrush(QtGui.QColor("#ffffff"))
                W = waveRect.width(); H = waveRect.height()
                mid = waveRect.center().y()
                bars = len(peaks); barW = max(1, int(W / bars))
                for i, p in enumerate(peaks):
                    h = max(1, int(p * H * 0.95))
                    yb = int(mid - h/2); xb = waveRect.left() + int(i * (W / bars))
                    painter.drawRect(QtCore.QRect(xb, yb, int(barW*0.9), h))
            else:
                painter.setBrush(QtGui.QColor("#3a3a44"))
                painter.drawRect(waveRect)

            # pills (derecha)
            sr  = index.data(SampleModel.Roles["SRRole"])
            bd  = index.data(SampleModel.Roles["BDRole"])
            dur = index.data(SampleModel.Roles["DurRole"])
            pills = [fmt_khz(sr), (f"{bd}-bit" if bd else "—"), fmt_dur(dur)]
            px = waveRect.right()
            for txt in reversed(pills):
                fm = option.fontMetrics
                w = fm.horizontalAdvance(txt) + 16
                rect = QtCore.QRect(px - w, waveRect.top()-26, w, 22)
                painter.fillRect(rect, QtGui.QColor("#232327"))
                painter.setPen(QtGui.QPen(QtGui.QColor("#d1d5db")))
                painter.drawText(rect.adjusted(8,0,-8,0), QtCore.Qt.AlignVCenter|QtCore.Qt.AlignLeft, txt)
                px -= (w + 8)

            # play button (icono)
        painter.setPen(QtGui.QPen(QtGui.QColor("#e5e7eb")))
        painter.drawText(playRect, QtCore.Qt.AlignCenter, "▶")

        painter.restore()

    def sizeHint(self, option, index):
        # si está seleccionado, sumar wave
        view = option.widget  # QListView
        selected = False
        if hasattr(view, "selectionModel"):
            selected = view.selectionModel().isSelected(index)
        h = self.ROW_H + (self.WAVE_H if selected else 0) + 12
        return QtCore.QSize(option.rect.width(), h)

# ------------------- Ventana -------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, samples_dir: Path):
        super().__init__()
        self.setWindowTitle("Lup Shots")
        self.samples_dir = samples_dir
        cfg = load_config()
        self.favorites = set(cfg.get("favorites", []))

        # Audio
        self.player = QtMultimedia.QMediaPlayer()
        self.audio_out = QtMultimedia.QAudioOutput()
        self.audio_out.setVolume(0.9)
        self.player.setAudioOutput(self.audio_out)
        self.player.mediaStatusChanged.connect(self._on_status)

        # Modelo/Proxy
        self.model = SampleModel()
        self.proxy = SampleProxy()
        self.proxy.setSourceModel(self.model)
        self.proxy.sort(0)

        # UI
        self._build_ui()

        # Escaneo en background
        self._scan_thread = Scanner(self.samples_dir, self.favorites)
        self._scan_thread.found.connect(self.model.add_item)
        self._scan_thread.done.connect(lambda: None)
        self._scan_thread.start()

    def _build_ui(self):
        central = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(central); v.setContentsMargins(16,16,16,8); v.setSpacing(10)

        self.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyside6") + "\nQWidget{background-color:#121214;}")

        menubar = self.menuBar(); menubar.setNativeMenuBar(False)
        opt = menubar.addMenu("&Opciones")
        opt.addAction("Cambiar carpeta de &samples…").triggered.connect(self.change_folder)
        donate_btn = QtWidgets.QPushButton("Donar")
        donate_btn.setStyleSheet("QPushButton{background:#16a34a;color:white;border:1px solid #15803d;border-radius:8px;padding:3px 10px;} QPushButton:hover{background:#22c55e;}")
        donate_btn.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl("https://www.gabrielgolker.com")))
        menubar.setCornerWidget(donate_btn, QtCore.Qt.TopRightCorner)
        QtCore.QTimer.singleShot(0, lambda: donate_btn.setFixedHeight(menubar.height()-2))

        # búsqueda
        self.search = QtWidgets.QLineEdit(placeholderText="Buscar (tags, nombre o key)…")
        self.search.textChanged.connect(self.proxy.set_search)
        v.addWidget(self.search)

        # contador resultados
        self.countLbl = QtWidgets.QLabel("0 resultados"); self.countLbl.setStyleSheet("color:#9ca3af;")
        v.addWidget(self.countLbl, 0, QtCore.Qt.AlignRight)

        # lista
        self.view = QtWidgets.QListView()
        self.view.setModel(self.proxy)
        self.view.setItemDelegate(RowDelegate())
        self.view.setUniformItemSizes(False)
        self.view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.view.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.view.setStyleSheet("QListView{border:none;}")
        self.view.clicked.connect(self._row_clicked)
        self.view.selectionModel().selectionChanged.connect(self._selection_changed)
        v.addWidget(self.view, 1)

        footer = QtWidgets.QLabel("© 2025 Gabriel Golker")
        footer.setAlignment(QtCore.Qt.AlignHCenter); footer.setStyleSheet("color:#9ca3af; padding:8px 0;")
        v.addWidget(footer)

        self.setCentralWidget(central)
        self.resize(1180, 760)

        # contador dinámico
        self.proxy.rowsInserted.connect(self._update_count)
        self.proxy.rowsRemoved.connect(self._update_count)
        self.proxy.modelReset.connect(self._update_count)
        self.proxy.layoutChanged.connect(self._update_count)
        self._update_count()

        # teclas
        self.installEventFilter(self)

    def _update_count(self, *a):
        self.countLbl.setText(f"{self.proxy.rowCount()} resultado" + ("" if self.proxy.rowCount()==1 else "s"))

    # click = play/pause
    def _row_clicked(self, idx: QtCore.QModelIndex):
        self._play_index(idx)

    def _play_index(self, proxy_index: QtCore.QModelIndex):
        if not proxy_index.isValid(): return
        # seleccionar si no lo está
        self.view.selectionModel().select(proxy_index, QtCore.QItemSelectionModel.ClearAndSelect)
        src = self.proxy.mapToSource(proxy_index)
        row = src.row()

        # si no hay meta/peaks -> calcular lazy en hilo y luego reproducir
        s = self.model.items[row]
        def start_play():
            url = QtCore.QUrl.fromLocalFile(str(s.path))
            self.player.setSource(url)
            self.player.setPosition(0)
            self.player.play()
            # refrescar fila para que crezca y muestre waveform/meta
            i = self.model.index(row)
            self.model.dataChanged.emit(i, i)

        if s.peaks is None and s.path.suffix.lower()==".wav":
            worker = MetaWorker(self.model, row)
            worker.ready.connect(lambda r, d, sr, bd, peaks, ch: (self.model.set_meta(r,d,sr,bd,peaks,ch), start_play()))
            worker.start()
        else:
            start_play()

    def _selection_changed(self):
        # Redibuja para expandir la seleccionada
        self.view.viewport().update()

    def _on_status(self, st):
        if st == QtMultimedia.QMediaPlayer.EndOfMedia:
            self.player.setPosition(0)

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.KeyPress:
            key = ev.key()
            if key in (QtCore.Qt.Key_Down, QtCore.Qt.Key_Up):
                rows = self.proxy.rowCount()
                if rows == 0: return True
                sel = self.view.selectionModel().currentIndex()
                if not sel.isValid():
                    target = self.proxy.index(0 if key==QtCore.Qt.Key_Down else rows-1, 0)
                else:
                    r = sel.row() + (1 if key==QtCore.Qt.Key_Down else -1)
                    r = max(0, min(rows-1, r))
                    target = self.proxy.index(r, 0)
                self._play_index(target)
                self.view.scrollTo(target, QtWidgets.QAbstractItemView.PositionAtCenter)
                return True
            if key == QtCore.Qt.Key_Space:
                sel = self.view.selectionModel().currentIndex()
                if sel.isValid(): self._play_index(sel); return True
        return super().eventFilter(obj, ev)

    def change_folder(self):
        dlg = QtWidgets.QFileDialog(self, "Seleccionar carpeta de samples")
        dlg.setFileMode(QtWidgets.QFileDialog.Directory); dlg.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
        dlg.setDirectory(str(self.samples_dir))
        if dlg.exec():
            self.samples_dir = Path(dlg.selectedFiles()[0])
            cfg = load_config(); cfg["samples_dir"] = str(self.samples_dir); save_config(cfg)
            # reset
            self.model.beginResetModel(); self.model.items.clear(); self.model.endResetModel()
            self.proxy.invalidate()
            if hasattr(self, "_scan_thread") and self._scan_thread.isRunning():
                self._scan_thread.requestInterruption(); self._scan_thread.wait()
            self._scan_thread = Scanner(self.samples_dir, self.favorites)
            self._scan_thread.found.connect(self.model.add_item)
            self._scan_thread.start()

# ------------------- bienvenida -------------------
class WelcomeDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bienvenido a Lup Shots")
        self.setModal(True); self.setMinimumWidth(520)
        title = QtWidgets.QLabel("<b>Bienvenido a Lup Shots</b>")
        sub   = QtWidgets.QLabel("Selecciona la carpeta donde están (o pondrás) tus shots."); sub.setWordWrap(True)
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
    def selected_path(self) -> Path:
        return Path(self.pathEdit.text().strip() or str(default_samples_dir()))

# ------------------- main -------------------
def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME); app.setOrganizationName(APP_ORG)
    app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyside6") + "\nQWidget{background-color:#121214;}")

    cfg = load_config()
    need_setup = (not cfg.get("first_run_done", False)) or (not Path(cfg.get("samples_dir","")).exists())
    if need_setup:
        dlg = WelcomeDialog()
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            chosen = dlg.selected_path()
            if not chosen.exists(): chosen.mkdir(parents=True, exist_ok=True)
            cfg["samples_dir"] = str(chosen); cfg["first_run_done"] = True; save_config(cfg)
        else:
            sys.exit(0)

    w = MainWindow(Path(cfg["samples_dir"])); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()






