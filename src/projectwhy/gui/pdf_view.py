"""PDF page display with a movable highlight rectangle."""

from __future__ import annotations

from PIL import Image as PILImage
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

from projectwhy.core.models import BBox


def _pil_to_qpixmap(im: PILImage.Image) -> QPixmap:
    if im.mode != "RGB":
        im = im.convert("RGB")
    data = im.tobytes("raw", "RGB")
    w, h = im.size
    qimg = QImage(data, w, h, 3 * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


class PDFView(QGraphicsView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pix_item: QGraphicsPixmapItem | None = None
        self._highlight: QGraphicsRectItem | None = None
        self._highlight_rgba = (255, 200, 0, 120)
        self._pen_rgba = (255, 160, 0, 200)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def set_highlight_color(self, rgba: tuple[int, int, int, int]) -> None:
        """RGBA fill for word highlight; pen is slightly darker/orange."""
        self._highlight_rgba = rgba
        r, g, b, a = rgba
        self._pen_rgba = (max(0, r - 40), max(0, g - 60), min(255, b + 40), min(255, a + 80))
        if self._highlight is not None:
            self._highlight.setBrush(QColor(*self._highlight_rgba))
            self._highlight.setPen(QColor(*self._pen_rgba))

    def set_page_image(self, im: PILImage.Image) -> None:
        self._scene.clear()
        self._pix_item = self._scene.addPixmap(_pil_to_qpixmap(im))
        self._highlight = QGraphicsRectItem()
        self._highlight.setBrush(QColor(*self._highlight_rgba))
        self._highlight.setPen(QColor(*self._pen_rgba))
        self._scene.addItem(self._highlight)
        self.fitInView(self._scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, e) -> None:  # noqa: ANN001
        super().resizeEvent(e)
        if self._pix_item is not None:
            self.fitInView(self._scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def set_highlight_bbox(self, bbox: BBox | None) -> None:
        if self._highlight is None:
            return
        if bbox is None:
            self._highlight.setVisible(False)
            return
        self._highlight.setVisible(True)
        self._highlight.setRect(QRectF(QPointF(bbox.x1, bbox.y1), QPointF(bbox.x2, bbox.y2)))
        self._scene.update()
