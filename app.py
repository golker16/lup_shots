# app.py
# Cambios en esta versión:
# - ORDEN Y NAVEGACIÓN
#   • Los favoritos (★) se ordenan primero SIEMPRE dentro de los resultados visibles.
#   • La navegación con ↑/↓ usa el nuevo orden visible (no el orden original interno).
#   • Al cambiar favoritos, el orden y la navegación se actualizan de inmediato.
#   • Al moverse con ↑/↓ se hace STOP del actual y se reproduce el nuevo inmediatamente.
#
# - PARSING POR CARPETAS (nuevo esquema) con fallback al formato viejo
#   Estructura recomendada:  ONESHOT/LOOP → género → general → (subcarpetas) → archivo
#   Ej.: ONESHOT/trap/drums/kick_X_808 mafia 1_KEY_NO_BPM_NO.wav
#   • sample_type = carpeta raíz (oneshot/loop)
#   • genres = [carpeta 1]
#   • generals = [carpeta 2]
#   • specifics = subcarpetas extra + prefijo del archivo antes de "_X_"
#   • title = texto entre "_X_" y "_KEY_/_BPM_" (se quita número final, p.ej. "808 mafia 1" → "808 mafia")
#   • key/bpm = sufijos "_KEY_*" y "_BPM_*" (NO → vacío/0)
#
# - INTERFAZ
#   • Popover de onda flotante anclado debajo, se oculta al pasar el mouse por encima.
#   • Entre el botón Drag y Play se muestra carátula/cover art (si existe vía mutagen) o un placeholder (WAV/MP3/FLAC…).
#   • Clic en cualquier parte de la fila (menos chips/estrella) reproduce/pausa.
#   • Menús de Key/BPM/Tipo: solo uno abierto a la vez; se cierran al clicar fuera o re-clic en el mismo botón.
#
# Requisitos opcionales: `mutagen` para leer carátulas incrustadas. Si no está, se usa placeholder.
import os, re, sys, json, unicodedata, contextlib, wave
from pathlib import Path
from collections import Counter

from PySide6 import QtCore, QtGui, QtWidgets, QtMultimedia
import qdarkstyle

APP_NAME = "Lup Shots"
APP_ORG  = "Lup"

VALID_EXTS = {".wav", ".aiff", ".aif", ".mp3", ".flac", ".ogg"}

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

def _clean_title_remove_trailing_number(title: str) -> str:
    # "808 mafia 1" -> "808 mafia" ; "Name - 02" -> "Name"
    t = re.sub(r"[\s\-]*\d+\s*$", "", title).strip()
    return t or title

def parse_from_path(path: Path, root: Path):
    """
    Parsing por CARPETAS (preferido) con fallback al formato anterior.
    """
    try:
        rel = path.relative_to(root)
    except Exception:
        rel = path

    parts = list(rel.parts)
    # parts: [ONESHOT|LOOP, genre, general, (subdirs*), filename]
    sample_type = ""
    genres, generals, specifics = [], [], []

    if len(parts) >= 2 and parts[0].upper() in ("ONESHOT", "LOOP"):
        sample_type = parts[0].lower()
        if len(parts) >= 2: genres.append(parts[1])
        if len(parts) >= 3: generals.append(parts[2])
        if len(parts) > 4:
            # subcarpetas entre "general" y archivo
            specifics.extend(list(parts[3:-1]))
        filename = parts[-1]
        meta_name = _parse_filename_piecewise(filename)
    else:
        # Fallback al formato anterior dentro del nombre
        filename = parts[-1]
        meta_name = _parse_legacy_filename(filename)

    # fusionar resultados (para esquema de carpetas también añadimos specifics del nombre)
    if sample_type:
        meta_name["sample_type"] = sample_type
    if genres:
        meta_name["genres"] = genres
    if generals:
        meta_name["generals"] = generals
    if specifics:
        meta_name["specifics"] = list(dict.fromkeys(specifics + meta_name.get("specifics", [])))  # unique order

    # limpiar título (quitar número final)
    meta_name["title"] = _clean_title_remove_trailing_number(meta_name.get("title", ""))

    return meta_name

def _parse_filename_piecewise(filename: str):
    """
    filename estilo: <specifics>_X_<TITLE>_KEY_<key>_BPM_<bpm>.<ext>
    """
    base = re.sub(r"\.[^.]+$", "", filename)

    parts = base.split("_X_")
    pre = parts[0] if parts else ""
    tail = parts[1] if len(parts) > 1 else ""

    # specifics desde el prefijo (separados por "_")
    sp_from_name = [t for t in pre.split("_") if t]

    # KEY/BPM
    mkey = re.search(r"(?:^|_)KEY_([^_]+)", tail, flags=re.I)
    key = (mkey.group(1).upper() if mkey else "").strip()
    key = "" if (not key or key == "NO") else key

    mbpm = re.search(r"(?:^|_)BPM_([^_]+)", tail, flags=re.I)
    bpm = 0
    if mbpm:
        bpm_txt = mbpm.group(1).strip()
        if bpm_txt.upper() != "NO" and bpm_txt.isdigit():
            bpm = int(bpm_txt)

    # título (hasta KEY/BPM)
    title = tail
    title = re.sub(r"_KEY_.*", "", title, flags=re.I)
    title = re.sub(r"_BPM_.*", "", title, flags=re.I)
    title = title.replace("_", " ").strip() or base

    return dict(
        sample_type="", genres=[], generals=[], specifics=sp_from_name,
        title=title, key=key, bpm=bpm
    )

def _parse_legacy_filename(filename: str):
    """
    Compat anterior:
    ONESHOT_GENERO_house_X_drums_X_clap_snare_X_JAUS_KEY_NO_BPM_120.wav
    """
    base = re.sub(r"\.[^.]+$", "", filename)

    sample_type = ""
    if base.upper().startswith("ONESHOT_"):
        sample_type = "oneshot"; base = base[len("ONESHOT_"):]
    elif base.upper().startswith("LOOP_"):
        sample_type = "loop"; base = base[len("LOOP_"):]

    parts = base.split("_X_")

    def clean(s): return (s or "").strip()
    graw = clean(parts[0] if len(parts) > 0 else "")
    genres = [t for t in re.sub(r"^GENERO_", "", graw, flags=re.I).split("_") if t]

    gr = clean(parts[1] if len(parts) > 1 else "")
    generals = [t for t in gr.split("_") if t]

    sp = clean(parts[2] if len(parts) > 2 else "")
    specifics = [t for t in sp.split("_") if t]

    tail = "_X_".join(parts[3:]) if len(parts) > 3 else ""

    mkey = re.search(r"(?:^|_)KEY_([^_]+)", tail, flags=re.I)
    key = (mkey.group(1).upper() if mkey else "").strip()
    key = "" if (not key or key == "NO") else key

    mbpm = re.search(r"(?:^|_)BPM_([^_]+)", tail, flags=re.I)
    bpm = 0
    if mbpm:
        bpm_txt = mbpm.group(1).strip()
        if bpm_txt.upper() != "NO" and bpm_txt.isdigit():
            bpm = int(bpm_txt)

    title = tail
    title = re.sub(r"_KEY_.*", "", title, flags=re.I)
    title = re.sub(r"_BPM_.*", "", title, flags=re.I)
    title = title.replace("_", " ").strip() or base

    return dict(
        sample_type=sample_type, genres=genres, generals=generals, specifics=specifics,
        title=title, key=key, bpm=bpm
    )

def read_pcm_waveform(path: Path, peaks=160):
    """
    Devuelve (peaks:list[float] or None, duration:float, sample_rate:int|0, bit_depth:int|0)
    Solo WAV PCM sin dependencias externas. Otros formatos: (None, 0.0, 0, 0)
    """
    try:
        if path.suffix.lower() != ".wav":
            return None, 0.0, 0, 0
        with contextlib.closing(wave.open(str(path), "rb")) as wf:
            n_channels = wf.getnchannels()
            n_frames   = wf.getnframes()
            framerate  = wf.getframerate()
            sampwidth  = wf.getsampwidth()  # bytes por muestra
            duration   = (n_frames / float(framerate)) if framerate else 0.0
            bit_depth  = sampwidth * 8
            sample_rate = framerate

            blocks = max(1, peaks)
            step = max(1, n_frames // blocks)
            import struct
            out = []
            for i in range(blocks):
                wf.setpos(min(i * step, n_frames - 1))
                frames = wf.readframes(min(step, n_frames - i * step))
                if sampwidth == 3:  # 24-bit aprox
                    samples = []
                    stride = 3 * n_channels
                    for j in range(0, len(frames) - stride + 1, stride):
                        chunk = frames[j:j+3]
                        b = int.from_bytes(chunk, "little", signed=True)
                        samples.append(abs(b) / float(2**23))
                else:
                    fmt_char = {1:"b", 2:"h", 4:"i"}.get(sampwidth)
                    if not fmt_char:
                        out.append(0.0); continue
                    fmt = "<" + fmt_char * (len(frames) // sampwidth)
                    ints = struct.unpack(fmt, frames)
                    ch0 = ints[0::n_channels] if n_channels > 0 else ints
                    max_val = float(2 ** (bit_depth - 1))
                    samples = [abs(x) / (max_val or 1.0) for x in ch0]
                peak = max(samples) if samples else 0.0
                out.append(peak)
            mx = max(out) if out else 1.0
            peaks_norm = [p / (mx or 1.0) for p in out]
            return peaks_norm, duration, sample_rate, bit_depth
    except Exception:
        return None, 0.0, 0, 0

# ---------- Cover art util (opcional con mutagen) ----------
def load_cover_pixmap(path: Path) -> QtGui.QPixmap | None:
    """
    Intenta extraer carátula incrustada usando mutagen (si está instalado).
    Soporta MP3 (ID3/APIC), FLAC (pictures), WAV con ID3 embebido (raro).
    """
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(str(path))
        if audio is None:
            return None
        data = None
        # MP3/ID3
        if hasattr(audio, "tags") and audio.tags:
            for key in list(audio.tags.keys()):
                if str(key).startswith("APIC"):
                    data = audio.tags[key].data
                    break
                if str(key).startswith("PIC"):
                    data = audio.tags[key].data
                    break
        # FLAC
        if data is None and hasattr(audio, "pictures") and audio.pictures:
            data = audio.pictures[0].data
        if data:
            img = QtGui.QImage.fromData(data)
            if not img.isNull():
                return QtGui.QPixmap.fromImage(img)
    except Exception:
        return None
    return None

def placeholder_pixmap(ext: str, size: int = 40) -> QtGui.QPixmap:
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtGui.QColor("#1f2937"))
    p = QtGui.QPainter(pm)
    p.setPen(QtGui.QColor("#e5e7eb"))
    font = QtGui.QFont()
    font.setPointSize(8); font.setBold(True)
    p.setFont(font)
    text = (ext or "").lstrip(".").upper()[:4] or "AUDIO"
    p.drawText(pm.rect(), QtCore.Qt.AlignCenter, text)
    p.end()
    return pm

# ----------------- UI: chips -----------------
class TagChip(QtWidgets.QFrame):
    includeRequested = QtCore.Signal(str)
    excludeRequested = QtCore.Signal(str)

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
        self.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(8,2,8,2); lay.setSpacing(6)

        self.lab = QtWidgets.QLabel(text); self.lab.setStyleSheet("border:none;")
        lay.addWidget(self.lab)

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

# ----------------- drag button -----------------
class DragButton(QtWidgets.QToolButton):
    def __init__(self, get_path_callable, parent=None):
        super().__init__(parent)
        self._get_path = get_path_callable
        self.setText("⠿")
        self.setToolTip("Arrastra para soltar este audio en tu DAW")
        self.setCursor(QtGui.QCursor(QtCore.Qt.OpenHandCursor))
        self.setStyleSheet("QToolButton{background:#1a1a1f;color:#9ca3af;border:1px solid #2e2e33;border-radius:8px;} QToolButton:hover{color:#e5e7eb;}")

    def mouseMoveEvent(self, e: QtGui.QMouseEvent):
        if e.buttons() & QtCore.Qt.LeftButton:
            path = self._get_path()
            if not path: return
            mime = QtCore.QMimeData()
            mime.setUrls([QtCore.QUrl.fromLocalFile(str(path))])
            drag = QtGui.QDrag(self)
            drag.setMimeData(mime)
            drag.exec(QtCore.Qt.CopyAction)
        else:
            super().mouseMoveEvent(e)

# ----------------- WaveWidget / PlayerPopover -----------------
class WaveWidget(QtWidgets.QWidget):
    def __init__(self, peaks=None, parent=None):
        super().__init__(parent)
        self._peaks = peaks or []
        self._progress = 0.0
        self.setMinimumHeight(54)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Fixed)

    def setPeaks(self, peaks): self._peaks = peaks or []; self.update()
    def setProgress(self, p): self._progress = max(0.0, min(1.0, p)); self.update()

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        r = self.rect()
        mid = r.center().y()
        w = max(1, r.width()); h = r.height()
        bars = max(1, len(self._peaks) or 120)
        barW = max(1, int(w / bars))
        cutoff = int(bars * self._progress)
        p.setPen(QtCore.Qt.NoPen)

        p.setBrush(QtGui.QColor("#e5e7eb"))
        for i in range(min(cutoff, bars)):
            pk = self._peaks[i] if (self._peaks and i < len(self._peaks)) else 0.35
            bh = max(1, int(pk * h * 0.92)); y = int(mid - bh / 2)
            p.drawRect(QtCore.QRect(int(i * (w / bars)), y, max(1, int(barW * 0.85)), bh))

        p.setBrush(QtGui.QColor("#a1a1aa"))
        for i in range(cutoff, bars):
            pk = self._peaks[i] if (self._peaks and i < len(self._peaks)) else 0.35
            bh = max(1, int(pk * h * 0.92)); y = int(mid - bh / 2)
            p.drawRect(QtCore.QRect(int(i * (w / bars)), y, max(1, int(barW * 0.85)), bh))

class PlayerPopover(QtWidgets.QFrame):
    """Popover hijo de la ventana principal (no se superpone sobre otras apps). Se oculta al pasar el mouse por encima."""
    def __init__(self, parent_window: QtWidgets.QMainWindow):
        super().__init__(parent_window)
        self._parent_window = parent_window
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.SubWindow)
        at = QtCore.Qt.WA_TranslucentBackground
        self.setAttribute(at, True)
        self.setObjectName("PlayerPopover")

        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24); shadow.setXOffset(0); shadow.setYOffset(8); shadow.setColor(QtGui.QColor(0,0,0,150))
        self.setGraphicsEffect(shadow)

        wrap = QtWidgets.QVBoxLayout(self)
        wrap.setContentsMargins(10,10,10,10); wrap.setSpacing(8)

        body = QtWidgets.QFrame(self)
        body.setStyleSheet("#PlayerPopover > QFrame { background:#101014; border:1px solid #2e2e33; border-radius:12px; }")
        inner = QtWidgets.QHBoxLayout(body); inner.setContentsMargins(12,12,12,12); inner.setSpacing(12)

        self.wave = WaveWidget()
        inner.addWidget(self.wave, 1)

        rightBox = QtWidgets.QVBoxLayout(); rightBox.setContentsMargins(0,0,0,0); rightBox.setSpacing(4)
        self.lblRate = QtWidgets.QLabel("—")
        self.lblBits = QtWidgets.QLabel("—")
        for lbl in (self.lblRate, self.lblBits):
            lbl.setStyleSheet("color:#cbd5e1;")
            lbl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        rightBox.addWidget(self.lblRate); rightBox.addWidget(self.lblBits)
        inner.addLayout(rightBox, 0)

        wrap.addWidget(body)

        self._duration_ms = 1
        self._anchor_widget = None
        self.resize(560, 96)

        # Ocultar al pasar el mouse por encima
        self.setMouseTracking(True)

    def enterEvent(self, e):
        self.hide()
        super().enterEvent(e)

    def mouseMoveEvent(self, e):
        self.hide()
        super().mouseMoveEvent(e)

    def setInfo(self, peaks, sample_rate, bit_depth, duration_ms: int):
        self.wave.setPeaks(peaks)
        self._duration_ms = max(1, duration_ms)
        rate_txt = f"{sample_rate/1000:.1f} kHz" if sample_rate else "—"
        bits_txt = f"{bit_depth}-bit" if bit_depth else "—"
        self.lblRate.setText(rate_txt)
        self.lblBits.setText(bits_txt)

    def setProgressMs(self, pos_ms: int):
        frac = max(0.0, min(1.0, pos_ms / float(self._duration_ms)))
        self.wave.setProgress(frac)

    def show_for_anchor(self, anchor: QtWidgets.QWidget):
        self._anchor_widget = anchor
        self._reposition()
        self.show()
        self.raise_()

    def _reposition(self):
        if not self._anchor_widget:
            return
        local_pt = self._anchor_widget.mapTo(self._parent_window, QtCore.QPoint(0, self._anchor_widget.height()))
        screen_w = self._parent_window.width()
        desired_w = min(640, max(420, int(screen_w * 0.55)))
        self.resize(desired_w, self.height())
        x = local_pt.x() - 12
        y = local_pt.y() + 6
        x = max(16, min(x, self._parent_window.width() - self.width() - 16))
        self.move(x, y)

# ----------------- Filtros (Key / BPM / Tipo) -----------------
class AnchorPopover(QtWidgets.QFrame):
    def __init__(self, parent_window: QtWidgets.QMainWindow):
        super().__init__(parent_window)
        self._parent_window = parent_window
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.SubWindow)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setObjectName("FilterPopover")
        self.setStyleSheet("""
            #FilterPopover > QFrame { background:#18181b; border:1px solid #30303a; border-radius:12px; }
            QPushButton, QToolButton { background:#232327; color:#e5e7eb; border:1px solid #3a3a44; border-radius:8px; padding:4px 10px; }
            QPushButton:hover, QToolButton:hover { background:#2a2b31; }
            QLabel { color:#e5e7eb; }
            QLineEdit { background:#1a1a1f; border:1px solid #2e2e33; border-radius:8px; padding:4px 8px; color:#e5e7eb; }
            QTabBar::tab { padding:8px 12px; background:#1a1a1f; color:#e5e7eb; border:1px solid #2e2e33; border-bottom: none; border-top-left-radius:10px; border-top-right-radius:10px; margin-right:6px; }
            QTabBar::tab:selected { background:#0b2530; border-color:#123043; }
            QSlider::groove:horizontal { height:6px; background:#2e2e33; border-radius:4px; }
            QSlider::handle:horizontal { background:#e5e7eb; width:14px; border-radius:7px; margin:-6px 0; }
        """)
        self._anchor = None

    def show_for_anchor(self, anchor: QtWidgets.QWidget):
        self._anchor = anchor
        self._reposition()
        self.show()
        self.raise_()

    def _reposition(self):
        if not self._anchor: return
        pt = self._anchor.mapTo(self._parent_window, QtCore.QPoint(0, self._anchor.height()))
        x = max(8, min(pt.x(), self._parent_window.width() - self.width() - 8))
        y = pt.y() + 6
        self.move(x, y)

class KeyFilterPopover(AnchorPopover):
    changed = QtCore.Signal(set, str)  # (keys, scale)

    def __init__(self, parent_window):
        super().__init__(parent_window)
        outer = QtWidgets.QVBoxLayout(self); outer.setContentsMargins(10,10,10,10); outer.setSpacing(8)
        card = QtWidgets.QFrame(self)
        lay = QtWidgets.QVBoxLayout(card); lay.setContentsMargins(12,12,12,12); lay.setSpacing(10)

        tabs = QtWidgets.QTabWidget(); tabs.setTabPosition(QtWidgets.QTabWidget.North)
        flats = QtWidgets.QWidget(); sharps = QtWidgets.QWidget()
        tabs.addTab(flats, "Flat keys"); tabs.addTab(sharps, "Sharp keys")

        self._key_buttons = []

        def grid_keys(parent, labels):
            grid = QtWidgets.QGridLayout(parent); grid.setContentsMargins(0,0,0,0); grid.setSpacing(8)
            row, col = 0, 0
            for k in labels:
                btn = QtWidgets.QToolButton(); btn.setText(k); btn.setCheckable(True)
                btn.setMinimumWidth(44)
                btn.clicked.connect(self._on_key_toggle)
                self._key_buttons.append(btn)
                grid.addWidget(btn, row, col)
                col += 1
                if col >= 7: row += 1; col = 0

        grid_keys(flats, ["Db","Eb","Gb","Ab","Bb","C","D","E","F","G","A","B"])
        grid_keys(sharps, ["C#","D#","F#","G#","A#","C","D","E","F","G","A","B"])

        lay.addWidget(tabs)

        scaleRow = QtWidgets.QHBoxLayout(); scaleRow.setSpacing(8)
        self.btnMaj = QtWidgets.QPushButton("Major"); self.btnMaj.setCheckable(True)
        self.btnMin = QtWidgets.QPushButton("Minor"); self.btnMin.setCheckable(True)
        for b in (self.btnMaj, self.btnMin): b.clicked.connect(self._exclusive_scale_emit)
        scaleRow.addWidget(self.btnMaj); scaleRow.addWidget(self.btnMin); scaleRow.addStretch(1)
        lay.addLayout(scaleRow)

        foot = QtWidgets.QHBoxLayout(); foot.addWidget(QtWidgets.QLabel('<a href="#">Clear</a>'))
        foot.itemAt(0).widget().linkActivated.connect(self._clear)
        foot.addStretch(1)
        btnClose = QtWidgets.QPushButton("Close")
        btnClose.clicked.connect(self.hide)
        foot.addWidget(btnClose)
        lay.addLayout(foot)

        outer.addWidget(card)
        self.resize(360, 240)

    def _on_key_toggle(self):
        # si no hay escala elegida y se activó alguna nota, asumir Major
        if not (self.btnMaj.isChecked() or self.btnMin.isChecked()):
            if any(b.isChecked() for b in self._key_buttons):
                self.btnMaj.setChecked(True)
        self._emit_change()

    def _exclusive_scale_emit(self):
        sender = self.sender()
        if sender is self.btnMaj and self.btnMaj.isChecked():
            self.btnMin.setChecked(False)
        elif sender is self.btnMin and self.btnMin.isChecked():
            self.btnMaj.setChecked(False)
        self._emit_change()

    def _collect(self):
        keys = {btn.text() for btn in self._key_buttons if btn.isChecked()}
        scale = "Major" if self.btnMaj.isChecked() else ("Minor" if self.btnMin.isChecked() else "")
        return keys, scale

    def _emit_change(self):
        keys, scale = self._collect()
        self.changed.emit(keys, scale)

    def _clear(self):
        for btn in self._key_buttons: btn.setChecked(False)
        self.btnMaj.setChecked(False); self.btnMin.setChecked(False)
        self._emit_change()

class BPMFilterPopover(AnchorPopover):
    changed = QtCore.Signal(int, int, int)  # (min, max, exact or 0)

    def __init__(self, parent_window):
        super().__init__(parent_window)
        outer = QtWidgets.QVBoxLayout(self); outer.setContentsMargins(10,10,10,10); outer.setSpacing(8)
        card = QtWidgets.QFrame(self)
        lay = QtWidgets.QVBoxLayout(card); lay.setContentsMargins(12,12,12,12); lay.setSpacing(10)

        tabs = QtWidgets.QTabWidget(); tabs.setTabPosition(QtWidgets.QTabWidget.North)
        self.pageRange = QtWidgets.QWidget(); self.pageExact = QtWidgets.QWidget()
        tabs.addTab(self.pageRange, "Range"); tabs.addTab(self.pageExact, "Exact")

        # RANGE
        rlay = QtWidgets.QVBoxLayout(self.pageRange); rlay.setContentsMargins(0,0,0,0); rlay.setSpacing(10)
        row1 = QtWidgets.QHBoxLayout()
        self.minSpin = QtWidgets.QSpinBox(); self.minSpin.setRange(1, 400); self.minSpin.setValue(1)
        self.maxSpin = QtWidgets.QSpinBox(); self.maxSpin.setRange(1, 400); self.maxSpin.setValue(300)
        self.minSpin.valueChanged.connect(lambda _: self._sync_range(from_spin=True))
        self.maxSpin.valueChanged.connect(lambda _: self._sync_range(from_spin=True))
        row1.addWidget(QtWidgets.QLabel("Min")); row1.addWidget(self.minSpin)
        row1.addSpacing(8); row1.addWidget(QtWidgets.QLabel("—"))
        row1.addSpacing(8); row1.addWidget(QtWidgets.QLabel("Max")); row1.addWidget(self.maxSpin)
        rlay.addLayout(row1)

        self.minSlider = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.minSlider.setRange(1, 400); self.minSlider.setValue(1)
        self.maxSlider = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.maxSlider.setRange(1, 400); self.maxSlider.setValue(300)
        self.minSlider.valueChanged.connect(lambda _: self._sync_range(from_spin=False))
        self.maxSlider.valueChanged.connect(lambda _: self._sync_range(from_spin=False))
        rlay.addWidget(self.minSlider); rlay.addWidget(self.maxSlider)

        # EXACT
        exLay = QtWidgets.QHBoxLayout(self.pageExact); exLay.setContentsMargins(0,0,0,0); exLay.setSpacing(8)
        self.exactSpin = QtWidgets.QSpinBox(); self.exactSpin.setRange(1, 400); self.exactSpin.setValue(120)
        self.exactSpin.valueChanged.connect(lambda _: self._apply(live=True))
        exLay.addWidget(QtWidgets.QLabel("BPM")); exLay.addWidget(self.exactSpin); exLay.addStretch(1)

        foot = QtWidgets.QHBoxLayout()
        clearLbl = QtWidgets.QLabel('<a href="#">Clear</a>')
        clearLbl.linkActivated.connect(self._clear)
        foot.addWidget(clearLbl); foot.addStretch(1)
        btnSave  = QtWidgets.QPushButton("Save")
        btnSave.clicked.connect(self._apply)
        foot.addWidget(btnSave)

        lay.addWidget(tabs); lay.addLayout(foot)
        outer.addWidget(card)
        self.resize(360, 220)

    def _sync_range(self, from_spin: bool):
        if from_spin:
            self.minSlider.setValue(self.minSpin.value())
            self.maxSlider.setValue(self.maxSpin.value())
        else:
            self.minSpin.setValue(self.minSlider.value())
            self.maxSpin.setValue(self.maxSlider.value())
        mn, mx = sorted((self.minSpin.value(), self.maxSpin.value()))
        self.minSpin.blockSignals(True); self.maxSpin.blockSignals(True)
        self.minSpin.setValue(mn); self.maxSpin.setValue(mx)
        self.minSpin.blockSignals(False); self.maxSpin.blockSignals(False)
        # aplicar en vivo
        self._apply(live=True)

    def _clear(self):
        self.minSpin.setValue(1); self.maxSpin.setValue(300); self.exactSpin.setValue(120)
        self.changed.emit(1, 300, 0)

    def _apply(self, live: bool=False):
        if self.findChild(QtWidgets.QTabWidget).currentIndex() == 1:
            self.changed.emit(0, 0, self.exactSpin.value())
            if not live: self.hide()
        else:
            mn, mx = sorted((self.minSpin.value(), self.maxSpin.value()))
            self.changed.emit(mn, mx, 0)
            if not live: self.hide()

class TypeFilterPopover(AnchorPopover):
    changed = QtCore.Signal(str)  # 'loop' | 'oneshot' | ''

    def __init__(self, parent_window):
        super().__init__(parent_window)
        outer = QtWidgets.QVBoxLayout(self); outer.setContentsMargins(10,10,10,10); outer.setSpacing(8)
        card = QtWidgets.QFrame(self)
        lay = QtWidgets.QVBoxLayout(card); lay.setContentsMargins(12,12,12,12); lay.setSpacing(10)

        self.grp = QtWidgets.QButtonGroup(self)
        self.rbLoops = QtWidgets.QRadioButton("Loops")
        self.rbOnes  = QtWidgets.QRadioButton("One-Shots")
        self.grp.addButton(self.rbLoops); self.grp.addButton(self.rbOnes)
        self.rbLoops.toggled.connect(lambda _: self._emit_and_close())
        self.rbOnes.toggled.connect(lambda _: self._emit_and_close())

        lay.addWidget(self.rbLoops); lay.addWidget(self.rbOnes)
        lay.addSpacing(10)
        foot = QtWidgets.QHBoxLayout()
        clearLbl = QtWidgets.QLabel('<a href="#">Clear</a>')
        clearLbl.linkActivated.connect(self._clear)
        foot.addWidget(clearLbl); foot.addStretch(1)
        btnClose = QtWidgets.QPushButton("Close")
        btnClose.clicked.connect(self.hide)
        foot.addWidget(btnClose)
        lay.addLayout(foot)

        outer.addWidget(card)
        self.resize(280, 160)

    def _clear(self):
        self.grp.setExclusive(False)
        self.rbLoops.setChecked(False); self.rbOnes.setChecked(False)
        self.grp.setExclusive(True)
        self.changed.emit("")

    def _emit_and_close(self):
        if self.rbLoops.isChecked():
            self.changed.emit("loop"); self.hide()
        elif self.rbOnes.isChecked():
            self.changed.emit("oneshot"); self.hide()

# ----------------- fila -----------------
class SampleRow(QtWidgets.QFrame):
    playClicked = QtCore.Signal(object)
    starToggled = QtCore.Signal(object)
    tagInclude  = QtCore.Signal(str)
    tagExclude  = QtCore.Signal(str)

    def __init__(self, info, is_fav: bool, parent=None):
        super().__init__(parent)
        self.info = info
        self.isPlaying = False
        self.isFav = is_fav
        self.setObjectName("SampleRow")
        self._apply_style()

        # Drag
        self.btnDrag = DragButton(lambda: self.info["path"])
        self.btnDrag.setFixedWidth(40)

        # Cover art
        self.cover = QtWidgets.QLabel()
        self.cover.setFixedSize(40, 40)
        pm = load_cover_pixmap(info["path"]) or placeholder_pixmap(info["path"].suffix, 40)
        self.cover.setPixmap(pm.scaled(40, 40, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        self.cover.setToolTip("Carátula/cover art (si existe)")

        # Play
        self.btnPlay = QtWidgets.QPushButton("▶")
        self.btnPlay.setFixedWidth(40)
        self.btnPlay.clicked.connect(lambda: self.playClicked.emit(self))
        self.btnPlay.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))

        # Chips (género/general/específicos/key)
        chipsL = QtWidgets.QHBoxLayout(); chipsL.setContentsMargins(0,0,0,0); chipsL.setSpacing(6)
        for g in info["genres"]:
            c = TagChip(g, "blue");   c.includeRequested.connect(self.tagInclude); c.excludeRequested.connect(self.tagExclude); chipsL.addWidget(c)
        for g in info["generals"]:
            c = TagChip(g, "indigo"); c.includeRequested.connect(self.tagInclude); c.excludeRequested.connect(self.tagExclude); chipsL.addWidget(c)
        for s in info["specifics"]:
            c = TagChip(s, "green");  c.includeRequested.connect(self.tagInclude); c.excludeRequested.connect(self.tagExclude); chipsL.addWidget(c)
        if info["key"]:
            ck = TagChip(info["key"], "violet"); ck.includeRequested.connect(self.tagInclude); ck.excludeRequested.connect(self.tagExclude); chipsL.addWidget(ck)

        chipsW = QtWidgets.QWidget(); chipsW.setStyleSheet("background:transparent;")
        ch = QtWidgets.QHBoxLayout(chipsW); ch.setContentsMargins(0,0,0,0); ch.setSpacing(6); ch.addLayout(chipsL); ch.addStretch(1)

        # Título + metadatos
        self.nameLbl = QtWidgets.QLabel(info["title"]); self.nameLbl.setStyleSheet("color:#e5e7eb;")
        self.nameLbl.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.nameLbl.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.nameLbl.mousePressEvent = lambda e: (self.playClicked.emit(self), e.accept())

        self.metaLbl = QtWidgets.QLabel(self._meta_text()); self.metaLbl.setStyleSheet("color:#9ca3af;")
        self.metaLbl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        # Estrella
        self.btnStar = QtWidgets.QToolButton()
        self.btnStar.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self._sync_star_icon()
        self.btnStar.clicked.connect(self._toggle_star)
        self._update_star_visibility(show_hover=False)

        left = QtWidgets.QHBoxLayout(); left.setContentsMargins(0,0,0,0); left.setSpacing(8)
        left.addWidget(chipsW); left.addWidget(self.nameLbl, 1); left.addWidget(self.metaLbl, 0); left.addWidget(self.btnStar)
        leftW = QtWidgets.QWidget(); leftW.setStyleSheet("background:transparent;"); leftW.setLayout(left)
        leftW.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        leftW.mousePressEvent = lambda e: (self.playClicked.emit(self), e.accept())

        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(10,10,10,10)
        grid.setHorizontalSpacing(10)
        # Orden: Drag | Cover | Play | resto
        grid.addWidget(self.btnDrag, 0, 0)
        grid.addWidget(self.cover,   0, 1)
        grid.addWidget(self.btnPlay, 0, 2)
        grid.addWidget(leftW,        0, 3)
        grid.setColumnStretch(3, 1)

        self.setMouseTracking(True)

    def _meta_text(self):
        pieces = []
        if self.info.get("sample_type"): pieces.append(self.info["sample_type"])
        if self.info.get("bpm"): pieces.append(f'{self.info["bpm"]} BPM')
        return " · ".join(pieces)

    def anchor_widget(self) -> QtWidgets.QWidget:
        return self.btnPlay

    def enterEvent(self, e):
        self._update_star_visibility(show_hover=True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._update_star_visibility(show_hover=False)
        super().leaveEvent(e)

    def _apply_style(self):
        if self.isPlaying:
            self.setStyleSheet("#SampleRow { background: rgba(37,99,235,0.18); border:1px solid #3b82f6; border-radius:12px; }")
        else:
            self.setStyleSheet("#SampleRow { background:#19191d; border:1px solid #303039; border-radius:12px; }")

    def _sync_star_icon(self):
        self.btnStar.setText("★" if self.isFav else "☆")
        self.btnStar.setToolTip("Quitar de favoritos" if self.isFav else "Marcar como favorito")

    def _update_star_visibility(self, show_hover: bool):
        if self.isFav:
            self.btnStar.setVisible(True)
        else:
            self.btnStar.setVisible(show_hover)

    def _toggle_star(self):
        self.isFav = not self.isFav
        self._sync_star_icon()
        self._update_star_visibility(show_hover=True)
        self.starToggled.emit(self)

    def setPlaying(self, v: bool):
        self.isPlaying = v; self.btnPlay.setText("⏸" if v else "▶"); self._apply_style()

# ----------------- fila de sugeridos -----------------
class TagRow(QtWidgets.QWidget):
    includeRequested = QtCore.Signal(str)
    excludeRequested = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self._tags = []           # [(tag, count)]
        self._ignored = set()
        self._hidden_for_menu = []
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.setMinimumHeight(28)

        self.wrap = QtWidgets.QHBoxLayout(self)
        self.wrap.setContentsMargins(0,0,0,0); self.wrap.setSpacing(6)

        self.menuBtn = QtWidgets.QToolButton()
        self.menuBtn.setText("…")
        self.menuBtn.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.menuBtn.setMinimumWidth(28)
        self.menuBtn.setStyleSheet("background:#232327;color:#e5e7eb;border:1px solid #3a3a44;border-radius:8px;padding:2px 10px;")
        self.menuBtn.clicked.connect(self._open_menu)

    def setData(self, tags_with_count, ignored=set()):
        self._tags = sorted([t for t in tags_with_count if t[0] not in ignored], key=lambda x: (-x[1], x[0]))
        self._ignored = set(ignored); self._rebuild()

    def resizeEvent(self, e): self._rebuild(); super().resizeEvent(e)

    def _rebuild(self):
        # limpiar correctamente (evita chips duplicados)
        while self.wrap.count():
            it = self.wrap.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        fm = self.fontMetrics()
        menu_w = self.menuBtn.sizeHint().width() + 6
        avail = max(0, self.width() - menu_w)
        used = 0; shown = []

        for tag, cnt in self._tags:
            chip_width = fm.horizontalAdvance(tag) + 22 + 26
            if used + chip_width > avail:
                break
            btn = TagChip(tag, "gray")
            btn.setToolTip(f"{cnt} coincidencias · Clic: incluir · Der: excluir")
            btn.includeRequested.connect(self.includeRequested.emit)
            btn.excludeRequested.connect(self.excludeRequested.emit)
            self.wrap.addWidget(btn); used += chip_width + 6; shown.append(tag)

        self.wrap.addStretch(1)
        self.wrap.addWidget(self.menuBtn)
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
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.positionChanged.connect(self._on_position)

        # filtros de búsqueda
        self.filter_keys = set()
        self.filter_scale = ""           # "Major" | "Minor" | ""
        self.filter_type  = ""           # "loop" | "oneshot" | ""
        self.filter_bpm_min = 1
        self.filter_bpm_max = 300
        self.filter_bpm_exact = 0        # 0 = desactivado

        # filtros de texto/etiquetas
        self.include_tags = set()
        self.exclude_tags = set()
        self.search_tokens = []

        cfg = load_config(); self.favorites = set(cfg.get("favorites", []))

        self._build_ui()
        self._load_samples()
        self._apply_filters()               # <- al abrir: favoritos primero
        self._refresh_tag_suggestions()
        QtCore.QTimer.singleShot(0, self._refresh_tag_suggestions)

        self._current_row = None
        self._ordered_visible_rows = []     # orden visible actual (para navegación ↑/↓)
        self.installEventFilter(self)

        # popover flotante de reproductor
        self.popover = PlayerPopover(self)
        self.scroll.verticalScrollBar().valueChanged.connect(self._reposition_popover)
        self.scroll.horizontalScrollBar().valueChanged.connect(self._reposition_popover)
        self.resizeEvent = self._wrap_resize(self.resizeEvent)

        # popovers de filtros (inicialmente ocultos)
        self.keyPop = KeyFilterPopover(self); self.keyPop.hide(); self.keyPop.changed.connect(self._on_key_filter_changed)
        self.bpmPop = BPMFilterPopover(self); self.bpmPop.hide(); self.bpmPop.changed.connect(self._on_bpm_filter_changed)
        self.typePop = TypeFilterPopover(self); self.typePop.hide(); self.typePop.changed.connect(self._on_type_filter_changed)

        # gestor de popovers (solo 1 abierto)
        self._active_popover = None
        self._active_button  = None

    # ---------- UI ----------
    def _build_ui(self):
        central = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(central); v.setContentsMargins(16,16,16,8); v.setSpacing(10)

        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #121214; }
            QLineEdit { background:#1a1a1f; border:1px solid #2e2e33; border-radius:10px; padding:6px 10px; color:#e5e7eb; }
            QScrollArea { border: none; }
            QMenuBar { background:#121214; color:#e5e7eb; }
            QMenuBar::item:selected { background:#1f2024; }
        """)

        menubar = self.menuBar()
        menubar.setNativeMenuBar(False)
        options = menubar.addMenu("&Opciones")
        act_change = options.addAction("Cambiar carpeta de &samples…")
        act_change.triggered.connect(self.change_folder)

        donate_btn = QtWidgets.QPushButton("Donar")
        donate_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        donate_btn.setStyleSheet("QPushButton{background:#16a34a;color:white;border:1px solid #15803d;border-radius:8px;padding:3px 10px;} QPushButton:hover{background:#22c55e;}")
        donate_btn.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl("https://www.gabrielgolker.com")))
        menubar.setCornerWidget(donate_btn, QtCore.Qt.TopRightCorner)
        QtCore.QTimer.singleShot(0, lambda: donate_btn.setFixedHeight(menubar.height()-2))

        # --- Barra de filtros (encima del buscador) ---
        filterRow = QtWidgets.QHBoxLayout(); filterRow.setContentsMargins(0,0,0,0); filterRow.setSpacing(8)
        self.btnKey  = QtWidgets.QToolButton(); self.btnKey.setText("Key ▾");  self._style_filter_btn(self.btnKey)
        self.btnBPM  = QtWidgets.QToolButton(); self.btnBPM.setText("BPM ▾");  self._style_filter_btn(self.btnBPM)
        self.btnType = QtWidgets.QToolButton(); self.btnType.setText("One-Shots & Loops ▾"); self._style_filter_btn(self.btnType)
        # toggle popovers
        self.btnKey.clicked.connect(lambda: self._toggle_popover(self.keyPop, self.btnKey))
        self.btnBPM.clicked.connect(lambda: self._toggle_popover(self.bpmPop, self.btnBPM))
        self.btnType.clicked.connect(lambda: self._toggle_popover(self.typePop, self.btnType))
        filterRow.addWidget(self.btnKey, 0); filterRow.addWidget(self.btnBPM, 0); filterRow.addWidget(self.btnType, 0); filterRow.addStretch(1)
        v.addLayout(filterRow)

        # buscador
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Buscar (tags, nombre)…")
        self.search.textChanged.connect(self._on_search_text)
        v.addWidget(self.search)

        # filtros activos (include/exclude)
        self.activeWrap = QtWidgets.QHBoxLayout()
        self.activeWrap.setContentsMargins(0,0,0,0); self.activeWrap.setSpacing(6)
        activeW = QtWidgets.QWidget(); activeW.setLayout(self.activeWrap)
        v.addWidget(activeW)

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

        footer = QtWidgets.QLabel("© 2025 Gabriel Golker")
        footer.setAlignment(QtCore.Qt.AlignHCenter)
        footer.setStyleSheet("color:#9ca3af; padding: 8px 0;")
        v.addWidget(footer)

        self.setCentralWidget(central)
        self.resize(1180, 760)

    def _style_filter_btn(self, btn: QtWidgets.QToolButton):
        btn.setStyleSheet("""
            QToolButton { background:#1a1a1f; color:#e5e7eb; border:1px solid #2e2e33; border-radius:12px; padding:6px 12px; }
            QToolButton:hover { background:#202027; }
        """)
        btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))

    # ---------- gestor de popovers ----------
    def _toggle_popover(self, popover: AnchorPopover, button: QtWidgets.QToolButton):
        # re-clic en el mismo botón → cerrar
        if self._active_popover is popover and popover.isVisible():
            popover.hide(); self._active_popover = None; self._active_button = None
        else:
            # cerrar el que esté abierto
            if self._active_popover and self._active_popover.isVisible():
                self._active_popover.hide()
            self._active_popover = popover
            self._active_button  = button
            popover.show_for_anchor(button)

    def _close_active_popover(self):
        if self._active_popover and self._active_popover.isVisible():
            self._active_popover.hide()
        self._active_popover = None
        self._active_button  = None

    # ---------- helpers para click-fuera ----------
    def _global_rect(self, w: QtWidgets.QWidget) -> QtCore.QRect:
        tl = w.mapToGlobal(QtCore.QPoint(0,0))
        br = w.mapToGlobal(QtCore.QPoint(w.width(), w.height()))
        return QtCore.QRect(tl, br)

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
            meta = parse_from_path(p, self.samples_dir)
            peaks, duration, sample_rate, bit_depth = read_pcm_waveform(p)
            duration_ms = int(duration * 1000)
            tags_flat = list(meta["genres"] + meta["generals"] + meta["specifics"])
            if meta["key"]:
                tags_flat.append(meta["key"])
            if meta["sample_type"]:
                tags_flat.append(meta["sample_type"])
            if meta["bpm"]:
                tags_flat.append(str(meta["bpm"]))
            hay = strip_accents_lower(" ".join(tags_flat + [meta["title"], p.name]))
            info = {
                "path": p, "filename": p.name,
                "genres": meta["genres"], "generals": meta["generals"], "specifics": meta["specifics"],
                "title": meta["title"], "key": meta["key"],
                "sample_type": meta["sample_type"], "bpm": meta["bpm"],
                "haystack": hay, "tagset": set(tags_flat),
                "peaks": peaks, "duration_ms": duration_ms,
                "sample_rate": sample_rate, "bit_depth": bit_depth,
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
        # Reordenar inmediatamente manteniendo la fila actual
        self._apply_filters()

    # ---------- filtros (texto/tags) ----------
    def _on_search_text(self, text: str):
        self.search_tokens = [strip_accents_lower(t) for t in text.strip().split() if t]
        self._apply_filters(); self._refresh_tag_suggestions()

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

    # ---------- filtros (Key/BPM/Tipo) ----------
    def _on_key_filter_changed(self, keys: set, scale: str):
        self.filter_keys = set(keys)
        self.filter_scale = scale or ""
        txt = "Key ▾" if not self.filter_keys else f"Key ({', '.join(sorted(self.filter_keys))}{' '+self.filter_scale if self.filter_scale else ''}) ▾"
        self.btnKey.setText(txt)
        self._apply_filters()

    def _on_bpm_filter_changed(self, mn: int, mx: int, exact: int):
        if exact:
            self.filter_bpm_exact = exact
            self.filter_bpm_min, self.filter_bpm_max = 1, 400
            self.btnBPM.setText(f"BPM ({exact}) ▾")
        else:
            self.filter_bpm_exact = 0
            self.filter_bpm_min, self.filter_bpm_max = mn, mx
            if mn == 1 and mx == 300:
                self.btnBPM.setText("BPM ▾")
            else:
                self.btnBPM.setText(f"BPM ({mn}-{mx}) ▾")
        self._apply_filters()

    def _on_type_filter_changed(self, t: str):
        self.filter_type = t or ""
        if not t:
            self.btnType.setText("One-Shots & Loops ▾")
        else:
            label = "Loops" if t == "loop" else "One-Shots"
            self.btnType.setText(f"{label} ▾")
        self._apply_filters()

    # ---------- aplicación de filtros y orden ----------
    def _set_list_order(self, rows_in_order):
        # Limpia el layout (sin destruir las filas) y reaplica en el nuevo orden
        while self.listLayout.count():
            item = self.listLayout.takeAt(0)
            # no eliminamos widgets; simplemente los desprendemos del layout
        for r in rows_in_order:
            self.listLayout.addWidget(r)
        self.listLayout.addStretch(1)

    def _apply_filters(self):
        visible_rows = []
        for i, row in enumerate(self.rows):
            s = self.samples[i]
            visible = True

            # texto
            for tok in self.search_tokens:
                if tok not in s["haystack"]: visible = False; break

            # include/exclude tags
            if visible and self.include_tags and not self.include_tags.issubset(s["tagset"]): visible = False
            if visible and self.exclude_tags and self.exclude_tags.intersection(s["tagset"]): visible = False

            # tipo
            if visible and self.filter_type and s.get("sample_type") != self.filter_type:
                visible = False

            # key
            if visible and self.filter_keys:
                if not s.get("key") or s["key"] not in self.filter_keys:
                    visible = False

            # BPM
            bpm = int(s.get("bpm") or 0)
            if visible and self.filter_bpm_exact:
                if bpm != self.filter_bpm_exact:
                    visible = False
            elif visible:
                if bpm and not (self.filter_bpm_min <= bpm <= self.filter_bpm_max):
                    visible = False

            row.setVisible(visible)
            if visible: visible_rows.append(row)

        # ORDEN: favoritos primero, luego alfabético por título
        visible_rows.sort(key=lambda r: (0 if r.info["filename"] in self.favorites else 1,
                                         strip_accents_lower(r.info["title"])))
        hidden_rows = [r for r in self.rows if r not in visible_rows]

        # Actualizamos el orden en el layout y el orden de navegación
        self._set_list_order(visible_rows + hidden_rows)
        self._ordered_visible_rows = visible_rows

        # Actualiza contador
        self.resLbl.setText(f"{len(visible_rows)} resultado" + ("" if len(visible_rows) == 1 else "s"))

        # Si la fila actual sigue visible, mantenemos su estado; si no, limpiamos
        if self._current_row and self._current_row not in visible_rows:
            self._current_row.setPlaying(False)
            self._current_row = None
            self.player.stop()
            self.popover.hide()

    def _refresh_tag_suggestions(self):
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
    def _ensure_visible(self, row: QtWidgets.QWidget):
        try:
            self.scroll.ensureWidgetVisible(row, xmargin=0, ymargin=8)
        except Exception:
            pass

    def _reposition_popover(self, *args):
        if self._current_row and self._current_row.isVisible():
            self.popover._reposition()

    def _play_row(self, row: SampleRow):
        # Cortar inmediatamente cualquier reproducción actual
        self.player.stop()
        if self._current_row and self._current_row is not row:
            self._current_row.setPlaying(False)

        url = QtCore.QUrl.fromLocalFile(str(row.info["path"]))
        self.player.setSource(url)
        self.player.setPosition(0)
        self.player.play()
        row.setPlaying(True)
        self._current_row = row

        # Popover
        peaks = row.info.get("peaks")
        duration_ms = row.info.get("duration_ms", 0) or 1
        sr = row.info.get("sample_rate", 0)
        bd = row.info.get("bit_depth", 0)
        self.popover.setInfo(peaks, sr, bd, duration_ms)
        self.popover.setProgressMs(0)
        self.popover.show_for_anchor(row.anchor_widget())

        self._ensure_visible(row)

    def _toggle_play_row(self, row: SampleRow):
        if self._current_row is row:
            st = self.player.playbackState()
            if st == QtMultimedia.QMediaPlayer.PlayingState:
                self.player.pause(); row.setPlaying(False)
            else:
                self.player.play(); row.setPlaying(True)
            self.popover.show_for_anchor(row.anchor_widget())
            self._ensure_visible(row)
            return
        self._play_row(row)

    def _move_selection(self, delta: int):
        rows = self._ordered_visible_rows or [r for r in self.rows if r.isVisible()]
        if not rows: return
        if self._current_row is None or self._current_row not in rows:
            target = rows[0] if delta >= 0 else rows[-1]
        else:
            idx = rows.index(self._current_row)
            idx = max(0, min(len(rows)-1, idx + delta))
            target = rows[idx]
        self._play_row(target)

    def _on_state(self, st):
        if not self._current_row: return
        if st == QtMultimedia.QMediaPlayer.PlayingState:
            self._current_row.setPlaying(True)
        elif st == QtMultimedia.QMediaPlayer.PausedState:
            self._current_row.setPlaying(False)

    def _on_position(self, pos_ms: int):
        self.popover.setProgressMs(pos_ms)

    def _on_status(self, status):
        if status == QtMultimedia.QMediaPlayer.EndOfMedia and self._current_row:
            self._current_row.setPlaying(False)
            self.player.setPosition(0)
            self.popover.setProgressMs(0)

    # ---------- teclado + cierre por clic fuera ----------
    def eventFilter(self, obj, ev):
        # Teclado navegación
        if ev.type() == QtCore.QEvent.KeyPress:
            key = ev.key()
            focus = QtWidgets.QApplication.focusWidget()
            is_text = isinstance(focus, (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit))

            if key == QtCore.Qt.Key_Down:
                self._move_selection(+1); return True
            if key == QtCore.Qt.Key_Up:
                self._move_selection(-1); return True

            if key in (QtCore.Qt.Key_Enter, QtCore.Qt.Key_Return):
                if not is_text:
                    rows = self._ordered_visible_rows or [r for r in self.rows if r.isVisible()]
                    target = self._current_row or (rows[0] if rows else None)
                    if target: self._toggle_play_row(target)
                    return True
                return False
            if key == QtCore.Qt.Key_Space:
                if not is_text:
                    rows = self._ordered_visible_rows or [r for r in self.rows if r.isVisible()]
                    if self._current_row is None and rows:
                        self._play_row(rows[0])
                    elif self._current_row:
                        self._toggle_play_row(self._current_row)
                    return True
                return False
            if key == QtCore.Qt.Key_Escape:
                self._close_active_popover()
                return True

        # Cierre por clic fuera del menú activo
        if ev.type() in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick):
            if self._active_popover and self._active_popover.isVisible():
                # punto global del clic
                if hasattr(ev, "globalPosition"):
                    gp = ev.globalPosition().toPoint()
                else:
                    gp = ev.globalPos()
                pop_rect = self._global_rect(self._active_popover)
                btn_rect  = self._global_rect(self._active_button) if self._active_button else QtCore.QRect()
                if not (pop_rect.contains(gp) or btn_rect.contains(gp)):
                    self._close_active_popover()
            # Si se hace clic en el propio botón que abrió el menú, _toggle_popover ya lo cierra.

        return False

    def _wrap_resize(self, original_resize_event):
        def handler(ev):
            original_resize_event(ev)
            self._reposition_popover()
        return handler

    # ---------- carpeta ----------
    def change_folder(self):
        dlg = QtWidgets.QFileDialog(self, "Seleccionar carpeta de samples")
        dlg.setFileMode(QtWidgets.QFileDialog.Directory)
        dlg.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
        dlg.setDirectory(str(self.samples_dir))
        if dlg.exec():
            self.samples_dir = Path(dlg.selectedFiles()[0])
            cfg = load_config(); cfg["samples_dir"] = str(self.samples_dir); save_config(cfg)
            while self.listLayout.count():
                it = self.listLayout.takeAt(0)
                if it.widget(): it.widget().deleteLater()
            self._load_samples()
            self._apply_filters()
            self._refresh_tag_suggestions()
            if not (self._current_row and self._current_row.isVisible()):
                self._current_row = None
                self.popover.hide()

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

    # Manejo global de teclas y cierre de popovers
    app.installEventFilter(w)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
