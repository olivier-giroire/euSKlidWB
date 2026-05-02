import FreeCAD as App
import FreeCADGui as Gui
from .dialogs import ask_distance_series, ask_angle_series, ask_radius, choose_solution, ask_grid_parameters
from .plane import SketchPlane
from .controller import (
    create_sketch_on_plane,
    open_eusklid_sketch,
    start_line_2pts_session,
    start_point_angle_session,
    start_circle_center_radius_session,
    start_circle_center_pass_session,
    start_circle_3pts_session,
    start_circle_2pts_radius_session,
    start_line_parallel_ref_series_session,
    start_line_parallel_ref_point_session,
    start_line_perpendicular_ref_point_session,
    start_line_grid_session,
    path_start,
    path_close,
    path_export,
    end_sketch,
    undo_contextual,
)
from .qt_compat import QtWidgets
from .core.i18n import tr

class _BaseCmd:
    def IsActive(self):
        return True

class CmdNewSketch(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("New Sketch"),"ToolTip":tr("Create a new euSKlid sketch")}
    def Activated(self):
        if App.ActiveDocument is None:
            App.newDocument()
        create_sketch_on_plane(SketchPlane.XY(), "euSKlidXY")




class CmdOpenSketch(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("Open Sketch"),"ToolTip":tr("Open an existing euSKlid sketch from the active document")}
    def Activated(self):
        open_eusklid_sketch()

class CmdLine2Pts(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("2 Anchors"),"ToolTip":tr("Create an infinite line through 2 anchors")}
    def Activated(self): start_line_2pts_session(construction=True)

class CmdLineParallelRefSeries(_BaseCmd):
    def GetResources(self):
        return {"MenuText":"Series ∥/Ref","ToolTip":"Create a series of lines parallel to a selected reference (line, U or V axis)."}
    def Activated(self):
        start_line_parallel_ref_series_session(ask_distance_series=ask_distance_series, construction=True)

class CmdLineParallelRefPoint(_BaseCmd):
    def GetResources(self):
        return {"MenuText": tr("∥/Ref + Anchor"), "ToolTip": tr("Create a line parallel to a selected reference through an anchor")}
    def Activated(self):
        start_line_parallel_ref_point_session(construction=True)

class CmdLinePerpendicularRefPoint(_BaseCmd):
    def GetResources(self):
        return {"MenuText": tr("⟂/Ref + Anchor"), "ToolTip": tr("Create a line perpendicular to a selected reference through an anchor")}
    def Activated(self):
        start_line_perpendicular_ref_point_session(construction=True)

class CmdPointAngle(_BaseCmd):
    def GetResources(self):
        return {
            "MenuText": tr("Series Ref, Pt, Angle"),
            "ToolTip": tr("Create a series of lines through a point, at angles measured from a reference."),
        }

    def Activated(self):
        start_point_angle_session(ask_angle_series=ask_angle_series, construction=True)


class CmdLineGrid(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("Grid"),"ToolTip":tr("Create a multi-series grid centered on a picked point")}
    def Activated(self):
        start_line_grid_session(ask_grid_parameters=ask_grid_parameters, construction=True)

class CmdCircleCenterRadius(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("Center / Radius"),"ToolTip":tr("Construction circle by center and radius")}
    def Activated(self):
        radius = ask_radius("Radius")
        if radius is None or radius <= 0:
            return
        start_circle_center_radius_session(radius=radius, construction=True)

class CmdCircleCenterPass(_BaseCmd):
    def GetResources(self): return {"MenuText": tr("Center / Anchor"), "ToolTip": tr("Construction circle by center and anchor (point, line tangency, circle tangency)")}
    def Activated(self): start_circle_center_pass_session(construction=True)

class CmdCircle3Pts(_BaseCmd):
    def GetResources(self): return {"MenuText": tr("3 Anchors"), "ToolTip": tr("Construction circle through 3 anchors")}
    def Activated(self): start_circle_3pts_session(construction=True)

class CmdCircle2PtsRadius(_BaseCmd):
    def GetResources(self): return {"MenuText": tr("2 Anchors / Radius"), "ToolTip": tr("Construction circle through 2 anchors with given radius")}
    def Activated(self):
        radius = ask_radius("Radius")
        if radius is None or radius <= 0:
            return
        start_circle_2pts_radius_session(radius=radius, choose_solution=choose_solution, construction=True)

class CmdPathStart(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("Start Path"),"ToolTip":tr("Start a new path")}
    def Activated(self): path_start()

class CmdPathClose(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("Close Path"),"ToolTip":tr("Close and terminate the current path")}
    def Activated(self): path_close()

class CmdPathExport(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("Export Path to Sketcher"),"ToolTip":tr("Export the current path to Sketcher")}
    def Activated(self): path_export()

class CmdUndo(_BaseCmd):
    def GetResources(self):
        return {"MenuText":"Undo","ToolTip":"Contextual undo for euSKlid","Accel":"Ctrl+Z"}
    def Activated(self):
        undo_contextual()

class CmdEndSketch(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("End Sketch"),"ToolTip":tr("Stop the active euSKlid tool")}
    def Activated(self): end_sketch()


class CmdSettings(_BaseCmd):
    def GetResources(self):
        return {"MenuText": tr("Settings"), "ToolTip": tr("euSKlid settings")}

    def Activated(self):
        from .ui.settings_dialog import show_settings_dialog
        show_settings_dialog()

def register_commands():
    Gui.addCommand("euSKlid_NewSketch", CmdNewSketch())
    Gui.addCommand("euSKlid_OpenSketch", CmdOpenSketch())
    Gui.addCommand("euSKlid_Line2Pts", CmdLine2Pts())
    Gui.addCommand("euSKlid_PointAngle", CmdPointAngle())
    Gui.addCommand("euSKlid_LineGrid", CmdLineGrid())
    Gui.addCommand("euSKlid_LineParallelRefSeries", CmdLineParallelRefSeries())
    Gui.addCommand("euSKlid_LineParallelRefPoint", CmdLineParallelRefPoint())
    Gui.addCommand("euSKlid_LinePerpendicularRefPoint", CmdLinePerpendicularRefPoint())
    Gui.addCommand("euSKlid_CircleCenterRadius", CmdCircleCenterRadius())
    Gui.addCommand("euSKlid_CircleCenterPass", CmdCircleCenterPass())
    Gui.addCommand("euSKlid_Circle3Pts", CmdCircle3Pts())
    Gui.addCommand("euSKlid_Circle2PtsRadius", CmdCircle2PtsRadius())
    Gui.addCommand("euSKlid_PathStart", CmdPathStart())
    Gui.addCommand("euSKlid_PathClose", CmdPathClose())
    Gui.addCommand("euSKlid_PathExport", CmdPathExport())
    Gui.addCommand("euSKlid_Undo", CmdUndo())
    Gui.addCommand("euSKlid_EndSketch", CmdEndSketch())
    Gui.addCommand("euSKlid_Settings", CmdSettings())
