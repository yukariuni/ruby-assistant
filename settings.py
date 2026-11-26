"""Réglages de Ruby: processus séparé du moteur (engine.py). Écrit config.json, que le moteur relit à chaud."""
import gc
import json
import math
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGraphicsDropShadowEffect,
                               QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QProgressBar,
                               QPushButton, QScrollArea, QSlider, QStackedWidget, QVBoxLayout, QWidget)

import audio
import config
import models
from config import EDGE, LANGS, SUPERTONIC, VOICES, load_cfg, phrases, save_cfg
import memory
from memory import private_mb
from models import fmt_size
from overlay import make_icon

DEFAULT_DEV = "(défaut système)"
EDGE_PX = 6  # épaisseur de la zone de redimensionnement sur le bord de la fenêtre
ICON = "Segoe MDL2 Assets"  # icônes natives de Windows
G = dict(home="", general="", voice="", listen="", ai="", models="", down="",
         minimize="", maximize="", restore="", close="", more="", move="", folder="",
         delete="", undo="", warn="", check="")
STATES = {  # état du moteur -> (titre, couleur)
    "stopped": ("Ruby est arrêtée", "#5B6478"), "starting": ("Démarrage…", "#FFB347"), "downloading": ("Téléchargement…", "#FFB347"),
    "needs_sync": ("Apprends-moi ta voix", "#FFB347"), "listening": ("À l'écoute", "#3DD68C"),
    "recording": ("Je t'écoute…", "#FF4D8D"), "thinking": ("Je réfléchis…", "#3DA9FF"),
    "speaking": ("Je réponds…", "#33E0C8"), "error": ("Erreur", "#FF5C6C"),
}
WHISPER = [("Rapide · base (≈300 Mo en mémoire)", "base"), ("Précis · small (≈430 Mo en mémoire)", "small")]  # « medium » dépasserait le plafond de 500 Mo
GROQ_MODELS = [("GPT-OSS 20B · rapide", "openai/gpt-oss-20b"), ("GPT-OSS 120B · plus précis", "openai/gpt-oss-120b")]
DELETE_NOTE = dict(
    whisper="Il sera retéléchargé automatiquement si Ruby en a de nouveau besoin.",
    voice="Elle sera retéléchargée automatiquement si tu utilises la voix locale.",
    wake="Ces petits fichiers seront retéléchargés automatiquement au prochain démarrage.",
    mine="Ruby oubliera ta voix: il faudra refaire « Apprendre ma voix » avant de pouvoir l'utiliser.")
LABEL = dict(whisper="Whisper", voice="la voix Supertonic", wake="openWakeWord")  # « Où installer … ? »
DE = dict(whisper="de Whisper", voice="de la voix Supertonic", wake="d'openWakeWord")  # « Les fichiers … »
QSS = """
* { font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: 13px; color: #E7E9EE; }
QMainWindow, #pages, QScrollArea, #pageBody { background: #0F1115; border: none; }
#dialog { background: #0F1115; border: 1px solid #262C3A; }
#root { background: #0F1115; border: 1px solid #262C3A; }
#titlebar { background: #0B0D11; border-bottom: 1px solid #1C212B; }
#titleText { color: #8A93A6; font-size: 12px; }
QPushButton#win, QPushButton#winclose { background: transparent; border: none; border-radius: 0; min-width: 46px; max-width: 46px; min-height: 38px;
    max-height: 38px; font-family: 'Segoe MDL2 Assets'; font-size: 10px; color: #C9CFDB; }
QPushButton#win:hover { background: #1E2430; }
QPushButton#winclose:hover { background: #E5484D; color: white; }
#sidebar { background: #12151B; border-right: 1px solid #1C212B; }
#logo { font-size: 18px; font-weight: 700; }
#muted, #rowDesc, #pageSub { color: #8A93A6; }
#path { color: #6F788D; font-size: 11px; }
#pageTitle { font-size: 26px; font-weight: 700; }
#rowTitle { font-weight: 600; }
#cardTitle { font-size: 11px; font-weight: 700; color: #7E879B; letter-spacing: 1px; }
#sep { background: #232A36; max-height: 1px; min-height: 1px; border: none; }
#bubbleYou { background: #3A1B27; border-radius: 12px; padding: 10px 14px; }
#bubbleRuby { background: #1E242F; border-radius: 12px; padding: 10px 14px; }
#toast { background: #222A3B; border: 1px solid #323B50; border-radius: 12px; padding: 11px 18px; }
#toast[kind="error"] { background: #2A1C22; border-color: #5A2A33; color: #FF9AA6; }
QLabel#badge { border-radius: 9px; padding: 2px 10px; font-size: 11px; font-weight: 600; }
QLabel#badge[kind="local"] { background: #12352A; color: #3DD68C; }
QLabel#badge[kind="cloud"] { background: #12304A; color: #5CB8FF; }
QLabel#badge[kind="warn"] { background: #3D2E12; color: #FFB347; }
QLabel#badge[kind="muted"] { background: #232A36; color: #98A1B5; }
QPushButton#primary { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #FF2D55, stop:1 #C4143C); border: none; border-radius: 10px;
                      padding: 10px 18px; font-weight: 600; color: white; }
QPushButton#primary:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #FF4D6D, stop:1 #D9204A); }
QPushButton#primary:disabled { background: #2A3040; color: #6B7388; }
QPushButton#ghost { background: #212838; border: 1px solid #2E3648; border-radius: 10px; padding: 9px 16px; }
QPushButton#ghost:hover { background: #2A3247; }
QPushButton#ghost:disabled { color: #5B6478; }
QPushButton#danger { background: #2A1C22; border: 1px solid #4A2A33; border-radius: 10px; padding: 10px 18px; color: #FF8A98; font-weight: 600; }
QPushButton#danger:hover { background: #351F27; }
QPushButton#dangerSolid { background: #D9304A; border: none; border-radius: 10px; padding: 10px 18px; color: white; font-weight: 600; }
QPushButton#dangerSolid:hover { background: #EC4660; }
QComboBox, QLineEdit { background: #0F1218; border: 1px solid #2A3040; border-radius: 9px; padding: 8px 12px; min-height: 18px; }
QComboBox:hover, QLineEdit:hover { border-color: #3A4258; }
QComboBox:focus, QLineEdit:focus { border-color: #E5173F; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox QAbstractItemView { background: #161A22; border: 1px solid #2A3040; selection-background-color: #2A3247; outline: none; padding: 4px; }
QMenu { background: #161A22; border: 1px solid #2A3040; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 9px 20px 9px 8px; border-radius: 6px; margin: 1px 0; }
QMenu::item:selected { background: #2A3247; }
QMenu::icon { padding-left: 8px; }
QSlider::groove:horizontal { height: 5px; background: #2A3040; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #E5173F; border-radius: 2px; }
QSlider::handle:horizontal { background: white; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }
QProgressBar { background: #262D3D; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; text-align: center; color: transparent; }
QProgressBar::chunk { border-radius: 4px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #FF6B86, stop:1 #E5173F); }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #2A3040; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""


# ---------------------------------------------------------------- animations
def animations_enabled():
    """Respecte « Afficher les animations dans Windows » (Options d'ergonomie): s'il est coupé, tout est instantané."""
    try:
        import ctypes
        on = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0)  # SPI_GETCLIENTAREAANIMATION
        return bool(on.value)
    except Exception:
        return True


ANIMATE = animations_enabled()


def ms(n):
    return n if ANIMATE else 0


def mix(a, b, t):
    a, b = QColor(a), QColor(b)
    return QColor(*(round(x + (y - x) * t) for x, y in zip(a.getRgb(), b.getRgb())))


def tween(owner, dur, setter, easing=QEasingCurve.OutCubic):
    a = QVariantAnimation(owner)
    a.setDuration(ms(dur))
    a.setEasingCurve(easing)
    a.valueChanged.connect(setter)
    return a


def run(a, start, end):
    a.stop()
    a.setStartValue(start)
    a.setEndValue(end)
    a.start()


def fade_in(w, dur=280, delay=0):
    """Fondu d'apparition. L'effet est retiré à la fin: un widget sous effet est dessiné en bitmap (texte moins net, plus lent)."""
    if not ANIMATE:
        return
    eff = QGraphicsOpacityEffect(w)
    eff.setOpacity(0.0)
    w.setGraphicsEffect(eff)
    a = QPropertyAnimation(eff, b"opacity", w)
    a.setDuration(dur)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setEasingCurve(QEasingCurve.OutCubic)

    def done():  # hors du signal « finished »: on ne détruit pas l'objet qui est en train d'émettre
        try:
            if w.graphicsEffect() is eff:
                w.setGraphicsEffect(None)
            a.deleteLater()
        except RuntimeError:  # le widget a été détruit entre-temps (page reconstruite)
            pass
    a.finished.connect(lambda: QTimer.singleShot(0, done))
    QTimer(w, singleShot=True, interval=delay, timeout=a.start).start()  # lié au widget: disparaît avec lui


def stagger(root, step=45, dur=320):
    """Fait apparaître les cartes de `root` l'une après l'autre."""
    for i, c in enumerate(root.findChildren(Card)):
        fade_in(c, dur, step * i)


def glyph(code, size=15, color="#C9CFDB"):
    lb = QLabel(code)
    lb.setStyleSheet(f"font-family: '{ICON}'; font-size: {size}px; color: {color};")
    return lb


def glyph_icon(code, color="#C9CFDB", size=16):
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.TextAntialiasing)
    f = QFont(ICON)
    f.setPixelSize(int(size * 1.7))
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(pm.rect(), Qt.AlignCenter, code)
    p.end()
    return QIcon(pm)


def shorten(path, n=58):
    s = str(path)
    return s if len(s) <= n else s[: n // 2 - 1] + "…" + s[-(n // 2):]


def pid_alive(pid):
    if sys.platform != "win32" or not pid:
        return False
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        k.GetExitCodeProcess(h, ctypes.byref(code))
        return code.value == 259  # STILL_ACTIVE
    finally:
        k.CloseHandle(h)


# ---------------------------------------------------------------- briques d'interface
class Badge(QLabel):
    def __init__(self, text, kind):
        super().__init__(text)
        self.setObjectName("badge")
        self.setProperty("kind", kind)


class WinButton(QPushButton):
    def __init__(self, code, name="win"):
        super().__init__(code)
        self.setObjectName(name)
        self.setFocusPolicy(Qt.NoFocus)


class TitleBar(QWidget):
    """Barre de titre sombre à la place de celle de Windows: se déplace à la souris, double-clic = agrandir."""

    def __init__(self, win, title, controls=("min", "max", "close")):
        super().__init__()
        self.win, self.has_max = win, "max" in controls
        self.setObjectName("titlebar")
        self.setFixedHeight(38)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 0, 0, 0)
        h.setSpacing(0)
        ic = QLabel()
        ic.setPixmap(make_icon().pixmap(16, 16))
        t = QLabel(title)
        t.setObjectName("titleText")
        h.addWidget(ic)
        h.addSpacing(8)
        h.addWidget(t)
        h.addStretch()
        if "min" in controls:
            b = WinButton(G["minimize"])
            b.clicked.connect(win.showMinimized)
            h.addWidget(b)
        if self.has_max:
            self.max_btn = WinButton(G["maximize"])
            self.max_btn.clicked.connect(win.toggle_max)
            h.addWidget(self.max_btn)
        close = WinButton(G["close"], "winclose")
        close.clicked.connect(win.close if self.has_max else win.reject)
        h.addWidget(close)

    def set_maximized(self, on):
        self.max_btn.setText(G["restore"] if on else G["maximize"])

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if getattr(self.win, "_max", False):
                self.win.toggle_max()
            self.win.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        if self.has_max and e.button() == Qt.LeftButton:
            self.win.toggle_max()


class GlowButton(QPushButton):
    """Bouton qui s'illumine au survol (ombre colorée animée). kind: primary / danger / dangerSolid / ghost."""
    GLOW = dict(primary=QColor(255, 45, 85, 170), danger=QColor(255, 90, 110, 110), dangerSolid=QColor(236, 70, 96, 170))

    def __init__(self, text, kind="primary"):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        self.glow = tween(self, 220, self._blur)
        self.set_kind(kind)

    def _fx(self):
        fx = self.graphicsEffect()
        return fx if isinstance(fx, QGraphicsDropShadowEffect) else None

    def _blur(self, v):
        """v: 0 (repos, ombre invisible) à 26 (survol, halo coloré)."""
        fx = self._fx()
        if fx:
            c = QColor(self.GLOW[self.objectName()])
            c.setAlpha(int(c.alpha() * min(v / 26, 1)))  # l'ombre apparaît en même temps qu'elle s'étale
            fx.setBlurRadius(v)
            fx.setColor(c)

    def set_kind(self, kind):
        self.setObjectName(kind)
        self.setStyle(self.style())  # réapplique la feuille de style
        if kind in self.GLOW:
            if not self._fx():
                fx = QGraphicsDropShadowEffect(self)
                fx.setOffset(0, 3)
                self.setGraphicsEffect(fx)
            self._blur(0.0)
        else:
            self.setGraphicsEffect(None)  # bouton discret: pas d'ombre

    def enterEvent(self, e):
        if self._fx() and self.isEnabled():
            run(self.glow, self._fx().blurRadius(), 26.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._fx():
            run(self.glow, self._fx().blurRadius(), 0.0)
        super().leaveEvent(e)


class ManageButton(QPushButton):
    """UN seul bouton par modèle: ouvre un menu (ouvrir, changer de dossier, supprimer…). actions: [(icône, texte, fonction, danger)]."""

    def __init__(self, actions):
        super().__init__("Gérer")
        self.actions_spec = actions
        self.setObjectName("ghost")
        self.setCursor(Qt.PointingHandCursor)
        self.setIcon(glyph_icon(G["more"]))
        self.clicked.connect(self.popup)

    def popup(self):
        m = QMenu(self)
        m.setWindowFlags(m.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)  # coins arrondis
        m.setAttribute(Qt.WA_TranslucentBackground)
        for code, text, fn, danger in self.actions_spec:
            m.addAction(glyph_icon(code, "#FF6B7A" if danger else "#C9CFDB"), text).triggered.connect(lambda _=False, fn=fn: QTimer.singleShot(0, fn))
        m.exec(self.mapToGlobal(QPoint(self.width() - m.sizeHint().width(), self.height() + 6)))


class Combo(QComboBox):
    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setPen(QColor("#8A93A6"))
        f = QFont(ICON)
        f.setPixelSize(10)
        p.setFont(f)
        p.drawText(self.rect().adjusted(0, 0, -12, 0), Qt.AlignRight | Qt.AlignVCenter, G["down"])


class Toggle(QCheckBox):
    """Interrupteur façon iOS: la pastille glisse et la couleur se fond."""

    def __init__(self, on, cb):
        super().__init__()
        self.setChecked(on)
        self.setFixedSize(44, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.t = 1.0 if on else 0.0
        self.anim = tween(self, 200, self._set)
        self.toggled.connect(lambda v: run(self.anim, self.t, 1.0 if v else 0.0))
        self.toggled.connect(cb)

    def _set(self, t):
        self.t = t
        self.update()

    def hitButton(self, pos):
        return True

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(mix("#3A4050", "#E5173F", self.t))
        p.drawRoundedRect(self.rect(), 12, 12)
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(11 + 22 * self.t, 12), 9, 9)


class SmoothBar(QProgressBar):
    """Barre dont la valeur glisse au lieu de sauter."""

    def __init__(self):
        super().__init__()
        self.a = QPropertyAnimation(self, b"value", self)

    def glide(self, v):
        self.a.stop()
        self.a.setDuration(ms(160))
        self.a.setStartValue(self.value())
        self.a.setEndValue(int(v))
        self.a.start()


class Card(QFrame):
    """Carte dont le contour s'éclaircit au survol."""

    def __init__(self, title=None):
        super().__init__()
        self.h = 0.0
        self.hover = tween(self, 180, self._set)
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(22, 18, 22, 6)
        self.v.setSpacing(0)
        if title:
            t = QLabel(title.upper())
            t.setObjectName("cardTitle")
            self.v.addWidget(t)
        self.n = 0

    def _set(self, t):
        self.h = t
        self.update()

    def enterEvent(self, e):
        run(self.hover, self.h, 1.0)

    def leaveEvent(self, e):
        run(self.hover, self.h, 0.0)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(mix("#161A22", "#1A1F29", self.h))
        p.setPen(QPen(mix("#232A36", "#3A4254", self.h), 1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)

    def add(self, w):
        if self.n:  # trait fin entre deux lignes
            sep = QFrame()
            sep.setObjectName("sep")
            self.v.addWidget(sep)
        self.n += 1
        self.v.addWidget(w)

    def row(self, title, desc, widget, badge=None):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 14, 0, 14)
        left = QVBoxLayout()
        left.setSpacing(3)
        top = QHBoxLayout()
        t = QLabel(title)
        t.setObjectName("rowTitle")
        top.addWidget(t)
        if badge:
            top.addSpacing(8)
            top.addWidget(Badge(*badge))
        top.addStretch()
        left.addLayout(top)
        w.desc_label = None
        if desc:
            w.desc_label = QLabel(desc)
            w.desc_label.setObjectName("rowDesc")
            w.desc_label.setWordWrap(True)
            left.addWidget(w.desc_label)
        h.addLayout(left, 1)
        h.addSpacing(24)
        h.addWidget(widget, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.add(w)
        return w


class Orb(QWidget):
    """Pastille de statut: la couleur se fond d'un état à l'autre, des ondes partent du centre quand Ruby est active."""

    def __init__(self, size=150):
        super().__init__()
        self.setFixedSize(size, size)
        self.color = self.target = QColor("#5B6478")
        self.active, self.t = False, 0.0
        self.fade = tween(self, 300, self._set_color)
        self.timer = QTimer(self, interval=33, timeout=self.tick)

    def _set_color(self, c):
        self.color = c
        self.update()

    def set_state(self, color, active):
        color = QColor(color)
        if color != self.target:
            run(self.fade, self.color, color)
            self.target = color
        self.active = active
        if active and not self.timer.isActive():
            self.timer.start()
        elif not active:
            self.timer.stop()
        self.update()

    def tick(self):
        if self.isVisible() and not self.window().isMinimized():
            self.t += 0.018
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(self.width() / 190, self.width() / 190)  # dessiné pour 190 px
        c, breath = QPointF(95, 95), (0.5 + 0.5 * math.sin(self.t * 2 * math.pi)) if self.active else 0.3
        g = QRadialGradient(c, 92)
        glow = QColor(self.color)
        glow.setAlpha(int(40 + 70 * breath))
        g.setColorAt(0.45, glow)
        glow.setAlpha(0)
        g.setColorAt(1, glow)
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, 92, 92)
        if self.active:  # 3 ondes qui s'élargissent et s'effacent
            for k in range(3):
                ph = (self.t * 0.6 + k / 3) % 1
                ring = QColor(self.color)
                ring.setAlpha(int(110 * (1 - ph) ** 2))
                p.setPen(QPen(ring, 2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c, 48 + 44 * ph, 48 + 44 * ph)
        p.setPen(Qt.NoPen)
        g2 = QRadialGradient(QPointF(80, 78), 60)
        g2.setColorAt(0, self.color.lighter(130))
        g2.setColorAt(1, self.color.darker(115))
        p.setBrush(g2)
        r = 46 + 3 * breath
        p.drawEllipse(c, r, r)
        p.setPen(QColor("white"))
        f = QFont(ICON)
        f.setPixelSize(30)
        p.setFont(f)
        p.drawText(QRectF(55, 55, 80, 80), Qt.AlignCenter, G["listen"])


class StatusDot(QWidget):
    """Voyant d'état: la couleur se fond, un halo pulse quand Ruby est active."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(20, 20)
        self.color = self.target = QColor("#5B6478")
        self.active, self.t = False, 0.0
        self.fade = tween(self, 250, self._set_color)
        self.timer = QTimer(self, interval=40, timeout=self.tick)

    def _set_color(self, c):
        self.color = c
        self.update()

    def set_state(self, color, active):
        color = QColor(color)
        if color != self.target:
            run(self.fade, self.color, color)
            self.target = color
        self.active = active
        if active and not self.timer.isActive():
            self.timer.start()
        elif not active:
            self.timer.stop()
        self.update()

    def tick(self):
        if self.isVisible() and not self.window().isMinimized():
            self.t = (self.t + 0.035) % 1
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        if self.active:
            halo = QColor(self.color)
            halo.setAlpha(int(120 * (1 - self.t)))
            p.setBrush(halo)
            p.drawEllipse(QPointF(10, 10), 4 + 6 * self.t, 4 + 6 * self.t)
        p.setBrush(self.color)
        p.drawEllipse(QPointF(10, 10), 4.5, 4.5)


class Indicator(QWidget):
    """Fond + barre d'accent du menu: glisse d'un bouton à l'autre."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#222A3B"))
        p.drawRoundedRect(self.rect(), 10, 10)
        p.setBrush(QColor("#FF2D55"))
        p.drawRoundedRect(QRectF(0, 11, 3, self.height() - 22), 1.5, 1.5)


class NavButton(QPushButton):
    def __init__(self, code, label):
        super().__init__()
        self.code, self.label, self.h = code, label, 0.0
        self.setCheckable(True)
        self.setFixedHeight(42)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.hover = tween(self, 170, self._set)

    def _set(self, t):
        self.h = t
        self.update()

    def enterEvent(self, e):
        run(self.hover, self.h, 1.0)

    def leaveEvent(self, e):
        run(self.hover, self.h, 0.0)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on, r = self.isChecked(), QRectF(self.rect())
        if self.h > 0 and not on:  # survol: fond qui apparaît en fondu
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(30, 36, 48, int(255 * self.h)))
            p.drawRoundedRect(r, 10, 10)
        p.setPen(QColor("#FFFFFF") if on else mix("#A9B1C3", "#FFFFFF", self.h * 0.7))
        f = QFont(ICON)
        f.setPixelSize(16)
        p.setFont(f)
        p.drawText(QRectF(16, 0, 26, r.height()), Qt.AlignCenter, self.code)
        f = QFont(self.font())
        f.setPixelSize(13)
        f.setWeight(QFont.DemiBold if on else QFont.Normal)
        p.setFont(f)
        p.drawText(QRectF(52, 0, r.width() - 60, r.height()), Qt.AlignVCenter | Qt.AlignLeft, self.label)


class Sidebar(QFrame):
    selected = Signal(int)

    def __init__(self, items):
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(240)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 20, 14, 16)
        v.setSpacing(4)
        logo = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(make_icon().pixmap(34, 34))
        name, sub = QLabel("Ruby"), QLabel("Assistant vocal")
        name.setObjectName("logo")
        sub.setObjectName("muted")
        txt = QVBoxLayout()
        txt.setSpacing(0)
        txt.addWidget(name)
        txt.addWidget(sub)
        logo.addWidget(ic)
        logo.addSpacing(6)
        logo.addLayout(txt)
        logo.addStretch()
        v.addLayout(logo)
        v.addSpacing(22)
        self.indicator = Indicator(self)  # créé avant les boutons: il reste sous eux
        self.slide = QPropertyAnimation(self.indicator, b"geometry", self)
        self.slide.setEasingCurve(QEasingCurve.OutCubic)
        self.buttons, self.index = [], 0
        for i, (code, label) in enumerate(items):
            b = NavButton(code, label)
            b.clicked.connect(lambda _=False, i=i: self.selected.emit(i))
            v.addWidget(b)
            self.buttons.append(b)
        self.buttons[0].setChecked(True)
        v.addStretch()
        card = Card()
        card.v.setContentsMargins(14, 12, 14, 14)
        card.v.setSpacing(10)
        row = QHBoxLayout()
        self.dot, self.state_lbl = StatusDot(), QLabel("Ruby est arrêtée")
        self.state_lbl.setObjectName("rowTitle")
        row.addWidget(self.dot)
        row.addWidget(self.state_lbl, 1)
        card.v.addLayout(row)
        self.engine_btn = GlowButton("Démarrer Ruby", "primary")
        card.v.addWidget(self.engine_btn)
        v.addWidget(card)

    def set_index(self, i, animate=True):
        self.index = i
        for k, b in enumerate(self.buttons):
            b.setChecked(k == i)
        target = self.buttons[i].geometry()
        if animate and ANIMATE and self.isVisible():
            self.slide.stop()
            self.slide.setDuration(320)
            self.slide.setStartValue(self.indicator.geometry())
            self.slide.setEndValue(target)
            self.slide.start()
        else:
            self.indicator.setGeometry(target)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.indicator.setGeometry(self.buttons[self.index].geometry())

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, lambda: self.indicator.setGeometry(self.buttons[self.index].geometry()))


class AnimStack(QStackedWidget):
    """Pages: la nouvelle glisse légèrement vers le haut pendant que ses cartes apparaissent l'une après l'autre."""

    def setCurrentIndex(self, i):
        if i == self.currentIndex():
            return
        super().setCurrentIndex(i)  # émet currentChanged: la page Modèles se reconstruit avant l'animation
        if ANIMATE and self.isVisible():
            page = self.currentWidget()
            a = QPropertyAnimation(page, b"pos", page)
            a.setDuration(320)
            a.setEasingCurve(QEasingCurve.OutCubic)
            a.setStartValue(QPoint(0, 20))
            a.setEndValue(QPoint(0, 0))
            a.finished.connect(a.deleteLater)
            a.start()
            stagger(page)


class Toast(QLabel):
    """Message éphémère en bas de la fenêtre (confirmation d'une suppression, d'un déplacement, erreur…)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setProperty("kind", "ok")
        self.setAlignment(Qt.AlignCenter)
        self.fx = QGraphicsOpacityEffect(self)
        self.fx.setOpacity(0.0)
        self.setGraphicsEffect(self.fx)
        self.fade = tween(self, 220, self.fx.setOpacity)
        self.slide = tween(self, 260, lambda y: self.move(self.x(), int(y)))
        self.timer = QTimer(self, singleShot=True, timeout=lambda: run(self.fade, self.fx.opacity(), 0.0))
        self.fade.finished.connect(lambda: self.fx.opacity() == 0 and self.hide())
        self.hide()

    def show_msg(self, text, error=False, hold=3200):
        self.setProperty("kind", "error" if error else "ok")
        self.setStyle(self.style())
        self.setText(text)
        self.setWordWrap(True)
        self.setFixedWidth(min(self.fontMetrics().horizontalAdvance(text) + 50, max(300, self.parent().width() - 80)))  # largeur du texte, à la ligne si trop long
        self.adjustSize()
        pw, ph = self.parent().width(), self.parent().height()
        x, y = (pw - self.width()) // 2, ph - self.height() - 28
        self.move(x, y + 14)
        self.show()
        self.raise_()
        run(self.fade, self.fx.opacity(), 1.0)
        run(self.slide, y + 14, y)
        self.timer.start(hold)


class Frameless(QDialog):
    """Boîte de dialogue à la charte de l'app: barre de titre sombre, apparition en fondu."""

    def __init__(self, parent, title, width, height=None):
        super().__init__(parent)
        self.setObjectName("dialog")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.width_, self.shown = width, False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        outer.addWidget(TitleBar(self, title, controls=("close",)))
        self.body = QVBoxLayout()
        self.body.setContentsMargins(34, 26, 34, 28)
        outer.addLayout(self.body, 1)
        self.setFixedWidth(width)
        if height:
            self.setFixedHeight(height)

    def fit(self):
        """Hauteur ajustée au contenu (textes qui passent à la ligne)."""
        self.setFixedHeight(self.layout().totalHeightForWidth(self.width_))

    def showEvent(self, e):
        super().showEvent(e)
        if not self.shown and ANIMATE:
            self.shown = True
            self.setWindowOpacity(0.0)
            a = QPropertyAnimation(self, b"windowOpacity", self)
            a.setDuration(180)
            a.setStartValue(0.0)
            a.setEndValue(1.0)
            a.start()


class Confirm(Frameless):
    """Question à l'utilisateur. buttons: [(texte, style)] (style: ghost / primary / dangerSolid). Retourne l'index cliqué, -1 si fermée."""

    def __init__(self, parent, title, text, buttons, icon=G["warn"]):
        super().__init__(parent, "Ruby", 500)
        self.choice = -1
        head = QHBoxLayout()
        head.setSpacing(16)
        badge = QLabel(icon)
        badge.setFixedSize(46, 46)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f"font-family: '{ICON}'; font-size: 20px; color: #FFB347; background: #3D2E12; border-radius: 23px;")
        t = QLabel(title)
        t.setStyleSheet("font-size: 18px; font-weight: 700;")
        t.setWordWrap(True)
        head.addWidget(badge, 0, Qt.AlignTop)
        head.addWidget(t, 1)
        self.body.addLayout(head)
        body = QLabel(text)
        body.setObjectName("rowDesc")
        body.setWordWrap(True)
        self.body.addSpacing(10)
        self.body.addWidget(body)
        self.body.addSpacing(22)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch()
        for i, (label, style) in enumerate(buttons):
            b = GlowButton(label, style)
            b.clicked.connect(lambda _=False, i=i: self.pick(i))
            row.addWidget(b)
        self.body.addLayout(row)
        self.fit()

    def pick(self, i):
        self.choice = i
        self.accept()

    @staticmethod
    def ask(parent, title, text, buttons, icon=G["warn"]):
        d = Confirm(parent, title, text, buttons, icon)
        d.exec()
        return d.choice


class MoveDialog(Frameless):
    """Déplacement d'un modèle avec progression. Annuler = la destination est nettoyée, rien n'est perdu."""
    progress = Signal(int, str)
    finished_ok = Signal(list)
    canceled = Signal()
    failed = Signal(str)

    def __init__(self, parent, label, pairs):
        super().__init__(parent, "Déplacement", 500)
        self.pairs, self.stop, self.error, self.leftovers, self.worker = pairs, False, "", [], None
        title = QLabel(f"Déplacement {label}")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        sub = QLabel("Copie, vérification, puis suppression de l'ancien emplacement. Si tu annules, rien n'est perdu.")
        sub.setObjectName("rowDesc")
        sub.setWordWrap(True)
        self.bar = SmoothBar()
        self.bar.setRange(0, 1000)
        self.info = QLabel("Préparation…")
        self.info.setObjectName("rowDesc")
        self.btn = GlowButton("Annuler", "ghost")
        self.btn.clicked.connect(self.reject)
        for w in (title, sub):
            self.body.addWidget(w)
        self.body.addSpacing(18)
        self.body.addWidget(self.bar)
        self.body.addSpacing(8)
        self.body.addWidget(self.info)
        self.body.addSpacing(20)
        self.body.addWidget(self.btn, 0, Qt.AlignRight)
        self.progress.connect(lambda v, t: (self.bar.glide(v), self.info.setText(t)))
        self.finished_ok.connect(self._ok)
        self.canceled.connect(lambda: QDialog.done(self, 0))
        self.failed.connect(self._failed)
        self.fit()

    def showEvent(self, e):
        super().showEvent(e)
        if self.worker is None:
            self.worker = threading.Thread(target=self.work, daemon=True)
            self.worker.start()

    def work(self):
        try:
            left = models.move(self.pairs, cancel=lambda: self.stop,
                               progress=lambda d, t, n: self.progress.emit(int(1000 * d / max(t, 1)), f"{fmt_size(d)} / {fmt_size(t)} · {n}"))
            self.finished_ok.emit([str(p) for p in left])
        except models.Cancelled:
            self.canceled.emit()
        except Exception as e:
            self.failed.emit(str(e))

    def _ok(self, left):
        self.leftovers = left
        self.bar.setValue(1000)
        QDialog.done(self, 1)

    def _failed(self, msg):
        self.error = msg
        QDialog.done(self, 0)

    def reject(self):  # fermer ou « Annuler »: on demande l'arrêt, la boîte se ferme quand la copie est nettoyée
        self.stop = True
        self.btn.setEnabled(False)
        self.info.setText("Annulation…")


class SyncDialog(Frameless):
    """Assistant « Apprendre ma voix »: enregistre les mots d'activation, des phrases au hasard, le silence; entraîne le détecteur."""
    step = Signal(str, str, int)
    level = Signal(float)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, parent, cfg):
        super().__init__(parent, "Apprendre ma voix", 520, 600)
        self.cfg, self.cancel = cfg, False
        self.body.setContentsMargins(40, 26, 40, 28)
        v = self.body
        self.meter = LevelMeter()
        v.addWidget(self.meter, 0, Qt.AlignHCenter)
        v.addSpacing(10)
        self.title = QLabel("Prêt ?")
        self.title.setStyleSheet("font-size: 20px; font-weight: 700;")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setWordWrap(True)
        self.sub = QLabel("Je vais te demander quelques phrases. Parle quand tu entends le petit son.")
        self.sub.setObjectName("pageSub")
        self.sub.setAlignment(Qt.AlignCenter)
        self.sub.setWordWrap(True)
        self.bar = SmoothBar()
        self.bar.setTextVisible(False)
        self.btn = GlowButton("Commencer", "primary")
        self.btn.clicked.connect(self.start)
        v.addWidget(self.title)
        v.addWidget(self.sub)
        v.addStretch()
        v.addWidget(self.bar)
        v.addSpacing(18)
        v.addWidget(self.btn)
        self.step.connect(self._step)
        self.level.connect(self.meter.set_level)
        self.finished_ok.connect(self._done)
        self.failed.connect(lambda m: (self.title.setText("Oups"), self.sub.setText(m), self.btn.setText("Fermer"),
                                       self.btn.clicked.disconnect(), self.btn.clicked.connect(self.reject)))
        self.decay = QTimer(self, interval=60, timeout=lambda: self.meter.set_level(0))
        self.decay.start()

    def _step(self, title, sub, i):
        if title != self.title.text():
            fade_in(self.title, 220)  # la consigne change: elle apparaît en fondu
        self.title.setText(title)
        self.sub.setText(sub)
        self.bar.glide(i)

    def _done(self):
        self.bar.glide(self.bar.maximum())
        self.title.setText("C'est fait ✔")
        fade_in(self.title, 260)
        self.sub.setText("Ruby connaît ta voix. Lance-la et dis ton mot d'activation. Si elle rate ou se déclenche trop, ajuste le seuil.")
        self.btn.setText("Terminer")
        self.btn.clicked.disconnect()
        self.btn.clicked.connect(self.accept)

    def reject(self):
        self.cancel = True
        super().reject()

    def start(self):
        self.btn.setEnabled(False)
        L = LANGS[self.cfg["lang"]]
        ph = phrases(self.cfg["words"])
        reps = max(3, config.N_POS // len(ph))
        self.steps = ([(True, p, f"{i}/{reps}") for p in ph for i in range(1, reps + 1)]
                      + [(False, f"« {t} »", "") for t in L["neg"]] + [(False, None, "")])
        self.bar.setRange(0, len(self.steps))
        threading.Thread(target=self.run_steps, daemon=True).start()

    def record(self):
        import wake  # seulement pendant l'apprentissage: la fenêtre de réglages seule n'a pas besoin de onnxruntime (≈25 Mo)
        n, chunks = int(config.REC_SEC * wake.SR), []

        def cb(x, *_):
            chunks.append(x[:, 0].copy())
            self.level.emit(float(np.sqrt((x.astype(np.float32) ** 2).mean())) / 3000)
        with sd.InputStream(samplerate=wake.SR, channels=1, dtype="int16", device=audio.device_index(self.cfg["mic"], "input"), callback=cb):
            time.sleep(config.REC_SEC)
        clip = np.concatenate(chunks)
        return np.pad(clip, (0, max(0, n - len(clip))))[:n]

    def run_steps(self):
        try:
            import wake
            out, vol = audio.device_index(self.cfg["speaker"], "output"), self.cfg["volume"]
            pos, neg = [], []
            for i, (is_pos, what, count) in enumerate(self.steps):
                while not self.cancel:
                    if what is None:
                        title, sub = "Reste silencieux", "J'écoute le bruit de ta pièce."
                    elif is_pos:
                        title, sub = f"Dis « {what} »", f"Répétition {count}"
                    else:
                        title, sub = f"Dis : {what}", "Une phrase au hasard, pour apprendre ce qui n'est pas mon nom."
                    self.step.emit(title, "Prépare-toi…", i)
                    time.sleep(1.0)
                    audio.play_sound("ready", out, vol)
                    self.step.emit(title, sub + "  —  parle maintenant", i)
                    clip = self.record()
                    if not is_pos or wake.speech_end(clip):
                        break
                    self.step.emit("Je n'ai rien entendu", "On recommence.", i)
                    time.sleep(1.2)
                if self.cancel:
                    return
                (pos if is_pos else neg).append(clip)
            self.step.emit("J'apprends ta voix…", "Quelques secondes.", len(self.steps))
            models.ensure_wake(models.folder(self.cfg, "wake"))  # no-op si déjà là
            wake.train(pos, neg, models.custom_or_none(self.cfg, "wake")).save(config.MODEL_FILE)
            config.LEGACY_MODEL.unlink(missing_ok=True)  # l'ancien format est remplacé par ce nouvel apprentissage
            np.savez(config.SAMPLES_FILE, pos=np.stack(pos), neg=np.stack(neg))
            self.cfg["synced"] = self.cfg["words"]
            fresh = load_cfg()  # ne pas écraser ce qui a changé entre-temps dans les réglages
            fresh["synced"] = self.cfg["words"]
            save_cfg(fresh)
            self.finished_ok.emit()
        except Exception as e:
            self.failed.emit(str(e))


class LevelMeter(QWidget):
    """Cercle qui grossit avec le volume du micro (assistant « Apprendre ma voix »)."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(180, 180)
        self.level = 0.0

    def set_level(self, v):
        self.level = max(v, self.level * 0.8)  # retombée douce
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c, r = QPointF(90, 90), 38 + 46 * min(self.level, 1)
        p.setPen(Qt.NoPen)
        for k, a in ((1.5, 25), (1.25, 55)):
            col = QColor("#FF2D55")
            col.setAlpha(a)
            p.setBrush(col)
            p.drawEllipse(c, r * k * 0.85, r * k * 0.85)
        p.setBrush(QColor("#E5173F"))
        p.drawEllipse(c, 38, 38)
        p.setPen(QColor("white"))
        f = QFont(ICON)
        f.setPixelSize(28)
        p.setFont(f)
        p.drawText(QRectF(52, 52, 76, 76), Qt.AlignCenter, G["listen"])


# ---------------------------------------------------------------- ce que Ruby utilise (page Modèles)
def model_rows(cfg):
    """(utilisés, autres, total_octets): ce que Ruby utilise, ce qui traîne sur le disque, et où tout ça se trouve."""
    cloud_ai = bool(cfg["groq_key"] or os.environ.get("GROQ_API_KEY"))
    name, local_voice = cfg["whisper"], cfg["engine"] == SUPERTONIC
    approx = dict(voice="≈385 Mo", wake="≈2,4 Mo")

    def row(kind, icon, title, model, key=None, in_use=True, pipeline=False):
        its = models.items(cfg, kind, key)
        ok = models.installed(cfg, kind, key)
        if kind == "mine":
            status = ("Appris", "local") if ok else ("À apprendre", "warn")
        else:
            todo = models.WHISPER_APPROX.get(key, "") if kind == "whisper" else approx[kind]
            status = ("Installé", "local") if ok else (f"À télécharger {todo}".strip(), "warn")
        return dict(kind=kind, key=key, icon=icon, title=title, model=model, where="local", size=models.size(its), items=its, status=status,
                    path=config.MODEL_FILE.parent if kind == "mine" else models.folder(cfg, kind),
                    custom=kind != "mine" and models.is_custom(cfg, kind), in_use=in_use, pipeline=pipeline,
                    movable=kind != "mine" and (in_use or kind != "whisper"))

    def cloud(icon, title, model, note):
        return dict(kind="cloud", key=None, icon=icon, title=title, model=model, where="cloud", size=0, items=[], status=(note, "cloud"),
                    path=None, custom=False, in_use=True, pipeline=True, movable=False)

    groq = dict((v, l) for l, v in GROQ_MODELS).get(cfg["groq_model"], cfg["groq_model"])
    used = [row("wake", G["listen"], "Mot d'activation", "openWakeWord", pipeline=True),
            row("mine", G["listen"], "Ta voix apprise", " · ".join(phrases(cfg["synced"])) or "Pas encore apprise"),
            row("whisper", G["general"], "Reconnaissance vocale", f"Whisper {name}", key=name, pipeline=True)]
    if cloud_ai:
        used.append(cloud(G["ai"], "Intelligence", groq, "Hébergé chez Groq, rien d'installé"))
    else:
        used.append(dict(cloud(G["ai"], "Intelligence", "Règles locales (pas de clé Groq)", "Intégré à Ruby"), where="local",
                         status=("Intégré à Ruby", "local")))
    if local_voice:
        used.append(row("voice", G["voice"], "Voix", f"Supertonic · {cfg['voice']}", pipeline=True))
    else:
        used.append(cloud(G["voice"], "Voix", f"Edge · {cfg['voice']}", "Hébergé chez Microsoft, rien d'installé"))
    others = [row("whisper", G["general"], "Reconnaissance vocale", f"Whisper {k}", key=k, in_use=False)
              for k in models.whisper_dirs(cfg) if k != name]
    if not local_voice and models.installed(cfg, "voice"):
        others.append(row("voice", G["voice"], "Voix", "Supertonic", in_use=False))
    return used, others, sum(r["size"] for r in used + others)


# ---------------------------------------------------------------- fenêtre principale
class Settings(QMainWindow):
    voice_done = Signal(str)
    groq_result = Signal(str)

    def __init__(self):
        super().__init__()
        self.cfg = load_cfg()
        self.setWindowTitle("Ruby — Réglages")
        self.setWindowIcon(make_icon())
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)  # barre de titre dessinée par TitleBar
        self.resize(1080, 740)
        self.setMinimumSize(920, 640)
        self.running, self.speaker, self._max, self._normal, self._ov, self._shown = False, None, False, None, False, False
        self._disk, self.path_rows, self._last = 0, {}, {}
        root = QFrame()
        root.setObjectName("root")
        self.setCentralWidget(root)
        col = QVBoxLayout(root)
        col.setContentsMargins(1, 1, 1, 1)
        col.setSpacing(0)
        self.titlebar = TitleBar(self, "Ruby — Réglages")
        col.addWidget(self.titlebar)
        body = QHBoxLayout()
        body.setSpacing(0)
        self.sidebar = Sidebar([(G["home"], "Accueil"), (G["general"], "Général"), (G["voice"], "Voix"), (G["listen"], "Écoute"),
                                (G["ai"], "Intelligence"), (G["models"], "Modèles")])
        self.dot, self.state_lbl, self.engine_btn = self.sidebar.dot, self.sidebar.state_lbl, self.sidebar.engine_btn
        self.engine_btn.clicked.connect(self.toggle_engine)
        body.addWidget(self.sidebar)
        self.pages = AnimStack()
        self.pages.setObjectName("pages")
        self.disk_anim = tween(self, 700, self._disk_text)
        for build in (self.page_home, self.page_general, self.page_voice, self.page_listen, self.page_ai, self.page_models):
            self.pages.addWidget(build())
        self.sidebar.selected.connect(self.pages.setCurrentIndex)
        self.pages.currentChanged.connect(self.on_page)
        body.addWidget(self.pages, 1)
        col.addLayout(body, 1)
        self.toast_widget = Toast(root)
        self.voice_done.connect(lambda m: (self.test_btn.setEnabled(True), m and self.voice_err.setText(m)))
        self.groq_result.connect(self.groq_lbl.setText)
        QApplication.instance().installEventFilter(self)
        self.timer = QTimer(self, interval=250, timeout=self.poll)
        self.timer.start()
        # La fenêtre ne garde que ce qu'elle utilise vraiment: ≈10 Mo au lieu de ≈54 (mesuré, animations comprises; 2 à 10 ms par passage).
        # C'est ce qui permet au moteur en pleine commande (pic ≈480 Mo) et à cette fenêtre de rester ensemble sous le plafond de 500 Mo.
        self.trimmer = QTimer(self, interval=5000, timeout=memory.trim)
        self.trimmer.start()
        self.refresh_models()

    def toast(self, text, error=False):
        self.toast_widget.show_msg(text, error)

    def on_page(self, i):
        self.sidebar.set_index(i)
        if i == 5:
            self.refresh_models()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._shown:
            self._shown = True
            if ANIMATE:  # la fenêtre apparaît en fondu, puis les cartes de l'accueil l'une après l'autre
                self.setWindowOpacity(0.0)
                a = QPropertyAnimation(self, b"windowOpacity", self)
                a.setDuration(240)
                a.setStartValue(0.0)
                a.setEndValue(1.0)
                a.start()
            QTimer.singleShot(60, lambda: stagger(self.pages.currentWidget()))

    # ---------- fenêtre sans cadre: agrandir et redimensionner à la main
    def toggle_max(self):
        if self._max:
            self.setGeometry(self._normal)
        else:
            self._normal = self.geometry()
            self.setGeometry(self.screen().availableGeometry())  # sans recouvrir la barre des tâches
        self._max = not self._max
        self.titlebar.set_maximized(self._max)

    def edges_at(self):
        e, g, r = Qt.Edge(0), QCursor.pos(), self.frameGeometry()
        if self._max or not r.adjusted(-2, -2, 2, 2).contains(g):
            return e
        for cond, edge in ((g.x() <= r.left() + EDGE_PX, Qt.Edge.LeftEdge), (g.x() >= r.right() - EDGE_PX, Qt.Edge.RightEdge),
                           (g.y() <= r.top() + EDGE_PX, Qt.Edge.TopEdge), (g.y() >= r.bottom() - EDGE_PX, Qt.Edge.BottomEdge)):
            if cond:
                e |= edge
        return e

    def eventFilter(self, obj, ev):
        if isinstance(obj, QWidget) and obj.window() is self and ev.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress):
            e = self.edges_at()
            L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
            cur = {L: Qt.SizeHorCursor, R: Qt.SizeHorCursor, T: Qt.SizeVerCursor, B: Qt.SizeVerCursor, L | T: Qt.SizeFDiagCursor,
                   R | B: Qt.SizeFDiagCursor, R | T: Qt.SizeBDiagCursor, L | B: Qt.SizeBDiagCursor}.get(e)
            if cur is not None:
                (QApplication.changeOverrideCursor if self._ov else QApplication.setOverrideCursor)(QCursor(cur))
                self._ov = True
                if ev.type() == QEvent.Type.MouseButtonPress and ev.button() == Qt.LeftButton:
                    self.windowHandle().startSystemResize(e)
                    return True
            elif self._ov:
                QApplication.restoreOverrideCursor()
                self._ov = False
        return False

    def leaveEvent(self, ev):
        if self._ov:
            QApplication.restoreOverrideCursor()
            self._ov = False

    # ---------- construction des pages
    def page(self, title, sub):
        """Page défilante, contenu centré (800 px max): même mise en page quelle que soit la taille de la fenêtre."""
        body = QWidget()
        body.setObjectName("pageBody")
        body.setMaximumWidth(800)
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 28, 0, 26)
        v.setSpacing(16)
        t, s = QLabel(title), QLabel(sub)
        t.setObjectName("pageTitle")
        s.setObjectName("pageSub")
        s.setWordWrap(True)
        v.addWidget(t)
        v.addWidget(s)
        v.addSpacing(6)
        wrap = QWidget()
        wrap.setObjectName("pageBody")
        h = QHBoxLayout(wrap)
        h.setContentsMargins(36, 0, 36, 0)
        h.addStretch(1)
        h.addWidget(body, 100)
        h.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(wrap)
        return sc, v

    def combo(self, key, items, then=None, width=270):
        """items: [(texte affiché, valeur enregistrée)]."""
        c = Combo()
        c.setFixedWidth(width)
        for label, value in items:
            c.addItem(label, value)
        if c.findData(self.cfg[key]) < 0:  # valeur enregistrée absente (périphérique débranché…): on la garde visible
            c.addItem(f"{self.cfg[key]} (introuvable)", self.cfg[key])
        c.setCurrentIndex(c.findData(self.cfg[key]))
        c.currentIndexChanged.connect(lambda i: self.set(key, c.itemData(i), then))
        return c

    def devices(self, kind):
        return [(DEFAULT_DEV, "")] + [(n, n) for n in audio.device_names(kind)]

    def slider(self, key, lo, hi, fmt, then=None):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        s, lbl = QSlider(Qt.Horizontal), QLabel()
        s.setFixedWidth(200)
        s.setRange(int(lo * 100), int(hi * 100))
        s.setValue(round(self.cfg[key] * 100))
        lbl.setFixedWidth(56)
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lbl.setText(fmt(self.cfg[key]))
        s.valueChanged.connect(lambda v: (lbl.setText(fmt(v / 100)), self.set(key, round(v / 100, 2), then)))
        h.addWidget(s)
        h.addWidget(lbl)
        return w

    def folder_row(self, card, kind, title, desc):
        """Ligne « Dossier d'installation » d'un modèle téléchargé: chemin actuel + bouton Changer…"""
        btn = GlowButton("Changer…", "ghost")
        btn.clicked.connect(lambda: self.change_folder(kind))
        w = card.row(title, desc + "\n", btn)
        self.path_rows.setdefault(kind, []).append((w.desc_label, desc))

    def refresh_paths(self):
        for kind, rows in self.path_rows.items():
            p = models.folder(self.cfg, kind)
            for lbl, desc in rows:
                lbl.setText(f"{desc}\n{shorten(p)}" + ("" if models.is_custom(self.cfg, kind) else "  (par défaut)"))
                lbl.setToolTip(str(p))

    def page_home(self):
        sc, v = self.page("Accueil", "Ce que Ruby fait en ce moment.")
        hero = Card()
        hero.v.setContentsMargins(26, 16, 26, 16)
        h = QHBoxLayout()
        self.orb = Orb()
        h.addWidget(self.orb)
        h.addSpacing(18)
        col = QVBoxLayout()
        col.addStretch()
        self.home_state = QLabel("Ruby est arrêtée")
        self.home_state.setStyleSheet("font-size: 26px; font-weight: 700;")
        self.tip = QLabel()
        self.tip.setObjectName("rowDesc")
        self.tip.setWordWrap(True)
        self.mem_lbl = QLabel()
        self.mem_lbl.setObjectName("path")
        col.addWidget(self.home_state)
        col.addSpacing(4)
        col.addWidget(self.tip)
        col.addSpacing(8)
        col.addWidget(self.mem_lbl)
        col.addStretch()
        h.addLayout(col, 1)
        hero.v.addLayout(h)
        v.addWidget(hero)
        lbl = QLabel("PIPELINE")
        lbl.setObjectName("cardTitle")
        v.addWidget(lbl)
        self.chips = QGridLayout()
        self.chips.setSpacing(12)
        v.addLayout(self.chips)
        c = Card("Dernière conversation")
        c.v.setContentsMargins(22, 18, 22, 18)
        c.v.setSpacing(10)
        self.home_text, self.home_reply = QLabel(), QLabel()
        self.home_text.setObjectName("bubbleYou")
        self.home_reply.setObjectName("bubbleRuby")
        self.home_none = QLabel("Aucune commande pour l'instant. Dis ton mot d'activation !")
        self.home_none.setObjectName("rowDesc")
        for lb in (self.home_text, self.home_reply):
            lb.setWordWrap(True)
            lb.setMaximumWidth(460)
            lb.hide()  # visibles seulement quand il y a quelque chose à montrer (voir poll)
        c.v.addWidget(self.home_none)
        c.v.addWidget(self.home_text, 0, Qt.AlignRight)
        c.v.addWidget(self.home_reply, 0, Qt.AlignLeft)
        v.addWidget(c)
        v.addStretch()
        return sc

    def page_general(self):
        sc, v = self.page("Général", "Langue, périphériques et apparence.")
        c = Card("Écoute")
        self.words = QLineEdit(self.cfg["words"])
        self.words.setFixedWidth(270)
        self.words.setPlaceholderText("hi;hey")
        self.words.textChanged.connect(lambda t: self.set("words", t.strip()))
        c.row("Mots d'activation", "Séparés par « ; ». Chaque mot est suivi de « Ruby » (hi;hey → « Hi Ruby », « Hey Ruby »). "
              "Refais « Apprendre ma voix » après un changement.", self.words)
        c.row("Langue", "Langue de la reconnaissance vocale et des réponses.",
              self.combo("lang", [(n, n) for n in LANGS], self.refresh_voices))
        c.row("Micro", "", self.combo("mic", self.devices("input")))
        c.row("Haut-parleurs", "", self.combo("speaker", self.devices("output")))
        v.addWidget(c)
        c2 = Card("Son et apparence")
        c2.row("Volume de Ruby", "Sons et voix.", self.slider("volume", 0.05, 1.0, lambda x: f"{round(x * 100)} %"))
        c2.row("Lueur d'écran", "Un halo lumineux autour de l'écran quand Ruby t'écoute.", Toggle(self.cfg["glow"], lambda on: self.set("glow", on)))
        v.addWidget(c2)
        c3 = Card("Mémoire")
        cap = QLabel(f"{config.MEM_LIMIT} Mo maximum")
        cap.setStyleSheet("color: #3DD68C; font-weight: 600;")
        c3.row("Plafond", "Au repos Ruby n'utilise que ≈10 Mo. Quand tu lui parles, Whisper se charge pendant ta phrase puis est libéré, "
               "et seulement après la voix: jamais les deux ensemble. Les phrases déjà dites restent sur le disque et sont rejouées "
               "sans recharger la voix.", cap)
        v.addWidget(c3)
        v.addStretch()
        return sc

    def page_voice(self):
        sc, v = self.page("Voix", "Comment Ruby te parle.")
        c = Card("Synthèse vocale")
        c.row("Moteur", "Supertonic tourne sur ton PC (rapide, sans Internet). Edge utilise les serveurs de Microsoft: plus de délai, Internet requis.",
              self.combo("engine", [(n, n) for n in VOICES], self.refresh_voices))
        self.voice_combo = self.combo("voice", [(n, n) for n in VOICES[self.cfg["engine"]][self.cfg["lang"]]])
        c.row("Voix", "", self.voice_combo)
        c.row("Vitesse", "", self.slider("speed", 0.7, 1.4, lambda x: f"×{x:.2f}"))
        self.test_btn = GlowButton("▶  Écouter", "ghost")
        self.test_btn.clicked.connect(self.test_voice)
        c.row("Tester", "Lit une phrase avec les réglages actuels.", self.test_btn)
        self.folder_row(c, "voice", "Dossier d'installation", "Où est installée la voix Supertonic (≈385 Mo, téléchargée une seule fois).")
        v.addWidget(c)
        self.voice_err = QLabel("")
        self.voice_err.setStyleSheet("color: #FF8A98;")
        self.voice_err.setWordWrap(True)
        v.addWidget(self.voice_err)
        v.addStretch()
        return sc

    def page_listen(self):
        sc, v = self.page("Écoute", "Ruby apprend ta voix pour ne répondre qu'à toi.")
        c = Card("Ma voix")
        self.sync_lbl = QLabel()
        self.sync_btn = GlowButton("Apprendre ma voix", "primary")
        self.sync_btn.clicked.connect(self.sync)
        c.row("Mots appris", "", self.sync_lbl)
        c.row("Apprentissage", "Environ 1 minute: tu dis tes mots d'activation, quelques phrases au hasard, puis le silence de la pièce.", self.sync_btn)
        v.addWidget(c)
        c2 = Card("Détection")
        c2.row("Seuil", "Plus haut = plus strict (moins de faux déclenchements). Plus bas = plus sensible.",
               self.slider("threshold", 0.5, 0.99, lambda x: f"{x:.2f}"))
        self.meter = SmoothBar()
        self.meter.setRange(0, 100)
        self.meter.setFixedWidth(270)
        c2.row("Détection en direct", "Dis ton mot d'activation: la barre doit dépasser le seuil.", self.meter)
        v.addWidget(c2)
        c3 = Card("Reconnaissance vocale")
        c3.row("Modèle Whisper", "Il tourne sur ton PC et se télécharge une seule fois. "
               "Plus il est gros, plus il comprend bien… et plus il est lent. Une copie optimisée (int8) est créée à côté, une seule fois: "
               "elle évite un pic de mémoire de 680 Mo au chargement.", self.combo("whisper", WHISPER), ("Sur ton PC", "local"))
        self.folder_row(c3, "whisper", "Dossier d'installation", "Où sont installés les modèles Whisper (≈480 Mo + ≈240 Mo de copie optimisée pour small).")
        v.addWidget(c3)
        v.addStretch()
        return sc

    def page_ai(self):
        sc, v = self.page("Intelligence", "Groq comprend n'importe quelle phrase. Sans clé, Ruby utilise ses règles locales.")
        c = Card("Groq")
        self.key = QLineEdit(self.cfg["groq_key"])
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setFixedWidth(270)
        self.key.setPlaceholderText("gsk_…")
        self.key.textChanged.connect(lambda t: self.set("groq_key", t.strip()))
        c.row("Clé API", "Gratuite sur console.groq.com. Stockée en clair dans config.json.", self.key)
        c.row("Modèle", "Ces modèles tournent sur les serveurs de Groq: rien n'est installé sur ton PC. "
              "Le 20B répond plus vite, le 120B comprend mieux les phrases compliquées.",
              self.combo("groq_model", GROQ_MODELS), ("Cloud · Groq", "cloud"))
        b = GlowButton("Tester la clé", "ghost")
        b.clicked.connect(self.test_groq)
        c.row("Vérification", "", b)
        v.addWidget(c)
        self.groq_lbl = QLabel("")
        v.addWidget(self.groq_lbl)
        note = QLabel("Avec Groq, chaque phrase transcrite (le texte, pas l'audio) est envoyée à leurs serveurs. "
                      "Si Groq est injoignable ou la clé vide, Ruby retombe sur ses règles locales.")
        note.setObjectName("rowDesc")
        note.setWordWrap(True)
        v.addWidget(note)
        v.addStretch()
        return sc

    def page_models(self):
        sc, v = self.page("Modèles", "Tout ce que Ruby télécharge et utilise. Choisis où chaque modèle est installé, ou supprime ceux dont tu n'as plus besoin.")
        self.models_box = QVBoxLayout()  # reconstruit à chaque affichage de la page
        self.models_box.setSpacing(16)
        v.addLayout(self.models_box)
        v.addStretch()
        return sc

    # ---------- page Modèles
    @staticmethod
    def clear(layout):
        while layout.count():
            w = layout.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def manage_actions(self, r):
        acts = []
        if r["path"] and Path(r["path"]).exists():
            acts.append((G["folder"], "Ouvrir le dossier", lambda: os.startfile(r["path"]), False))
        if r["movable"]:
            acts.append((G["move"], "Changer le dossier…", lambda: self.change_folder(r["kind"]), False))
        if r["custom"]:
            acts.append((G["undo"], "Revenir au dossier par défaut", lambda: self.change_folder(r["kind"], default=True), False))
        if r["items"]:
            acts.append((G["delete"], "Supprimer…", lambda: self.delete_model(r), True))
        return acts

    def model_row(self, r):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 14, 0, 14)
        h.setSpacing(14)
        h.addWidget(glyph(r["icon"], 20, "#FF4D6D"), 0, Qt.AlignTop)
        left = QVBoxLayout()
        left.setSpacing(3)
        t, m = QLabel(r["title"]), QLabel(r["model"])
        t.setObjectName("rowTitle")
        m.setObjectName("rowDesc")
        left.addWidget(t)
        left.addWidget(m)
        if r["path"]:
            p = QLabel(("Données : " if r["kind"] == "mine" else "Dossier : ") + shorten(r["path"], 52))
            p.setObjectName("path")
            p.setToolTip(str(r["path"]))
            left.addWidget(p)
        h.addLayout(left, 1)
        right = QVBoxLayout()
        right.setSpacing(6)
        badges = QHBoxLayout()
        badges.addStretch()
        badges.addWidget(Badge("Sur ton PC" if r["where"] == "local" else "Cloud", r["where"]))
        badges.addWidget(Badge(*r["status"]))
        right.addLayout(badges)
        if r["size"]:
            sz = QLabel(f"{fmt_size(r['size'])} sur le disque")
            sz.setObjectName("rowDesc")
            right.addWidget(sz, 0, Qt.AlignRight)
        h.addLayout(right)
        acts = self.manage_actions(r)
        btn = ManageButton(acts) if acts else QWidget()
        btn.setFixedWidth(104)
        btn.manage_for = r
        h.addWidget(btn, 0, Qt.AlignVCenter)
        return w

    def chip(self, r):
        chip = Card()
        chip.v.setContentsMargins(14, 12, 14, 12)
        chip.v.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(glyph(r["icon"], 15, "#FF4D6D"))
        head.addWidget(QLabel(r["title"]))
        head.addStretch()
        chip.v.addLayout(head)
        m = QLabel(r["model"])
        m.setObjectName("rowDesc")
        m.setWordWrap(True)
        chip.v.addWidget(m)
        chip.v.addWidget(Badge("Sur ton PC" if r["where"] == "local" else "Cloud", r["where"]), 0, Qt.AlignLeft)
        return chip

    def _disk_text(self, v):
        try:
            self.disk_lbl.setText(fmt_size(int(v)))
        except RuntimeError:  # le libellé a été reconstruit pendant l'animation
            pass

    def refresh_models(self, animate=False):
        used, others, total = model_rows(self.cfg)
        self.clear(self.chips)
        self.clear(self.models_box)
        card = Card("Utilisés actuellement")
        for r in used:
            card.add(self.model_row(r))
        self.models_box.addWidget(card)
        if others:
            c2 = Card("Autres modèles sur ton PC")
            for r in others:
                c2.add(self.model_row(r))
            self.models_box.addWidget(c2)
        c3 = Card("Espace disque")
        self.disk_lbl = QLabel(fmt_size(total))
        self.disk_lbl.setStyleSheet("font-size: 16px; font-weight: 600;")
        c3.row("Modèles sur ton PC", "Aucune limite: Ruby n'impose aucun quota. Chaque modèle se gère avec son bouton « Gérer ».", self.disk_lbl)
        self.models_box.addWidget(c3)
        run(self.disk_anim, self._disk, total)
        self._disk = total
        for i, r in enumerate(x for x in used if x["pipeline"]):
            self.chips.addWidget(self.chip(r), i // 2, i % 2)
        self.refresh_paths()
        if animate:
            for i in range(self.models_box.count()):
                fade_in(self.models_box.itemAt(i).widget(), 300, 50 * i)

    # ---------- état
    def set(self, key, value, then=None):
        self.cfg[key] = value
        save_cfg(self.cfg)
        if then:
            then()

    def refresh_voices(self):
        vs = VOICES[self.cfg["engine"]][self.cfg["lang"]]
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        for n in vs:
            self.voice_combo.addItem(n, n)
        self.voice_combo.setCurrentIndex(max(0, self.voice_combo.findData(self.cfg["voice"])))
        self.voice_combo.blockSignals(False)
        self.set("voice", self.voice_combo.currentData())

    def read_status(self):
        try:
            st = json.loads(config.STATUS_FILE.read_text("utf-8"))
            return st if time.time() - st["ts"] < 3 else None  # battement absent: le moteur est arrêté
        except (OSError, ValueError, KeyError):
            return None

    def changed(self, key, value):
        """True si `value` est nouveau pour `key` (évite de relancer une animation ou un style toutes les 250 ms)."""
        if self._last.get(key) == value:
            return False
        self._last[key] = value
        return True

    def poll(self):
        st = self.read_status()
        self.running = st is not None
        state = st["state"] if st else "stopped"
        text, color = STATES.get(state, (state, "#5B6478"))
        active = self.running and state != "stopped"
        if self.changed("state", (state, active)):
            self.dot.set_state(color, active)
            self.orb.set_state(color, active)
            self.state_lbl.setText(text)
            self.home_state.setText(text)
            fade_in(self.home_state, 220)
        if self.changed("running", self.running):
            self.engine_btn.setText("Arrêter Ruby" if self.running else "Démarrer Ruby")
            self.engine_btn.set_kind("danger" if self.running else "primary")
        heard, said = (st or {}).get("text") or "", (st or {}).get("reply") or ""
        if self.changed("heard", heard):
            self.home_text.setText(heard)
            self.home_text.setVisible(bool(heard))
            heard and fade_in(self.home_text, 300)
        if self.changed("said", said):
            self.home_reply.setText(said)
            self.home_reply.setVisible(bool(said))
            said and fade_in(self.home_reply, 300, 140)
        self.home_none.setVisible(not heard and not said)
        mem, loaded = (st or {}).get("mem"), (st or {}).get("loaded") or []
        own = private_mb()  # cette fenêtre compte aussi dans le plafond
        self.mem_lbl.setText(f"Mémoire de Ruby : {mem + own} Mo sur {config.MEM_LIMIT} (moteur {mem}, réglages {own})  ·  "
                             + ("en mémoire : " + ", ".join(loaded) if loaded else "aucun modèle chargé")
                             if st and mem else "")
        self.meter.glide(round((st or {}).get("score", 0.0) * 100))
        ph = phrases(self.cfg["synced"])
        ok = ph and ph == phrases(self.cfg["words"]) and config.MODEL_FILE.exists()
        detail = (st or {}).get("detail") or ""
        self.tip.setText(detail and f"Préparation en cours: {detail}. Ça ne se fait qu'une fois." or
                         f"Dis « {' » ou « '.join(ph or phrases(self.cfg['words']))} », attends le petit son, puis parle.\n"
                         "Exemples: « Ouvre Discord », « Cherche des recettes de pâtes », « Combien font 12 fois 7 ? », « Mets pause ».")
        self.sync_lbl.setText(" · ".join(ph) if ok else "Pas encore appris (ou mots changés)")
        self.sync_lbl.setStyleSheet(f"color: {'#3DD68C' if ok else '#FFB347'}; font-weight: 600;")

    # ---------- moteur
    def toggle_engine(self):
        if self.running:
            config.QUIT_FILE.touch()
        else:
            config.launch("engine.py")
        self.engine_btn.setEnabled(False)
        QTimer.singleShot(2500, lambda: self.engine_btn.setEnabled(True))

    def stop_engine(self):
        """Arrête le moteur s'il tourne: il garde ses modèles ouverts, et Windows refuse alors de les déplacer ou de les supprimer."""
        st = self.read_status()
        if st is None:
            return False
        config.QUIT_FILE.touch()
        deadline = time.time() + 12
        while time.time() < deadline and (self.read_status() or pid_alive(st.get("pid"))):
            QApplication.processEvents()
            time.sleep(0.1)
        return True

    def restart_engine(self, was_running):
        if was_running:
            config.launch("engine.py")

    def release_speaker(self):
        self.speaker = None  # la voix de « Écouter » garde ses fichiers ouverts: on la lâche avant de toucher au dossier
        gc.collect()

    # ---------- gérer un modèle
    def delete_model(self, r):
        size = models.size(r["items"])
        if Confirm.ask(self, f"Supprimer {r['model']} ?", f"{fmt_size(size)} seront libérés.\n\n{DELETE_NOTE[r['kind']]}",
                       [("Annuler", "ghost"), ("Supprimer", "dangerSolid")]) != 1:
            return
        was = self.stop_engine()
        self.release_speaker()
        try:
            models.remove(r["items"])
            if r["kind"] == "mine":
                self.set("synced", "")
        except OSError as e:
            self.toast(f"Impossible de supprimer: {e}", error=True)
            self.refresh_models(animate=True)
            self.restart_engine(was)
            return
        stays_off = was and r["in_use"]  # Ruby en avait besoin: la relancer maintenant le retélécharge aussitôt, on laisse l'utilisateur décider
        self.toast(f"{r['model']} supprimé · {fmt_size(size)} libérés" + (" · Ruby est arrêtée" if stays_off else ""))
        self.refresh_models(animate=True)
        self.restart_engine(was and not stays_off)

    def change_folder(self, kind, default=False):
        """Change le dossier d'installation d'un modèle; propose de déplacer ce qui est déjà téléchargé."""
        cur, label = models.folder(self.cfg, kind), LABEL[kind]
        if default:
            new = models.default_folder(kind)
        else:
            picked = QFileDialog.getExistingDirectory(self, f"Choisis où installer {label}", str(cur.parent if cur.parent.exists() else Path.home()))
            if not picked:
                return
            new = Path(picked) / models.SUBDIR[kind]  # sous-dossier dédié: déplacer ou supprimer ne touchera qu'aux modèles de Ruby
        if new == cur:
            self.toast("C'est déjà le dossier actuel")
            return
        pairs = models.relocation(self.cfg, kind, new)
        move = False
        if pairs:
            c = Confirm.ask(self, "Déplacer les fichiers déjà téléchargés ?",
                            f"Les fichiers {DE[kind]} sont déjà téléchargés ({fmt_size(models.size([a for a, _ in pairs]))}).\n\nNouveau dossier :\n{new}",
                            [("Annuler", "ghost"), ("Laisser sur place", "ghost"), ("Déplacer", "primary")], icon=G["folder"])
            if c in (-1, 0):
                return
            move = c == 2
        was = self.stop_engine()
        self.release_speaker()
        if move:
            d = MoveDialog(self, DE[kind], pairs)
            if d.exec() != QDialog.Accepted:
                self.toast(d.error and f"Déplacement impossible: {d.error}" or "Déplacement annulé: rien n'a changé", error=bool(d.error))
                self.restart_engine(was)
                return
            if d.leftovers:
                self.toast("Copié, mais l'ancien emplacement n'a pas pu être nettoyé (fichiers utilisés)", error=True)
        self.cfg["paths"][kind] = "" if default else str(new)
        save_cfg(self.cfg)
        self.refresh_models(animate=True)
        self.toast("Dossier par défaut rétabli" if default else f"Dossier changé · {shorten(new, 44)}")
        self.restart_engine(was)

    def test_voice(self):
        if (self.read_status() or {}).get("loaded"):  # le moteur utilise Whisper ou la voix: les charger aussi ici dépasserait le plafond de mémoire
            self.voice_err.setText("Ruby est en train de traiter une commande: réessaie dans un instant.")
            return
        self.test_btn.setEnabled(False)
        self.voice_err.setText("")

        def go():
            err, sp = "", None
            try:
                import tts
                sp = self.speaker = self.speaker or tts.Speaker()
                sp.say(LANGS[self.cfg["lang"]]["hello"], dict(self.cfg))
            except Exception as e:
                err = f"Erreur: {e}"
            finally:
                if sp:
                    sp.unload()  # ≈415 Mo: la phrase reste sur disque, la rejouer ne recharge rien
                    memory.trim()
            self.voice_done.emit(err)
        threading.Thread(target=go, daemon=True).start()

    def test_groq(self):
        key = self.cfg["groq_key"] or os.environ.get("GROQ_API_KEY", "")
        self.groq_lbl.setText("Vérification…")

        def go():
            import requests  # ici seulement: la fenêtre n'en a pas besoin le reste du temps
            try:
                r = requests.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=8)
                msg = "✓ Clé valide" if r.ok else f"✗ Refusée (HTTP {r.status_code})"
            except requests.RequestException as e:
                msg = f"✗ Injoignable ({type(e).__name__})"
            self.groq_result.emit(msg if key else "✗ Aucune clé")
        threading.Thread(target=go, daemon=True).start()

    def sync(self):
        if not phrases(self.cfg["words"]):
            self.sync_lbl.setText("Mets d'abord un mot d'activation (page Général).")
            return
        was = self.stop_engine()  # le micro ne doit servir qu'à l'apprentissage
        SyncDialog(self, dict(self.cfg)).exec()
        self.cfg = load_cfg()  # l'assistant a mis à jour « synced »
        self.restart_engine(was)


def main():
    if sys.platform == "win32":  # la barre des tâches affiche le logo de Ruby, pas celui de Python
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Ruby.Assistant.Settings")
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    app.setFont(QFont("Segoe UI", 10))
    w = Settings()
    if "--shots" in sys.argv:  # captures des pages (vérification visuelle de mes propres fenêtres uniquement)
        base = sys.argv[sys.argv.index("--shots") + 1]
        w.resize(1080, 1050)
        w.show()

        def shot(i):  # vraie boucle d'événements: les animations se déroulent avant la capture
            if i >= w.pages.count():
                SyncDialog(w, dict(w.cfg)).grab().save(f"{base}_wizard.png")
                return app.quit()
            w.pages.setCurrentIndex(i)
            QTimer.singleShot(1300, lambda: (w.grab().save(f"{base}_{i}.png"), shot(i + 1)))
        QTimer.singleShot(1500, lambda: shot(0))
        app.exec()
        return
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
