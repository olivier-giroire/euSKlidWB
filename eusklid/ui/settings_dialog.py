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

from PySide import QtCore, QtGui
from ..core.config import load_config, load_default_config, save_config, set_config
from ..core.i18n import tr


def make_spin(minv=0, maxv=9999, default=0):
    s = QtGui.QSpinBox()
    s.setRange(minv, maxv)
    s.setValue(default)
    s.setFixedWidth(56)
    return s


def make_color_btn():
    btn = QtGui.QPushButton()
    btn.setFixedSize(18, 18)
    btn.setToolTip(tr("Color"))

    def set_color(rgb):
        r, g, b = [int(max(0.0, min(1.0, c)) * 255) for c in rgb]
        btn.setStyleSheet("QPushButton { background-color: rgb(%d,%d,%d); border: 1px solid #555; border-radius: 9px; padding: 0px; }" % (r, g, b))
        btn._rgb = (r / 255.0, g / 255.0, b / 255.0)

    def pick():
        col = QtGui.QColorDialog.getColor()
        if col.isValid():
            set_color((col.red() / 255.0, col.green() / 255.0, col.blue() / 255.0))

    btn.clicked.connect(pick)
    set_color((1.0, 1.0, 1.0))
    return btn


def get_color(btn):
    return getattr(btn, "_rgb", (1.0, 1.0, 1.0))


def _set_color_btn(btn, rgb):
    btn._rgb = tuple(rgb)
    r, g, b = [int(max(0.0, min(1.0, c)) * 255) for c in btn._rgb]
    btn.setStyleSheet("QPushButton { background-color: rgb(%d,%d,%d); border: 1px solid #555; border-radius: 9px; padding: 0px; }" % (r, g, b))


def _refresh_existing_freecad_views():
    """Apply the current config to already visible FreeCAD objects/overlays."""
    try:
        import FreeCAD as App
        from ..feature import ensure_proxy
        from ..core.config import get_config

        cfg = get_config()
        c = cfg.get("construction", {}).get("lines", {})
        color = tuple(c.get("color", (1.0, 1.0, 1.0)))
        width = float(c.get("thickness", 2))
        alpha = int(c.get("alpha", 0))

        doc = App.ActiveDocument
        if doc is not None:
            for obj in getattr(doc, "Objects", []):
                try:
                    is_eusklid = False
                    proxy = getattr(obj, "Proxy", None)
                    if proxy is not None and proxy.__class__.__name__ == "euSKlidFeature":
                        is_eusklid = True
                    elif "SketchJson" in getattr(obj, "PropertiesList", []):
                        ensure_proxy(obj)
                        is_eusklid = True

                    if not is_eusklid:
                        continue

                    vo = getattr(obj, "ViewObject", None)
                    if vo is None:
                        continue
                    vo.LineColor = color
                    vo.PointColor = color
                    vo.ShapeColor = color
                    vo.LineWidth = width
                    vo.Transparency = alpha
                except Exception:
                    pass
    except Exception:
        pass

    try:
        from .. import indicator
        indicator.refresh_all_indicators()
    except Exception:
        pass

    try:
        from ..tools import path_tools
        path_tools.refresh_path_visuals()
    except Exception:
        pass


class SettingsDialog(QtGui.QDialog):
    def __init__(self, parent=None):
        super(SettingsDialog, self).__init__(parent)

        self.setWindowTitle(tr("euSKlid Settings"))
        self.setWindowModality(QtCore.Qt.NonModal)
        self.setModal(False)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        self.resize(620, 650)

        layout = QtGui.QVBoxLayout(self)

        self.tabs = QtGui.QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._build_gui_tab(), tr("GUI"))
        self.tabs.addTab(self._build_work_tab(), tr("Work"))
        self.tabs.addTab(self._build_export_tab(), tr("Export"))
        self.tabs.addTab(self._build_feeling_tab(), tr("Feeling"))

        btns = QtGui.QHBoxLayout()
        self.btn_reset = QtGui.QPushButton(tr("Reset"))
        self.btn_apply = QtGui.QPushButton(tr("Apply"))
        self.btn_ok = QtGui.QPushButton(tr("OK"))
        self.btn_cancel = QtGui.QPushButton(tr("Cancel"))

        btns.addWidget(self.btn_reset)
        btns.addStretch()
        btns.addWidget(self.btn_apply)
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        layout.addLayout(btns)

        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_ok.clicked.connect(self._on_ok)
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_cancel.clicked.connect(self.reject)

        self._load(load_config())

    def _style_row(self, form, label, color_attr, thick_attr, alpha_attr, thick_default=2, alpha_default=0):
        row = QtGui.QHBoxLayout()
        color = make_color_btn()
        thick = make_spin(0, 20, thick_default)
        alpha = make_spin(0, 100, alpha_default)

        setattr(self, color_attr, color)
        setattr(self, thick_attr, thick)
        setattr(self, alpha_attr, alpha)

        row.addWidget(color)
        row.addSpacing(8)
        row.addWidget(QtGui.QLabel(tr("Thickness")))
        row.addWidget(thick)
        row.addSpacing(10)
        row.addWidget(QtGui.QLabel(tr("Transparency")))
        row.addWidget(alpha)
        row.addStretch()
        form.addRow(tr(label), row)

    def _build_gui_tab(self):
        w = QtGui.QWidget()
        v = QtGui.QVBoxLayout(w)

        g_ar = QtGui.QGroupBox(tr("Direction Arrows"))
        f = QtGui.QFormLayout(g_ar)
        self.ar_color = make_color_btn()
        self.ar_alpha = make_spin(0, 100, 30)
        self.ar_thick = make_spin(0, 20, 5)
        self.ar_len = make_spin(0, 500, 60)
        self.ar_arrow = make_spin(0, 100, 10)
        self.ar_step = make_spin(0, 200, 30)
        self.ar_count = make_spin(0, 100, 15)
        f.addRow(tr("Color"), self.ar_color)
        f.addRow(tr("Transparency"), self.ar_alpha)
        f.addRow(tr("Thickness"), self.ar_thick)
        f.addRow(tr("Length"), self.ar_len)
        f.addRow(tr("Arrow size"), self.ar_arrow)
        f.addRow(tr("Step"), self.ar_step)
        f.addRow(tr("Count"), self.ar_count)

        g_pt = QtGui.QGroupBox(tr("Points"))
        f = QtGui.QFormLayout(g_pt)
        self.pt_size = make_spin(0, 200, 20)
        self.pt_alpha = make_spin(0, 100, 30)
        self.pt_sel = make_color_btn()
        self.pt_snap = make_color_btn()
        self.pt_fixed = make_color_btn()
        self.pt_hover = make_color_btn()
        self.pt_marker = make_color_btn()
        f.addRow(tr("Size"), self.pt_size)
        f.addRow(tr("Transparency"), self.pt_alpha)
        f.addRow(tr("Selected"), self.pt_sel)
        f.addRow(tr("Snap"), self.pt_snap)
        f.addRow(tr("Fixed"), self.pt_fixed)
        f.addRow(tr("Hover"), self.pt_hover)
        f.addRow(tr("Markers"), self.pt_marker)

        v.addWidget(g_ar)
        v.addWidget(g_pt)
        v.addStretch()
        return w

    def _build_work_tab(self):
        w = QtGui.QWidget()
        v = QtGui.QVBoxLayout(w)

        g_construction = QtGui.QGroupBox(tr("Construction"))
        f = QtGui.QFormLayout(g_construction)
        self._style_row(f, "Primitives", "c_line_color", "c_line_thick", "c_line_alpha", 2, 0)
        self._style_row(f, "Highlight", "h_color", "h_thick", "h_alpha", 3, 40)
        self._style_row(f, "Preview", "pr_color", "pr_thick", "pr_alpha", 2, 70)

        g_path = QtGui.QGroupBox(tr("Path"))
        f = QtGui.QFormLayout(g_path)
        self._style_row(f, "Current path", "p_cur", "p_cur_thick", "p_cur_alpha", 5, 0)
        self._style_row(f, "Candidate path", "p_cand", "p_cand_thick", "p_cand_alpha", 3, 0)
        self._style_row(f, "Closed path", "p_closed", "p_closed_thick", "p_closed_alpha", 6, 0)
        self._style_row(f, "Geometric overloads", "p_overload", "p_overload_thick", "p_overload_alpha", 8, 20)

        v.addWidget(g_construction)
        v.addWidget(g_path)
        v.addStretch()
        return w

    def _build_export_tab(self):
        w = QtGui.QWidget()
        v = QtGui.QVBoxLayout(w)

        g_sym = QtGui.QGroupBox(tr("Symmetry constraints"))
        f = QtGui.QFormLayout(g_sym)

        self.export_axial_symmetry_y = QtGui.QCheckBox()
        self.export_axial_symmetry_y.setToolTip(tr("Detect point symmetry about the sketch Y axis during Path export"))

        self.export_axial_symmetry_x = QtGui.QCheckBox()
        self.export_axial_symmetry_x.setToolTip(tr("Detect point symmetry about the sketch X axis during Path export"))

        self.export_central_symmetry = QtGui.QCheckBox()
        self.export_central_symmetry.setToolTip(tr("Detect point symmetry about the sketch origin during Path export"))

        self.export_arbitrary_symmetry_axes = QtGui.QCheckBox()
        self.export_arbitrary_symmetry_axes.setToolTip(tr("Detect non-axis-aligned symmetry axes during Path export"))

        self.export_arbitrary_symmetry_centers = QtGui.QCheckBox()
        self.export_arbitrary_symmetry_centers.setToolTip(tr("Detect arbitrary symmetry centers during Path export"))

        self.export_symmetry_min_score = make_spin(3, 99, 4)
        self.export_symmetry_min_score.setToolTip(tr("Minimum number of symmetric point pairs required to accept an arbitrary symmetry"))

        self.export_reduce_redundant_constraints = QtGui.QCheckBox()
        self.export_reduce_redundant_constraints.setToolTip(tr("Try to remove redundant exported constraints after solving, without changing the sketch degrees of freedom"))

        f.addRow(tr("Axial symmetry Y export"), self.export_axial_symmetry_y)
        f.addRow(tr("Axial symmetry X export"), self.export_axial_symmetry_x)
        f.addRow(tr("Central symmetry export"), self.export_central_symmetry)
        f.addRow(tr("Detect arbitrary symmetry axes"), self.export_arbitrary_symmetry_axes)
        f.addRow(tr("Detect arbitrary symmetry centers"), self.export_arbitrary_symmetry_centers)
        f.addRow(tr("Minimum symmetry score"), self.export_symmetry_min_score)
        f.addRow(tr("Reduce redundant constraints"), self.export_reduce_redundant_constraints)

        v.addWidget(g_sym)
        v.addStretch()
        return w

    def _build_feeling_tab(self):
        w = QtGui.QWidget()
        f = QtGui.QFormLayout(w)
        self.snap_thresh = make_spin(0, 200, 20)
        self.autogrid = QtGui.QComboBox()
        self.autogrid.addItems(["off", "cm", "mm", "0.1mm"])
        self.refresh_interval = make_spin(50, 2000, 120)
        self.function_reentrance = QtGui.QCheckBox()
        self.console_messages = QtGui.QCheckBox()
        self.help_messages = QtGui.QCheckBox()
        f.addRow(tr("Snap threshold (px)"), self.snap_thresh)
        f.addRow(tr("Autogrid"), self.autogrid)
        f.addRow(tr("Refresh interval (ms)"), self.refresh_interval)
        f.addRow(tr("Function reentrance"), self.function_reentrance)
        f.addRow(tr("Console messages"), self.console_messages)
        f.addRow(tr("Help messages"), self.help_messages)
        return w

    def _on_apply(self):
        cfg = self._collect()
        save_config(cfg)
        set_config(cfg)

        _refresh_existing_freecad_views()

        try:
            import FreeCAD as App
            if App.ActiveDocument is not None:
                App.ActiveDocument.recompute()
        except Exception:
            pass

        try:
            import FreeCADGui as Gui
            Gui.updateGui()
            if Gui.ActiveDocument is not None:
                try:
                    Gui.ActiveDocument.ActiveView.redraw()
                except Exception:
                    pass
        except Exception:
            pass

    def _on_ok(self):
        self._on_apply()
        self.accept()

    def _on_reset(self):
        self._load(load_default_config())

    def _collect(self):
        construction_style = {
            "color": get_color(self.c_line_color),
            "thickness": self.c_line_thick.value(),
            "alpha": self.c_line_alpha.value(),
        }
        return {
            "gui": {
                "arrows": {
                    "color": get_color(self.ar_color),
                    "alpha": self.ar_alpha.value(),
                    "thickness": self.ar_thick.value(),
                    "length": self.ar_len.value(),
                    "arrow_size": self.ar_arrow.value(),
                    "step": self.ar_step.value(),
                    "count": self.ar_count.value()
                },
                "points": {
                    "size": self.pt_size.value(),
                    "alpha": self.pt_alpha.value(),
                    "colors": {
                        "selected": get_color(self.pt_sel),
                        "snap": get_color(self.pt_snap),
                        "fixed": get_color(self.pt_fixed),
                        "hover": get_color(self.pt_hover),
                        "marker": get_color(self.pt_marker)
                    }
                }
            },
            "construction": {
                "lines": dict(construction_style),
                "circles": dict(construction_style),
                "grids": dict(construction_style),
                "polygons": dict(construction_style),
            },
            "highlight": {
                "color": get_color(self.h_color),
                "thickness": self.h_thick.value(),
                "alpha": self.h_alpha.value()
            },
            "preview": {
                "color": get_color(self.pr_color),
                "thickness": self.pr_thick.value(),
                "alpha": self.pr_alpha.value()
            },
            "path": {
                "current": {
                    "color": get_color(self.p_cur),
                    "thickness": self.p_cur_thick.value(),
                    "alpha": self.p_cur_alpha.value()
                },
                "candidate": {
                    "color": get_color(self.p_cand),
                    "thickness": self.p_cand_thick.value(),
                    "alpha": self.p_cand_alpha.value()
                },
                "closed": {
                    "color": get_color(self.p_closed),
                    "thickness": self.p_closed_thick.value(),
                    "alpha": self.p_closed_alpha.value()
                },
                "overload": {
                    "color": get_color(self.p_overload),
                    "thickness": self.p_overload_thick.value(),
                    "alpha": self.p_overload_alpha.value(),
                    "point_size": max(1, int(self.p_overload_thick.value()))
                }
            },
            "export": {
                "axial_symmetry_y": self.export_axial_symmetry_y.isChecked(),
                "axial_symmetry_x": self.export_axial_symmetry_x.isChecked(),
                "central_symmetry": self.export_central_symmetry.isChecked(),
                "arbitrary_symmetry_axes": self.export_arbitrary_symmetry_axes.isChecked(),
                "arbitrary_symmetry_centers": self.export_arbitrary_symmetry_centers.isChecked(),
                "symmetry_min_score": max(3, int(self.export_symmetry_min_score.value())),
                "reduce_redundant_constraints": self.export_reduce_redundant_constraints.isChecked()
            },
            "feeling": {
                "snap_threshold": self.snap_thresh.value(),
                "autogrid": self.autogrid.currentText(),
                "refresh_interval_ms": self.refresh_interval.value(),
                "function_reentrance": self.function_reentrance.isChecked(),
                "console_messages": self.console_messages.isChecked(),
                "help_messages": self.help_messages.isChecked()
            }
        }

    def _load(self, cfg):
        try:
            _set_color_btn(self.ar_color, cfg["gui"]["arrows"]["color"])
            self.ar_alpha.setValue(cfg["gui"]["arrows"]["alpha"])
            self.ar_thick.setValue(cfg["gui"]["arrows"].get("thickness", 5))
            self.ar_len.setValue(cfg["gui"]["arrows"].get("length", 60))
            self.ar_arrow.setValue(cfg["gui"]["arrows"].get("arrow_size", 10))
            self.ar_step.setValue(cfg["gui"]["arrows"].get("step", 30))
            self.ar_count.setValue(cfg["gui"]["arrows"].get("count", 15))

            self.pt_size.setValue(cfg["gui"]["points"].get("size", 20))
            self.pt_alpha.setValue(cfg["gui"]["points"].get("alpha", 30))
            colors = cfg["gui"]["points"].get("colors", {})
            _set_color_btn(self.pt_sel, colors.get("selected", (0.2, 0.4, 1.0)))
            _set_color_btn(self.pt_snap, colors.get("snap", (0.2, 1.0, 0.2)))
            _set_color_btn(self.pt_fixed, colors.get("fixed", (1.0, 1.0, 0.0)))
            _set_color_btn(self.pt_hover, colors.get("hover", (1.0, 0.0, 1.0)))
            _set_color_btn(self.pt_marker, colors.get("marker", (1.0, 0.5, 0.0)))

            c = cfg.get("construction", {}).get("lines", {})
            _set_color_btn(self.c_line_color, c.get("color", (1.0, 1.0, 1.0)))
            self.c_line_thick.setValue(c.get("thickness", 2))
            self.c_line_alpha.setValue(c.get("alpha", 0))

            h = cfg.get("highlight", {})
            _set_color_btn(self.h_color, h.get("color", (1.0, 0.8, 0.1)))
            self.h_thick.setValue(h.get("thickness", 3))
            self.h_alpha.setValue(h.get("alpha", 40))

            pvw = cfg.get("preview", {})
            _set_color_btn(self.pr_color, pvw.get("color", (0.1, 0.4, 1.0)))
            self.pr_thick.setValue(pvw.get("thickness", 2))
            self.pr_alpha.setValue(pvw.get("alpha", 70))

            p = cfg.get("path", {})
            cur = p.get("current", {})
            _set_color_btn(self.p_cur, cur.get("color", (1.0, 0.5, 0.0)))
            self.p_cur_thick.setValue(cur.get("thickness", 5))
            self.p_cur_alpha.setValue(cur.get("alpha", 0))

            cand = p.get("candidate", {})
            _set_color_btn(self.p_cand, cand.get("color", (0.6, 1.0, 0.6)))
            self.p_cand_thick.setValue(cand.get("thickness", 3))
            self.p_cand_alpha.setValue(cand.get("alpha", 0))

            closed = p.get("closed", {})
            _set_color_btn(self.p_closed, closed.get("color", (0.0, 0.45, 0.0)))
            self.p_closed_thick.setValue(closed.get("thickness", 6))
            self.p_closed_alpha.setValue(closed.get("alpha", 0))

            overload = p.get("overload", {})
            _set_color_btn(self.p_overload, overload.get("color", (1.0, 0.55, 0.55)))
            self.p_overload_thick.setValue(overload.get("thickness", 8))
            self.p_overload_alpha.setValue(overload.get("alpha", 20))

            self.snap_thresh.setValue(cfg["feeling"].get("snap_threshold", 20))
            self.refresh_interval.setValue(cfg["feeling"].get("refresh_interval_ms", 120))
            self.function_reentrance.setChecked(bool(cfg["feeling"].get("function_reentrance", True)))
            export_cfg = cfg.get("export", {})
            self.export_axial_symmetry_y.setChecked(bool(export_cfg.get("axial_symmetry_y", True)))
            self.export_axial_symmetry_x.setChecked(bool(export_cfg.get("axial_symmetry_x", True)))
            self.export_central_symmetry.setChecked(bool(export_cfg.get("central_symmetry", False)))
            self.export_arbitrary_symmetry_axes.setChecked(bool(export_cfg.get("arbitrary_symmetry_axes", False)))
            self.export_arbitrary_symmetry_centers.setChecked(bool(export_cfg.get("arbitrary_symmetry_centers", False)))
            self.export_symmetry_min_score.setValue(max(3, int(export_cfg.get("symmetry_min_score", 4))))
            self.export_reduce_redundant_constraints.setChecked(bool(export_cfg.get("reduce_redundant_constraints", False)))
            self.console_messages.setChecked(bool(cfg["feeling"].get("console_messages", False)))
            self.help_messages.setChecked(bool(cfg["feeling"].get("help_messages", False)))
            idx = self.autogrid.findText(cfg["feeling"].get("autogrid", cfg["feeling"].get("autocorrect", "off")))
            if idx >= 0:
                self.autogrid.setCurrentIndex(idx)
        except Exception:
            pass

_settings_dialog = None


def _freecad_main_window():
    try:
        import FreeCADGui as Gui
        return Gui.getMainWindow()
    except Exception:
        return None


def show_settings_dialog():
    """Show the settings dialog as a non-modal child of FreeCAD's main window."""
    global _settings_dialog

    if _settings_dialog is None:
        _settings_dialog = SettingsDialog(parent=_freecad_main_window())
        _settings_dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)

    _settings_dialog.show()
    _settings_dialog.raise_()
    _settings_dialog.activateWindow()
    return _settings_dialog
