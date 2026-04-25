import FreeCAD as App

class SketchPlane:
    def __init__(self, origin, u, v, name):
        self.origin = App.Vector(*origin)
        self.u = App.Vector(*u)
        self.v = App.Vector(*v)
        self.name = name
        self._normalize_axes()
        self.normal = self.u.cross(self.v)

    def _normalize_axes(self):
        if self.u.Length == 0 or self.v.Length == 0:
            raise ValueError("Invalid sketch plane axes.")
        self.u.normalize()
        self.v = self.v - self.u * self.u.dot(self.v)
        if self.v.Length == 0:
            raise ValueError("Collinear sketch plane axes.")
        self.v.normalize()

    @classmethod
    def XY(cls): return cls((0,0,0),(1,0,0),(0,1,0),"XY")
    @classmethod
    def XZ(cls): return cls((0,0,0),(1,0,0),(0,0,1),"XZ")
    @classmethod
    def YZ(cls): return cls((0,0,0),(0,1,0),(0,0,1),"YZ")

    @classmethod
    def from_three_points(cls,p0,p1,p2):
        P0=App.Vector(*p0); P1=App.Vector(*p1); P2=App.Vector(*p2)
        u=P1-P0; w=P2-P0
        if u.Length == 0 or w.Length == 0:
            raise ValueError("Degenerate points.")
        n=u.cross(w)
        if n.Length == 0:
            raise ValueError("The three points are collinear.")
        v=n.cross(u)
        return cls((P0.x,P0.y,P0.z),(u.x,u.y,u.z),(v.x,v.y,v.z),"3PTS")

    def uv_to_world(self, uv):
        u,v = uv
        p = self.origin + self.u*float(u) + self.v*float(v)
        return (p.x,p.y,p.z)

    def world_to_uv(self, p):
        pv = App.Vector(*p) - self.origin
        return (pv.dot(self.u), pv.dot(self.v))

    def to_dict(self):
        return {
            "origin":[self.origin.x,self.origin.y,self.origin.z],
            "u":[self.u.x,self.u.y,self.u.z],
            "v":[self.v.x,self.v.y,self.v.z],
            "name":self.name
        }

    @classmethod
    def from_dict(cls,d):
        return cls(tuple(d["origin"]), tuple(d["u"]), tuple(d["v"]), d.get("name","Custom"))
