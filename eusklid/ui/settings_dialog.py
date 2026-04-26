from PySide import QtGui
from ..core.config import load_config, load_default_config, save_config, set_config
from ..core.i18n import tr


def make_spin(minv=0, maxv=9999, default=0):
    s = QtGui.QSpinBox()
    s.setRange(minv, maxv)
    s.setValue(default)
    return s


def make_color_btn():
    btn = QtGui.QPushButton()
    btn.setFixedWidth(50)

    def set_color(rgb):
        r, g, b = [int(max(0.0, min(1.0, c)) * 255) for c in rgb]
        btn.setStyleSheet("background-color: rgb(%d,%d,%d);" % (r, g, b))
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


class SettingsDialog(QtGui.QDialog):
    def __init__(self, parent=None):
        super(SettingsDialog, self).__init__(parent)

        self.setWindowTitle(tr("euSKlid Settings"))
        self.resize(520, 650)

        layout = QtGui.QVBoxLayout(self)

        self.tabs = QtGui.QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._build_gui_tab(), tr("GUI"))
        self.tabs.addTab(self._build_work_tab(), tr("Work"))
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
        self.c_line_color = make_color_btn()
        self.c_line_thick = make_spin(0, 20, 2)
        self.c_line_alpha = make_spin(0, 100, 0)
        f.addRow(tr("Color"), self.c_line_color)
        f.addRow(tr("Thickness"), self.c_line_thick)
        f.addRow(tr("Transparency"), self.c_line_alpha)

        g_highlight = QtGui.QGroupBox(tr("Highlight"))
        f = QtGui.QFormLayout(g_highlight)
        self.h_color = make_color_btn()
        self.h_thick = make_spin(0, 20, 3)
        self.h_alpha = make_spin(0, 100, 40)
        f.addRow(tr("Color"), self.h_color)
        f.addRow(tr("Thickness"), self.h_thick)
        f.addRow(tr("Transparency"), self.h_alpha)

        g_path = QtGui.QGroupBox(tr("Path"))
        v_path = QtGui.QVBoxLayout(g_path)

        g_cur = QtGui.QGroupBox(tr("Current path"))
        f = QtGui.QFormLayout(g_cur)
        self.p_cur = make_color_btn()
        self.p_cur_thick = make_spin(0, 20, 5)
        self.p_cur_alpha = make_spin(0, 100, 0)
        f.addRow(tr("Color"), self.p_cur)
        f.addRow(tr("Thickness"), self.p_cur_thick)
        f.addRow(tr("Transparency"), self.p_cur_alpha)

        g_cand = QtGui.QGroupBox(tr("Candidate path"))
        f = QtGui.QFormLayout(g_cand)
        self.p_cand = make_color_btn()
        self.p_cand_thick = make_spin(0, 20, 3)
        self.p_cand_alpha = make_spin(0, 100, 0)
        f.addRow(tr("Color"), self.p_cand)
        f.addRow(tr("Thickness"), self.p_cand_thick)
        f.addRow(tr("Transparency"), self.p_cand_alpha)

        g_closed = QtGui.QGroupBox(tr("Closed path"))
        f = QtGui.QFormLayout(g_closed)
        self.p_closed = make_color_btn()
        self.p_closed_thick = make_spin(0, 20, 6)
        self.p_closed_alpha = make_spin(0, 100, 0)
        f.addRow(tr("Color"), self.p_closed)
        f.addRow(tr("Thickness"), self.p_closed_thick)
        f.addRow(tr("Transparency"), self.p_closed_alpha)

        v_path.addWidget(g_cur)
        v_path.addWidget(g_cand)
        v_path.addWidget(g_closed)

        v.addWidget(g_construction)
        v.addWidget(g_highlight)
        v.addWidget(g_path)
        v.addStretch()
        return w

    def _build_feeling_tab(self):
        w = QtGui.QWidget()
        f = QtGui.QFormLayout(w)
        self.snap_thresh = make_spin(0, 200, 20)
        self.autogrid = QtGui.QComboBox()
        self.autogrid.addItems(["off", "cm", "mm", "0.1mm"])
        self.refresh_interval = make_spin(50, 2000, 120)
        self.console_messages = QtGui.QCheckBox()
        self.help_messages = QtGui.QCheckBox()
        f.addRow(tr("Snap threshold (px)"), self.snap_thresh)
        f.addRow(tr("Autogrid"), self.autogrid)
        f.addRow(tr("Refresh interval (ms)"), self.refresh_interval)
        f.addRow(tr("Console messages"), self.console_messages)
        f.addRow(tr("Help messages"), self.help_messages)
        return w

    def _on_apply(self):
        cfg = self._collect()
        save_config(cfg)
        set_config(cfg)

        try:
            import FreeCAD as App
            import FreeCADGui as Gui

            if App.ActiveDocument is not None:
                App.ActiveDocument.recompute()

            Gui.updateGui()

            if Gui.ActiveDocument is not None:
                try:
                    Gui.ActiveDocument.ActiveView.redraw()
                except Exception:
                    pass

            try:
                from .. import indicator
                if hasattr(indicator, "refresh_all_indicators"):
                    indicator.refresh_all_indicators()
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
                "lines": {
                    "color": get_color(self.c_line_color),
                    "thickness": self.c_line_thick.value(),
                    "alpha": self.c_line_alpha.value()
                },
                "circles": {
                    "color": get_color(self.c_line_color),
                    "thickness": self.c_line_thick.value(),
                    "alpha": self.c_line_alpha.value()
                },
                "grids": {
                    "color": get_color(self.c_line_color),
                    "thickness": self.c_line_thick.value(),
                    "alpha": self.c_line_alpha.value()
                },
                "polygons": {
                    "color": get_color(self.c_line_color),
                    "thickness": self.c_line_thick.value(),
                    "alpha": self.c_line_alpha.value()
                }
            },
            "highlight": {
                "color": get_color(self.h_color),
                "thickness": self.h_thick.value(),
                "alpha": self.h_alpha.value()
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
                }
            },
            "feeling": {
                "snap_threshold": self.snap_thresh.value(),
                "autogrid": self.autogrid.currentText(),
                "refresh_interval_ms": self.refresh_interval.value(),
                "console_messages": self.console_messages.isChecked(),
                "help_messages": self.help_messages.isChecked()
            }
        }

    def _load(self, cfg):
        try:

            self.ar_color._rgb = tuple(cfg["gui"]["arrows"]["color"])
            self.ar_alpha.setValue(cfg["gui"]["arrows"]["alpha"])
            self.ar_thick.setValue(cfg["gui"]["arrows"]["thickness"])
            self.ar_len.setValue(cfg["gui"]["arrows"]["length"])
            self.ar_arrow.setValue(cfg["gui"]["arrows"]["arrow_size"])
            self.ar_step.setValue(cfg["gui"]["arrows"]["step"])
            self.ar_count.setValue(cfg["gui"]["arrows"]["count"])

            self.pt_size.setValue(cfg["gui"]["points"]["size"])
            self.pt_alpha.setValue(cfg["gui"]["points"]["alpha"])
            self.pt_sel._rgb = tuple(cfg["gui"]["points"]["colors"]["selected"])
            self.pt_snap._rgb = tuple(cfg["gui"]["points"]["colors"]["snap"])
            self.pt_fixed._rgb = tuple(cfg["gui"]["points"]["colors"]["fixed"])
            self.pt_hover._rgb = tuple(cfg["gui"]["points"]["colors"]["hover"])
            self.pt_marker._rgb = tuple(cfg["gui"]["points"]["colors"]["marker"])

            self.c_line_color._rgb = tuple(cfg["construction"]["lines"]["color"])
            self.c_line_thick.setValue(cfg["construction"]["lines"].get("thickness", 2))
            self.c_line_alpha.setValue(cfg["construction"]["lines"].get("alpha", 0))

            hcfg = cfg.get("work", {}).get("highlight", cfg.get("highlight", {}))
            self.h_color._rgb = tuple(hcfg.get("color", (1.0, 0.8, 0.1)))
            self.h_thick.setValue(hcfg.get("thickness", 3))
            self.h_alpha.setValue(hcfg.get("alpha", 40))

            self.p_cur._rgb = tuple(cfg["path"]["current"]["color"])
            self.p_cur_thick.setValue(cfg["path"]["current"].get("thickness", 5))
            self.p_cur_alpha.setValue(cfg["path"]["current"].get("alpha", 0))

            self.p_cand._rgb = tuple(cfg["path"]["candidate"]["color"])
            self.p_cand_thick.setValue(cfg["path"]["candidate"].get("thickness", 3))
            self.p_cand_alpha.setValue(cfg["path"]["candidate"].get("alpha", 0))

            self.p_closed._rgb = tuple(cfg["path"]["closed"]["color"])
            self.p_closed_thick.setValue(cfg["path"]["closed"].get("thickness", 6))
            self.p_closed_alpha.setValue(cfg["path"]["closed"].get("alpha", 0))

            self.snap_thresh.setValue(cfg["feeling"]["snap_threshold"])
            self.refresh_interval.setValue(cfg["feeling"].get("refresh_interval_ms", 120))
            self.console_messages.setChecked(bool(cfg["feeling"].get("console_messages", False)))
            self.help_messages.setChecked(bool(cfg["feeling"].get("help_messages", False)))
            idx = self.autogrid.findText(cfg["feeling"].get("autogrid", cfg["feeling"].get("autocorrect", "off")))
            if idx >= 0:
                self.autogrid.setCurrentIndex(idx)

            for btn in [
                self.ar_color, self.pt_sel, self.pt_snap, self.pt_fixed,
                self.pt_hover, self.pt_marker, self.c_line_color, self.h_color,
                self.p_cur, self.p_cand, self.p_closed
            ]:
                r, g, b = [int(c * 255) for c in btn._rgb]
                btn.setStyleSheet("background-color: rgb(%d,%d,%d);" % (r, g, b))
        except Exception:
            pass
