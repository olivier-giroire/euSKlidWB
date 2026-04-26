euSKlidWB B1 build for FreeCAD.

New in B1:
- Center / tg now supports tangent references of type:
  - line
  - circle
- 2 Tg / Radius now supports:
  - line + line
  - line + circle
  - circle + circle
- When multiple solutions exist, choice is made graphically:
  - candidate circles are previewed
  - click near the desired preview circle to validate

Menu structure remains the current top-level structure.
Path and some other functions are still placeholders.


Patch 3:
- preview for line 2pts
- preview for center/radius, center/point, 3 points circles
- preview uses the same snapped point that the click will use


Patch 5.2:
- 2 Points / 1 Tg now supports tangent circle reference
- highlight of selected line/circle under mouse during tangency pick
- built from Patch 4.1 MERGED base


Patch 6:
- Lines: Point / Tg Circle, //U + Tg, //V + Tg, //Ref + Tg
- includes project_point_on_line and highlight helpers


Patch 7.3 clean:
- standardized raw_uv vs uv in tangent line sessions
- line preview follows nearest solution under mouse


Patch 8:
- auto view orientation when creating sketch planes
- X/Y axes may be used as line references
- new Lines menu centered on Ref
- added Series ∥/Ref, ∥/Ref + Point, ⟂/Ref + Point


Patch 8.1:
- stabilize ∥/Ref + Point and ⟂/Ref + Point sessions
- restore line preview during second step


## V1.1.3 XY-only simplification

- Removed the U/V visual frame overlay.
- Removed FreeCAD X/Y/Z axis-cross hide/restore side effects.
- euSKlid data is interpreted in the FreeCAD XY plane.
- Axis-parallel UI now exposes X/Y labels.
