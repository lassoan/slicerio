"""Check that every NRRD test data file of the slicerio ``TestingData`` release loads correctly in 3D Slicer.

This script must run inside 3D Slicer. It reads the data set manifest (``manifest_rev001.json`` of the GitHub release
by default, or a local copy), downloads any missing file into a data folder (verifying the SHA256 checksum), loads each file with the
loader the manifest names (volume / sequence / transform / segmentation), and checks node class, dimensions,
number of components, voxel vector type, frame/segment/layer counts, gradient counts and that LPS/RAS twin files
load to the same geometry. Headers are also re-read with pynrrd and compared with the manifest.

Run from the host with::

    python scripts/testing_data/run_in_slicer.py check_test_data_in_slicer.py                       # published release
    python scripts/testing_data/run_in_slicer.py check_test_data_in_slicer.py --manifest .testing_data/manifest_rev001.json

or directly: ``Slicer.exe --no-main-window --python-script check_test_data_in_slicer.py -- [options]``.
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request

import numpy as np
import nrrd
import vtk

import slicer
import slicer.util

MANIFEST_URL = "https://github.com/lassoan/slicerio/releases/download/TestingData/manifest_rev001.json"

VECTOR_TYPE_NAMES = {
    slicer.vtkMRMLVolumeNode.VoxelVectorTypeUndefined: "Undefined",
    slicer.vtkMRMLVolumeNode.VoxelVectorTypeSpatial: "Spatial",
    slicer.vtkMRMLVolumeNode.VoxelVectorTypeColorRGB: "ColorRGB",
    slicer.vtkMRMLVolumeNode.VoxelVectorTypeColorRGBA: "ColorRGBA",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(location):
    if location.startswith("http://") or location.startswith("https://"):
        with urllib.request.urlopen(location) as r:
            return json.loads(r.read().decode("utf-8"))
    with open(location) as f:
        return json.load(f)


def ensure_file(entry, data_dir, base_url):
    path = os.path.join(data_dir, entry["name"])
    if os.path.exists(path) and sha256(path) == entry["sha256"]:
        return path
    url = entry.get("url") or (base_url + entry["name"])
    print(f"downloading {url}")
    os.makedirs(data_dir, exist_ok=True)
    urllib.request.urlretrieve(url, path)
    actual = sha256(path)
    if actual != entry["sha256"]:
        raise RuntimeError(f"{entry['name']}: checksum mismatch ({actual} != {entry['sha256']})")
    return path


def ijk_to_ras(node):
    m = vtk.vtkMatrix4x4()
    node.GetIJKToRASMatrix(m)
    return np.array([[m.GetElement(r, c) for c in range(4)] for r in range(4)])


def header_matches(path, expected_header):
    """Compare the header fields recorded in the manifest with the file's actual header."""
    actual = nrrd.read_header(path)
    problems = []
    for key, value in expected_header.items():
        if key not in actual:
            problems.append(f"missing header field '{key}'")
            continue
        a = actual[key]
        if hasattr(a, "tolist"):
            a = a.tolist()
            a = [[None if (isinstance(x, float) and np.isnan(x)) else x for x in row] if isinstance(row, list)
                 else (None if (isinstance(row, float) and np.isnan(row)) else row) for row in a]
        if isinstance(value, list) and isinstance(a, list):
            try:
                equal = np.allclose(np.array(value, dtype=float), np.array(a, dtype=float), equal_nan=True)
            except (TypeError, ValueError):
                equal = value == a
        else:
            equal = value == a
        if not equal:
            problems.append(f"header field '{key}': file has {a!r}, manifest says {value!r}")
    return problems


class Checker:

    def __init__(self):
        self.results = []   # dict(name, passed, detail)
        self.geometry = {}  # file name -> IJK->RAS of the loaded node (for twin comparisons)
        self.notes = []

    def result(self, name, passed, detail):
        self.results.append({"file": name, "passed": bool(passed), "detail": detail})
        print(f"{'PASS' if passed else 'FAIL'}  {name}: {detail}")

    def check_entry(self, entry, path):
        expect = entry.get("expect", {})
        if expect.get("skip"):
            self.result(entry["name"], True, "companion data file, not loaded by itself")
            return
        problems = header_matches(path, entry.get("header", {}))
        loader = entry.get("slicer_loader")
        try:
            if loader == "volume":
                node = slicer.util.loadVolume(path, properties={"singleFile": True, "show": False})
                problems += self.check_volume(entry, node)
            elif loader == "sequence":
                node = slicer.util.loadSequence(path)
                problems += self.check_sequence(entry, node)
            elif loader == "transform":
                node = slicer.util.loadTransform(path)
                problems += self.check_transform(entry, node)
            elif loader == "segmentation":
                node = slicer.util.loadSegmentation(path)
                problems += self.check_segmentation(entry, node)
            else:
                problems.append(f"unknown loader {loader!r}")
                node = None
        except Exception as e:  # noqa: BLE001
            problems.append(f"loading failed: {e}")
            node = None
        detail = "; ".join(problems) if problems else self.describe(entry, node)
        self.result(entry["name"], not problems, detail)

    @staticmethod
    def describe(entry, node):
        if node is None:
            return "ok"
        cls = node.GetClassName()
        if node.IsA("vtkMRMLVolumeNode"):
            img = node.GetImageData()
            tensors = img.GetPointData().GetTensors()
            components = tensors.GetNumberOfComponents() if tensors is not None else img.GetNumberOfScalarComponents()
            return f"{cls} {img.GetDimensions()} x {components} {img.GetScalarTypeAsString()}"
        if node.IsA("vtkMRMLSequenceNode"):
            f = node.GetNthDataNode(0)
            if f.IsA("vtkMRMLTransformNode"):
                grid = f.GetTransformFromParentAs("vtkOrientedGridTransform")
                return f"{cls} {node.GetNumberOfDataNodes()} frames of {f.GetClassName()} (grid {grid.GetDisplacementGrid().GetDimensions()})"
            return f"{cls} {node.GetNumberOfDataNodes()} frames of {f.GetClassName()} {f.GetImageData().GetDimensions()}"
        if node.IsA("vtkMRMLSegmentationNode"):
            s = node.GetSegmentation()
            return f"{cls} {s.GetNumberOfSegments()} segments in {s.GetNumberOfLayers()} layer(s)"
        if node.IsA("vtkMRMLTransformNode"):
            return f"{cls} ({node.GetTransformFromParentAs('vtkOrientedGridTransform').GetClassName()})"
        return cls

    def check_volume(self, entry, node):
        expect = entry.get("expect", {})
        problems = []
        img = node.GetImageData()
        tensors = img.GetPointData().GetTensors()
        components = tensors.GetNumberOfComponents() if tensors is not None else img.GetNumberOfScalarComponents()
        if "node_class" in expect and node.GetClassName() != expect["node_class"]:
            problems.append(f"class {node.GetClassName()} != {expect['node_class']}")
        if "dimensions" in expect and list(img.GetDimensions()) != list(expect["dimensions"]):
            problems.append(f"dimensions {list(img.GetDimensions())} != {expect['dimensions']}")
        if "components" in expect and components != expect["components"]:
            problems.append(f"components {components} != {expect['components']}")
        problems += self.check_voxel_vector_type(expect, node)
        if "gradients" in expect and node.GetNumberOfGradients() != expect["gradients"]:
            problems.append(f"gradients {node.GetNumberOfGradients()} != {expect['gradients']}")
        self.geometry[entry["name"]] = ijk_to_ras(node)
        problems += self.check_twin_geometry(entry)
        return problems

    def check_voxel_vector_type(self, expect, node):
        """Older Slicer versions do not infer the voxel vector type (RGB/RGBA/spatial) from the NRRD kinds; that is
        reported as a note, not as a failure, because the file itself still loads correctly."""
        if "voxel_vector_type" not in expect:
            return []
        actual = VECTOR_TYPE_NAMES.get(node.GetVoxelVectorType())
        if actual == expect["voxel_vector_type"]:
            return []
        if actual == "Undefined":
            self.notes.append(f"{node.GetName()}: voxel vector type {expect['voxel_vector_type']} not inferred by this Slicer version")
            return []
        return [f"voxel vector type {actual} != {expect['voxel_vector_type']}"]

    def check_sequence(self, entry, node):
        expect = entry.get("expect", {})
        problems = []
        if "frames" in expect and node.GetNumberOfDataNodes() != expect["frames"]:
            problems.append(f"frames {node.GetNumberOfDataNodes()} != {expect['frames']}")
        frame = node.GetNthDataNode(0) if node.GetNumberOfDataNodes() else None
        if frame is None:
            return problems + ["sequence has no frames"]
        if "frame_class" in expect and frame.GetClassName() != expect["frame_class"]:
            problems.append(f"frame class {frame.GetClassName()} != {expect['frame_class']}")
        if frame.IsA("vtkMRMLTransformNode"):
            # displacement field sequence: frames are grid transforms
            return problems + self.check_transform(entry, frame)
        if "components" in expect and frame.GetImageData().GetNumberOfScalarComponents() != expect["components"]:
            problems.append(f"components {frame.GetImageData().GetNumberOfScalarComponents()} != {expect['components']}")
        problems += self.check_voxel_vector_type(expect, frame)
        self.geometry[entry["name"]] = ijk_to_ras(frame)
        problems += self.check_twin_geometry(entry)
        return problems

    def check_transform(self, entry, node):
        expect = entry.get("expect", {})
        problems = []
        if "node_class" in expect and node.GetClassName() != expect["node_class"]:
            problems.append(f"class {node.GetClassName()} != {expect['node_class']}")
        grid = node.GetTransformFromParentAs("vtkOrientedGridTransform")
        if grid is None:
            return problems + ["not a grid transform"]
        img = grid.GetDisplacementGrid()
        if "components" in expect and img.GetNumberOfScalarComponents() != expect["components"]:
            problems.append(f"components {img.GetNumberOfScalarComponents()} != {expect['components']}")
        # geometry of the displacement grid for twin comparison
        m = np.eye(4)
        d = vtk.vtkMatrix4x4()
        if grid.GetGridDirectionMatrix():
            d.DeepCopy(grid.GetGridDirectionMatrix())
        sp, org = img.GetSpacing(), img.GetOrigin()
        for r in range(3):
            for c in range(3):
                m[r, c] = d.GetElement(r, c) * sp[c]
            m[r, 3] = org[r]
        self.geometry[entry["name"]] = m
        problems += self.check_twin_geometry(entry)
        # sample the transform at a few points so that an unusable transform is caught
        b = [0.0] * 6
        img.GetBounds(b)
        p = grid.TransformPoint((b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2)
        if not all(np.isfinite(p)):
            problems.append("transform evaluates to non-finite values")
        return problems

    def check_segmentation(self, entry, node):
        expect = entry.get("expect", {})
        problems = []
        s = node.GetSegmentation()
        if "segments" in expect and s.GetNumberOfSegments() != expect["segments"]:
            problems.append(f"segments {s.GetNumberOfSegments()} != {expect['segments']}")
        if "layers" in expect and s.GetNumberOfLayers() != expect["layers"]:
            problems.append(f"layers {s.GetNumberOfLayers()} != {expect['layers']}")
        # geometry of the binary labelmap representation of the first segment
        ids = vtk.vtkStringArray()
        s.GetSegmentIDs(ids)
        if ids.GetNumberOfValues():
            lm = slicer.vtkOrientedImageData.SafeDownCast(s.GetSegmentRepresentation(ids.GetValue(0), "Binary labelmap"))
            if lm is not None:
                m = vtk.vtkMatrix4x4()
                lm.GetImageToWorldMatrix(m)
                self.geometry[entry["name"]] = np.array([[m.GetElement(r, c) for c in range(4)] for r in range(4)])
        problems += self.check_twin_geometry(entry)
        return problems

    def check_twin_geometry(self, entry):
        twin = entry.get("expect", {}).get("same_geometry_as")
        if not twin:
            return []
        if twin not in self.geometry or entry["name"] not in self.geometry:
            return [f"cannot compare geometry with {twin} (not loaded yet; keep files sorted so the LPS file comes first)"]
        if not np.allclose(self.geometry[twin], self.geometry[entry["name"]], atol=1e-3):
            return [f"geometry differs from {twin}"]
        return []


def main(argv):
    parser = argparse.ArgumentParser(description="Check slicerio NRRD test data in 3D Slicer")
    parser.add_argument("--manifest", default=MANIFEST_URL, help="manifest URL or local path (default: the published manifest_rev001.json)")
    parser.add_argument("--data-dir", default=None, help="folder holding (or receiving) the data files; default: next to a local manifest, "
                        "or <repository root>/.testing_data/downloaded for a remote manifest")
    parser.add_argument("--only", default=None, help="comma-separated list of file names to check")
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    if args.data_dir:
        data_dir = os.path.abspath(args.data_dir)   # Slicer's loaders resolve relative paths against Slicer's own working directory
    elif not args.manifest.startswith("http"):
        data_dir = os.path.dirname(os.path.abspath(args.manifest))
    else:
        data_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".testing_data", "downloaded"))
    only = set(args.only.split(",")) if args.only else None

    slicer.mrmlScene.Clear(False)
    checker = Checker()
    start = time.time()
    # Keep LPS originals before their twins: sort so that names without "_RAS" come first.
    entries = sorted(manifest["files"], key=lambda e: ("_RAS" in e["name"], e["name"]))
    for entry in entries:
        if only and entry["name"] not in only:
            continue
        try:
            path = ensure_file(entry, data_dir, manifest.get("base_url", ""))
        except Exception as e:  # noqa: BLE001
            checker.result(entry["name"], False, f"download failed: {e}")
            continue
        # companion files (e.g. detached raw data) must be present next to the header
        for companion in entry.get("companions", []):
            comp_entry = next((e for e in manifest["files"] if e["name"] == companion), None)
            if comp_entry:
                ensure_file(comp_entry, data_dir, manifest.get("base_url", ""))
        checker.check_entry(entry, path)

    failed = [r for r in checker.results if not r["passed"]]
    summary = f"{len(checker.results) - len(failed)}/{len(checker.results)} files OK in {time.time() - start:.0f} s"
    print(summary)
    return {"status": "ok" if not failed else "failed", "summary": summary, "results": checker.results, "notes": checker.notes,
            "manifest": args.manifest, "data_dir": data_dir, "slicer": slicer.app.applicationVersion}


if __name__ == "__main__":
    _argv = sys.argv[1:]
    if "--" in _argv:
        _argv = _argv[_argv.index("--") + 1:]
    __execResult = main(_argv)
