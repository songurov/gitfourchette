# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""Small, dependency-free charts for the repository manager on Home."""

import math

from gitfourchette.qt import *


CHART_COLORS = (
    QColor("#f39c35"), QColor("#f04b3a"), QColor("#f7cf43"),
    QColor("#7ed957"), QColor("#4da3ff"), QColor("#a77bea"),
)


class CommitActivityChart(QWidget):
    """Line chart of commits per month, one series per contributor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.months: list[str] = []
        self.series: list[tuple[str, list[int]]] = []
        self.setMinimumHeight(270)

    def setData(self, months: list[str], series: list[tuple[str, list[int]]]):
        self.months = months
        self.series = series
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        textColor = palette.color(QPalette.ColorRole.Text)
        gridColor = palette.color(QPalette.ColorRole.Mid)
        gridColor.setAlpha(80)

        left, top, right, bottom = 42, 18, 18, 58
        plot = QRectF(left, top, max(1, self.width() - left - right),
                      max(1, self.height() - top - bottom))
        if not self.months:
            painter.setPen(textColor)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.tr("No commits to plot"))
            return

        maximum = max((max(values, default=0) for _name, values in self.series), default=0)
        maximum = max(1, maximum)
        steps = 4
        painter.setFont(self.font())
        for i in range(steps + 1):
            y = plot.bottom() - plot.height() * i / steps
            painter.setPen(gridColor)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(textColor)
            painter.drawText(QRectF(0, y - 9, left - 7, 18),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             str(round(maximum * i / steps)))

        denominator = max(1, len(self.months) - 1)
        for i, month in enumerate(self.months):
            x = plot.left() + plot.width() * i / denominator
            if len(self.months) <= 6 or i % math.ceil(len(self.months) / 6) == 0 \
                    or i == len(self.months) - 1:
                painter.setPen(textColor)
                painter.drawText(QRectF(x - 45, plot.bottom() + 6, 90, 20),
                                 Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                                 month)

        for seriesIndex, (_name, values) in enumerate(self.series):
            color = CHART_COLORS[seriesIndex % len(CHART_COLORS)]
            painter.setPen(QPen(color, 2.0))
            points = []
            for i, value in enumerate(values):
                x = plot.left() + plot.width() * i / denominator
                y = plot.bottom() - plot.height() * value / maximum
                points.append(QPointF(x, y))
            if len(points) == 1:
                painter.drawEllipse(points[0], 2.5, 2.5)
            elif points:
                painter.drawPolyline(QPolygonF(points))

        legendY = self.height() - 22
        legendX = left
        metrics = painter.fontMetrics()
        for seriesIndex, (name, _values) in enumerate(self.series):
            width = metrics.horizontalAdvance(name) + 24
            if legendX + width > self.width() - right:
                break
            painter.setBrush(CHART_COLORS[seriesIndex % len(CHART_COLORS)])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(legendX, legendY + 4, 8, 8)
            painter.setPen(textColor)
            painter.drawText(legendX + 13, legendY, width - 13, 18,
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
            legendX += width


class ContributorDonut(QWidget):
    """Donut showing the relative share of the top contributors."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.contributors: list[tuple[str, int]] = []
        self.setMinimumSize(260, 260)

    def setData(self, contributors: list[tuple[str, int]]):
        self.contributors = contributors[:5]
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        total = sum(count for _name, count in self.contributors)
        if total <= 0:
            painter.setPen(self.palette().color(QPalette.ColorRole.Text))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.tr("No contributors"))
            return

        side = min(self.width(), self.height()) - 28
        outer = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        start = 90 * 16
        painter.setPen(Qt.PenStyle.NoPen)
        for index, (_name, count) in enumerate(self.contributors):
            span = -round(360 * 16 * count / total)
            painter.setBrush(CHART_COLORS[index % len(CHART_COLORS)])
            painter.drawPie(outer, start, span)
            start += span

        holeSide = side * .42
        hole = QRectF((self.width() - holeSide) / 2, (self.height() - holeSide) / 2,
                      holeSide, holeSide)
        painter.setBrush(self.palette().color(QPalette.ColorRole.Base))
        painter.drawEllipse(hole)
