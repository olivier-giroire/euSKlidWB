# SPDX-License-Identifier: LGPL-2.1-or-later
#
# euSKlidWB - FreeCAD Workbench
# Copyright (C) 2026 Olivier Giroire
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

from .qt_compat import QtCore, QtWidgets
from .utils import parse_distance_series
from .core.i18n import tr


def _freecad_main_window():
    try:
        import FreeCADGui as Gui
        return Gui.getMainWindow()
    except Exception:
        return None


class DistanceSeriesDialog(QtWidgets.QDialog):
    """Non-modal editor for Series //Ref distances with live preview callbacks."""

    def __init__(self, title, parent=None, on_preview=None, on_accept=None, on_cancel=None):
        super(DistanceSeriesDialog, self).__init__(parent)
        self._on_preview = on_preview
        self._on_accept = on_accept
        self._on_cancel = on_cancel
        self._last_valid_values = None
        self._closed_by_accept = False

        self.setWindowTitle(tr("euSKlid") + " - " + tr("Series ∥/Ref"))
        self.setWindowModality(QtCore.Qt.NonModal)
        self.setModal(False)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        self.resize(560, 260)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(title))

        self.text = QtWidgets.QPlainTextEdit()
        self.text.setPlainText("")
        self.text.setPlaceholderText("")
        layout.addWidget(self.text, 1)

        self.status = QtWidgets.QLabel("")
        layout.addWidget(self.status)

        help_label = QtWidgets.QLabel(tr("Examples:\n30,33,40,43\nrepeat 13 (0,1) origin 0 step 2.5\nrepeat 13 (0,1) org 0 step 2.5, repeat 6 (0,2) o 40 s 8"))
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_values)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(80)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self.text.textChanged.connect(self._schedule_preview)
        QtCore.QTimer.singleShot(0, self._refresh_preview)

    def _schedule_preview(self):
        self._preview_timer.start()

    def _parse(self):
        return parse_distance_series(self.text.toPlainText())

    def _refresh_preview(self):
        try:
            values = self._parse()
            self._last_valid_values = values
            self.status.setText(tr("Preview: %d line(s)") % len(values))
            if self._on_preview:
                self._on_preview(values)
        except Exception as exc:
            self._last_valid_values = None
            self.status.setText(tr("Invalid distance series: ") + str(exc))
            if self._on_preview:
                self._on_preview(None)

    def _accept_values(self):
        try:
            values = self._parse()
        except Exception:
            QtWidgets.QMessageBox.warning(
                self,
                tr("euSKlid"),
                tr("Invalid distance series.\nExamples:\n30,33,40,43\nrepeat 13 (0,1) origin 0 step 2.5"),
            )
            return
        self._closed_by_accept = True
        if self._on_accept:
            self._on_accept(values)
        self.accept()

    def reject(self):
        if not self._closed_by_accept and self._on_cancel:
            self._on_cancel()
        super(DistanceSeriesDialog, self).reject()


def ask_distance_series(title, on_preview=None, on_accept=None, on_cancel=None):
    if on_preview is not None or on_accept is not None or on_cancel is not None:
        dlg = DistanceSeriesDialog(
            title,
            parent=_freecad_main_window(),
            on_preview=on_preview,
            on_accept=on_accept,
            on_cancel=on_cancel,
        )
        dlg.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

    text, ok = QtWidgets.QInputDialog.getText(None, tr("euSKlid"), title)
    if not ok:
        return None
    try:
        return parse_distance_series(text)
    except Exception:
        QtWidgets.QMessageBox.warning(None, tr("euSKlid"), tr("Invalid distance series.\nExamples:\n30,33,40,43\nrepeat 13 (0,1) origin 0 step 2.5"))
        return None


def ask_radius(title, default=10.0):
    value, ok = QtWidgets.QInputDialog.getDouble(None, tr("euSKlid"), title, default, 0.0, 1e9, 6)
    return value if ok else None


def choose_solution(title, labels):
    item, ok = QtWidgets.QInputDialog.getItem(None, tr("euSKlid"), title, labels, 0, False)
    return labels.index(item) if ok else None



_LIVE_DIALOGS = []


def _remember_live_dialog(dlg):
    try:
        _LIVE_DIALOGS.append(dlg)
        dlg.destroyed.connect(lambda *_args, d=dlg: _forget_live_dialog(d))
    except Exception:
        pass
    return dlg


def _forget_live_dialog(dlg):
    try:
        if dlg in _LIVE_DIALOGS:
            _LIVE_DIALOGS.remove(dlg)
    except Exception:
        pass


def _show_live_dialog(dlg):
    try:
        dlg.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
    except Exception:
        pass
    dlg.show()
    try:
        dlg.raise_()
        dlg.activateWindow()
    except Exception:
        pass
    return _remember_live_dialog(dlg)


class GridParametersDialog(QtWidgets.QDialog):
    """Non-modal grid parameter editor with live preview callbacks."""

    def __init__(self, parent=None, on_preview=None, on_accept=None, on_cancel=None):
        super(GridParametersDialog, self).__init__(parent)
        self._on_preview = on_preview
        self._on_accept = on_accept
        self._on_cancel = on_cancel
        self._closed_by_accept = False
        self._rows = []

        self.setWindowTitle(tr("euSKlid") + " - " + tr("Grid"))
        self.setWindowModality(QtCore.Qt.NonModal)
        self.setModal(False)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        self.resize(640, 260)

        layout = QtWidgets.QVBoxLayout(self)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel(tr("NB series")))
        self.nb = QtWidgets.QSpinBox()
        self.nb.setRange(2, 6)
        self.nb.setValue(2)
        top.addWidget(self.nb)
        top.addStretch(1)
        layout.addLayout(top)

        self.rows_container = QtWidgets.QWidget()
        self.rows_layout = QtWidgets.QFormLayout(self.rows_container)
        layout.addWidget(self.rows_container)

        self.status = QtWidgets.QLabel("")
        layout.addWidget(self.status)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_values)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(80)
        self._preview_timer.timeout.connect(self._refresh_preview)

        self.nb.valueChanged.connect(self._rebuild_rows)
        self._rebuild_rows(self.nb.value())
        QtCore.QTimer.singleShot(0, self._refresh_preview)

    def _schedule_preview(self):
        self._preview_timer.start()

    def _rebuild_rows(self, n):
        while self.rows_layout.rowCount():
            self.rows_layout.removeRow(0)
        self._rows = []
        labels = "ABCDEF"
        for i in range(int(n)):
            roww = QtWidgets.QWidget()
            rowl = QtWidgets.QHBoxLayout(roww)
            rowl.setContentsMargins(0, 0, 0, 0)

            step = QtWidgets.QDoubleSpinBox()
            step.setDecimals(6)
            step.setRange(0.000001, 1e9)
            step.setValue(10.0)

            angle = QtWidgets.QDoubleSpinBox()
            angle.setDecimals(6)
            angle.setRange(-360.0, 360.0)
            angle.setValue(0.0 if i == 0 else 90.0 if i == 1 else 0.0)

            count = QtWidgets.QSpinBox()
            count.setRange(1, 999)
            count.setValue(11)

            rowl.addWidget(QtWidgets.QLabel(f"{labels[i]} " + tr("count")))
            rowl.addWidget(count)
            rowl.addSpacing(12)
            rowl.addWidget(QtWidgets.QLabel(f"{labels[i]} " + tr("step")))
            rowl.addWidget(step)
            rowl.addSpacing(12)
            rowl.addWidget(QtWidgets.QLabel(f"{labels[i]} " + tr("angle")))
            rowl.addWidget(angle)
            rowl.addStretch(1)
            self.rows_layout.addRow(roww)
            self._rows.append((count, step, angle))

            count.valueChanged.connect(self._schedule_preview)
            step.valueChanged.connect(self._schedule_preview)
            angle.valueChanged.connect(self._schedule_preview)

        self._schedule_preview()

    def values(self):
        series = []
        labels = "ABCDEF"
        for i, (count, step, angle) in enumerate(self._rows):
            series.append({
                "name": labels[i],
                "count": int(count.value()),
                "step": float(step.value()),
                "angle": float(angle.value()),
            })
        return {
            "nb_series": int(self.nb.value()),
            "series": series,
        }

    def _refresh_preview(self):
        try:
            params = self.values()
            total = sum(int(s.get("count", 0)) for s in params.get("series", []))
            self.status.setText(tr("Preview: %d line(s)") % total)
            if self._on_preview:
                self._on_preview(params)
        except Exception as exc:
            self.status.setText(tr("Invalid grid parameters: ") + str(exc))
            if self._on_preview:
                self._on_preview(None)

    def _accept_values(self):
        try:
            params = self.values()
        except Exception:
            QtWidgets.QMessageBox.warning(self, tr("euSKlid"), tr("Invalid grid parameters."))
            return
        self._closed_by_accept = True
        if self._on_accept:
            self._on_accept(params)
        self.accept()

    def reject(self):
        if not self._closed_by_accept and self._on_cancel:
            self._on_cancel()
        super(GridParametersDialog, self).reject()


def ask_grid_parameters(on_preview=None, on_accept=None, on_cancel=None):
    if on_preview is not None or on_accept is not None or on_cancel is not None:
        dlg = GridParametersDialog(
            parent=_freecad_main_window(),
            on_preview=on_preview,
            on_accept=on_accept,
            on_cancel=on_cancel,
        )
        return _show_live_dialog(dlg)

    dlg = GridParametersDialog(parent=_freecad_main_window())
    if dlg.exec_():
        return dlg.values()
    return None


def _parse_angle_series_text(text):
    return [
        float(x)
        for x in str(text).replace(",", " ").split()
        if x.strip()
    ]


class AngleSeriesDialog(QtWidgets.QDialog):
    """Non-modal editor for Ref/Pt/Angle series with live preview callbacks."""

    def __init__(self, title=None, parent=None, on_preview=None, on_accept=None, on_cancel=None):
        super(AngleSeriesDialog, self).__init__(parent)
        self._on_preview = on_preview
        self._on_accept = on_accept
        self._on_cancel = on_cancel
        self._closed_by_accept = False
        self._last_valid_values = None

        self.setWindowTitle(tr("euSKlid") + " - " + (title or tr("Series Ref, Pt, Angle")))
        self.setWindowModality(QtCore.Qt.NonModal)
        self.setModal(False)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        self.resize(460, 180)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(tr("Angles in degrees, trigonometric direction, separated by spaces or commas:")))

        self.text = QtWidgets.QLineEdit()
        self.text.setText("")
        self.text.setPlaceholderText("")
        layout.addWidget(self.text)

        self.status = QtWidgets.QLabel("")
        layout.addWidget(self.status)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_values)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(80)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self.text.textChanged.connect(self._schedule_preview)
        QtCore.QTimer.singleShot(0, self._refresh_preview)

    def _schedule_preview(self):
        self._preview_timer.start()

    def _parse(self):
        return _parse_angle_series_text(self.text.text())

    def _refresh_preview(self):
        try:
            values = self._parse()
            self._last_valid_values = values
            self.status.setText(tr("Preview: %d line(s)") % len(values))
            if self._on_preview:
                self._on_preview(values)
        except Exception as exc:
            self._last_valid_values = None
            self.status.setText(tr("Invalid angle series: ") + str(exc))
            if self._on_preview:
                self._on_preview(None)

    def _accept_values(self):
        try:
            values = self._parse()
        except Exception:
            QtWidgets.QMessageBox.warning(
                self,
                tr("euSKlid"),
                tr("Invalid angle series. Examples:\n0 30 45 90\n0, 30, 45, 90"),
            )
            return
        self._closed_by_accept = True
        if self._on_accept:
            self._on_accept(values)
        self.accept()

    def reject(self):
        if not self._closed_by_accept and self._on_cancel:
            self._on_cancel()
        super(AngleSeriesDialog, self).reject()


def ask_angle_series(title=None, on_preview=None, on_accept=None, on_cancel=None):
    title = title or tr("Series Ref, Pt, Angle")
    if on_preview is not None or on_accept is not None or on_cancel is not None:
        dlg = AngleSeriesDialog(
            title=title,
            parent=_freecad_main_window(),
            on_preview=on_preview,
            on_accept=on_accept,
            on_cancel=on_cancel,
        )
        return _show_live_dialog(dlg)

    text, ok = QtWidgets.QInputDialog.getText(
        None,
        title,
        tr("Angles in degrees, trigonometric direction, separated by spaces or commas:"),
    )
    if not ok:
        return None
    try:
        return _parse_angle_series_text(text)
    except Exception:
        QtWidgets.QMessageBox.warning(
            None,
            tr("euSKlid"),
            tr("Invalid angle series. Examples:\n0 30 45 90\n0, 30, 45, 90"),
        )
        return None
