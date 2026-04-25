import FreeCAD as App
import FreeCADGui as Gui
from .dialogs import ask_distance_series, ask_radius, choose_solution, ask_grid_parameters, ask_polygon_parameters
from .plane import SketchPlane
from .controller import (
    create_sketch_on_plane,
    open_eusklid_sketch,
    start_line_2pts_session,
    start_parallel_reference_session,
    create_parallel_axis,
    start_point_angle_session,
    start_circle_center_radius_session,
    start_circle_center_pass_session,
    start_circle_3pts_session,
    start_circle_2pts_radius_session,
    start_circle_center_tangent_session,
    start_circle_2tg_radius_session,
    start_circle_2pts_1tangent_session,
    start_line_point_tangent_circle_session,
    start_line_parallel_u_tangent_circle_session,
    start_line_parallel_v_tangent_circle_session,
    start_line_parallel_ref_tangent_circle_session,
    start_line_parallel_ref_series_session,
    start_line_parallel_ref_point_session,
    start_line_perpendicular_ref_point_session,
    start_line_grid_session,
    start_circle_to_polygon_session,
    stop_active_session,
    get_or_create_euclid_sketch,
    show_local_frame,
    clear_all_indicators,
    origin_mode_message,
    placeholder_message,
    path_start,
    path_close,
    path_end,
    path_export,
    end_sketch,
    undo_contextual,
)
from .exporter import export_to_native_sketch
from .qt_compat import QtWidgets
from .core.i18n import tr

class _BaseCmd:
    def IsActive(self): return True

class _PlaceholderCmd(_BaseCmd):
    label = "Placeholder"
    def GetResources(self): return {"MenuText":self.label,"ToolTip":self.label}
    def Activated(self): placeholder_message(self.label)


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

class CmdNewSketchOnFace(_PlaceholderCmd):
    label = "On face"



class CmdLine2Pts(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("2 Anchors"),"ToolTip":tr("Create an infinite line through 2 anchors")}
    def Activated(self): start_line_2pts_session(construction=True)

class CmdParallelU(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("// U"),"ToolTip":tr("Create lines parallel to U. Positive values go toward +V.")}
    def Activated(self):
        values = ask_distance_series("Distances parallel to U (space separated). Positive values go toward +V.")
        if values is None: return
        create_parallel_axis("U", values, construction=True)

class CmdParallelV(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("// V"),"ToolTip":tr("Create lines parallel to V. Positive values go toward +U.")}
    def Activated(self):
        values = ask_distance_series("Distances parallel to V (space separated). Positive values go toward +U.")
        if values is None: return
        create_parallel_axis("V", values, construction=True)

class CmdParallelRef(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("// Ref"),"ToolTip":tr("Pick a reference, see positive-side arrow, then enter signed distances.")}
    def Activated(self): start_parallel_reference_session(ask_distance_series=ask_distance_series, construction=True)


class CmdLineParallelRefSeries(_BaseCmd):
    def GetResources(self):
        return {"MenuText":"Series ∥/Ref","ToolTip":"Create a series of lines parallel to a selected reference (line, U or V axis)."}
    def Activated(self):
        start_line_parallel_ref_series_session(ask_distance_series=ask_distance_series, construction=True)

class CmdLineParallelRefPoint(_BaseCmd):
    def GetResources(self):
        return {"MenuText":"∥/Ref + Anchor","ToolTip":"Create a line parallel to a selected reference through an anchor"}
    def Activated(self):
        start_line_parallel_ref_point_session(construction=True)

class CmdLinePerpendicularRefPoint(_BaseCmd):
    def GetResources(self):
        return {"MenuText":"⟂/Ref + Anchor","ToolTip":"Create a line perpendicular to a selected reference through an anchor"}
    def Activated(self):
        start_line_perpendicular_ref_point_session(construction=True)

class CmdLinePointTgCircle(_BaseCmd):
    def GetResources(self):
        return {"MenuText":"Point + Tg","ToolTip":"Line through a point tangent to a circle"}
    def Activated(self):
        start_line_2pts_session(construction=True)

class CmdLineParallelUTg(_BaseCmd):
    def GetResources(self):
        return {"MenuText":"//U + Tg","ToolTip":"Line parallel to U tangent to a circle"}
    def Activated(self):
        start_line_parallel_u_tangent_circle_session(construction=True)

class CmdLineParallelVTg(_BaseCmd):
    def GetResources(self):
        return {"MenuText":"//V + Tg","ToolTip":"Line parallel to V tangent to a circle"}
    def Activated(self):
        start_line_parallel_v_tangent_circle_session(construction=True)

class CmdLineParallelRefTg(_BaseCmd):
    def GetResources(self):
        return {"MenuText":"∥/Ref + Tg","ToolTip":"Line parallel to a reference and tangent to a circle"}
    def Activated(self):
        start_line_parallel_ref_point_session(construction=True)

class CmdPointAngle(_BaseCmd):
    def GetResources(self):
        return {"MenuText": "Point + Angle", "ToolTip": "Create a line through a point with an angle relative to a reference."}

    def Activated(self):
        def _ask_angle():
            value, ok = QtWidgets.QInputDialog.getDouble(None, "Point + Angle", "Angle (deg):", 45.0, -360.0, 360.0, 2)
            if not ok:
                return None
            return value
        start_point_angle_session(_ask_angle, construction=True)


class CmdLineGrid(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("Grid"),"ToolTip":tr("Create a multi-series grid centered on a picked point")}
    def Activated(self):
        params = ask_grid_parameters()
        if params is None:
            return
        start_line_grid_session(params, construction=True)

class CmdCircleCenterRadius(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("Center / Radius"),"ToolTip":tr("Construction circle by center and radius")}
    def Activated(self):
        radius = ask_radius("Radius")
        if radius is None or radius <= 0: return
        start_circle_center_radius_session(radius=radius, construction=True)

class CmdCircleCenterPass(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("Center / Anchor"),"ToolTip":tr("Construction circle by center and anchor (point, line tangency, circle tangency)")}
    def Activated(self): start_circle_center_pass_session(construction=True)

class CmdCircle3Pts(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("3 Anchors"),"ToolTip":tr("Construction circle through 3 anchors")}
    def Activated(self): start_circle_3pts_session(construction=True)

class CmdCircle2PtsRadius(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("2 Anchors / Radius"),"ToolTip":tr("Construction circle through 2 anchors with given radius")}
    def Activated(self):
        radius = ask_radius("Radius")
        if radius is None or radius <= 0: return
        start_circle_2pts_radius_session(radius=radius, choose_solution=choose_solution, construction=True)

class CmdCircleCenterTg(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("Center / tg"),"ToolTip":tr("Center then tangent reference (line or circle). Multiple solutions are chosen graphically.")}
    def Activated(self): start_circle_center_tangent_session(construction=True)

class CmdCircle2TgRadius(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("2 Tg / Radius"),"ToolTip":tr("Two tangent references (line/circle) and a radius. Multiple solutions are chosen graphically.")}
    def Activated(self):
        radius = ask_radius("Radius")
        if radius is None or radius <= 0: return
        start_circle_2tg_radius_session(radius=radius, construction=True)



class CmdCircle2Pts1Tg(_BaseCmd):
    def GetResources(self):
        return {"MenuText":"2 Points / 1 Tg","ToolTip":"Two points then one tangent line reference. Multiple solutions are chosen graphically."}
    def Activated(self):
        start_circle_2pts_1tangent_session(construction=True)



class CmdCircleToPolygon(_BaseCmd):
    def GetResources(self):
        return {"MenuText":"To Polygon","ToolTip":"Convert or add a regular polygon from a reference circle"}
    def Activated(self):
        params = ask_polygon_parameters()
        if params is None:
            return
        start_circle_to_polygon_session(params=params, construction=True)
class CmdPathStart(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("Start Path"),"ToolTip":tr("Start a new path")}
    def Activated(self): path_start()

class CmdPathClose(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("Close Path"),"ToolTip":tr("Close and terminate the current path")}
    def Activated(self): path_close()

class CmdPathEnd(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("End Path"),"ToolTip":tr("End the current path")}
    def Activated(self): path_end()

class CmdPathExport(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("Export Path to Sketcher"),"ToolTip":tr("Export the current path to Sketcher")}
    def Activated(self): path_export()

class CmdExportSketcher(_BaseCmd):
    def GetResources(self): return {"MenuText":tr("Export Construction to Sketcher"),"ToolTip":tr("Export all entities to native Sketcher")}
    def Activated(self): export_to_native_sketch(get_or_create_euclid_sketch())

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
        from .ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog()
        dlg.exec_()

def register_commands():
    Gui.addCommand("euSKlid_NewSketch", CmdNewSketch())
    Gui.addCommand("euSKlid_OpenSketch", CmdOpenSketch())
    Gui.addCommand("euSKlid_NewSketchOnFace", CmdNewSketchOnFace())
    Gui.addCommand("euSKlid_Line2Pts", CmdLine2Pts())
    Gui.addCommand("euSKlid_ParallelU", CmdParallelU())
    Gui.addCommand("euSKlid_ParallelV", CmdParallelV())
    Gui.addCommand("euSKlid_ParallelRef", CmdParallelRef())
    Gui.addCommand("euSKlid_PointAngle", CmdPointAngle())
    Gui.addCommand("euSKlid_LineGrid", CmdLineGrid())
    Gui.addCommand("euSKlid_LineParallelRefTg", CmdLineParallelRefTg())
    Gui.addCommand("euSKlid_LineParallelVTg", CmdLineParallelVTg())
    Gui.addCommand("euSKlid_LineParallelUTg", CmdLineParallelUTg())
    Gui.addCommand("euSKlid_LineParallelRefSeries", CmdLineParallelRefSeries())
    Gui.addCommand("euSKlid_LineParallelRefPoint", CmdLineParallelRefPoint())
    Gui.addCommand("euSKlid_LinePerpendicularRefPoint", CmdLinePerpendicularRefPoint())
    Gui.addCommand("euSKlid_LinePointTgCircle", CmdLinePointTgCircle())
    Gui.addCommand("euSKlid_CircleCenterRadius", CmdCircleCenterRadius())
    Gui.addCommand("euSKlid_CircleCenterPass", CmdCircleCenterPass())
    Gui.addCommand("euSKlid_Circle3Pts", CmdCircle3Pts())
    Gui.addCommand("euSKlid_Circle2PtsRadius", CmdCircle2PtsRadius())
    Gui.addCommand("euSKlid_CircleCenterTg", CmdCircleCenterTg())
    Gui.addCommand("euSKlid_Circle2TgRadius", CmdCircle2TgRadius())
    Gui.addCommand("euSKlid_Circle2Pts1Tg", CmdCircle2Pts1Tg())
    Gui.addCommand("euSKlid_CircleToPolygon", CmdCircleToPolygon())
    Gui.addCommand("euSKlid_PathStart", CmdPathStart())
    Gui.addCommand("euSKlid_PathClose", CmdPathClose())
    Gui.addCommand("euSKlid_PathEnd", CmdPathEnd())
    Gui.addCommand("euSKlid_PathExport", CmdPathExport())
    Gui.addCommand("euSKlid_Undo", CmdUndo())
    Gui.addCommand("euSKlid_ExportSketcher", CmdExportSketcher())
    Gui.addCommand("euSKlid_EndSketch", CmdEndSketch())
    Gui.addCommand("euSKlid_Settings", CmdSettings())
