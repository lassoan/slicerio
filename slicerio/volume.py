# -*- coding: utf-8 -*-
"""Reading and writing of NRRD image volumes as 3D Slicer writes them.

Supported files: 2D and 3D scalar images, color images (RGB, RGBA), vector fields (velocity, displacement),
tensor images (DTI), multi-component "list" images (DWI, overlapping segmentations), and time sequences of all of
these (Slicer ``.seq.nrrd`` files with the time axis as the last ``list`` axis), in LPS or RAS coordinate systems.

A volume is a ``dict`` with these keys:

``voxels``
    numpy array with the axes in NRRD file order: the component axis first (if any), then the spatial axes
    (i, j[, k]), then the sequence (time) axis last (if any). This is the array that pynrrd returns.
``ijkToLPS``
    4x4 matrix from voxel indices (i, j, k) of the spatial axes to physical LPS coordinates (mm). For 2D images
    the third column is (0, 0, 1, 0).
``spaceDimension``
    2 or 3.
``component`` (optional, only for multi-component images)
    ``{"kind": <NRRD axis kind of the component axis, e.g. "RGB-color", "vector", "3D-matrix", "list">,
    "label": <quantity of the voxel values or None>, "unit": <unit of the voxel values or None>}``
``measurementFrame`` (optional)
    3x3 matrix that maps component vectors of ``vector`` / ``covariant-vector`` / gradient components to LPS.
    See :func:`component_vectors_to_lps`.
``sequence`` (optional, only for sequences)
    ``{"indexName": ..., "indexUnit": ..., "indexType": ..., "indexValues": [str, ...]}`` of the time axis.
``displacementFieldType`` and ``intentCode`` (optional)
    present for displacement fields written by Slicer (``displacement field type:=resampling`` / ``modeling`` and
    ``intent_code:=1006``). See :func:`apply_displacement_field`.
``encoding`` and any other NRRD header field
    stored as read, written back as is.
"""

from collections import OrderedDict
import re
import urllib.parse

import numpy as np

# NRRD axis kinds that describe a position in space (the image grid)
_DOMAIN_KINDS = ("domain", "space")
# Axis kinds of Slicer sequence (time) axes
_SEQUENCE_KINDS = ("list", "time")
# Component kinds whose 3 components are spatial vectors (transformed by the measurement frame and by LPS/RAS changes)
_SPATIAL_VECTOR_KINDS = ("vector", "covariant-vector", "3-vector", "3-gradient", "3-normal", "normal", "point")

_RAS_TO_LPS = np.diag([-1.0, -1.0, 1.0, 1.0])


def _space_to_lps(space, space_dimension):
    if space is None:
        return np.eye(4)
    if space in ("left-posterior-superior", "LPS"):
        return np.eye(4)
    if space in ("right-anterior-superior", "RAS"):
        return _RAS_TO_LPS
    raise IOError(f"Unsupported space '{space}': only left-posterior-superior and right-anterior-superior are supported")


def _classify_axes(kinds, sizes, space_dimension):
    """Return (component_axis, domain_axes, sequence_axis) indices for the NRRD axes."""
    non_domain = [i for i, k in enumerate(kinds) if k not in _DOMAIN_KINDS]
    domain_axes = [i for i, k in enumerate(kinds) if k in _DOMAIN_KINDS]
    component_axis = None
    sequence_axis = None
    for axis in non_domain:
        if axis == 0 and component_axis is None and (len(non_domain) == 1 or axis < domain_axes[0]):
            component_axis = axis
        elif axis == len(kinds) - 1 and kinds[axis] in _SEQUENCE_KINDS and axis > domain_axes[-1]:
            sequence_axis = axis
        else:
            raise IOError(f"Unsupported axis layout: kinds {kinds}. Expected [component] domain... [list].")
    if space_dimension is not None and len(domain_axes) != space_dimension:
        raise IOError(f"The number of domain axes ({len(domain_axes)}) does not match the space dimension ({space_dimension})")
    if len(domain_axes) not in (2, 3):
        raise IOError(f"Unsupported number of spatial axes: {len(domain_axes)}")
    return component_axis, domain_axes, sequence_axis


def read_volume(filename, skip_voxels=False):
    """Read an image volume from a NRRD file into a dict (see the module documentation for the keys).

    :param filename: NRRD file (``.nrrd``, ``.nhdr``, ``.seq.nrrd``, ``.seg.nrrd``)
    :param skip_voxels: if True then only the header is read and ``voxels`` is None
    """
    import nrrd

    if skip_voxels:
        header = nrrd.read_header(filename)
        voxels = None
    else:
        voxels, header = nrrd.read(filename)

    kinds = header.get("kinds")
    sizes = list(header["sizes"])
    dimension = int(header["dimension"])
    if kinds is None:
        kinds = ["domain"] * dimension
    space = header.get("space")
    space_dimension = header.get("space dimension")
    if space_dimension is None and space is not None:
        space_dimension = 3
    component_axis, domain_axes, sequence_axis = _classify_axes(kinds, sizes, space_dimension)
    space_dimension = len(domain_axes)
    space_to_lps = _space_to_lps(space, space_dimension)

    volume = OrderedDict()
    volume["voxels"] = voxels

    # Geometry
    ijk_to_space = np.eye(4)
    if "space directions" in header:
        directions = np.asarray(header["space directions"], dtype=float)
        for column, axis in enumerate(domain_axes):
            ijk_to_space[0:space_dimension, column] = directions[axis][0:space_dimension]
    elif "spacings" in header:
        spacings = header["spacings"]
        for column, axis in enumerate(domain_axes):
            spacing = spacings[axis]
            ijk_to_space[column, column] = 1.0 if (spacing is None or np.isnan(spacing)) else float(spacing)
    if "space origin" in header:
        ijk_to_space[0:space_dimension, 3] = np.asarray(header["space origin"], dtype=float)[0:space_dimension]
    volume["ijkToLPS"] = space_to_lps @ ijk_to_space
    volume["spaceDimension"] = space_dimension

    labels = header.get("labels")
    units = header.get("units")

    def axis_text(values, axis):
        if values is None or axis is None or axis >= len(values):
            return None
        return values[axis] if values[axis] not in ("", None) else None

    if component_axis is not None:
        volume["component"] = OrderedDict([("kind", kinds[component_axis]),
                                           ("label", axis_text(labels, component_axis)),
                                           ("unit", axis_text(units, component_axis))])

    if "measurement frame" in header:
        frame = np.asarray(header["measurement frame"], dtype=float)
        if frame.shape == (space_dimension, space_dimension):
            frame_lps = space_to_lps[0:space_dimension, 0:space_dimension] @ frame
            volume["measurementFrame"] = frame_lps

    sequence_item_pattern = None
    if sequence_axis is not None:
        sequence = OrderedDict()
        sequence["indexName"] = axis_text(labels, sequence_axis)
        sequence["indexUnit"] = axis_text(units, sequence_axis)
        sequence["indexType"] = header.get(f"axis {sequence_axis} index type")
        index_values = header.get(f"axis {sequence_axis} index values")
        if index_values is not None:
            sequence["indexValues"] = [urllib.parse.unquote(v) for v in str(index_values).split(" ") if v != ""]
        else:
            sequence["indexValues"] = [str(i) for i in range(sizes[sequence_axis])]
        volume["sequence"] = sequence
        sequence_item_pattern = re.compile(rf"^axis {sequence_axis} item ([0-9]+) (.+)$")

    # Remaining header fields
    skipped = {"type", "endian", "dimension", "sizes", "kinds", "space", "space dimension", "space directions",
               "space origin", "spacings", "measurement frame", "labels", "units", "data file", "line skip", "byte skip"}
    if sequence_axis is not None:
        skipped.update({f"axis {sequence_axis} index type", f"axis {sequence_axis} index values"})
    for key, value in header.items():
        if key in skipped:
            continue
        if key == "displacement field type":
            volume["displacementFieldType"] = value
        elif key == "intent_code":
            volume["intentCode"] = str(value)
        elif sequence_item_pattern is not None and sequence_item_pattern.match(key):
            # per-frame attributes: axis 3 item 0002 <attribute name>:=<value>
            match = sequence_item_pattern.match(key)
            items = volume["sequence"].setdefault("itemAttributes", {})
            items.setdefault(int(match.group(1)), OrderedDict())[match.group(2)] = value
        else:
            volume[key] = value

    return volume


def write_volume(filename, volume, compression_level=9, space="LPS"):
    """Write a volume dict (see :func:`read_volume`) to a NRRD file.

    :param space: coordinate system of the written geometry: "LPS" (default, what Slicer writes) or "RAS".
      Voxel values are never changed; for vector images the measurement frame is converted accordingly.
    """
    import nrrd

    voxels = volume["voxels"]
    if voxels is None:
        raise ValueError("Volume does not contain voxels")
    space_dimension = int(volume.get("spaceDimension", 3))
    component = volume.get("component")
    sequence = volume.get("sequence")
    expected_dimension = space_dimension + (1 if component else 0) + (1 if sequence else 0)
    if voxels.ndim != expected_dimension:
        raise ValueError(f"Voxel array has {voxels.ndim} axes but {expected_dimension} are expected "
                         f"({'a component axis, ' if component else ''}{space_dimension} spatial axes{', a sequence axis' if sequence else ''})")

    ijk_to_lps = np.asarray(volume["ijkToLPS"], dtype=float)
    if space.upper() in ("LPS", "LEFT-POSTERIOR-SUPERIOR"):
        lps_to_space = np.eye(4)
        space_name = "left-posterior-superior"
    elif space.upper() in ("RAS", "RIGHT-ANTERIOR-SUPERIOR"):
        lps_to_space = _RAS_TO_LPS  # its own inverse
        space_name = "right-anterior-superior"
    else:
        raise ValueError("space must be 'LPS' or 'RAS'")
    ijk_to_space = lps_to_space @ ijk_to_lps

    header = OrderedDict()
    kinds = []
    directions = []
    labels = []
    units = []
    nan_row = [np.nan] * space_dimension
    if component:
        kinds.append(component.get("kind", "list"))
        directions.append(nan_row)
        labels.append(component.get("label") or "")
        units.append(component.get("unit") or "")
    for axis in range(space_dimension):
        kinds.append("domain")
        directions.append(list(ijk_to_space[0:space_dimension, axis]))
        labels.append("")
        units.append("")
    if sequence:
        kinds.append("list")
        directions.append(nan_row)
        labels.append(sequence.get("indexName") or "")
        units.append(sequence.get("indexUnit") or "")

    if space_dimension == 3:
        header["space"] = space_name
    else:
        header["space dimension"] = space_dimension
    header["kinds"] = kinds
    header["space directions"] = np.array(directions, dtype=float)
    header["space origin"] = ijk_to_space[0:space_dimension, 3]
    if any(labels):
        header["labels"] = labels
    if any(units):
        header["units"] = units
    if "measurementFrame" in volume:
        frame_lps = np.asarray(volume["measurementFrame"], dtype=float)
        header["measurement frame"] = lps_to_space[0:space_dimension, 0:space_dimension] @ frame_lps
    header["encoding"] = volume.get("encoding", "gzip")

    if sequence:
        sequence_axis = voxels.ndim - 1
        if sequence.get("indexType"):
            header[f"axis {sequence_axis} index type"] = sequence["indexType"]
        index_values = sequence.get("indexValues")
        if index_values is None:
            index_values = [str(i) for i in range(voxels.shape[-1])]
        if len(index_values) != voxels.shape[-1]:
            raise ValueError("The number of sequence index values does not match the number of frames")
        header[f"axis {sequence_axis} index values"] = " ".join(urllib.parse.quote(str(v), safe="") for v in index_values)
        for item_index, attributes in sequence.get("itemAttributes", {}).items():
            for name, value in attributes.items():
                header[f"axis {sequence_axis} item {int(item_index):04d} {name}"] = value

    if "displacementFieldType" in volume:
        header["displacement field type"] = volume["displacementFieldType"]
    if "intentCode" in volume:
        header["intent_code"] = str(volume["intentCode"])

    internal_keys = {"voxels", "ijkToLPS", "spaceDimension", "component", "measurementFrame", "sequence",
                     "displacementFieldType", "intentCode", "encoding"}
    for key, value in volume.items():
        if key in internal_keys or key in header:
            continue
        header[key] = value

    nrrd.write(filename, voxels, header, compression_level=compression_level, index_order="F")


def component_vectors_to_lps(volume):
    """Voxel array of a 3-component vector image with the vectors expressed in LPS coordinates.

    Applies the measurement frame (identity if not present). The returned array has the same axes as ``voxels``.
    """
    voxels = volume["voxels"]
    component = volume.get("component")
    if component is None or voxels.shape[0] != 3:
        raise ValueError("Volume is not a 3-component vector image")
    frame = np.asarray(volume.get("measurementFrame", np.eye(3)), dtype=float)
    if np.allclose(frame, np.eye(3)):
        return voxels
    return np.einsum("ij,j...->i...", frame, voxels.astype(np.float64))


def number_of_frames(volume):
    """Number of frames of a sequence (1 for a non-sequence volume)."""
    return volume["voxels"].shape[-1] if "sequence" in volume else 1


def sequence_frame(volume, frame_index):
    """Extract one frame of a sequence as a non-sequence volume dict (voxel data is not copied)."""
    if "sequence" not in volume:
        raise ValueError("Volume is not a sequence")
    frame = OrderedDict()
    for key, value in volume.items():
        if key == "voxels":
            frame[key] = value[..., frame_index] if value is not None else None
        elif key == "sequence":
            attributes = value.get("itemAttributes", {}).get(frame_index)
            if attributes:
                frame.update(attributes)
        else:
            frame[key] = value
    return frame


def create_sequence(frames, index_values=None, index_name="time", index_unit="s", index_type="numeric"):
    """Stack volumes of identical geometry into a sequence volume (time axis last)."""
    if not frames:
        raise ValueError("At least one frame is required")
    first = frames[0]
    for frame in frames[1:]:
        if frame["voxels"].shape != first["voxels"].shape or not np.allclose(frame["ijkToLPS"], first["ijkToLPS"]):
            raise ValueError("All frames must have the same shape and geometry")
    sequence = OrderedDict()
    for key, value in first.items():
        if key == "voxels":
            sequence["voxels"] = np.stack([frame["voxels"] for frame in frames], axis=-1)
        else:
            sequence[key] = value
    if index_values is None:
        index_values = [str(i) for i in range(len(frames))]
    sequence["sequence"] = OrderedDict([("indexName", index_name), ("indexUnit", index_unit), ("indexType", index_type),
                                        ("indexValues", [str(v) for v in index_values])])
    return sequence


def sample_volume(volume, points_lps, outside_value=0.0):
    """Trilinear (or bilinear for 2D) interpolation of a scalar or multi-component volume at physical points.

    :param points_lps: (N, 3) array of LPS coordinates
    :return: (N,) array for scalar volumes, (N, components) array for multi-component volumes
    """
    voxels = volume["voxels"]
    if "sequence" in volume:
        raise ValueError("Extract a frame with sequence_frame first")
    component = volume.get("component")
    space_dimension = int(volume.get("spaceDimension", 3))
    data = voxels if component else voxels[np.newaxis, ...]       # (c, i, j[, k])
    if space_dimension == 2:
        data = data[..., np.newaxis]                                  # (c, i, j, 1)
    data = np.moveaxis(data, 0, -1).astype(np.float64)                # (i, j, k, c)
    lps_to_ijk = np.linalg.inv(np.asarray(volume["ijkToLPS"], dtype=float))
    points = np.asarray(points_lps, dtype=float)
    ijk = points @ lps_to_ijk[0:3, 0:3].T + lps_to_ijk[0:3, 3]
    shape = np.array(data.shape[0:3])
    result = np.full((len(points), data.shape[3]), float(outside_value))
    inside = np.all((ijk >= -0.5) & (ijk <= shape - 0.5), axis=1)
    ijk = np.clip(ijk[inside], 0, shape - 1)
    base = np.floor(ijk).astype(int)
    base = np.minimum(base, np.maximum(shape - 2, 0))
    frac = ijk - base
    accumulated = np.zeros((len(ijk), data.shape[3]))
    for di in (0, 1):
        wi = frac[:, 0] if di else 1 - frac[:, 0]
        ii = np.minimum(base[:, 0] + di, shape[0] - 1)
        for dj in (0, 1):
            wj = frac[:, 1] if dj else 1 - frac[:, 1]
            jj = np.minimum(base[:, 1] + dj, shape[1] - 1)
            for dk in (0, 1):
                wk = frac[:, 2] if dk else 1 - frac[:, 2]
                kk = np.minimum(base[:, 2] + dk, shape[2] - 1)
                accumulated += (wi * wj * wk)[:, np.newaxis] * data[ii, jj, kk]
    result[inside] = accumulated
    return result if component else result[:, 0]


def apply_displacement_field(volume, displacement_field, reference=None, outside_value=0.0):
    """Resample an image through a displacement field, as Slicer does when a volume is "hardened" under a transform.

    The displacement field must be a resampling field (``displacementFieldType`` "resampling", the convention of
    Slicer and ITK): the output voxel at physical position ``p`` takes the input value interpolated at ``p + d(p)``,
    where ``d`` is the displacement (in LPS, trilinearly interpolated between grid points). Fields of type
    "modeling" (transform to parent) are not supported.

    :param volume: scalar 3D volume to resample (linear interpolation)
    :param displacement_field: 3-component vector volume, e.g. read from a Slicer displacement field .nrrd
    :param reference: volume whose grid is used for the output (default: the input volume)
    :return: volume dict on the reference grid with float64 voxels
    """
    if volume.get("component") or "sequence" in volume or int(volume.get("spaceDimension", 3)) != 3:
        raise ValueError("Only 3D scalar volumes can be resampled")
    field_type = displacement_field.get("displacementFieldType", "resampling")
    if field_type != "resampling":
        raise ValueError(f"Unsupported displacement field type '{field_type}' (only 'resampling' is supported)")
    reference = reference if reference is not None else volume
    shape = reference["voxels"].shape[-3:] if reference.get("component") is None else reference["voxels"].shape[1:4]
    ijk_to_lps = np.asarray(reference["ijkToLPS"], dtype=float)
    ii, jj, kk = np.meshgrid(np.arange(shape[0]), np.arange(shape[1]), np.arange(shape[2]), indexing="ij")
    ijk = np.column_stack([ii.ravel(), jj.ravel(), kk.ravel()]).astype(float)
    points = ijk @ ijk_to_lps[0:3, 0:3].T + ijk_to_lps[0:3, 3]
    field_lps = OrderedDict(displacement_field)
    field_lps["voxels"] = component_vectors_to_lps(displacement_field)
    displacements = sample_volume(field_lps, points, outside_value=0.0)
    values = sample_volume(volume, points + displacements, outside_value=outside_value)
    result = OrderedDict()
    for key, value in volume.items():
        if key == "voxels":
            result["voxels"] = values.reshape(shape)
        elif key == "ijkToLPS":
            result["ijkToLPS"] = ijk_to_lps.copy()
        else:
            result[key] = value
    return result
