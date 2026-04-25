import FreeCAD as App
import Part
from .storage import load_data, dump_data
from .geom import LineEntity2D, CircleEntity2D
from .math2d import visible_segment_for_line
from .core.groups import ensure_euclid_groups, get_construction_group, add_to_group
from .core.config import get_config


def _construction_style(kind="lines"):
    try:
        cfg = get_config().get("construction", {}).get(kind, {})
        color = tuple(cfg.get("color", (1.0, 1.0, 1.0)))
        width = float(cfg.get("thickness", 2))
        alpha = int(cfg.get("alpha", 0))
        return color, width, alpha
    except Exception:
        return (1.0, 1.0, 1.0), 2.0, 0


def _apply_construction_line_style(obj):
    """Apply Construction/Lines style to the euSKlid sketch view object.

    V0.6.6 scope: line-style validation on the existing compound-based
    construction display. Per-entity styling will be handled separately
    when circles/grids/polygons are split or rendered independently.
    """
    try:
        vo = getattr(obj, "ViewObject", None)
        if vo is None:
            return
        color, width, alpha = _construction_style("lines")
        vo.LineColor = color
        vo.PointColor = color
        vo.ShapeColor = color
        vo.LineWidth = width
        vo.Transparency = alpha
    except Exception:
        pass


class euSKlidFeature:
    def __init__(self,obj):
        obj.Proxy=self
        self.ensure(obj)

    def ensure(self,obj):
        props=getattr(obj,"PropertiesList",[])
        if "SketchJson" not in props:
            obj.addProperty("App::PropertyString","SketchJson","euSKlid","Serialized planar sketch data")
        if "PlaneName" not in props:
            obj.addProperty("App::PropertyString","PlaneName","euSKlid","Sketch plane name")
            obj.PlaneName="XY"

    def execute(self,obj):
        data=load_data(obj.SketchJson)
        shapes=[]
        obj.PlaneName=data.plane.name
        for ent in data.entities:
            try:
                if isinstance(ent,LineEntity2D):
                    if isinstance(getattr(ent, "meta", None), dict) and "segment_a" in ent.meta and "segment_b" in ent.meta:
                        uv1 = tuple(ent.meta["segment_a"])
                        uv2 = tuple(ent.meta["segment_b"])
                    else:
                        uv1,uv2=visible_segment_for_line(ent.origin, ent.direction, 1000.0)
                    p1=App.Vector(*data.plane.uv_to_world(uv1))
                    p2=App.Vector(*data.plane.uv_to_world(uv2))
                    shapes.append(Part.makeLine(p1,p2))
                elif isinstance(ent,CircleEntity2D):
                    center=App.Vector(*data.plane.uv_to_world(ent.center))
                    n=data.plane.normal
                    shapes.append(Part.Circle(center, App.Vector(n.x,n.y,n.z), ent.radius).toShape())
            except Exception as e:
                App.Console.PrintError("euSKlid execute entity error: %s\n" % str(e))
        obj.Shape=Part.Compound(shapes) if shapes else Part.Shape()
        _apply_construction_line_style(obj)

    def onDocumentRestored(self,obj):
        self.ensure(obj)

class ViewProvidereuSKlid:
    def __init__(self,vo): vo.Proxy=self
    def attach(self,vo): self.ViewObject=vo
    def getIcon(self): return ""
    def updateData(self,fp,prop): pass
    def onChanged(self,vp,prop): pass
    def __getstate__(self): return None
    def __setstate__(self,state): return None

def ensure_proxy(obj):
    if not getattr(obj,"Proxy",None) or obj.Proxy.__class__.__name__!="euSKlidFeature":
        euSKlidFeature(obj)
    try:
        if obj.ViewObject and not getattr(obj.ViewObject,"Proxy",None):
            ViewProvidereuSKlid(obj.ViewObject)
    except Exception:
        pass
    return obj

def create_sketch(doc=None,name="euSKlid",plane=None):
    from .storage import SketchData
    doc=doc or App.ActiveDocument
    ensure_euclid_groups(doc)
    obj=doc.addObject("Part::FeaturePython",name)
    euSKlidFeature(obj)
    ViewProvidereuSKlid(obj.ViewObject)
    _apply_construction_line_style(obj)
    data=SketchData(plane=plane)
    obj.SketchJson=dump_data(data)
    obj.PlaneName=plane.name if plane else "XY"
    try:
        add_to_group(obj, get_construction_group(doc))
    except Exception:
        pass
    doc.recompute()
    return obj

def get_data(obj):
    ensure_proxy(obj)
    return load_data(obj.SketchJson)

def set_data(obj,data):
    ensure_proxy(obj)
    obj.SketchJson=dump_data(data)
    obj.touch()
