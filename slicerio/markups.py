# -*- coding: utf-8 -*-
"""Functions for reading, writing, and converting markup files used by 3D Slicer.

Supported formats:

- ``.mrk.json``: current JSON-based format (Slicer >= 6.x)
- ``.fcsv``: legacy CSV-based fiducial format (Slicer < 6.x)

Format notes
------------
**FCSV** stores each control point as a comma-separated row with columns
``id, x, y, z, ow, ox, oy, oz, vis, sel, lock, label, desc, associatedNodeID``.
The orientation is encoded as a unit quaternion ``(ow, ox, oy, oz)`` = ``(w, x, y, z)``.

**mrk.json** stores orientation as a 9-element, row-major rotation matrix
``[R00, R01, R02, R10, R11, R12, R20, R21, R22]``.
Both formats use the same coordinate system (LPS or RAS) recorded in the file header.
"""

from pathlib import Path


_MARKUPS_SCHEMA = (
    "https://raw.githubusercontent.com/slicer/slicer/master/"
    "Modules/Loadable/Markups/Resources/Schema/markups-schema-v1.0.3.json#"
)


def _quaternion_to_rotation_matrix(w, x, y, z):
    """Return a 9-element row-major rotation matrix from a unit quaternion (w, x, y, z).

    The returned list is [R00, R01, R02, R10, R11, R12, R20, R21, R22].
    """
    return [
        1 - 2*(y**2 + z**2),  2*(x*y - w*z),         2*(x*z + w*y),
        2*(x*y + w*z),         1 - 2*(x**2 + z**2),   2*(y*z - w*x),
        2*(x*z - w*y),         2*(y*z + w*x),          1 - 2*(x**2 + y**2),
    ]



def read_markups_fcsv(file_path):
    """Read a legacy Slicer fiducial CSV file (``.fcsv``).

    Returns a dict with the same structure as :func:`read_markups_json` so the
    two formats can be used interchangeably.

    FCSV is the legacy format used by 3D Slicer (before version 6) for storing
    point (fiducial) markup nodes.  The orientation quaternion ``(ow, ox, oy, oz)``
    stored in each row is converted to the 9-element row-major rotation matrix
    used by the mrk.json format.

    :param file_path: path to the ``.fcsv`` file
    :return: dict with the markups data matching the mrk.json schema

    Example::

        markups = read_markups_fcsv("F_1.fcsv")
        for cp in markups["markups"][0]["controlPoints"]:
            print(cp["label"], cp["position"])
    """

    # In very old .fcsv files, the coordinate system was not specified and RAS was used
    coordinate_system = "RAS"

    columns = None
    control_points = []

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith("#"):
                if "CoordinateSystem" in line:
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        value = parts[1].strip()
                        # Older .fcsv files (Slicer<4.11) encode the system as an integer: 0 = RAS, 1 = LPS
                        if value == "0":
                            coordinate_system = "RAS"
                        elif value == "1":
                            coordinate_system = "LPS"
                        else:
                            coordinate_system = value
                elif "columns" in line:
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        columns = [c.strip() for c in parts[1].split(",")]
                continue
            if columns is None:
                continue

            values = line.split(",")
            # zip stops at the shorter sequence; extra trailing fcsv columns are ignored
            row = dict(zip(columns, values))

            point_id = row.get("id", "").strip()
            x = float(row.get("x", 0))
            y = float(row.get("y", 0))
            z = float(row.get("z", 0))
            ow = float(row.get("ow", 0))
            ox = float(row.get("ox", 0))
            oy = float(row.get("oy", 0))
            oz = float(row.get("oz", 1))
            visibility = row.get("vis", "1").strip() == "1"
            selected = row.get("sel", "1").strip() == "1"
            locked = row.get("lock", "0").strip() == "1"
            label = row.get("label", "").strip()
            description = row.get("desc", "").strip()
            associated_node_id = row.get("associatedNodeID", "").strip()

            cp = {
                "id": point_id,
                "label": label,
                "position": [x, y, z],
                "orientation": _quaternion_to_rotation_matrix(ow, ox, oy, oz),
                "selected": selected,
                "locked": locked,
                "visibility": visibility,
            }
            if description:
                cp["description"] = description
            if associated_node_id:
                cp["associatedNodeID"] = associated_node_id
            control_points.append(cp)

    # Drop orientation from all points if every point uses the default quaternion.
    # This is the most common case, because Markups module in Slicer core always used
    # the default orientation, and this default orientation should not be preserved.
    _default = _quaternion_to_rotation_matrix(0.0, 0.0, 0.0, 1.0)
    if all(cp["orientation"] == _default for cp in control_points):
        for cp in control_points:
            del cp["orientation"]

    return {
        "@schema": _MARKUPS_SCHEMA,
        "markups": [
            {
                "type": "Fiducial",
                "coordinateSystem": coordinate_system,
                "controlPoints": control_points,
            }
        ],
    }


def fcsv_to_markups_json(input_path, output_path=None):
    """Convert a legacy Slicer fiducial CSV file (``.fcsv``) to the current
    markup JSON format (``.mrk.json``).

    :param input_path: path to the source ``.fcsv`` file
    :param output_path: path for the output ``.mrk.json`` file.  When *None*,
        the output path is derived from *input_path* by replacing the ``.fcsv``
        extension with ``.mrk.json``.
    :return: :class:`pathlib.Path` of the written ``.mrk.json`` file

    Example::

        # Write next to the source file
        out = fcsv_to_markups_json("F_1.fcsv")

        # Write to a specific location
        out = fcsv_to_markups_json("F_1.fcsv", "/tmp/converted.mrk.json")
    """
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path.with_suffix(".mrk.json")
    output_path = Path(output_path)

    import json
    markups = read_markups_fcsv(input_path)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(markups, f, indent=4)
    return output_path
