import json
from .plane import SketchPlane
from .geom import LineEntity2D, CircleEntity2D

class SketchData:
    def __init__(self, plane=None, entities=None):
        self.plane = plane or SketchPlane.XY()
        self.entities = entities or []

    def to_dict(self):
        return {"plane":self.plane.to_dict(),"entities":[e.to_dict() for e in self.entities]}

    @classmethod
    def from_dict(cls,d):
        ents=[]
        for item in d.get("entities",[]):
            if item.get("kind")=="line":
                ents.append(LineEntity2D.from_dict(item))
            elif item.get("kind")=="circle":
                ents.append(CircleEntity2D.from_dict(item))
        return cls(plane=SketchPlane.XY(), entities=ents)

def load_data(text):
    if not text:
        return SketchData()
    try:
        return SketchData.from_dict(json.loads(text))
    except Exception:
        return SketchData()

def dump_data(data):
    return json.dumps(data.to_dict(), indent=2)
