import os
import sys
import inspect

import FreeCAD as App
import FreeCADGui as Gui


def tr(text):
    # Safe fallback during early workbench discovery.
    # The real translator is loaded inside Initialize(), after sys.path is ready.
    return text


class euSKlidWorkbench(Gui.Workbench):
    MenuText = "euSKlid"
    ToolTip = "euSKlid planar sketching workbench for FreeCAD"
    Icon = ""

    def Initialize(self):
        wb_dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
        if wb_dir not in sys.path:
            sys.path.insert(0, wb_dir)

        global tr
        try:
            from eusklid.core.i18n import tr as _real_tr
            tr = _real_tr
            self.MenuText = tr("euSKlid")
            self.ToolTip = tr("euSKlid planar sketching workbench for FreeCAD")
        except Exception:
            pass

        import eusklid.commands as cmds
        cmds.register_commands()

        self.appendToolbar(tr("euSKlid"), [
            "euSKlid_NewSketch",
            "euSKlid_OpenSketch",
            "euSKlid_EndSketch",
            "euSKlid_Undo",
            "euSKlid_Settings",
        ])

        self.appendMenu(tr("Sketch"), [
            "euSKlid_NewSketch",
            "euSKlid_OpenSketch",
            "euSKlid_EndSketch",
            "euSKlid_Undo",
            "euSKlid_Settings",
        ])

        self.appendMenu(tr("Lines"), [
            "euSKlid_Line2Pts",
            "euSKlid_LineParallelRefSeries",
            "euSKlid_LineParallelRefPoint",
            "euSKlid_LinePerpendicularRefPoint",
            "euSKlid_PointAngle",
            "euSKlid_LineGrid",
        ])

        self.appendMenu(tr("Circles"), [
            "euSKlid_CircleCenterRadius",
            "euSKlid_CircleCenterPass",
            "euSKlid_Circle3Pts",
            "euSKlid_Circle2PtsRadius",
            "euSKlid_CircleToPolygon",
        ])

        self.appendMenu(tr("Path"), [
            "euSKlid_PathStart",
            "euSKlid_PathClose",
            "euSKlid_PathEnd",
            "euSKlid_PathExport",
        ])

    def Activated(self):
        pass

    def Deactivated(self):
        try:
            stop_active_session = None
            try:
                from eusklid.controller import stop_active_session as _stop
                stop_active_session = _stop
            except Exception:
                stop_active_session = None

            if stop_active_session is not None:
                try:
                    stop_active_session()
                except Exception:
                    pass

            try:
                import eusklid.indicator as indicator
                if hasattr(indicator, "reset_overlay_states"):
                    indicator.reset_overlay_states(clear_frame_too=True)
                else:
                    indicator.clear_all()
            except Exception:
                pass

            if Gui.ActiveDocument is not None:
                Gui.ActiveDocument.ActiveView.setAxisCross(True)
                Gui.ActiveDocument.ActiveView.redraw()
        except Exception:
            pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(euSKlidWorkbench())
