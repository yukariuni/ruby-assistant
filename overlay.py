"""Lueur autour de l'écran quand Ruby écoute (comme Siri / ChatGPT qui contrôle un PC).

Fenêtre plein écran transparente, au-dessus de tout, qui laisse passer les clics et ne prend pas le focus.
"""
import math
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QConicalGradient, QIcon, QImage, QPainter
from PySide6.QtWidgets import QWidget

COLORS = ["#FF1744", "#FF4D8D", "#C13CFF", "#FF8A4D", "#FF4D8D", "#FF1744"]  # boucle: le dégradé tourne sans coupure
ASSETS = Path(__file__).parent / "assets"
BAND = 96  # largeur de la lueur en pixels


def make_icon():
    """Logo de Ruby (assets/icon_*.png). Qt choisit la taille la plus proche: net de 16 à 512 px."""
    icon = QIcon()
    for n in (16, 20, 24, 32, 48, 64, 128, 256, 512):
        icon.addFile(str(ASSETS / f"icon_{n}.png"))
    return icon


class Glow(QWidget):
    def __init__(self, screen):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.setWindowOpacity(0)
        self.angle, self.speed, self.pulse = 0.0, 2.0, 0.0
        self._mask_img, self._mask_size = None, None
        self.timer = QTimer(self, interval=33, timeout=self._tick)  # ~30 images/s, seulement quand visible
        self.fade = QPropertyAnimation(self, b"windowOpacity", self, duration=350)
        self.fade.finished.connect(self._faded)

    def set_active(self, on, speed=2.0):
        """on: affiche (fondu) ou masque. speed: vitesse de rotation des couleurs (plus vite = Ruby réfléchit)."""
        self.speed = speed
        self.fade.stop()
        self.fade.setStartValue(self.windowOpacity())
        self.fade.setEndValue(1.0 if on else 0.0)
        if on and not self.isVisible():
            self.show()
            self.timer.start()
        self.fade.start()

    def _faded(self):
        if self.windowOpacity() == 0:
            self.timer.stop()
            self.hide()

    def _tick(self):
        self.angle = (self.angle + self.speed) % 360
        self.pulse = (self.pulse + 0.06 * self.speed / 2) % 6.2832
        self.update()

    def _mask(self):
        """Opacité de la lueur selon la distance au bord de l'écran (vive au bord, très douce vers l'intérieur). Calculée une fois par taille."""
        w, h = self.width(), self.height()
        if self._mask_img is None or self._mask_size != (w, h):
            y, x = np.ogrid[:h, :w]
            xd, yd, r = np.minimum(x, w - 1 - x), np.minimum(y, h - 1 - y), 40  # r: arrondi des coins (pas de couture en diagonale)
            ex, ey = np.maximum(r - xd, 0), np.maximum(r - yd, 0)
            d = np.where((ex > 0) & (ey > 0), np.maximum(r - np.hypot(ex, ey), 0), np.minimum(xd, yd)).astype(np.float32)
            a = (np.clip(1 - d / BAND, 0, 1) ** 3 * 235).astype(np.uint8)
            self._mask_img = QImage(a.data, w, h, w, QImage.Format_Alpha8).copy()  # copie: le tableau numpy disparaît ensuite
            self._mask_size = (w, h)
        return self._mask_img

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        grad = QConicalGradient(QPointF(w / 2, h / 2), self.angle)
        for i, c in enumerate(COLORS):
            grad.setColorAt(i / (len(COLORS) - 1), QColor(c))
        buf = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        buf.fill(Qt.transparent)
        q = QPainter(buf)
        # seules les 4 bandes du bord sont peintes: le centre de l'écran ne coûte rien
        for r in (QRect(0, 0, w, BAND), QRect(0, h - BAND, w, BAND), QRect(0, BAND, BAND, h - 2 * BAND), QRect(w - BAND, BAND, BAND, h - 2 * BAND)):
            q.setCompositionMode(QPainter.CompositionMode_Source)
            q.fillRect(r, grad)
            q.setCompositionMode(QPainter.CompositionMode_DestinationIn)  # applique l'opacité du masque à cette bande
            q.drawImage(r.topLeft(), self._mask(), r)
        q.end()
        p = QPainter(self)
        p.setOpacity(0.85 + 0.15 * math.sin(self.pulse))  # respiration lente de l'intensité (70 % à 100 %)
        p.drawImage(0, 0, buf)
