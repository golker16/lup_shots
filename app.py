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

    # géneros múltiples
    graw = clean(parts[0] if len(parts) > 0 else "")
    genres = [t for t in re.sub(r"^GENERO_", "", graw, flags=re.I).split("_") if t]

    # general (admitimos varios por si vienen unidos con '_')
    gr = clean(parts[1] if len(parts) > 1 else "")
    generals = [t for t in gr.split("_") if t]

    # específicos
    sp = clean(parts[2] if len(parts) > 2 else "")
    specifics = [t for t in sp.split("_") if t]

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
class TagButton(QtWidgets.QPushButton):
    includeRequested = QtCore.Signal(str)  # clic izq
    excludeRequested = QtCore.Signal(str)  # clic der

    def __init__(self, text: str, tone: str, parent=None, show_minus_hover=True):
        super().__init__(text, parent)
        self.raw_text = text
        self.show_minus_hover = show_minus_hover
        base = {
            "blue":   "background:#061e2b;color:#b3e4ff;border:1px solid #123043;",
            "indigo": "background:#0c0e32;color:#c7c9ff;border:1px solid #1d226b;",
            "green":  "background:#0e3b24;color:#d4ffe3;border:1px solid #1b5e3a;",
            "violet": "background:#311251;color:#e7ccff;border:1px solid #52227d;",
            "red":    "background:#3b1111;color:#ffd4d4;border:1px solid #6b1f1f;",
            "gray":   "background:#2a2a33;color:#d1d5db;border:1px solid #3a3a44;",
        }[tone]
        self.setStyleSheet(base + " border-radius:10px; padding:2px 8px;")
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.setToolTip("Clic: incluir · Clic derecho: excluir")

    def mousePressEvent(self, e: QtGui.QMouseEvent):
        if e.button() == QtCore.Qt.RightButton:
            self.excludeRequested.emit(self.raw_text)
        else:
            self.includeRequested.emit(self.raw_text)
        super().mousePressEvent(e)

    def enterEvent(self, e):
        if self.show_minus_hover:
            self.setText("− " + self.raw_text)
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self.show_minus_hover:
            self.setText(self.raw_text)
        super().leaveEvent(e)

class SelectedChip(QtWidgets.QWidget):
    removed = QtCore.Signal(str)  # emite tag

    def __init__(self, text: str, negate=False, parent=None):
        super().__init__(parent)
        self.tag = text
        lab = QtWidgets.QLabel(("NOT " if negate else "") + text)
        lab.setStyleSheet(
            ("background:#0e3b24;color:#d4ffe3;border:1px solid #1b5e3a;" if not negate
             else "background:#3b1111;color:#ffd4d4;border:1px solid #6b1f1f;")
            + " border-radius:10px; padding:2px 8px;"
        )
        x = QtWidgets.QToolButton()
        x.setText("×"); x.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        x.clicked.connect(lambda: self.removed.emit(self.tag))
        x.setStyleSheet("color:#e5e7eb;")
        lay = QtWidgets.QHBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(6)
        lay.addWidget(lab); lay.addWidget(x)

# ----------------- mini wave -----------------
class WaveWidget(QtWidgets.QWidget):
    def __init__(self, peaks=None, parent=None):
        super().__init__(parent)
        self._peaks = peaks or []
        self._progress = 0.0
        self.setMinimumHeight(42)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")

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
        w = r.width(); h = r.height()
        bars = len(self._peaks) or 1
        barW = max(1, int(w / bars))

        cutoff = int(bars * self._progress)

        # reproducido (claro)
        p.setBrush(QtGui.QColor("#ffffff"))
        p.setPen(QtCore.Qt.NoPen)
        for i in range(cutoff):
            pk = self._peaks[i] if i < len(self._peaks) else 0
            bh = max(1, int(pk * h * 0.95))
            y = int(mid - bh / 2)
            p.drawRect(QtCore.QRect(int(i * (w / bars)), y, int(barW * 0.9), bh))

        # resto (gris)
        p.setBrush(QtGui.QColor("#a1a1aa"))
        for i in range(cutoff, bars):
            pk = self._peaks[i] if i < len(self._peaks) else 0
            bh = max(1, int(pk * h * 0.95))
            y = int(mid - bh / 2)
            p.drawRect(QtCore.QRect(int(i * (w / bars)), y, int(barW * 0.9), bh))

# ----------------- fila de sample -----------------
class SampleRow(QtWidgets.QFrame):
    playRequested = QtCore.Signal(object)   # self

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.isPlaying = False
        self.setObjectName("SampleRow")
        self._apply_style()

        # botón play
        self.btn = QtWidgets.QPushButton("▶")
        self.btn.setFixedWidth(40)
        self.btn.clicked.connect(lambda: self.playRequested.emit(self))
        self.btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))

        # chips
        chip_bar = QtWidgets.QHBoxLayout(); chip_bar.setContentsMargins(0,0,0,0); chip_bar.setSpacing(6)
        for g in info["genres"]:
            b = TagButton(g, "blue", show_minus_hover=True)
            b.includeRequested.connect(self._bubble_include)
            b.excludeRequested.connect(self._bubble_exclude)
            chip_bar.addWidget(b)
        for g in info["generals"]:
            b = TagButton(g, "indigo", show_minus_hover=True)
            b.includeRequested.connect(self._bubble_include)
            b.excludeRequested.connect(self._bubble_exclude)
            chip_bar.addWidget(b)
        for s in info["specifics"]:
            b = TagButton(s, "green", show_minus_hover=True)
            b.includeRequested.connect(self._bubble_include)
            b.excludeRequested.connect(self._bubble_exclude)
            chip_bar.addWidget(b)
        kb = TagButton(info["key"], "violet", show_minus_hover=True)
        kb.includeRequested.connect(self._bubble_include)
        kb.excludeRequested.connect(self._bubble_exclude)
        chip_bar.addWidget(kb)

        chip_wrap = QtWidgets.QWidget(); chip_l = QtWidgets.QHBoxLayout(chip_wrap)
        chip_l.setContentsMargins(0,0,0,0); chip_l.setSpacing(6)
        chip_l.addLayout(chip_bar); chip_l.addStretch(1)

        # nombre
        self.nameLbl = QtWidgets.QLabel(info["title"])
        self.nameLbl.setStyleSheet("color:#e5e7eb;")
        self.nameLbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        left = QtWidgets.QHBoxLayout()
        left.setContentsMargins(0,0,0,0); left.setSpacing(8)
        left.addWidget(chip_wrap); left.addWidget(self.nameLbl, 1)
        leftW = QtWidgets.QWidget(); leftW.setLayout(left)

        # wave
        self.wave = WaveWidget(info.get("peaks"))

        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(10,10,10,10)
        grid.setHorizontalSpacing(10)
        grid.addWidget(self.btn, 0, 0)
        grid.addWidget(leftW, 0, 1)
        grid.addWidget(self.wave, 0, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

    def _bubble_include(self, tag):
        self.parent().parent().parent().parent().includeRequested.emit(tag)

    def _bubble_exclude(self, tag):
        self.parent().parent().parent().parent().excludeRequested.emit(tag)

    def _apply_style(self):
        if self.isPlaying:
            self.setStyleSheet("#SampleRow { background: rgba(37,99,235,0.18); border:1px solid #3b82f6; border-radius:12px; }")
        else:
            self.setStyleSheet("#SampleRow { background:#1b1b23; border:1px solid #262632; border-radius:12px; }")

    def setPlaying(self, v: bool):
        self.isPlaying = v
        self.btn.setText("■" if v else "▶")
        self._apply_style()

    def setPeaks(self, peaks):
        self.wave.setPeaks(peaks)

    def setProgress(self, p):
        self.wave.setProgress(p)

# ----------------- fila de tags sugeridos -----------------
class TagRow(QtWidgets.QWidget):
    includeRequested = QtCore.Signal(str)
    excludeRequested = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self._tags = []           # [(tag, count)]
        self._ignored = set()     # ya seleccionados
        self._hidden_for_menu = []

        self._wrap = QtWidgets.QHBoxLayout(self)
        self._wrap.setContentsMargins(0,0,0,0)
        self._wrap.setSpacing(6)

        self.menuBtn = QtWidgets.QToolButton()
        self.menuBtn.setText("…")
        self.menuBtn.setStyleSheet("background:#2a2a33;color:#e5e7eb;border:1px solid #3a3a44;border-radius:8px;padding:2px 10px;")
        self.menuBtn.clicked.connect(self._open_menu)

    def setData(self, tags_with_count, ignored=set()):
        # Orden: frecuencia desc, luego alfabético
        self._tags = sorted(
            [t for t in tags_with_count if t[0] not in ignored],
            key=lambda x: (-x[1], x[0])
        )
        self._ignored = set(ignored)
        self._rebuild()

    def resizeEvent(self, e):
        self._rebuild()
        super().resizeEvent(e)

    def _rebuild(self):
        while self._wrap.count():
            it = self._wrap.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        if not self._tags:
            return

        fm = self.fontMetrics()
        avail = max(0, self.width() - 60)  # 60px para el botón "…"
        used = 0
        shown = []

        for tag, cnt in self._tags:
            chip_width = fm.horizontalAdvance("− " + tag) + 22
            if used + chip_width > avail:
                break
            btn = TagButton(tag, "gray", show_minus_hover=True)
            btn.setToolTip(f"{cnt} coincidencias · Clic: incluir · Der: excluir")
            btn.includeRequested.connect(self.includeRequested.emit)
            btn.excludeRequested.connect(self.excludeRequested.emit)
            self._wrap.addWidget(btn)
            used += chip_width + 6
            shown.append(tag)

        self._wrap.addStretch(1)
        self._wrap.addWidget(self.menuBtn)
        self._hidden_for_menu = [t for t, _ in self._tags if t not in shown]

    def _open_menu(self):
        if not self._tags:
            return
        m = QtWidgets.QMenu(self)
        m.setStyleSheet("QMenu{background:#111827;color:#e5e7eb;border:1px solid #374151;}"
                        "QMenu::item:selected{background:#1f2937;}")
        for tag in self._hidden_for_menu[:60]:
            act = QtGui.QAction(tag, m)
            act.setToolTip("Clic para incluir (clic derecho para excluir)")
            def handler(checked=False, t=tag):
                self.includeRequested.emit(t)
            act.triggered.connect(handler)
            m.addAction(act)
        if not self._hidden_for_menu:
            m.addAction("(sin más tags)").setEnabled(False)
        m.exec(self.menuBtn.mapToGlobal(QtCore.QPoint(self.menuBtn.width()//2, self.menuBtn.height())))
        
# ----------------- ventana principal -----------------
class MainWindow(QtWidgets.QMainWindow):
    includeRequested = QtCore.Signal(str)
    excludeRequested = QtCore.Signal(str)

    def __init__(self, samples_dir: Path):
        super().__init__()
        self.setWindowTitle("Lup Shots")
        self.samples_dir = samples_dir

        # audio
        self.player = QtMultimedia.QMediaPlayer()
        self.audio_out = QtMultimedia.QAudioOutput()
        self.audio_out.setVolume(0.9)
        self.player.setAudioOutput(self.audio_out)
        self.player.positionChanged.connect(self._on_position)
        self.player.mediaStatusChanged.connect(self._on_status)

        # filtros
        self.include_tags = set()
        self.exclude_tags = set()
        self.search_tokens = []

        # UI
        self._build_ui()
        self._load_samples()
        self._refresh_tag_suggestions()
        self.search.textChanged.connect(self._on_search_text)

        # wiring para clicks en chips dentro de filas
        self.includeRequested.connect(self._include_tag)
        self.excludeRequested.connect(self._exclude_tag)

        # navegación teclado
        self._current_row = None
        self.installEventFilter(self)

    # ---------- UI ----------
    def _build_ui(self):
        central = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(central)
        v.setContentsMargins(16,16,16,8)
        v.setSpacing(10)

        # menú
        menu = self.menuBar()
        file_menu = menu.addMenu("&Archivo")
        file_menu.addAction("Cambiar carpeta de &samples…").triggered.connect(self.change_folder)
        file_menu.addSeparator()
        file_menu.addAction("Salir").triggered.connect(self.close)

        # buscador
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Buscar (tags, nombre o key)…")
        v.addWidget(self.search)

        # filtros activos
        self.activeWrap = QtWidgets.QHBoxLayout()
        self.activeWrap.setContentsMargins(0,0,0,0)
        self.activeWrap.setSpacing(6)
        activeW = QtWidgets.QWidget(); activeW.setLayout(self.activeWrap)
        v.addWidget(activeW)

        # fila de sugeridos
        self.tagRow = TagRow()
        self.tagRow.includeRequested.connect(self._include_tag)
        self.tagRow.excludeRequested.connect(self._exclude_tag)
        v.addWidget(self.tagRow)

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

    # ---------- carga samples ----------
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
            if meta["key"] != "—":
                tags_flat.append(meta["key"])
            hay = strip_accents_lower(" ".join(
                tags_flat + [meta["title"], p.name]
            ))
            info = {
                "path": p,
                "filename": p.name,
                "genres": meta["genres"],
                "generals": meta["generals"],
                "specifics": meta["specifics"],
                "title": meta["title"],
                "key": meta["key"],
                "peaks": peaks,
                "duration": duration,
                "haystack": hay,
                "tagset": set(tags_flat),
            }
            row = SampleRow(info)
            row.playRequested.connect(self._toggle_play_row)
            self.rows.append(row)
            self.samples.append(info)
            self.listLayout.addWidget(row)
        self.listLayout.addStretch(1)

    # ---------- filtrado ----------
    def _on_search_text(self, text: str):
        self.search_tokens = [strip_accents_lower(t) for t in text.strip().split() if t]
        self._apply_filters()
        self._refresh_tag_suggestions()

    def _include_tag(self, tag: str):
        if tag in self.exclude_tags:
            self.exclude_tags.remove(tag)
        self.include_tags.add(tag)
        self._redraw_active_filters()
        self._apply_filters()
        self._refresh_tag_suggestions()

    def _exclude_tag(self, tag: str):
        if tag in self.include_tags:
            self.include_tags.remove(tag)
        self.exclude_tags.add(tag)
        self._redraw_active_filters()
        self._apply_filters()
        self._refresh_tag_suggestions()

    def _remove_tag(self, tag: str):
        self.include_tags.discard(tag)
        self.exclude_tags.discard(tag)
        self._redraw_active_filters()
        self._apply_filters()
        self._refresh_tag_suggestions()

    def _redraw_active_filters(self):
        while self.activeWrap.count():
            it = self.activeWrap.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        # incluidos
        for t in sorted(self.include_tags):
            c = SelectedChip(t, negate=False)
            c.removed.connect(self._remove_tag)
            self.activeWrap.addWidget(c)
        # excluidos
        for t in sorted(self.exclude_tags):
            c = SelectedChip(t, negate=True)
            c.removed.connect(self._remove_tag)
            self.activeWrap.addWidget(c)
        self.activeWrap.addStretch(1)

    def _apply_filters(self):
        for i, row in enumerate(self.rows):
            s = self.samples[i]
            visible = True
            # búsqueda
            for tok in self.search_tokens:
                if tok not in s["haystack"]:
                    visible = False
                    break
            if visible and self.include_tags:
                # incluidos (AND)
                if not self.include_tags.issubset(s["tagset"]):
                    visible = False
            if visible and self.exclude_tags:
                if self.exclude_tags.intersection(s["tagset"]):
                    visible = False
            row.setVisible(visible)

    def _refresh_tag_suggestions(self):
        # FREC DE TAGS EN RESULTADOS VISIBLES (ya aplicados búsqueda + include + exclude)
        freq = Counter()
        for i, row in enumerate(self.rows):
            if not row.isVisible():  # solo lo que quedó visible
                continue
            s = self.samples[i]
            for t in s["tagset"]:
                # no sugerir tags ya seleccionados
                if t in self.include_tags or t in self.exclude_tags:
                    continue
                freq[t] += 1

        # lista (tag, count) → TagRow se encarga de ordenar por (-count, tag)
        tags_with_count = list(freq.items())
        ignored = self.include_tags | self.exclude_tags
        self.tagRow.setData(tags_with_count, ignored)

    # ---------- reproducción ----------
    def _toggle_play_row(self, row: SampleRow):
        # si ya está sonando → re-disparo (reinicia desde 0)
        if row.isPlaying:
            self.player.setPosition(0)
            self.player.play()
            return
        # parar todo
        for r in self.rows:
            if r.isPlaying:
                r.setPlaying(False)
        # preparar y sonar
        url = QtCore.QUrl.fromLocalFile(str(row.info["path"]))
        self.player.setSource(url)
        self.player.play()
        row.setPlaying(True)
        self._current_row = row

    def _on_position(self, pos_ms: int):
        if not self._current_row:
            return
        dur = max(1, int(self.player.duration()))
        p = max(0.0, min(1.0, pos_ms / float(dur)))
        self._current_row.setProgress(p)

    def _on_status(self, status):
        # al terminar, deseleccionar y permitir replay
        if status == QtMultimedia.QMediaPlayer.EndOfMedia and self._current_row:
            self._current_row.setPlaying(False)
            self._current_row.setProgress(0.0)
            self._current_row = None

    # ---------- teclado (↑/↓/Enter/Espacio) ----------
    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.KeyPress:
            key = ev.key()
            visible_rows = [r for r in self.rows if r.isVisible()]
            if not visible_rows:
                return False
            if key in (QtCore.Qt.Key_Enter, QtCore.Qt.Key_Return, QtCore.Qt.Key_Space):
                target = self._current_row or visible_rows[0]
                self._toggle_play_row(target)
                return True
            elif key == QtCore.Qt.Key_Down:
                if self._current_row is None:
                    self._toggle_play_row(visible_rows[0]); return True
                try:
                    idx = visible_rows.index(self._current_row)
                except ValueError:
                    idx = -1
                next_row = visible_rows[min(idx + 1, len(visible_rows) - 1)]
                self._toggle_play_row(next_row)
                return True
            elif key == QtCore.Qt.Key_Up:
                if self._current_row is None:
                    self._toggle_play_row(visible_rows[0]); return True
                try:
                    idx = visible_rows.index(self._current_row)
                except ValueError:
                    idx = 0
                prev_row = visible_rows[max(idx - 1, 0)]
                self._toggle_play_row(prev_row)
                return True
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




