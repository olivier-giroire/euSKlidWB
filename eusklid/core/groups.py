
import FreeCAD as App
import Part

ROOT_NAME = "euSKlidRoot"
CONTEXT_NAME = "euSKlidContext"
FRAME_NAME = "euSKlidFrame"
INDICATORS_NAME = "euSKlidIndicators"
TRANSIENT_NAME = "euSKlidTransient"
CONSTRUCTION_NAME = "euSKlidConstruction"
PATH_NAME = "euSKlidPath"


def _set_label(obj, label):
    try:
        obj.Label = label
    except Exception:
        pass


def _get_or_create_group(doc, name, label, parent=None):
    obj = doc.getObject(name)
    if obj is None:
        obj = doc.addObject("App::DocumentObjectGroup", name)
    _set_label(obj, label)
    if parent is not None:
        try:
            if obj not in getattr(parent, 'Group', []):
                parent.addObject(obj)
        except Exception:
            pass
    return obj

def _show_uv_frame_impl(plane, origin_uv=(0.0, 0.0)):
    global _FRAME_OBJECTS
    _FRAME_OBJECTS = _remove_objects(_FRAME_OBJECTS)

    doc = App.ActiveDocument
    if doc is None:
        return []

    ensure_euclid_groups(doc)
    grp = get_frame_group(doc)

    # --- constantes stables ---
    FRAME_PX = 150.0
    ARROW_PX = 30.0
    THICK = 3.0

    # --- conversion écran -> monde ---
    u_len = _pixels_to_world(plane, origin_uv, FRAME_PX)
    v_len = _pixels_to_world(plane, origin_uv, FRAME_PX)
    head = _pixels_to_world(plane, origin_uv, ARROW_PX)

    ox, oy, oz = plane.uv_to_world(origin_uv)
    origin = App.Vector(ox, oy, oz)

    ux, uy, uz = plane.uv_to_world((origin_uv[0] + u_len, origin_uv[1]))
    vx, vy, vz = plane.uv_to_world((origin_uv[0], origin_uv[1] + v_len))

    u_tip = App.Vector(ux, uy, uz)
    v_tip = App.Vector(vx, vy, vz)

    objs = []

    def make_line(p1, p2, color, name):
        obj = doc.addObject("Part::Feature", name)
        obj.Shape = Part.makeLine(p1, p2)
        grp.addObject(obj)

        obj.ViewObject.LineColor = color
        obj.ViewObject.LineWidth = THICK
        obj.ViewObject.Selectable = False
        return obj

    # --- axes ---
    objs.append(make_line(origin, u_tip, (1.0, 0.0, 0.0), "euSKlidFrameU"))
    objs.append(make_line(origin, v_tip, (0.0, 0.65, 0.0), "euSKlidFrameV"))

    # --- flèches ---
    h = head

    objs.append(make_line(
        u_tip,
        App.Vector(u_tip.x - h, u_tip.y + 0.45 * h, u_tip.z),
        (1.0, 0.0, 0.0),
        "euSKlidFrameUHeadA"
    ))
    objs.append(make_line(
        u_tip,
        App.Vector(u_tip.x - h, u_tip.y - 0.45 * h, u_tip.z),
        (1.0, 0.0, 0.0),
        "euSKlidFrameUHeadB"
    ))

    objs.append(make_line(
        v_tip,
        App.Vector(v_tip.x + 0.45 * h, v_tip.y - h, v_tip.z),
        (0.0, 0.65, 0.0),
        "euSKlidFrameVHeadA"
    ))
    objs.append(make_line(
        v_tip,
        App.Vector(v_tip.x - 0.45 * h, v_tip.y - h, v_tip.z),
        (0.0, 0.65, 0.0),
        "euSKlidFrameVHeadB"
    ))

    # --- labels ---
    label_px = max(12.0, FRAME_PX * 0.12)
    font_size = _pixels_to_fontsize(label_px)

    def make_label(text, pos, color, name):
        obj = doc.addObject("App::AnnotationLabel", name)
        grp.addObject(obj)

        obj.Position = pos
        obj.LabelText = [text]

        obj.ViewObject.TextColor = color
        obj.ViewObject.FontSize = font_size
        obj.ViewObject.Selectable = False
        return obj

    u_off = _pixels_to_world(plane, (origin_uv[0] + u_len, origin_uv[1]), 10.0)
    v_off = _pixels_to_world(plane, (origin_uv[0], origin_uv[1] + v_len), 10.0)

    u_pos = App.Vector(u_tip.x + u_off, u_tip.y, u_tip.z)
    v_pos = App.Vector(v_tip.x, v_tip.y + v_off, v_tip.z)

    objs.append(make_label("U", u_pos, (1.0, 0.0, 0.0), "euSKlidLabelU"))
    objs.append(make_label("V", v_pos, (0.0, 0.65, 0.0), "euSKlidLabelV"))

    _FRAME_OBJECTS = objs

    doc.recompute()
    return objs

def ensure_euclid_groups(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    root = _get_or_create_group(doc, ROOT_NAME, 'Sketch')
    context = _get_or_create_group(doc, CONTEXT_NAME, 'Context', root)
    _get_or_create_group(doc, FRAME_NAME, 'Frame', context)
    _get_or_create_group(doc, INDICATORS_NAME, 'Indicators', context)
    _get_or_create_group(doc, TRANSIENT_NAME, 'Transient', context)
    _get_or_create_group(doc, CONSTRUCTION_NAME, 'Construction', root)
    _get_or_create_group(doc, PATH_NAME, 'Path', root)
    return root


def get_root_group(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    ensure_euclid_groups(doc)
    return doc.getObject(ROOT_NAME)


def get_frame_group(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    ensure_euclid_groups(doc)
    return doc.getObject(FRAME_NAME)


def get_indicators_group(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    ensure_euclid_groups(doc)
    return doc.getObject(INDICATORS_NAME)


def get_transient_group(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    ensure_euclid_groups(doc)
    return doc.getObject(TRANSIENT_NAME)


def get_construction_group(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    ensure_euclid_groups(doc)
    return doc.getObject(CONSTRUCTION_NAME)


def get_path_group(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    ensure_euclid_groups(doc)
    return doc.getObject(PATH_NAME)


def add_to_group(obj, group):
    if obj is None or group is None:
        return obj
    try:
        if obj not in getattr(group, 'Group', []):
            group.addObject(obj)
    except Exception:
        pass
    return obj
