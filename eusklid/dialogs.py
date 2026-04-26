from .qt_compat import QtWidgets, QtCore
from .plane import SketchPlane
from .utils import parse_distance_series
from .core.i18n import tr

def ask_three_points_plane():
    return SketchPlane.XY()

def ask_distance_series(title):
    text, ok = QtWidgets.QInputDialog.getText(None,tr("euSKlid"),title)
    if not ok:
        return None
    try:
        return parse_distance_series(text)
    except Exception:
        QtWidgets.QMessageBox.warning(None,tr("euSKlid"),tr("Invalid distance series.\nExamples:\n30,33,40,43\nrepeat 13 (0,1) origin 0 step 2.5"))
        return None

def ask_radius(title, default=10.0):
    value, ok = QtWidgets.QInputDialog.getDouble(None,tr("euSKlid"),title,default,0.0,1e9,6)
    return value if ok else None

def choose_solution(title, labels):
    item, ok = QtWidgets.QInputDialog.getItem(None,tr("euSKlid"),title,labels,0,False)
    return labels.index(item) if ok else None


def ask_grid_parameters():
    class GridDialog(QtWidgets.QDialog):
        def __init__(self, parent=None):
            super(GridDialog, self).__init__(parent)
            self.setWindowTitle(tr("Grid"))
            self._rows = []
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

            buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

            self.nb.valueChanged.connect(self._rebuild_rows)
            self._rebuild_rows(self.nb.value())

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

    dlg = GridDialog()
    if dlg.exec_():
        return dlg.values()
    return None


def ask_polygon_parameters():
    class PolygonDialog(QtWidgets.QDialog):
        def __init__(self, parent=None):
            super(PolygonDialog, self).__init__(parent)
            self.setWindowTitle("To Polygon")
            layout = QtWidgets.QFormLayout(self)

            self.nb_edges = QtWidgets.QSpinBox()
            self.nb_edges.setRange(3, 360)
            self.nb_edges.setValue(6)
            layout.addRow("NB edges", self.nb_edges)

            self.inout = QtWidgets.QComboBox()
            self.inout.addItems(["IN", "OUT"])
            layout.addRow("IN / OUT", self.inout)

            self.action = QtWidgets.QComboBox()
            self.action.addItems(["Convert circle", "Add polygon"])
            layout.addRow("Action", self.action)

            self.orient = QtWidgets.QComboBox()
            self.orient.addItems(["snap edge_middle", "snap vertice", "snap ∥/Edge"])
            layout.addRow("Orientation", self.orient)

            buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            layout.addRow(buttons)

        def values(self):
            return {
                "nb_edges": int(self.nb_edges.value()),
                "inout": "in" if self.inout.currentIndex() == 0 else "out",
                "action": "convert" if self.action.currentIndex() == 0 else "add",
                "orientation": ["edge_middle", "vertice", "parallel_edge"][self.orient.currentIndex()],
            }

    dlg = PolygonDialog()
    if dlg.exec_():
        return dlg.values()
    return None
