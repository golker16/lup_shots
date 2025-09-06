# app.py
import os, re, sys, json, wave, contextlib, unicodedata
from pathlib import Path
from collections import Counter

from PySide6 import QtCore, QtGui, QtWidgets, QtMultimedia
import qdarkstyle

APP_NAME = "Lup Shots"
APP_ORG  = "Lup"

VALID_EXTS = {".wav", ".aiff", ".aif", ".mp3", ".flac", ".ogg"}
WAVE_PEAKS = 160

CONFIG_DIR  = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = CONFIG_DIR / "config.json"

# ----------------- util -----------------
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
    nf = unicodedata.normalize("NFD", s or "")
    return "".join(ch for ch in nf if unicodedata.category(ch) != "Mn").lower()

def parse_from_filename(filename: str):
    """
    GENERO_trap_hiphop_X_drums_X_clap_snare_X_SQUISH_KEY_NO_.wav
    -> genres=['trap','hiphop'], generals=['drums'], specifics=['clap','snare'], title='SQUISH', key='—'
    """
    base = re.sub(r"\.[^.]+$", "", filename)
    parts = base.split("_X_")

    def clean(s):
        return (s or "").strip()

    # géneros (pueden venir varios con "_")
    graw = clean(parts[0] if len(parts) > 0 else "")
    genres = [t for t in re.sub(r"^GENERO_", "", graw, flags=re.I).split("_") if t]

    # general (también permitimos varios)
    gr = clean(parts[1] if len(parts) > 1 else "")
    generals = [t for t in gr.split("_") if t]

    # específicos (lista)
    sp = clean(parts[2] if len(parts) > 2 else "")
    specifics = [t for t in sp.split("_") if t]

    # título + KEY
    tail = "_X_".join(parts[3:]) if len(parts) > 3 else ""
    title = re.sub(r"_KEY_.+", "", tail).replace("_", " ").strip() or base
    mkey = re.search(r"_KEY_([^_]+)_?", tail, flags=re.I)
    key = (mkey.group(1).upper() if mkey else "").strip()
    key = "—" if (not key or key == "NO") else key

    return dict(genres=genres, generals=generals, specifics=specifics, title=title, key=key)

def read_pcm_waveform(path: Path, peaks=WAVE_PEAKS):
    """Onda rápida para WAV PCM; otros formatos → placeholder (None)."""
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

# ----------------- chips -----------------
class TagChip(QtWidgets.QFrame):
    includeRequested = QtCore.Signal(str)  # clic IZQ o botón ＋
    excludeRequested = QtCore.Signal(str)  # clic DER o botón −

    def __init__(self, text: str, tone: str, parent=None):
        super().__init__(parent)
        self.raw_text = text
        colors = {
            "blue":   "background:#0b2530;color:#b3e4ff;border:1px solid #123043;",
            "indigo": "background:#12183c;color:#c7c9ff;border:1px solid #1d226b;",
            "green":  "background:#0f3d28;color:#d4ffe3;border:1px solid #1b5e3a;",
            "violet": "background:#351457;color:#e7ccff;border:1px solid #52227d;",
            "gray":   "background:#232327;color:#d1d5db;border:1px solid #3a3a44;",
        }[tone]
        self.setStyleSheet(colors + " border-radius:10px;")
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))

        self.setObjectName("TagChip")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(8,2,8,2); lay.setSpacing(6)

        self.lab = QtWidgets.QLabel(text); self.lab.setStyleSheet("border:none;")
        lay.addWidget(self.lab)

        # Botones ocultos (aparecen al hover)
        self.btnPlus = QtWidgets.QToolButton(); self.btnPlus.setText("＋")
        self.btnPlus.setStyleSheet("QToolButton{background:#14532d;color:#ecfdf5;border:1px solid #166534;border-radius:6px;padding:0 4px;}")
        self.btnPlus.setVisible(False); self.btnPlus.clicked.connect(lambda: self.includeRequested.emit(self.raw_text))

        self.btnMinus = QtWidgets.QToolButton(); self.btnMinus.setText("−")
        self.btnMinus.setStyleSheet("QToolButton{background:#7f1d1d;color:#ffe4e6;border:1px solid #991b1b;border-radius:6px;padding:0 4px;}")
        self.btnMinus.setVisible(False); self.btnMinus.clicked.connect(lambda: self.excludeRequested.emit(self.raw_text))

        lay.addWidget(self.btnPlus); lay.addWidget(self.btnMinus)

    def enterEvent(self, e):
        self.btnPlus.setVisible(True)
        self.btnMinus.setVisible(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.btnPlus.setVisible(False)
        self.btnMinus.setVisible(False)
        super().leaveEvent(e)

    def mousePressEvent(self, e: QtGui.QMouseEvent):
        if e.button() == QtCore.Qt.RightButton:
            self.excludeRequested.emit(self.raw_text)
        else:
            self.includeRequested.emit(self.raw_text)
        e.accept()

class SelectedChip(QtWidgets.QWidget):
    removed = QtCore.Signal(str)

    def __init__(self, text: str, negate=False, parent=None):
        super().__init__(parent)
        self.tag = text
        lab = QtWidgets.QLabel(("NOT " if negate else "") + text)
        lab.setStyleSheet(
            ("background:#0f3d28;color:#d4ffe3;border:1px solid #1b5e3a;" if not negate
             else "background:#3b1111;color:#ffd4d4;border:1px solid #6b1f1f;")
            + " border-radius:10px; padding:2px 8px;"
        )
        btn = QtWidgets.QToolButton(); btn.setText("×")
        btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        btn.clicked.connect(lambda: self.removed.emit(self.tag))
        btn.setStyleSheet("color:#e5e7eb;")
        lay = QtWidgets.QHBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(6)
        lay.addWidget(lab); lay.addWidget(btn)

# ----------------- wave -----------------
class WaveWidget(QtWidgets.QWidget):
    def __init__(self, peaks=None, parent=None):
        super().__init__(parent)
        self._peaks = peaks or []
        self._progress = 0.0
        self.setMinimumHeight(42)
        self.setMinimumWidth(60)  # para no desaparecer en ventanas estrechas
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Fixed)

    def setPeaks(self, peaks):
        self._peaks = peaks or []
        self.update()

    def setProgress(self, p):
        self._progress = max(0.0, min(1.0, p))
        self.update()

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        r = self.rect()
        mid = r.center().y()
        w = max(1, r.width()); h = r.height()
        bars = max(1, len(self._peaks))
        barW = max(1, int(w / bars))
        cutoff = int(bars * self._progress)
        p.setPen(QtCore.Qt.NoPen)

        # reproducido (claro)
        p.setBrush(QtGui.QColor("#ffffff"))
        for i in range(min(cutoff, bars)):
            pk = self._peaks[i] if i < len(self._peaks) else 0
            bh = max(1, int(pk * h * 0.95)); y = int(mid - bh / 2)
            p.drawRect(QtCore.QRect(int(i * (w / bars)), y, int(barW * 0.9), bh))

        # resto (gris)
        p.setBrush(QtGui.QColor("#a1a1aa"))
        for i in range(cutoff, bars):
            pk = self._peaks[i] if i < len(self._peaks) else 0
            bh = max(1, int(pk * h * 0.95)); y = int(mid - bh / 2)
            p.drawRect(QtCore.QRect(int(i * (w / bars)), y, int(barW * 0.9), bh))

# ----------------- fila -----------------
class SampleRow(QtWidgets.QFrame):
    playClicked = QtCore.Signal(object)      # self
    starToggled = QtCore.Signal(object)      # self
    tagInclude  = QtCore.Signal(str)
    tagExclude  = QtCore.Signal(str)

    def __init__(self, info, is_fav: bool, parent=None):
        super().__init__(parent)
        self.info = info
        self.isPlaying = False
        self.isFav = is_fav
        self.setObjectName("SampleRow")
        self._apply_style()

        # PLAY
        self.btnPlay = QtWidgets.QPushButton("▶")
        self.btnPlay.setFixedWidth(40)
        self.btnPlay.clicked.connect(lambda: self.playClicked.emit(self))
        self.btnPlay.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))

        # TAGS (mismo fondo que fila)
        chipsL = QtWidgets.QHBoxLayout(); chipsL.setContentsMargins(0,0,0,0); chipsL.setSpacing(6)
        for g in info["genres"]:
            c = TagChip(g, "blue");   c.includeRequested.connect(self.tagInclude); c.excludeRequested.connect(self.tagExclude); chipsL.addWidget(c)
        for g in info["generals"]:
            c = TagChip(g, "indigo"); c.includeRequested.connect(self.tagInclude); c.excludeRequested.connect(self.tagExclude); chipsL.addWidget(c)
        for s in info["specifics"]:
            c = TagChip(s, "green");  c.includeRequested.connect(self.tagInclude); c.excludeRequested.connect(self.tagExclude); chipsL.addWidget(c)
        ck = TagChip(info["key"], "violet"); ck.includeRequested.connect(self.tagInclude); ck.excludeRequested.connect(self.tagExclude); chipsL.addWidget(ck)
        chipsW = QtWidgets.QWidget(); chipsW.setStyleSheet("background:transparent;")
        ch = QtWidgets.QHBoxLayout(chipsW); ch.setContentsMargins(0,0,0,0); ch.setSpacing(6); ch.addLayout(chipsL); ch.addStretch(1)

        # NOMBRE (elide)
        self.nameLbl = QtWidgets.QLabel(info["title"]); self.nameLbl.setStyleSheet("color:#e5e7eb;")
        self.nameLbl.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        # STAR
        self.btnStar = QtWidgets.QToolButton(); self.btnStar.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self._sync_star_icon()
        self.btnStar.clicked.connect(self._toggle_star)

        left = QtWidgets.QHBoxLayout(); left.setContentsMargins(0,0,0,0); left.setSpacing(8)
        left.addWidget(chipsW); left.addWidget(self.nameLbl, 1); left.addWidget(self.btnStar)
        leftW = QtWidgets.QWidget(); leftW.setStyleSheet("background:transparent;"); leftW.setLayout(left)

        # WAVE (no desaparece al achicar)
        self.wave = WaveWidget(info.get("peaks"))
        self.wave.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Fixed)

        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(10,10,10,10)
        grid.setHorizontalSpacing(10)
        grid.addWidget(self.btnPlay, 0, 0)
        grid.addWidget(leftW, 0, 1)
        grid.addWidget(self.wave, 0, 2)
        grid.setColumnStretch(1, 1)   # nombre/tags ocupa el resto
        grid.setColumnStretch(2, 1)

        # drag externo
        self.setMouseTracking(True); self._drag_start = None

    def _apply_style(self):
        if self.isPlaying:
            self.setStyleSheet("#SampleRow { background: rgba(37,99,235,0.18); border:1px solid #3b82f6; border-radius:12px; }")
        else:
            self.setStyleSheet("#SampleRow { background:#19191d; border:1px solid #303039; border-radius:12px; }")

    def _sync_star_icon(self):
        self.btnStar.setText("★" if self.isFav else "☆")
        self.btnStar.setToolTip("Quitar de favoritos" if self.isFav else "Marcar como favorito")

    def _toggle_star(self):
        self.isFav = not self.isFav
        self._sync_star_icon()
        self.starToggled.emit(self)

    def setPlaying(self, v: bool):
        self.isPlaying = v; self.btnPlay.setText("⏸" if v else "▶"); self._apply_style()

    def setProgress(self, p): self.wave.setProgress(p)
    def setPeaks(self, peaks): self.wave.setPeaks(peaks)

    # drag
    def mousePressEvent(self, e: QtGui.QMouseEvent):
        if e.button() == QtCore.Qt.LeftButton:
            self._drag_start = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QtGui.QMouseEvent):
        if self._drag_start is None: return super().mouseMoveEvent(e)
        if (e.position().toPoint() - self._drag_start).manhattanLength() < 8: return
        drag = QtGui.QDrag(self); mime = QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile(str(self.info["path"]))])
        drag.setMimeData(mime); drag.exec(QtCore.Qt.CopyAction); self._drag_start = None
        super().mouseMoveEvent(e)

# ----------------- fila de sugeridos -----------------
class TagRow(QtWidgets.QWidget):
    includeRequested = QtCore.Signal(str)
    excludeRequested = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self._tags = []           # [(tag, count)]
        self._ignored = set()
        self._hidden_for_menu = []

        self.wrap = QtWidgets.QHBoxLayout(self)
        self.wrap.setContentsMargins(0,0,0,0); self.wrap.setSpacing(6)

        self.menuBtn = QtWidgets.QToolButton()
        self.menuBtn.setText("…")
        self.menuBtn.setStyleSheet("background:#232327;color:#e5e7eb;border:1px solid #3a3a44;border-radius:8px;padding:2px 10px;")
        self.menuBtn.clicked.connect(self._open_menu)

    def setData(self, tags_with_count, ignored=set()):
        # orden por frecuencia desc y alfabético
        self._tags = sorted([t for t in tags_with_count if t[0] not in ignored], key=lambda x: (-x[1], x[0]))
        self._ignored = set(ignored); self._rebuild()

    def resizeEvent(self, e): self._rebuild(); super().resizeEvent(e)

    def _rebuild(self):
        while self.wrap.count():
            it = self.wrap.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        if not self._tags:
            self.wrap.addStretch(1); self.wrap.addWidget(self.menuBtn); return

        fm = self.fontMetrics(); avail = max(0, self.width() - 60); used = 0; shown = []
        for tag, cnt in self._tags:
            chip_width = fm.horizontalAdvance(tag) + 22 + 26  # texto + padding + botones hover aprox
            if used + chip_width > avail: break
            btn = TagChip(tag, "gray")
            btn.setToolTip(f"{cnt} coincidencias · Clic: incluir · Der: excluir")
            btn.includeRequested.connect(self.includeRequested.emit)
            btn.excludeRequested.connect(self.excludeRequested.emit)
            self.wrap.addWidget(btn); used += chip_width + 6; shown.append(tag)
        self.wrap.addStretch(1); self.wrap.addWidget(self.menuBtn)
        self._hidden_for_menu = [t for t, _ in self._tags if t not in shown]

    def _open_menu(self):
        m = QtWidgets.QMenu(self)
        m.setStyleSheet("QMenu{background:#121214;color:#e5e7eb;border:1px solid #2e2e33;} QMenu::item:selected{background:#1f2024;}")
        if not self._hidden_for_menu:
            m.addAction("(sin más tags)").setEnabled(False)
        for tag in self._hidden_for_menu[:80]:
            act = QtGui.QAction(tag, m)
            def trig(checked=False, t=tag): self.includeRequested.emit(t)
            act.triggered.connect(trig)
            m.addAction(act)
        m.exec(self.menuBtn.mapToGlobal(QtCore.QPoint(self.menuBtn.width()//2, self.menuBtn.height())))

# ----------------- ventana principal -----------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, samples_dir: Path):
        super().__init__()
        self.setWindowTitle("Lup Shots")
        self.samples_dir = samples_dir

        # audio
        self.player = QtMultimedia.QMediaPlayer()
        self.audio_out = QtMultimedia.QAudioOutput(); self.audio_out.setVolume(0.9)
        self.player.setAudioOutput(self.audio_out)
        self.player.positionChanged.connect(self._on_position)
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.playbackStateChanged.connect(self._on_state)

        # filtros
        self.include_tags = set()
        self.exclude_tags = set()
        self.search_tokens = []

        # favoritos
        cfg = load_config(); self.favorites = set(cfg.get("favorites", []))

        # UI
        self._build_ui()
        self._load_samples()
        self._apply_filters()
        self._refresh_tag_suggestions()

        # teclado
        self._current_row = None
        self.installEventFilter(self)

        # asegúrate de que la TagRow se dibuje también al primer show
        QtCore.QTimer.singleShot(0, self._refresh_tag_suggestions)

    # ---------- UI ----------
    def _build_ui(self):
        central = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(central); v.setContentsMargins(16,16,16,8); v.setSpacing(10)

        # override fondo app
        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #121214; }
            QLineEdit { background:#1a1a1f; border:1px solid #2e2e33; border-radius:10px; padding:6px 10px; color:#e5e7eb; }
            QScrollArea { border: none; }
            QMenuBar { background:#121214; color:#e5e7eb; }
            QMenuBar::item:selected { background:#1f2024; }
        """)

        # menú -> "Opciones"
        menubar = self.menuBar()
        options = menubar.addMenu("&Opciones")
        act_change = options.addAction("Cambiar carpeta de &samples…")
        act_change.triggered.connect(self.change_folder)

        # botón DONAR a la derecha
        donate_btn = QtWidgets.QPushButton("Donar")
        donate_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        donate_btn.setStyleSheet("QPushButton{background:#16a34a;color:white;border:1px solid #15803d;border-radius:8px;padding:4px 10px;} QPushButton:hover{background:#22c55e;}")
        donate_btn.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl("https://www.gabrielgolker.com")))
        menubar.setCornerWidget(donate_btn, QtCore.Qt.TopRightCorner)

        # buscador
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Buscar (tags, nombre o key)…")
        self.search.textChanged.connect(self._on_search_text)
        v.addWidget(self.search)

        # filtros activos
        self.activeWrap = QtWidgets.QHBoxLayout()
        self.activeWrap.setContentsMargins(0,0,0,0); self.activeWrap.setSpacing(6)
        activeW = QtWidgets.QWidget(); activeW.setLayout(self.activeWrap)
        v.addWidget(activeW)

        # fila sugeridos + contador
        row = QtWidgets.QHBoxLayout(); row.setContentsMargins(0,0,0,0); row.setSpacing(10)
        self.tagRow = TagRow()
        self.tagRow.includeRequested.connect(self._include_tag)
        self.tagRow.excludeRequested.connect(self._exclude_tag)
        self.resLbl = QtWidgets.QLabel("0 resultados"); self.resLbl.setStyleSheet("color:#9ca3af;")
        row.addWidget(self.tagRow, 1); row.addWidget(self.resLbl, 0, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        tagRowW = QtWidgets.QWidget(); tagRowW.setLayout(row)
        v.addWidget(tagRowW)

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
        self.resize(1180, 760)

    # ---------- carga ----------
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
        self.samples = []
        for p in self._collect_files():
            meta = parse_from_filename(p.name)
            peaks, duration = read_pcm_waveform(p)
            tags_flat = list(meta["genres"] + meta["generals"] + meta["specifics"])
            if meta["key"] != "—": tags_flat.append(meta["key"])
            hay = strip_accents_lower(" ".join(tags_flat + [meta["title"], p.name]))
            info = {
                "path": p, "filename": p.name,
                "genres": meta["genres"], "generals": meta["generals"], "specifics": meta["specifics"],
                "title": meta["title"], "key": meta["key"], "peaks": peaks, "duration": duration,
                "haystack": hay, "tagset": set(tags_flat),
            }
            row = SampleRow(info, is_fav=(p.name in self.favorites))
            row.playClicked.connect(self._toggle_play_row)
            row.tagInclude.connect(self._include_tag)
            row.tagExclude.connect(self._exclude_tag)
            row.starToggled.connect(self._toggle_favorite)
            self.rows.append(row); self.samples.append(info); self.listLayout.addWidget(row)
        self.listLayout.addStretch(1)

    # ---------- favoritos ----------
    def _toggle_favorite(self, row: SampleRow):
        name = row.info["filename"]
        if row.isFav: self.favorites.add(name)
        else: self.favorites.discard(name)
        cfg = load_config(); cfg["favorites"] = sorted(self.favorites); save_config(cfg)
        self._apply_filters()        # reordena

    # ---------- filtros ----------
    def _on_search_text(self, text: str):
        self.search_tokens = [strip_accents_lower(t) for t in text.strip().split() if t]
        self._apply_filters()
        self._refresh_tag_suggestions()

    def _include_tag(self, tag: str):
        self.exclude_tags.discard(tag); self.include_tags.add(tag)
        self._redraw_active_filters(); self._apply_filters(); self._refresh_tag_suggestions()

    def _exclude_tag(self, tag: str):
        self.include_tags.discard(tag); self.exclude_tags.add(tag)
        self._redraw_active_filters(); self._apply_filters(); self._refresh_tag_suggestions()

    def _remove_tag(self, tag: str):
        self.include_tags.discard(tag); self.exclude_tags.discard(tag)
        self._redraw_active_filters(); self._apply_filters(); self._refresh_tag_suggestions()

    def _redraw_active_filters(self):
        while self.activeWrap.count():
            it = self.activeWrap.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        for t in sorted(self.include_tags):
            chip = SelectedChip(t, negate=False); chip.removed.connect(self._remove_tag); self.activeWrap.addWidget(chip)
        for t in sorted(self.exclude_tags):
            chip = SelectedChip(t, negate=True);  chip.removed.connect(self._remove_tag); self.activeWrap.addWidget(chip)
        self.activeWrap.addStretch(1)

    def _apply_filters(self):
        visible_count = 0
        for i, row in enumerate(self.rows):
            s = self.samples[i]
            visible = True
            for tok in self.search_tokens:
                if tok not in s["haystack"]: visible = False; break
            if visible and self.include_tags and not self.include_tags.issubset(s["tagset"]): visible = False
            if visible and self.exclude_tags and self.exclude_tags.intersection(s["tagset"]): visible = False
            row.setVisible(visible)
            if visible: visible_count += 1

        # orden -> favoritos primero entre visibles, luego alfabético por título
        visible_rows = [r for r in self.rows if r.isVisible()]
        hidden_rows  = [r for r in self.rows if not r.isVisible()]
        visible_rows.sort(key=lambda r: (0 if r.info["filename"] in self.favorites else 1,
                                         strip_accents_lower(r.info["title"])))
        # reinsertar en layout
        for i in reversed(range(self.listLayout.count())):
            it = self.listLayout.takeAt(i)
            if it and it.widget(): self.listLayout.removeItem(it)
        for r in visible_rows + hidden_rows:
            self.listLayout.addWidget(r)
        self.listLayout.addStretch(1)

        # contador
        self.resLbl.setText(f"{visible_count} resultado" + ("" if visible_count == 1 else "s"))

    def _refresh_tag_suggestions(self):
        # frecuencia de tags SOLO sobre lo visible
        freq = Counter()
        for i, row in enumerate(self.rows):
            if not row.isVisible(): continue
            s = self.samples[i]
            for t in s["tagset"]:
                if t in self.include_tags or t in self.exclude_tags: continue
                freq[t] += 1
        tags_with_count = list(freq.items())
        self.tagRow.setData(tags_with_count, ignored=self.include_tags | self.exclude_tags)

    # ---------- reproducción / navegación ----------
    def _toggle_play_row(self, row: SampleRow):
        # si es el actual:
        if self._current_row is row:
            st = self.player.playbackState()
            if st == QtMultimedia.QMediaPlayer.PlayingState:
                self.player.pause(); row.setPlaying(False)  # pausa
            elif st == QtMultimedia.QMediaPlayer.PausedState:
                self.player.play(); row.setPlaying(True)    # reanuda
            else:  # StoppedState -> volver a 0 y play
                self.player.setPosition(0); self.player.play(); row.setPlaying(True)
            return

        # parar el que estuviera
        if self._current_row:
            self._current_row.setPlaying(False)

        # preparar y sonar
        url = QtCore.QUrl.fromLocalFile(str(row.info["path"]))
        self.player.setSource(url)
        self.player.setPosition(0)
        self.player.play()
        row.setPlaying(True)
        self._current_row = row

    def _move_selection(self, delta: int):
        visible_rows = [r for r in self.rows if r.isVisible()]
        if not visible_rows: return
        if self._current_row is None or self._current_row not in visible_rows:
            target = visible_rows[0]
        else:
            idx = visible_rows.index(self._current_row)
            idx = max(0, min(len(visible_rows)-1, idx + delta))
            target = visible_rows[idx]
        # si está reproduciendo, pausar y pasar al target
        if self.player.playbackState() == QtMultimedia.QMediaPlayer.PlayingState and self._current_row:
            self.player.pause()
            self._current_row.setPlaying(False)
        self._toggle_play_row(target)

    def _on_state(self, st):
        if not self._current_row: return
        if st == QtMultimedia.QMediaPlayer.PlayingState:
            self._current_row.setPlaying(True)
        elif st == QtMultimedia.QMediaPlayer.PausedState:
            self._current_row.setPlaying(False)

    def _on_position(self, pos_ms: int):
        if not self._current_row: return
        dur = max(1, int(self.player.duration()))
        p = max(0.0, min(1.0, pos_ms / float(dur)))
        self._current_row.setProgress(p)

    def _on_status(self, status):
        # al terminar, queda seleccionado y listo para replay
        if status == QtMultimedia.QMediaPlayer.EndOfMedia and self._current_row:
            self._current_row.setPlaying(False)
            self._current_row.setProgress(0.0)
            self.player.setPosition(0)

    # ---------- teclado ----------
    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.KeyPress:
            key = ev.key()
            if key == QtCore.Qt.Key_Space:
                if self._current_row is None:
                    # reproduce el primero visible
                    vis = [r for r in self.rows if r.isVisible()]
                    if vis: self._toggle_play_row(vis[0])
                else:
                    self._toggle_play_row(self._current_row)
                return True
            if key in (QtCore.Qt.Key_Enter, QtCore.Qt.Key_Return):
                target = self._current_row or ( [r for r in self.rows if r.isVisible()] or [None] )[0]
                if target: self._toggle_play_row(target)
                return True
            if key == QtCore.Qt.Key_Down:
                self._move_selection(+1); return True
            if key == QtCore.Qt.Key_Up:
                self._move_selection(-1); return True
        return False

    # ---------- carpeta ----------
    def change_folder(self):
        dlg = QtWidgets.QFileDialog(self, "Seleccionar carpeta de samples")
        dlg.setFileMode(QtWidgets.QFileDialog.Directory)
        dlg.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
        dlg.setDirectory(str(self.samples_dir))
        if dlg.exec():
            self.samples_dir = Path(dlg.selectedFiles()[0])
            cfg = load_config(); cfg["samples_dir"] = str(self.samples_dir); save_config(cfg)
            # recargar
            while self.listLayout.count():
                it = self.listLayout.takeAt(0)
                if it.widget(): it.widget().deleteLater()
            self._load_samples()
            self._apply_filters()
            self._refresh_tag_suggestions()

# ----------------- bienvenida -----------------
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

        footer = QtWidgets.QLabel("© 2025 Gabriel Golker")
        footer.setAlignment(QtCore.Qt.AlignHCenter)
        footer.setStyleSheet("color:#9ca3af; padding-top:8px;")

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title); lay.addWidget(sub); lay.addLayout(row); lay.addLayout(btns); lay.addWidget(footer)

    def _browse(self):
        dlg = QtWidgets.QFileDialog(self, "Seleccionar carpeta de samples")
        dlg.setFileMode(QtWidgets.QFileDialog.Directory); dlg.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
        dlg.setDirectory(self.pathEdit.text())
        if dlg.exec(): self.pathEdit.setText(dlg.selectedFiles()[0])

    def selected_path(self) -> Path:
        return Path(self.pathEdit.text().strip() or str(default_samples_dir()))

# ----------------- arranque -----------------
def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME); app.setOrganizationName(APP_ORG)
    # qdarkstyle + override del fondo
    app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyside6") + "\nQWidget{background-color:#121214;}")

    cfg = load_config()
    need_setup = (not cfg.get("first_run_done", False)) or (not Path(cfg.get("samples_dir", "")).exists())
    if need_setup:
        dlg = WelcomeDialog()
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            chosen = dlg.selected_path()
            if not chosen.exists(): chosen.mkdir(parents=True, exist_ok=True)
            cfg["samples_dir"] = str(chosen); cfg["first_run_done"] = True; save_config(cfg)
        else:
            sys.exit(0)

    samples_dir = Path(cfg["samples_dir"])
    w = MainWindow(samples_dir); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()





