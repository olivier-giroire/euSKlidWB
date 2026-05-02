# SPDX-License-Identifier: LGPL-2.1-or-later
#
# euSKlidWB - FreeCAD Workbench
# Copyright (C) 2026 Olivier Giroire
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

import os
import json
import copy
import FreeCAD as App


_CURRENT = None


def _plugin_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _default_config_path():
    return os.path.join(_plugin_root(), "resources", "defaults.json")


def _user_config_path():
    return os.path.join(App.getUserAppDataDir(), "euSKlid.json")


def _hard_fallback():
    return {
        "gui": {
            "uv": {
                "size": 150,
                "arrow_size": 30,
                "thickness": 3
            },
            "arrows": {
                "color": [1.0, 0.0, 0.0],
                "alpha": 30,
                "thickness": 5,
                "length": 60,
                "arrow_size": 10,
                "step": 30,
                "count": 15
            },
            "points": {
                "size": 20,
                "alpha": 30,
                "colors": {
                    "selected": [0.2, 0.4, 1.0],
                    "snap": [0.2, 1.0, 0.2],
                    "fixed": [1.0, 1.0, 0.0],
                    "hover": [1.0, 0.0, 1.0],
                    "marker": [1.0, 0.5, 0.0]
                }
            }
        },
        "construction": {
            "lines": {
                "color": [1.0, 1.0, 1.0],
                "thickness": 2,
                "alpha": 0
            },
            "circles": {
                "color": [1.0, 1.0, 1.0],
                "thickness": 2,
                "alpha": 0
            },
            "grids": {
                "color": [0.7, 0.7, 0.7],
                "thickness": 1,
                "alpha": 50
            },
            "polygons": {
                "color": [1.0, 1.0, 1.0],
                "thickness": 2,
                "alpha": 0
            }
        },
        "highlight": {
            "color": [1.0, 0.8, 0.1],
            "thickness": 3,
            "alpha": 40
        },
        "preview": {
            "color": [0.1, 0.4, 1.0],
            "thickness": 2,
            "alpha": 70
        },
        "path": {
            "current": {
                "color": [1.0, 0.5, 0.0],
                "thickness": 5,
                "alpha": 0
            },
            "candidate": {
                "color": [0.6, 1.0, 0.6],
                "thickness": 3,
                "alpha": 0
            },
            "closed": {
                "color": [0.0, 0.45, 0.0],
                "thickness": 6,
                "alpha": 0
            }
        },
        "feeling": {
            "snap_threshold": 20,
            "autogrid": "off",
            "refresh_interval_ms": 120,
            "function_reentrance": True,
            "console_messages": False,
            "help_messages": False
        }
    }


def _merge(base, override):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


def load_default_config():
    path = _default_config_path()
    cfg = _hard_fallback()

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg = data
        except Exception:
            cfg = _hard_fallback()

    return cfg


def load_user_config():
    path = _user_config_path()
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    return {}



def _migrate_config(cfg):
    try:
        feeling = cfg.get("feeling", {})
        if "autogrid" not in feeling and "autocorrect" in feeling:
            feeling["autogrid"] = feeling.get("autocorrect", "off")
        if "autocorrect" in feeling:
            try:
                del feeling["autocorrect"]
            except Exception:
                pass
    except Exception:
        pass
    return cfg


def load_config():
    cfg = copy.deepcopy(load_default_config())
    user = load_user_config()
    _merge(cfg, user)
    return _migrate_config(cfg)


def save_config(cfg):
    cfg = _migrate_config(cfg)
    path = _user_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def get_config():
    global _CURRENT
    if _CURRENT is None:
        _CURRENT = load_config()
    return copy.deepcopy(_CURRENT)


def set_config(cfg):
    global _CURRENT
    _CURRENT = copy.deepcopy(cfg)


