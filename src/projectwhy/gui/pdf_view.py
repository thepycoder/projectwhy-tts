"""PDF page display with a movable highlight rectangle."""

from __future__ import annotations

from PIL import Image as PILImage
from PyQt6.QtCore import QPointF, QRectF, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from projectwhy.core.models import BBox, Block
from projectwhy.gui.inspector.colors import rgb_for_block_type


def _pil_to_qpixmap(im: PILImage.Image, dpr: float = 1.0) -> QPixmap:
    if im.mode != "RGB":
        im = im.convert("RGB")
    data = im.tobytes("raw", "RGB")
    w, h = im.size
    qimg = QImage(data, w, h, 3 * w, QImage.Format.Format_RGB888)
    pm = QPixmap.fromImage(qimg.copy())
    if dpr != 1.0:
        pm.setDevicePixelRatio(dpr)
    return pm


class PDFView(QGraphicsView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pix_item: QGraphicsPixmapItem | None = None
        self._highlight: QGraphicsRectItem | None = None
        self._highlight_rgba = (255, 200, 0, 120)
        self._pen_rgba = (255, 160, 0, 200)
        self._source_image: PILImage.Image | None = None
        self._bbox_scale = 1.0
        self._overlay_blocks: list[Block] = []
        self._overlay_active_idx: int | None = None
        self._show_overlays: bool = False
        self._overlay_items: list = []
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)
        self._resize_timer.timeout.connect(self._render_to_viewport)

    def set_highlight_color(self, rgba: tuple[int, int, int, int]) -> None:
        """RGBA fill for word highlight; pen is slightly darker/orange."""
        self._highlight_rgba = rgba
        r, g, b, a = rgba
        self._pen_rgba = (max(0, r - 40), max(0, g - 60), min(255, b + 40), min(255, a + 80))
        if self._highlight is not None:
            self._highlight.setBrush(QColor(*self._highlight_rgba))
            self._highlight.setPen(QColor(*self._pen_rgba))

    def set_page_image(self, im: PILImage.Image) -> None:
        self._source_image = im
        self._render_to_viewport()

    def _render_to_viewport(self) -> None:
        if self._source_image is None:
            return
        im = self._source_image
        src_w, src_h = im.size

        self._scene.clear()

        vp = self.viewport().size()
        dpr = self.devicePixelRatioF()
        target_w = max(1, int(vp.width() * dpr))
        target_h = max(1, int(vp.height() * dpr))

        scale = min(target_w / src_w, target_h / src_h, 1.0)
        if scale < 1.0:
            display_w = max(1, round(src_w * scale))
            display_h = max(1, round(src_h * scale))
            display_im = im.resize((display_w, display_h), PILImage.Resampling.LANCZOS)
            pixmap = _pil_to_qpixmap(display_im, dpr)
            self._bbox_scale = (display_w / dpr) / src_w
        else:
            pixmap = _pil_to_qpixmap(im)
            self._bbox_scale = 1.0

        self._pix_item = self._scene.addPixmap(pixmap)
        self._overlay_items.clear()
        self._draw_overlays()

        self._highlight = QGraphicsRectItem()
        self._highlight.setBrush(QColor(*self._highlight_rgba))
        self._highlight.setPen(QColor(*self._pen_rgba))
        self._highlight.setZValue(10)
        self._scene.addItem(self._highlight)

        self.resetTransform()
        self.setSceneRect(self._scene.itemsBoundingRect())
        self.centerOn(self._pix_item)

    def resizeEvent(self, e) -> None:  # noqa: ANN001
        super().resizeEvent(e)
        if self._pix_item is not None:
            self.centerOn(self._pix_item)
        if self._source_image is not None:
            self._resize_timer.start()

    def set_highlight_bbox(self, bbox: BBox | None) -> None:
        if self._highlight is None:
            return
        if bbox is None:
            self._highlight.setVisible(False)
            return
        s = self._bbox_scale
        self._highlight.setVisible(True)
        self._highlight.setRect(QRectF(
            QPointF(bbox.x1 * s, bbox.y1 * s),
            QPointF(bbox.x2 * s, bbox.y2 * s),
        ))
        self._scene.update()

    def set_show_overlays(self, show: bool) -> None:
        self._show_overlays = show
        if self._pix_item is not None:
            self._draw_overlays()

    def set_block_overlays(self, blocks: list[Block], active_idx: int | None) -> None:
        self._overlay_blocks = list(blocks)
        self._overlay_active_idx = active_idx
        if self._pix_item is not None:
            self._draw_overlays()

    def _draw_overlays(self) -> None:
        for it in self._overlay_items:
            self._scene.removeItem(it)
        self._overlay_items.clear()
        if not self._show_overlays or not self._overlay_blocks or self._pix_item is None:
            return

        s = self._bbox_scale
        for i, block in enumerate(self._overlay_blocks):
            bb = block.bbox
            rect = QRectF(QPointF(bb.x1 * s, bb.y1 * s), QPointF(bb.x2 * s, bb.y2 * s))
            rgb = rgb_for_block_type(block.block_type)
            active = self._overlay_active_idx is not None and i == self._overlay_active_idx
            fill_a = 100 if active else 55

            ritem = QGraphicsRectItem(rect)
            ritem.setBrush(QBrush(QColor(rgb[0], rgb[1], rgb[2], fill_a)))
            pen_w = 3.0 if active else 1.5
            ritem.setPen(QPen(QColor(*rgb), pen_w))
            ritem.setZValue(5)
            self._scene.addItem(ritem)
            self._overlay_items.append(ritem)

            label = QGraphicsSimpleTextItem(str(i))
            f = QFont()
            f.setPointSize(9)
            label.setFont(f)
            label.setBrush(QBrush(QColor(30, 30, 30)))
            label.setPos(rect.topLeft() + QPointF(2, 2))
            label.setZValue(6)
            # Keep labels upright when the user rotates the view.
            label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            label.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

            self._scene.addItem(label)
            self._overlay_items.append(label)
