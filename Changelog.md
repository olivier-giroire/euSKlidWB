
# euSKlidWB v1.3.0

## 🚀 Symmetries centric release
- intelligent Sketcher constraint export
- axial and central symmetry detection
- arbitrary symmetry axes and centers
- configurable Export settings tab
- reduced over-constraint during Path export

This release introduces a major cleanup of the codebase along with significant improvements to user experience, tool behavior, and workflow consistency.



# euSKlidWB v1.2.0

## 🚀 Major update – UX, stability and codebase cleanup

This release introduces a major cleanup of the codebase along with significant improvements to user experience, tool behavior, and workflow consistency.

---

## ✨ New Features

### 🔁 Tool Reentrance (configurable)
- New option in *Feeling* settings: **Function reentrance**
- When enabled, tools remain active after execution
- Press **ESC** to exit the active tool

### ⚡ Live Parameter Preview
- Real-time preview while editing parameters for:
  - Lines → Series ∥ / Ref
  - Lines → Series (angles)
  - Lines → Grid
- Immediate visual feedback during input

---

## 🧠 Behavior Improvements

### 🧭 Tool Lifecycle Management
- Only **one active tool at a time**
- Starting a new tool automatically exits the previous one
- ESC key now reliably exits active tools

### 🪟 Non-modal Dialogs
- Parameter dialogs no longer block FreeCAD
- You can interact with the 3D view while editing parameters
- "Apply" updates are now live

### 🎯 Preview Consistency
- Preview now uses configured visual settings (color, width, etc.)
- Immediate refresh after settings changes

---

## 🧹 Cleanup & Refactoring

- Removed unused functions, helpers, and dead code
- Removed obsolete commands and unreachable features
- Cleaned command registration and menu structure
- Simplified tool activation paths

---

## 🧾 UI/UX Improvements

- Removed default example values from input fields
- Cleaner input experience (no accidental pre-filled data)
- Improved clarity of parameter dialogs

---

## 🌍 Internationalization

- Updated translations for new UI strings
- Fixed UTF-8 encoding issues in i18n update tool

---

## 🛠 Internal Changes

- Centralized session handling improvements
- Improved config reload behavior
- Better separation of tool logic and UI
- Stabilized preview rendering pipeline

---

## ⚠️ Breaking Changes

- Some previously available commands were removed (unused or obsolete)
- Legacy export paths replaced by Path-based workflow

---

## 🎯 Summary
