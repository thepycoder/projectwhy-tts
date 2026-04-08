"""PDF page display with a movable highlight rectangle."""

from __future__ import annotations

from PIL import Image as PILImage
from PyQt6.QtCore import QPointF, QRectF, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from projectwhy.core.models import BBox, Block
from projectwhy.core.pdf import word_bbox_at_blocks_point
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
    """Left-click a word to seek (signal); drag to pan. Hover highlights the word under the cursor."""

    word_clicked = pyqtSignal(float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pix_item: QGraphicsPixmapItem | None = None
        self._hover_highlight: QGraphicsRectItem | None = None
        self._highlight: QGraphicsRectItem | None = None
        self._highlight_rgba = (255, 200, 0, 120)
        self._pen_rgba = (255, 160, 0, 200)
        self._hover_fill = QColor(100, 160, 255, 90)
        self._hover_pen = QColor(60, 120, 220, 180)
        self._source_image: PILImage.Image | None = None
        self._bbox_scale = 1.0
        self._overlay_blocks: list[Block] = []
        self._overlay_active_idx: int | None = None
        self._show_overlays: bool = False
        self._overlay_items: list = []
        self._hover_blocks: list[Block] = []

        self._left_press_viewport: QPointF | None = None
        self._left_pan_active = False
        self._last_pan_viewport: QPointF | None = None

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)
        self._resize_timer.timeout.connect(self._render_to_viewport)

    def set_hover_blocks(self, blocks: list[Block]) -> None:
        """Blocks on the current page (page-image word bboxes) used for hover hit-testing."""
        self._hover_blocks = list(blocks)

    def set_highlight_color(self, rgba: list[int] | tuple[int, int, int, int]) -> None:
        """RGBA fill for word highlight; pen is slightly darker/orange."""
        self._highlight_rgba = tuple(rgba)
        r, g, b, a = self._highlight_rgba
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

        self._hover_highlight = QGraphicsRectItem()
        self._hover_highlight.setBrush(QBrush(self._hover_fill))
        self._hover_highlight.setPen(QPen(self._hover_pen))
        self._hover_highlight.setZValue(9)
        self._hover_highlight.setVisible(False)
        self._scene.addItem(self._hover_highlight)

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

    def leaveEvent(self, e) -> None:  # noqa: ANN001
        self._clear_hover()
        super().leaveEvent(e)

    def _pixmap_local_from_viewport(self, viewport_pos: QPointF) -> QPointF | None:
        if self._pix_item is None:
            return None
        scene_pt = self.mapToScene(viewport_pos.toPoint())
        local = self._pix_item.mapFromScene(scene_pt)
        br = self._pix_item.boundingRect()
        if not br.contains(local):
            return None
        return local

    def _image_coords_from_viewport(self, viewport_pos: QPointF) -> tuple[float, float] | None:
        local = self._pixmap_local_from_viewport(viewport_pos)
        if local is None:
            return None
        x = float(local.x()) / self._bbox_scale
        y = float(local.y()) / self._bbox_scale
        return x, y

    def _scroll_viewport_by(self, delta: QPointF) -> None:
        h = self.horizontalScrollBar()
        v = self.verticalScrollBar()
        h.setValue(h.value() - int(round(delta.x())))
        v.setValue(v.value() - int(round(delta.y())))

    def _clear_hover(self) -> None:
        if self._hover_highlight is not None:
            self._hover_highlight.setVisible(False)
        self.unsetCursor()

    def _update_hover_at_viewport(self, viewport_pos: QPointF) -> None:
        if self._hover_highlight is None or self._left_press_viewport is not None:
            return
        coords = self._image_coords_from_viewport(viewport_pos)
        if coords is None:
            self._clear_hover()
            return
        bbox = word_bbox_at_blocks_point(self._hover_blocks, coords[0], coords[1])
        if bbox is None:
            self._clear_hover()
            return
        s = self._bbox_scale
        self._hover_highlight.setRect(
            QRectF(
                QPointF(bbox.x1 * s, bbox.y1 * s),
                QPointF(bbox.x2 * s, bbox.y2 * s),
            )
        )
        self._hover_highlight.setVisible(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scene.update()

    def mousePressEvent(self, e) -> None:  # noqa: ANN001
        if e.button() == Qt.MouseButton.LeftButton:
            self._left_press_viewport = QPointF(e.position())
            self._left_pan_active = False
            self._last_pan_viewport = QPointF(e.position())
            self._clear_hover()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: ANN001
        if e.buttons() == Qt.MouseButton.NoButton:
            self._update_hover_at_viewport(QPointF(e.position()))
            super().mouseMoveEvent(e)
            return

        if (e.buttons() & Qt.MouseButton.LeftButton) and self._left_press_viewport is not None:
            dist = (QPointF(e.position()) - self._left_press_viewport).manhattanLength()
            drag = QApplication.startDragDistance()
            if not self._left_pan_active and dist >= drag:
                self._left_pan_active = True
                self._clear_hover()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._left_pan_active and self._last_pan_viewport is not None:
                d = QPointF(e.position()) - self._last_pan_viewport
                self._last_pan_viewport = QPointF(e.position())
                self._scroll_viewport_by(d)
                e.accept()
                return

        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: ANN001
        if e.button() == Qt.MouseButton.LeftButton and self._left_press_viewport is not None:
            if not self._left_pan_active:
                coords = self._image_coords_from_viewport(self._left_press_viewport)
                if coords is not None:
                    self.word_clicked.emit(coords[0], coords[1])
            self._left_press_viewport = None
            self._left_pan_active = False
            self._last_pan_viewport = None
            self.unsetCursor()
            self._update_hover_at_viewport(QPointF(e.position()))
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def set_highlight_bbox(self, bbox: BBox | None) -> None:
        if self._highlight is None:
            return
        if bbox is None:
            self._highlight.setVisible(False)
            return
        s = self._bbox_scale
        self._highlight.setVisible(True)
        self._highlight.setRect(
            QRectF(
                QPointF(bbox.x1 * s, bbox.y1 * s),
                QPointF(bbox.x2 * s, bbox.y2 * s),
            )
        )
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
