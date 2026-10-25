"""Generate NRRD test data sets with 3D Slicer.

This script must run inside 3D Slicer (tested with Slicer 5.13 / 2026-10). It downloads source data with the
SampleData module (and Visible Human cryosections from NLM), derives smaller but still realistic data sets of many
kinds (2D, 2D+t, color, 3D with anisotropic spacing and with oblique axes, 3D+t, displacement/velocity fields, segmentations, DWI, DTI, LPS and RAS), writes them
with Slicer's own file writers, verifies that every file round-trips (reload and compare) and that displacement
fields warp images exactly as the stored reference images, and finally writes ``manifest.json`` describing all
outputs. The output folder (``<repository root>/.testing_data`` by default, git-ignored) is meant to be uploaded as
assets of the ``TestingData`` GitHub release of slicerio.

Run it from the host with::

    python scripts/testing_data/run_in_slicer.py generate_test_data.py

or directly::

    Slicer.exe --no-main-window --python-script scripts/testing_data/generate_test_data.py -- --output <dir>

Options::

    --output DIR        output folder (default: <repository root>/.testing_data, git-ignored)
    --only A,B,...      generate only the listed groups (mrhead, visiblehuman, ctcardio, displacement, segmentation,
                        dwi, dti). The manifest is rebuilt from all files present in the output folder.
    --max-mb N          per-file size ceiling in MB (default 10); generation fails if a file is larger.
    --extra-module-paths A.py;B.py
                        load scripted modules from source files first (Elastix.py, SequenceRegistration.py) when the
                        SlicerElastix / SequenceRegistration extensions are not installed (the Elastix module must find
                        the elastix executables: set 'Elastix/CustomElastixPath' in the application settings if needed).

A few variants that Slicer cannot write itself (true 2D images, RAS-space twins, 6-component symmetric tensors)
are derived with pynrrd from the Slicer-written files; every derived file is still verified by loading it into
Slicer.
"""

import argparse
import datetime
import hashlib
import itertools
import json
import math
import os
import sys
import time
import urllib.request

import numpy as np
import nrrd
import vtk
from vtk.util import numpy_support

import slicer
import slicer.util
import SampleData

RELEASE_TAG = "TestingData"
RELEASE_BASE_URL = f"https://github.com/lassoan/slicerio/releases/download/{RELEASE_TAG}/"
VISIBLE_HUMAN_URL = "https://data.lhncbc.nlm.nih.gov/public/Visible-Human/Male-Images/PNG_format/head/"
# Output never goes next to the source files: default is the git-ignored .testing_data folder in the repository root
DEFAULT_OUTPUT_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".testing_data"))

HEADER_KEYS = ("type", "dimension", "space", "space dimension", "sizes", "kinds", "encoding", "endian",
               "space directions", "space origin", "spacings", "measurement frame", "data file",
               "labels", "units", "displacement field type", "intent_code", "DataNodeClassName",
               "axis 3 index type", "axis 3 index values", "axis 2 index type", "axis 2 index values",
               "modality", "DWMRI_b-value", "Segmentation_MasterRepresentation",
               "Segmentation_ContainedRepresentationNames", "Segmentation_ReferenceImageExtentOffset")


# ----------------------------------------------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------------------------------------------

class Generator:

    def __init__(self, output_dir, max_mb):
        self.output_dir = os.path.abspath(output_dir)
        self.cache_dir = os.path.join(self.output_dir, "cache")
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        self.max_bytes = int(max_mb * 1024 * 1024)
        self.sample_data = SampleData.SampleDataLogic()
        self.entries = {}   # file name -> manifest entry
        self.log_lines = []
        self.checks = []    # (name, passed, detail)
        self.notes = {}

    # ---- logging / checks ----
    def log(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line)
        self.log_lines.append(line)

    def check(self, name, condition, detail=""):
        self.checks.append((name, bool(condition), detail))
        if not condition:
            raise RuntimeError(f"CHECK FAILED: {name} {detail}")
        self.log(f"  ok: {name}" + (f" ({detail})" if detail else ""))

    # ---- files ----
    def path(self, filename):
        return os.path.join(self.output_dir, filename)

    @staticmethod
    def sha256(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def header_summary(path):
        h = nrrd.read_header(path)
        out = {}
        for k, v in h.items():
            if k in HEADER_KEYS or k.startswith("Segment") and (k.endswith("_Name") or k.endswith("_LabelValue") or k.endswith("_Layer")):
                if hasattr(v, "tolist"):
                    v = v.tolist()
                    # NaN is not valid JSON; the NRRD "none" direction becomes null
                    v = [[None if (isinstance(x, float) and math.isnan(x)) else x for x in row] if isinstance(row, list)
                         else (None if (isinstance(row, float) and math.isnan(row)) else row) for row in v]
                out[k] = v
        return out

    def record(self, filename, category, description, source, loader, coordinate_system="LPS", written_by="Slicer",
               expect=None, companions=None):
        """Register an output file in the manifest (size/hash/header are read from the file)."""
        p = self.path(filename)
        size = os.path.getsize(p)
        if size > self.max_bytes:
            raise RuntimeError(f"{filename} is {size/1e6:.1f} MB, above the {self.max_bytes/1e6:.0f} MB ceiling")
        entry = {
            "name": filename,
            "url": RELEASE_BASE_URL + filename,
            "category": category,
            "description": description,
            "source": source,
            "written_by": written_by,
            "coordinate_system": coordinate_system,
            "slicer_loader": loader,
            "size_bytes": size,
            "sha256": self.sha256(p),
            "header": self.header_summary(p) if filename.endswith((".nrrd", ".nhdr")) else {},
            "expect": expect or {},
        }
        if companions:
            entry["companions"] = companions
        self.entries[filename] = entry
        self.log(f"wrote {filename}: {size/1e6:.2f} MB, kinds={entry['header'].get('kinds')}, space={entry['header'].get('space', entry['header'].get('space dimension'))}")
        return entry

    def save(self, node, filename, compression=True):
        p = self.path(filename)
        ok = slicer.util.saveNode(node, p, properties={"useCompression": 1 if compression else 0})
        if not ok:
            raise RuntimeError(f"Failed to save {filename}")
        return p

    # ---- geometry / array helpers ----
    @staticmethod
    def ijk_to_ras(node):
        m = vtk.vtkMatrix4x4()
        node.GetIJKToRASMatrix(m)
        return np.array([[m.GetElement(r, c) for c in range(4)] for r in range(4)])

    @staticmethod
    def set_ijk_to_ras(node, matrix):
        m = vtk.vtkMatrix4x4()
        for r in range(4):
            for c in range(4):
                m.SetElement(r, c, float(matrix[r][c]))
        node.SetIJKToRASMatrix(m)

    @staticmethod
    def volume_array(node):
        """Voxel array as (k, j, i[, components]) numpy array, works for scalar, vector, DWI and DTI nodes."""
        img = node.GetImageData()
        pd = img.GetPointData()
        arr = pd.GetScalars() if pd.GetScalars() is not None else pd.GetTensors()
        a = numpy_support.vtk_to_numpy(arr)
        dims = img.GetDimensions()
        nc = arr.GetNumberOfComponents()
        shape = (dims[2], dims[1], dims[0]) + ((nc,) if nc > 1 else ())
        return a.reshape(shape)

    @staticmethod
    def make_image_data(array_kji, vtk_type=None):
        """vtkImageData from a (k, j, i[, c]) array."""
        a = np.ascontiguousarray(array_kji)
        nc = a.shape[3] if a.ndim == 4 else 1
        img = vtk.vtkImageData()
        img.SetDimensions(a.shape[2], a.shape[1], a.shape[0])
        flat = a.reshape(-1, nc) if nc > 1 else a.reshape(-1)
        varr = numpy_support.numpy_to_vtk(flat, deep=True, array_type=vtk_type)
        varr.SetNumberOfComponents(nc)
        img.GetPointData().SetScalars(varr)
        return img

    def new_volume(self, cls, name, array_kji, ijk_to_ras, vector_type=None):
        node = slicer.mrmlScene.AddNewNodeByClass(cls, name)
        node.SetAndObserveImageData(self.make_image_data(array_kji))
        self.set_ijk_to_ras(node, ijk_to_ras)
        if vector_type is not None:
            node.SetVoxelVectorType(vector_type)
        node.CreateDefaultDisplayNodes()
        return node

    def downsample_volume(self, node, factors, name=None, cls=None):
        """Resample a volume node (scalar or vector) by integer factors with linear interpolation.

        The result has the same physical extent; geometry is updated exactly from vtkImageResize's output spacing/origin.
        """
        img = node.GetImageData()
        dims = img.GetDimensions()
        resize = vtk.vtkImageResize()
        resize.SetInputData(img)
        resize.SetResizeMethodToOutputDimensions()
        resize.SetOutputDimensions([max(1, int(round(d / f))) for d, f in zip(dims, factors)])
        resize.InterpolateOn()
        resize.Update()
        out_img = vtk.vtkImageData()
        out_img.DeepCopy(resize.GetOutput())
        sp = out_img.GetSpacing()
        org = out_img.GetOrigin()
        out_img.SetSpacing(1, 1, 1)
        out_img.SetOrigin(0, 0, 0)
        local = np.array([[sp[0], 0, 0, org[0]], [0, sp[1], 0, org[1]], [0, 0, sp[2], org[2]], [0, 0, 0, 1]])
        new_ijk_to_ras = self.ijk_to_ras(node) @ local
        cls = cls or node.GetClassName()
        new_node = slicer.mrmlScene.AddNewNodeByClass(cls, name or (node.GetName() + "_down"))
        new_node.SetAndObserveImageData(out_img)
        self.set_ijk_to_ras(new_node, new_ijk_to_ras)
        if hasattr(node, "GetVoxelVectorType"):
            new_node.SetVoxelVectorType(node.GetVoxelVectorType())
        new_node.CreateDefaultDisplayNodes()
        return new_node

    # ---- pynrrd derived variants ----
    def ras_twin(self, src, dst, vector_mode=None):
        """Write an RAS-space twin of an LPS NRRD file (voxel values untouched unless vector_mode says otherwise).

        vector_mode: None (scalar/label data), "lps_components" (vector components stay LPS; measurement frame
        diag(-1,-1,1) maps them to the RAS space) or "ras_components" (x/y components negated, identity frame).
        """
        data, h = nrrd.read(self.path(src))
        h = dict(h)
        assert h["space"] == "left-posterior-superior", src
        h["space"] = "right-anterior-superior"
        sd = np.array(h["space directions"], dtype=float)
        sd[:, 0:2] *= -1
        h["space directions"] = sd
        so = np.array(h["space origin"], dtype=float)
        so[0:2] *= -1
        h["space origin"] = so
        if vector_mode == "lps_components":
            h["measurement frame"] = np.array([[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0]])
        elif vector_mode == "ras_components":
            data = data.copy()
            data[0:2, ...] *= -1
            h["measurement frame"] = np.eye(3)
        nrrd.write(self.path(dst), data, h)

    # ---- round-trip comparisons ----
    def compare_volume(self, name, node, filename, exact=True, loader="volume"):
        """Reload a saved volume and compare voxels + geometry with the node it was written from."""
        p = self.path(filename)
        if loader == "volume":
            reloaded = slicer.util.loadVolume(p, properties={"singleFile": True, "show": False})
        else:
            reloaded = slicer.util.loadNodeFromFile(p, loader, {"show": False})
        a0 = self.volume_array(node)
        a1 = self.volume_array(reloaded)
        self.check(f"{name}: class", reloaded.GetClassName() == node.GetClassName(), reloaded.GetClassName())
        self.check(f"{name}: shape", a0.shape == a1.shape, str(a1.shape))
        if exact:
            self.check(f"{name}: voxels identical", np.array_equal(a0, a1))
        else:
            self.check(f"{name}: voxels allclose", np.allclose(a0, a1, rtol=1e-5, atol=1e-5))
        self.check(f"{name}: IJK->RAS", np.allclose(self.ijk_to_ras(node), self.ijk_to_ras(reloaded), atol=1e-4))
        if node.IsA("vtkMRMLVectorVolumeNode"):
            self.check(f"{name}: voxel vector type", node.GetVoxelVectorType() == reloaded.GetVoxelVectorType(), str(reloaded.GetVoxelVectorType()))
        return reloaded

    def save_transform_sequence(self, seq, filename):
        """Write a sequence of grid transform nodes as a displacement field sequence (vtkMRMLTransformSequenceStorageNode)."""
        storage = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformSequenceStorageNode")
        storage.SetFileName(self.path(filename))
        storage.SetUseCompression(1)
        seq.SetAndObserveStorageNodeID(storage.GetID())
        if not storage.WriteData(seq):
            raise RuntimeError(f"Failed to save {filename}: {storage.GetUserMessages().GetAllMessagesAsString()}")
        return self.path(filename)

    @staticmethod
    def grid_array(transform_node):
        """Displacement vectors (k, j, i, 3) of the from-parent grid of a transform node, and the grid's IJK->RAS matrix."""
        grid = transform_node.GetTransformFromParentAs("vtkOrientedGridTransform")
        img = grid.GetDisplacementGrid()
        dims = img.GetDimensions()
        a = numpy_support.vtk_to_numpy(img.GetPointData().GetScalars()).reshape(dims[2], dims[1], dims[0], 3)
        m = np.eye(4)
        d = vtk.vtkMatrix4x4()
        if grid.GetGridDirectionMatrix():
            d.DeepCopy(grid.GetGridDirectionMatrix())
        sp, org = img.GetSpacing(), img.GetOrigin()
        for r in range(3):
            for c in range(3):
                m[r, c] = d.GetElement(r, c) * sp[c]
            m[r, 3] = org[r]
        return a, m

    def compare_sequence(self, name, seq, filename, exact=True):
        reloaded = slicer.util.loadSequence(self.path(filename))
        self.check(f"{name}: frame count", reloaded.GetNumberOfDataNodes() == seq.GetNumberOfDataNodes(), str(reloaded.GetNumberOfDataNodes()))
        for i in range(seq.GetNumberOfDataNodes()):
            f0, f1 = seq.GetNthDataNode(i), reloaded.GetNthDataNode(i)
            if f0.IsA("vtkMRMLTransformNode"):
                if not f1.IsA("vtkMRMLTransformNode"):
                    raise RuntimeError(f"CHECK FAILED: {name}: frame {i} reloaded as {f1.GetClassName()}, expected a transform node")
                a0, m0 = self.grid_array(f0)
                a1, m1 = self.grid_array(f1)
                if a0.shape != a1.shape or not np.allclose(a0, a1, atol=1e-4) or not np.allclose(m0, m1, atol=1e-4):
                    raise RuntimeError(f"CHECK FAILED: {name}: displacement grid of frame {i} differs after reload")
                if abs(float(seq.GetNthIndexValue(i)) - float(reloaded.GetNthIndexValue(i))) > 1e-9:
                    raise RuntimeError(f"CHECK FAILED: {name}: index value of frame {i} differs")
                continue
            a0, a1 = self.volume_array(f0), self.volume_array(f1)
            equal = np.array_equal(a0, a1) if exact else np.allclose(a0, a1, rtol=1e-5, atol=1e-5)
            if not equal or not np.allclose(self.ijk_to_ras(f0), self.ijk_to_ras(f1), atol=1e-4):
                raise RuntimeError(f"CHECK FAILED: {name}: frame {i} differs after reload")
            if abs(float(seq.GetNthIndexValue(i)) - float(reloaded.GetNthIndexValue(i))) > 1e-9:
                raise RuntimeError(f"CHECK FAILED: {name}: index value of frame {i} differs")
        self.check(f"{name}: all frames identical", True, f"{seq.GetNumberOfDataNodes()} frames")
        return reloaded

    def transform_points(self, transform_node, points):
        t = transform_node.GetTransformFromParent()
        return np.array([t.TransformPoint(p) for p in points])

    def sample_points(self, volume_node, n=300, seed=0):
        b = [0.0] * 6
        volume_node.GetRASBounds(b)
        rng = np.random.default_rng(seed)
        return np.column_stack([rng.uniform(b[0], b[1], n), rng.uniform(b[2], b[3], n), rng.uniform(b[4], b[5], n)])

    def resample_through_transform(self, volume_node, transform_node, reference_node, name):
        """Resample volume_node through transform_node onto the grid of reference_node (linear interpolation).

        Uses Slicer's "Resample Scalar/Vector/DWI Volume" CLI; the transform is applied as a resampling transform
        (output voxel at position p takes the input value at T(p), ITK convention, same as Slicer's "Harden transform").
        """
        out = slicer.mrmlScene.AddNewNodeByClass(volume_node.GetClassName(), name)
        params = {"inputVolume": volume_node.GetID(), "outputVolume": out.GetID(), "referenceVolume": reference_node.GetID(),
                  "transformationFile": transform_node.GetID(), "interpolationType": "linear"}
        cli = slicer.cli.runSync(slicer.modules.resamplescalarvectordwivolume, None, params)
        if cli.GetStatusString() != "Completed":
            raise RuntimeError(f"Resampling failed: {cli.GetStatusString()}: {cli.GetErrorText()}")
        slicer.mrmlScene.RemoveNode(cli)
        out.CreateDefaultDisplayNodes()
        return out

    def resample_to_spacing(self, volume_node, spacing, name):
        """Resample a scalar volume to a new voxel spacing (linear interpolation, ResampleScalarVolume CLI)."""
        out = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", name)
        params = {"InputVolume": volume_node.GetID(), "OutputVolume": out.GetID(),
                  "outputPixelSpacing": ",".join(str(x) for x in spacing), "interpolationType": "linear"}
        cli = slicer.cli.runSync(slicer.modules.resamplescalarvolume, None, params)
        if cli.GetStatusString() != "Completed":
            raise RuntimeError(f"Resampling failed: {cli.GetStatusString()}: {cli.GetErrorText()}")
        slicer.mrmlScene.RemoveNode(cli)
        out.CreateDefaultDisplayNodes()
        return out

    def resample_to_reference(self, volume_node, reference_node, name):
        """Resample a volume onto the grid of reference_node without any transform (linear interpolation)."""
        out = slicer.mrmlScene.AddNewNodeByClass(volume_node.GetClassName(), name)
        params = {"inputVolume": volume_node.GetID(), "outputVolume": out.GetID(), "referenceVolume": reference_node.GetID(),
                  "interpolationType": "linear"}
        cli = slicer.cli.runSync(slicer.modules.resamplescalarvectordwivolume, None, params)
        if cli.GetStatusString() != "Completed":
            raise RuntimeError(f"Resampling failed: {cli.GetStatusString()}: {cli.GetErrorText()}")
        slicer.mrmlScene.RemoveNode(cli)
        out.CreateDefaultDisplayNodes()
        return out

    def make_oblique_copy(self, volume_node, angles_deg, name):
        """Resample volume_node onto a grid with the same spacing but rotated (still orthogonal) axes.

        The new grid is centered on the original volume and cropped to the largest box that fits inside it, so no
        padding is needed and the physical content is identical to the axis-aligned volume (same location and
        orientation of the anatomy; only the sampling grid is oblique).
        """
        m = self.ijk_to_ras(volume_node)
        dims = np.array(volume_node.GetImageData().GetDimensions(), dtype=float)
        spacing = np.linalg.norm(m[:3, :3], axis=0)
        dirs = m[:3, :3] / spacing
        rot = vtk.vtkTransform()
        rot.RotateX(angles_deg[0])
        rot.RotateY(angles_deg[1])
        rot.RotateZ(angles_deg[2])
        r = np.array([[rot.GetMatrix().GetElement(i, j) for j in range(3)] for i in range(3)])
        new_dirs = r @ dirs
        half = spacing * (dims - 1) / 2.0                    # physical half extents of the original box (voxel centers)
        q = np.abs(dirs.T @ new_dirs)                        # rotated axes expressed in the original axis frame
        scale = min(half[a] / float(q[a] @ half) for a in range(3)) * 0.98
        new_dims = np.floor(2 * scale * half / spacing).astype(int) + 1
        new_half = spacing * (new_dims - 1) / 2.0
        center = (m @ np.array([(dims[0] - 1) / 2, (dims[1] - 1) / 2, (dims[2] - 1) / 2, 1.0]))[:3]
        origin = center - new_dirs @ new_half
        new_m = np.eye(4)
        new_m[:3, :3] = new_dirs * spacing
        new_m[:3, 3] = origin
        # all corners of the new grid must lie inside the original volume (no padding)
        inv = np.linalg.inv(m)
        for ci, cj, ck in itertools.product([0, new_dims[0] - 1], [0, new_dims[1] - 1], [0, new_dims[2] - 1]):
            ijk = inv @ (new_m @ np.array([ci, cj, ck, 1.0]))
            if np.any(ijk[:3] < -1e-6) or np.any(ijk[:3] > dims - 1 + 1e-6):
                raise RuntimeError("oblique grid is not inside the original volume")
        reference = self.new_volume("vtkMRMLScalarVolumeNode", name + "_grid", np.zeros((new_dims[2], new_dims[1], new_dims[0]), np.uint8), new_m)
        oblique = self.resample_to_reference(volume_node, reference, name)
        slicer.mrmlScene.RemoveNode(reference)
        return oblique

    # ------------------------------------------------------------------------------------------------------------
    # Group 1: MRHead scalar variants (3D LPS/RAS, raw, detached header, 2D)
    # ------------------------------------------------------------------------------------------------------------
    def generate_mrhead(self):
        self.log("== MRHead ==")
        native = self.sample_data.downloadSample("MRHead")
        native.SetName("MRHead_native")
        # Anisotropic spacing (every axis differs by >= 20%) so that axis-order mistakes in readers are detectable
        spacing = (1.0, 1.25, 1.6)
        mr = self.resample_to_spacing(native, spacing, "MRHead")
        dims = list(mr.GetImageData().GetDimensions())
        src = (f"3D Slicer SampleData 'MRHead' (MR-head.nrrd, T1 MRI of a head, 256x256x130 @ 1x1x1.3 mm) resampled by Slicer to "
               f"anisotropic {spacing[0]}x{spacing[1]}x{spacing[2]} mm spacing ({dims[0]}x{dims[1]}x{dims[2]} voxels)")
        self.mrhead = mr
        self.mrhead_source = src

        self.save(mr, "MRHead_3D.nrrd")
        self.record("MRHead_3D.nrrd", "3D", "3D scalar volume (short), gzip encoding, anisotropic spacing", src, "volume",
                    expect={"node_class": "vtkMRMLScalarVolumeNode", "dimensions": dims, "components": 1})
        self.compare_volume("MRHead_3D", mr, "MRHead_3D.nrrd")

        # RAS twin (header only)
        self.ras_twin("MRHead_3D.nrrd", "MRHead_3D_RAS.nrrd")
        self.record("MRHead_3D_RAS.nrrd", "3D", "Same voxels as MRHead_3D.nrrd with the geometry expressed in RAS space "
                    "(space directions/origin x,y negated); must load at the identical position", src, "volume",
                    coordinate_system="RAS", written_by="pynrrd (from MRHead_3D.nrrd)",
                    expect={"node_class": "vtkMRMLScalarVolumeNode", "dimensions": dims, "components": 1, "same_geometry_as": "MRHead_3D.nrrd"})
        self.compare_volume("MRHead_3D_RAS", mr, "MRHead_3D_RAS.nrrd")

        # oblique copy: same physical content on a rotated (orthogonal) grid cropped inside the original volume
        angles = (20.0, 10.0, -5.0)
        oblique = self.make_oblique_copy(mr, angles, "MRHead_oblique")
        self.mrhead_oblique = oblique
        odims = list(oblique.GetImageData().GetDimensions())
        self.oblique_source = (f"MRHead_3D.nrrd resampled by Slicer onto an oblique grid (axes rotated by {angles[0]}, {angles[1]}, {angles[2]} degrees "
                               f"about the R, A, S axes, same spacing, {odims[0]}x{odims[1]}x{odims[2]} voxels, cropped to lie inside the original volume)")
        self.save(oblique, "MRHead_3D_oblique.nrrd")
        self.record("MRHead_3D_oblique.nrrd", "3D (oblique)", "3D scalar volume with oblique axes (non-axis-aligned 'space directions', still orthogonal). "
                    "Same anatomy at the same physical location as MRHead_3D.nrrd, so the two can be compared after resampling; no padding voxels",
                    self.oblique_source, "volume", expect={"node_class": "vtkMRMLScalarVolumeNode", "dimensions": odims, "components": 1})
        self.compare_volume("MRHead_3D_oblique", oblique, "MRHead_3D_oblique.nrrd")
        # the oblique volume resampled back onto the axis-aligned grid must agree with the original inside its footprint
        back = self.resample_to_reference(oblique, mr, "MRHead_oblique_back")
        a_mr, a_back = self.volume_array(mr).astype(np.float64), self.volume_array(back).astype(np.float64)
        inside = a_back != 0
        diff = np.abs(a_mr - a_back)[inside]
        self.check("MRHead_3D_oblique: physical content matches MRHead_3D (median abs diff after resampling back < 10)", float(np.median(diff)) < 10,
                   f"median {np.median(diff):.1f}, 95th percentile {np.percentile(diff, 95):.1f}, {inside.mean()*100:.0f}% of voxels covered")

        # downsampled copy for the uncompressed variants
        mr2 = self.downsample_volume(mr, (2, 2, 2), "MRHead_down2")
        self.save(mr2, "MRHead_3D_raw.nrrd", compression=False)
        self.record("MRHead_3D_raw.nrrd", "3D", "3D scalar volume, raw (uncompressed) encoding, 2x downsampled", src, "volume",
                    expect={"node_class": "vtkMRMLScalarVolumeNode", "components": 1, "encoding": "raw"})
        self.compare_volume("MRHead_3D_raw", mr2, "MRHead_3D_raw.nrrd")
        self.save(mr2, "MRHead_3D_detached.nhdr")
        self.record("MRHead_3D_detached.nhdr", "3D", "Detached NRRD header; voxel data in MRHead_3D_detached.raw.gz (gzip), 2x downsampled", src, "volume",
                    expect={"node_class": "vtkMRMLScalarVolumeNode", "components": 1},
                    companions=["MRHead_3D_detached.raw.gz"])
        self.record("MRHead_3D_detached.raw.gz", "3D", "Voxel data of MRHead_3D_detached.nhdr (not a standalone file)", src, None,
                    expect={"skip": True})
        self.compare_volume("MRHead_3D_detached", mr2, "MRHead_3D_detached.nhdr")

        # true 2D slice (dimension 2, 2D space)
        data, h = nrrd.read(self.path("MRHead_3D.nrrd"))
        # MRHead is sagittally acquired: file axis 2 (k) is the left-right direction; take the mid-sagittal slice
        # of the file axes 0 and 1 (anisotropic in-plane spacing).
        k = data.shape[2] // 2
        sl = np.ascontiguousarray(data[:, :, k])
        sp = [float(np.linalg.norm(h["space directions"][0])), float(np.linalg.norm(h["space directions"][1]))]
        h2 = {"type": "short", "dimension": 2, "space dimension": 2, "sizes": list(sl.shape), "kinds": ["domain", "domain"],
              "space directions": np.array([[sp[0], 0.0], [0.0, sp[1]]]), "space origin": np.array([0.0, 0.0]),
              "encoding": "gzip"}
        nrrd.write(self.path("MRHead_2D.nrrd"), sl, h2)
        self.record("MRHead_2D.nrrd", "2D", f"True 2D image (dimension: 2) - slice {k} of file axis 2 of MRHead_3D.nrrd, {sp[0]}x{sp[1]} mm pixels; "
                    "2D space (space dimension: 2) because a 3D 'space' with two domain axes is rejected by ITK/Slicer",
                    src, "volume", coordinate_system="2D", written_by="pynrrd (from MRHead_3D.nrrd)",
                    expect={"node_class": "vtkMRMLScalarVolumeNode", "dimensions": [sl.shape[0], sl.shape[1], 1], "components": 1})
        n2d = slicer.util.loadVolume(self.path("MRHead_2D.nrrd"), properties={"singleFile": True, "show": False})
        self.check("MRHead_2D: loads as a single slice", tuple(n2d.GetImageData().GetDimensions()) == (sl.shape[0], sl.shape[1], 1))
        self.check("MRHead_2D: voxels identical", np.array_equal(self.volume_array(n2d)[0].T, sl))

    # ------------------------------------------------------------------------------------------------------------
    # Group 2: Visible Human color (RGB / RGBA, 3D and 2D)
    # ------------------------------------------------------------------------------------------------------------
    def download_visible_human_slice(self, index):
        filename = f"a_vm{index}.png"
        p = os.path.join(self.cache_dir, "visible_human", filename)
        if not os.path.exists(p) or os.path.getsize(p) < 100000:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            self.log(f"  downloading {filename}")
            urllib.request.urlretrieve(VISIBLE_HUMAN_URL + filename, p)
        return p

    @staticmethod
    def read_png(path):
        r = vtk.vtkPNGReader()
        r.SetFileName(path)
        r.Update()
        img = r.GetOutput()
        dims = img.GetDimensions()
        a = numpy_support.vtk_to_numpy(img.GetPointData().GetScalars()).reshape(dims[1], dims[0], -1)
        return a[::-1, :, :3]  # VTK stores rows bottom-up; return top-down rows, drop alpha if any

    @staticmethod
    def body_mask(rgb):
        """Tissue mask of a Visible Human cryosection: not the blue gel/black background. Returns uint8 0/255."""
        import scipy.ndimage as ndi
        r, g, b = (rgb[..., i].astype(np.int16) for i in range(3))
        blue = (b > r + 15) & (b > g - 5)
        dark = rgb.max(axis=2) < 45
        mask = ~(blue | dark)
        mask = ndi.binary_opening(mask, iterations=2)
        mask = ndi.binary_closing(mask, iterations=3)
        mask = ndi.binary_fill_holes(mask)
        # keep the largest connected component (the body), drop labels/markers
        lab, n = ndi.label(mask)
        if n > 1:
            sizes = ndi.sum(mask, lab, range(1, n + 1))
            mask = lab == (1 + int(np.argmax(sizes)))
        return (mask.astype(np.uint8) * 255)

    @staticmethod
    def block_mean(a, f):
        """Downsample a (rows, cols, c) image by integer factor f with block averaging."""
        rows = (a.shape[0] // f) * f
        cols = (a.shape[1] // f) * f
        a = a[:rows, :cols].astype(np.float32)
        a = a.reshape(rows // f, f, cols // f, f, -1).mean(axis=(1, 3))
        return np.clip(np.round(a), 0, 255).astype(np.uint8)

    def generate_visible_human(self):
        self.log("== Visible Human head (RGB/RGBA) ==")
        # Crop box (pixels of the 2048x1216 frame) containing the head in slices 1001-1240; excludes the gray scale and labels.
        x0, x1, y0, y1 = 620, 1380, 180, 980
        first, last, step = 1001, 1240, 3
        down = 4
        pixel_mm = 0.33
        slice_mm = 1.0
        indices = list(range(first, last + 1, step))
        src = (f"NLM Visible Human Project, male cryosections a_vm{first}.png..a_vm{last}.png (every {step}rd slice), "
               f"cropped to the head (pixels x {x0}-{x1}, y {y0}-{y1}) and {down}x block-averaged. "
               "Courtesy of the U.S. National Library of Medicine.")
        rgb_frames, alpha_frames = [], []
        full_res_slice = None
        full_res_alpha = None
        middle_index = indices[len(indices) // 2]
        for idx in indices:
            a = self.read_png(self.download_visible_human_slice(idx))[y0:y1, x0:x1]
            m = self.body_mask(a)
            if idx == middle_index:
                full_res_slice, full_res_alpha = a.copy(), m.copy()
            rgb_frames.append(self.block_mean(a, down))
            alpha_frames.append(self.block_mean(m[..., None], down)[..., 0])
        rgb = np.stack(rgb_frames)                           # (k, j, i, 3)
        alpha = np.stack(alpha_frames)                       # (k, j, i)
        rgba = np.concatenate([rgb, alpha[..., None]], axis=-1)
        # Geometry: image columns run patient right -> left (viewed from the feet, anterior at the bottom of the
        # photo), rows run posterior -> anterior, slice numbers increase towards the feet.
        s = pixel_mm * down
        dz = slice_mm * step
        nk, nj, ni = rgb.shape[:3]
        # IJK->RAS: i -> -R (towards L), j -> +A, k -> -S; origin so that the volume is centered near (0,0,0)
        m = np.array([[-s, 0, 0, s * (ni - 1) / 2.0],
                      [0, s, 0, -s * (nj - 1) / 2.0],
                      [0, 0, -dz, dz * (nk - 1) / 2.0],
                      [0, 0, 0, 1]])
        vh_rgb = self.new_volume("vtkMRMLVectorVolumeNode", "VisibleHumanHead_RGB", rgb, m, slicer.vtkMRMLVolumeNode.VoxelVectorTypeColorRGB)
        vh_rgba = self.new_volume("vtkMRMLVectorVolumeNode", "VisibleHumanHead_RGBA", rgba, m, slicer.vtkMRMLVolumeNode.VoxelVectorTypeColorRGBA)
        self.save(vh_rgb, "VisibleHumanHead_3D_RGB.nrrd")
        self.record("VisibleHumanHead_3D_RGB.nrrd", "3D+RGB", f"3D RGB color volume (unsigned char, 3 components), {ni}x{nj}x{nk} @ {s:.2f}x{s:.2f}x{dz:.0f} mm",
                    src, "volume", expect={"node_class": "vtkMRMLVectorVolumeNode", "components": 3, "voxel_vector_type": "ColorRGB"})
        self.compare_volume("VisibleHumanHead_3D_RGB", vh_rgb, "VisibleHumanHead_3D_RGB.nrrd")
        self.save(vh_rgba, "VisibleHumanHead_3D_RGBA.nrrd")
        self.record("VisibleHumanHead_3D_RGBA.nrrd", "3D+RGBA", "3D RGBA color volume (unsigned char, 4 components); alpha = tissue mask "
                    "(0 in the blue embedding gel and black background, 255 in the body)", src, "volume",
                    expect={"node_class": "vtkMRMLVectorVolumeNode", "components": 4, "voxel_vector_type": "ColorRGBA"})
        self.compare_volume("VisibleHumanHead_3D_RGBA", vh_rgba, "VisibleHumanHead_3D_RGBA.nrrd")

        # 2D color slices at full 0.33 mm resolution (true 2D: dimension 3 = color axis + two domain axes)
        src2d = (f"NLM Visible Human Project, male cryosection a_vm{middle_index}.png cropped to the head at full 0.33 mm resolution. "
                 "Courtesy of the U.S. National Library of Medicine.")
        sl = np.ascontiguousarray(np.transpose(full_res_slice, (2, 1, 0)))        # (c, i, j) for pynrrd (Fortran order)
        h = {"type": "unsigned char", "dimension": 3, "space dimension": 2, "sizes": list(sl.shape),
             "kinds": ["RGB-color", "domain", "domain"],
             "space directions": np.array([[np.nan, np.nan], [pixel_mm, 0.0], [0.0, pixel_mm]]),
             "space origin": np.array([0.0, 0.0]), "encoding": "gzip"}
        nrrd.write(self.path("VisibleHumanHead_2D_RGB.nrrd"), sl, h)
        self.record("VisibleHumanHead_2D_RGB.nrrd", "2D+RGB", "True 2D RGB image (dimension: 3 = RGB-color + 2 domain axes, 2D space)", src2d,
                    "volume", coordinate_system="2D", written_by="pynrrd",
                    expect={"node_class": "vtkMRMLVectorVolumeNode", "components": 3, "voxel_vector_type": "ColorRGB", "dimensions": [sl.shape[1], sl.shape[2], 1]})
        n = slicer.util.loadVolume(self.path("VisibleHumanHead_2D_RGB.nrrd"), properties={"singleFile": True, "show": False})
        self.check("VisibleHumanHead_2D_RGB: loads as RGB vector volume", n.GetVoxelVectorType() == slicer.vtkMRMLVolumeNode.VoxelVectorTypeColorRGB and n.GetImageData().GetNumberOfScalarComponents() == 3)
        self.check("VisibleHumanHead_2D_RGB: voxels identical", np.array_equal(np.transpose(self.volume_array(n)[0], (2, 1, 0)), sl))
        sla = np.ascontiguousarray(np.transpose(np.concatenate([full_res_slice, full_res_alpha[..., None]], axis=-1), (2, 1, 0)))
        h["sizes"] = list(sla.shape)
        h["kinds"] = ["RGBA-color", "domain", "domain"]
        nrrd.write(self.path("VisibleHumanHead_2D_RGBA.nrrd"), sla, h)
        self.record("VisibleHumanHead_2D_RGBA.nrrd", "2D+RGBA", "True 2D RGBA image (RGBA-color + 2 domain axes, 2D space); alpha = tissue mask", src2d,
                    "volume", coordinate_system="2D", written_by="pynrrd",
                    expect={"node_class": "vtkMRMLVectorVolumeNode", "components": 4, "voxel_vector_type": "ColorRGBA", "dimensions": [sla.shape[1], sla.shape[2], 1]})
        n = slicer.util.loadVolume(self.path("VisibleHumanHead_2D_RGBA.nrrd"), properties={"singleFile": True, "show": False})
        self.check("VisibleHumanHead_2D_RGBA: loads as RGBA vector volume", n.GetVoxelVectorType() == slicer.vtkMRMLVolumeNode.VoxelVectorTypeColorRGBA and n.GetImageData().GetNumberOfScalarComponents() == 4)
        self.check("VisibleHumanHead_2D_RGBA: voxels identical", np.array_equal(np.transpose(self.volume_array(n)[0], (2, 1, 0)), sla))

    # ------------------------------------------------------------------------------------------------------------
    # Group 3: CT cardiac time series (3D+t, 2D+t) and derived 3D+t displacement / velocity sequences
    # ------------------------------------------------------------------------------------------------------------
    def make_sequence(self, name, frames, index_values, index_name="time", index_unit="s"):
        seq = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", name)
        seq.SetIndexName(index_name)
        seq.SetIndexUnit(index_unit)
        seq.SetIndexType(seq.NumericIndex)
        for frame, value in zip(frames, index_values):
            seq.SetDataNodeAtValue(frame, str(value))
        return seq

    def generate_ctcardio(self):
        self.log("== CT cardio sequence ==")
        nodes = self.sample_data.downloadSamples("CTCardioSeq")
        src_seq = [n for n in nodes if n.IsA("vtkMRMLSequenceNode")][0]
        n_frames_src = src_seq.GetNumberOfDataNodes()
        selected = list(range(0, n_frames_src, 2))  # 5 of the 10 cardiac phases
        frame_period_s = 0.1
        src = (f"3D Slicer SampleData 'CTCardioSeq' (CT-cardio.seq.nrrd, 4D cardiac CT, 10 phases, 128x104x72 @ 1.15x1.15x2 mm); "
               f"phases {selected} re-saved by Slicer")
        # Copy the selected frames into scene nodes (sequence data nodes live in the sequence's private scene and cannot be
        # used directly by CLI modules).
        frames = []
        for i in selected:
            frame = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", f"CTCardio_frame_{i}")
            frame.CopyContent(src_seq.GetNthDataNode(i))
            frame.CreateDefaultDisplayNodes()
            frames.append(frame)
        times = [round(i * frame_period_s, 3) for i in range(len(frames))]
        seq = self.make_sequence("CTCardio_3Dt", frames, times)
        self.save(seq, "CTCardio_3Dt.seq.nrrd")
        self.record("CTCardio_3Dt.seq.nrrd", "3D+t", f"3D+t scalar volume sequence (short), {len(frames)} frames; time axis is the last "
                    "('list') axis, frame times in 'axis 3 index values'", src, "sequence",
                    expect={"frames": len(frames), "frame_class": "vtkMRMLScalarVolumeNode", "components": 1})
        self.compare_sequence("CTCardio_3Dt", seq, "CTCardio_3Dt.seq.nrrd")

        # 2D+t (true 2D frames): one axial slice of each frame
        data, h = nrrd.read(self.path("CTCardio_3Dt.seq.nrrd"))   # (i, j, k, t)
        k = data.shape[2] // 2
        sl = np.ascontiguousarray(data[:, :, k, :])
        sp = [float(np.linalg.norm(h["space directions"][0])), float(np.linalg.norm(h["space directions"][1]))]
        h2 = {"type": "short", "dimension": 3, "space dimension": 2, "sizes": list(sl.shape), "kinds": ["domain", "domain", "list"],
              "space directions": np.array([[sp[0], 0.0], [0.0, sp[1]], [np.nan, np.nan]]), "space origin": np.array([0.0, 0.0]),
              "labels": ["", "", "time"], "units": ["", "", "s"], "encoding": "gzip",
              "axis 2 index type": "numeric", "axis 2 index values": " ".join(str(t) for t in times)}
        nrrd.write(self.path("CTCardio_2Dt.seq.nrrd"), sl, h2)
        self.record("CTCardio_2Dt.seq.nrrd", "2D+t", f"True 2D+t: axial slice {k} of every frame of CTCardio_3Dt.seq.nrrd (2 domain axes + "
                    "a 'list' time axis, 2D space). Slicer loads it as a single multi-component vector volume (one component per frame), "
                    "not as a sequence.", src, "volume", coordinate_system="2D", written_by="pynrrd (from CTCardio_3Dt.seq.nrrd)",
                    expect={"node_class": "vtkMRMLVectorVolumeNode", "components": len(frames), "dimensions": [sl.shape[0], sl.shape[1], 1]})
        n = slicer.util.loadVolume(self.path("CTCardio_2Dt.seq.nrrd"), properties={"singleFile": True, "show": False})
        self.check("CTCardio_2Dt: loads as vector volume with one component per frame",
                   n.GetImageData().GetNumberOfScalarComponents() == len(frames) and tuple(n.GetImageData().GetDimensions()) == (sl.shape[0], sl.shape[1], 1))
        self.check("CTCardio_2Dt: voxels identical", np.array_equal(np.transpose(self.volume_array(n)[0], (1, 0, 2)), sl))

        # ---- displacement field sequence from image registration + motion-compensated reference frames + velocity sequence
        self.log("== CT cardio 3D+t displacement (SequenceRegistration) / velocity ==")
        frame0 = frames[0]
        ref = self.downsample_volume(frame0, (2, 2, 2), "CTCardio_frame0_down2")   # displacement grid geometry (2.3x2.3x4 mm)
        b = [0.0] * 6
        frame0.GetRASBounds(b)
        center = np.array([(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2])
        half = np.array([(b[1] - b[0]) / 2, (b[3] - b[2]) / 2, (b[5] - b[4]) / 2])
        tl = slicer.modules.transforms.logic()
        transform_seq, preset_name = self.register_sequence(seq, fixed_item=0)
        disp_frames, warped_frames, vel_frames, grids = [], [], [], []
        for i, t in enumerate(times):
            phase = 2 * math.pi * i / len(times)
            # Registration result for frame i: transform from the fixed frame (0) to frame i, stored by the Elastix module as
            # a grid transform ("from parent" = resampling transform). Resample it onto the coarser displacement grid.
            grid = tl.ConvertToGridTransform(transform_seq.GetNthDataNode(i), ref)
            grid.SetName(f"CTCardio_grid_{i}")
            grids.append(grid)
            gdims = grid.GetTransformFromParentAs("vtkOrientedGridTransform").GetDisplacementGrid().GetDimensions()
            if tuple(gdims) != tuple(ref.GetImageData().GetDimensions()):
                raise RuntimeError(f"unexpected grid dimensions {gdims}")
            disp_frames.append(grid)
            # Motion-compensated frame: frame i resampled through its displacement field onto the grid of frame 0
            warped_frames.append(self.resample_through_transform(frames[i], grid, frame0, f"CTCardio_warped_{i}"))
            vel_frames.append(self.make_velocity_volume(ref, center, half, f"CTCardio_vel_{i}", scale=1.0 + 0.5 * math.sin(phase), swirl=phase))
        # registration quality: motion-compensated frames must be closer to frame 0 than the original frames
        a0 = self.volume_array(frame0).astype(np.float64)
        for i in range(1, len(times)):
            before = float(np.abs(self.volume_array(frames[i]).astype(np.float64) - a0).mean())
            after = float(np.abs(self.volume_array(warped_frames[i]).astype(np.float64) - a0).mean())
            self.check(f"CTCardio registration frame {i}: mean abs difference to frame 0 reduced", after < before, f"{before:.1f} -> {after:.1f} HU")
        disp_seq = self.make_sequence("CTCardio_3Dt_displacement", disp_frames, times)
        # A sequence of grid transform nodes is written by Slicer's transform sequence storage node, which adds the
        # same key/value fields as the Transforms module does for a single displacement field: NIfTI intent code 1006
        # (NIFTI_INTENT_DISPVECT) and the transform direction ('displacement field type').
        self.save_transform_sequence(disp_seq, "CTCardio_3Dt_displacement.seq.nrrd")
        src_d = (f"Image registration of CTCardio_3Dt.seq.nrrd with the SequenceRegistration Slicer extension (Elastix, preset '{preset_name}'), "
                 "fixed frame 0, moving frames 1..n; the resulting transforms (fixed -> moving, i.e. resampling transforms) sampled on the 2x "
                 "downsampled grid of frame 0; vectors are 'resampling' displacements (from parent) in LPS; frame 0 is the identity (zero field)")
        self.record("CTCardio_3Dt_displacement.seq.nrrd", "3D+t+displacement", f"3D+t displacement field sequence (float, 3 'vector' components + 3 domain + 'list' time axis), {len(times)} frames, "
                    "from image registration, written by Slicer as a grid transform sequence ('intent_code:=1006', 'displacement field type:=resampling', "
                    "as the Transforms module writes displacement fields); Slicer loads it back as a sequence of transform nodes. "
                    "Frame i maps frame 0 positions to frame i positions: resampling CTCardio_3Dt.seq.nrrd frame i through it "
                    "gives the motion-compensated frame stored in CTCardio_3Dt_displacement_resampled.seq.nrrd frame i (which therefore resembles frame 0).",
                    src_d, "sequence", expect={"frames": len(times), "frame_class": "vtkMRMLTransformNode", "components": 3})
        self.compare_sequence("CTCardio_3Dt_displacement", disp_seq, "CTCardio_3Dt_displacement.seq.nrrd", exact=False)
        warped_seq = self.make_sequence("CTCardio_3Dt_displacement_resampled", warped_frames, times)
        self.save(warped_seq, "CTCardio_3Dt_displacement_resampled.seq.nrrd")
        self.record("CTCardio_3Dt_displacement_resampled.seq.nrrd", "3D+t (reference)", "Reference for the displacement sequence: frame i of CTCardio_3Dt.seq.nrrd "
                    "resampled (linear interpolation, onto the grid of frame 0) through frame i of CTCardio_3Dt_displacement.seq.nrrd = motion-compensated sequence", src_d, "sequence",
                    expect={"frames": len(times), "frame_class": "vtkMRMLScalarVolumeNode", "components": 1})
        self.compare_sequence("CTCardio_3Dt_displacement_resampled", warped_seq, "CTCardio_3Dt_displacement_resampled.seq.nrrd")
        # warping test: reload displacement frames as transforms (import from vector volume) and re-warp frame 0
        reloaded = slicer.util.loadSequence(self.path("CTCardio_3Dt_displacement.seq.nrrd"))
        self.verify_sequence_warping("CTCardio_3Dt_displacement (LPS)", reloaded, grids, frames, frame0, warped_frames)
        # RAS twin of the displacement sequence
        self.ras_twin("CTCardio_3Dt_displacement.seq.nrrd", "CTCardio_3Dt_displacement_RAS.seq.nrrd", vector_mode="lps_components")
        self.record("CTCardio_3Dt_displacement_RAS.seq.nrrd", "3D+t+displacement", "RAS-space twin of CTCardio_3Dt_displacement.seq.nrrd: geometry in RAS, vector "
                    "components kept in LPS with 'measurement frame' diag(-1,-1,1) mapping them to RAS", src_d, "sequence",
                    coordinate_system="RAS", written_by="pynrrd (from CTCardio_3Dt_displacement.seq.nrrd)",
                    expect={"frames": len(times), "frame_class": "vtkMRMLTransformNode", "components": 3, "same_geometry_as": "CTCardio_3Dt_displacement.seq.nrrd"})
        reloaded_ras = slicer.util.loadSequence(self.path("CTCardio_3Dt_displacement_RAS.seq.nrrd"))
        self.verify_sequence_warping("CTCardio_3Dt_displacement (RAS)", reloaded_ras, grids, frames, frame0, warped_frames)

        vel_seq = self.make_sequence("CTCardio_3Dt_velocity", vel_frames, times)
        self.save(vel_seq, "CTCardio_3Dt_velocity.seq.nrrd")
        self.record("CTCardio_3Dt_velocity.seq.nrrd", "3D+t+velocity", f"3D+t velocity vector field sequence (float32, 3 'vector' components labelled 'velocity' with unit 'mm/s'), {len(times)} frames; "
                    "synthetic pulsatile swirling flow in the chest, 4D-flow-MRI-like", "Synthetic, on the 2x downsampled grid of CTCardio_3Dt.seq.nrrd frame 0",
                    "sequence", expect={"frames": len(times), "frame_class": "vtkMRMLVectorVolumeNode", "components": 3, "voxel_vector_type": "Spatial"})
        self.compare_sequence("CTCardio_3Dt_velocity", vel_seq, "CTCardio_3Dt_velocity.seq.nrrd", exact=False)

    def register_sequence(self, seq, fixed_item=0, preset_id="default0"):
        """Register all frames of a volume sequence to one fixed frame with the SequenceRegistration extension (Elastix).

        Returns (transform sequence, preset name). Frame i of the transform sequence maps fixed-frame positions to
        frame-i positions (Elastix convention; the fixed frame gets an identity transform).
        """
        if not hasattr(slicer.modules, "sequenceregistration"):
            raise RuntimeError("The SequenceRegistration module is not available. Install the 'SequenceRegistration' and 'SlicerElastix' "
                               "extensions (Extensions Manager), or pass their module .py files with --extra-module-paths.")
        import SequenceRegistration
        logic = SequenceRegistration.SequenceRegistrationLogic()
        logic.logCallback = lambda text: self.log("    " + text) if (text.startswith("Registering") or "completed" in text) else None
        presets = logic.elastixLogic.getRegistrationPresets()
        preset_index = next(i for i, p in enumerate(presets) if p.getID() == preset_id)
        self.log(f"  registering {seq.GetNumberOfDataNodes()} frames to frame {fixed_item} with Elastix preset '{presets[preset_index].getName()}' ({preset_id})")
        transform_seq = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "CTCardio_registration_transforms")
        logic.registerVolumeSequence(seq, None, transform_seq, fixed_item, preset_index, computeMovingToFixedTransform=True)
        if transform_seq.GetNumberOfDataNodes() != seq.GetNumberOfDataNodes():
            raise RuntimeError("Sequence registration did not produce a transform for every frame")
        return transform_seq, presets[preset_index].getName()

    def verify_sequence_warping(self, name, disp_seq_node, grids, input_frames, frame0, warped_frames):
        """The reloaded displacement sequence (frames are transform nodes) must match the registration transforms and
        re-warping the input frames with it must reproduce the stored motion-compensated frames."""
        for i in range(disp_seq_node.GetNumberOfDataNodes()):
            tnode = disp_seq_node.GetNthDataNode(i)
            if not tnode.IsA("vtkMRMLTransformNode"):
                raise RuntimeError(f"CHECK FAILED: {name}: frame {i} is a {tnode.GetClassName()}, expected a transform node")
            pts = self.sample_points(frame0, n=200, seed=i)
            expected = self.transform_points(grids[i], pts)
            got = self.transform_points(tnode, pts)
            if not np.allclose(expected, got, atol=0.2):
                raise RuntimeError(f"CHECK FAILED: {name}: frame {i} transform differs (max {np.abs(expected-got).max():.3f} mm)")
            # the sequence's data nodes live in its private scene; copy into the main scene for the CLI resampler
            tcopy = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode", f"{name}_frame_{i}")
            tcopy.CopyContent(tnode)
            warped = self.resample_through_transform(input_frames[i], tcopy, frame0, f"{name}_rewarped_{i}")
            a0, a1 = self.volume_array(warped_frames[i]), self.volume_array(warped)
            diff = np.abs(a0.astype(np.float64) - a1.astype(np.float64))
            frac_diff = float((diff > 1).mean())
            if frac_diff > 0.01:
                raise RuntimeError(f"CHECK FAILED: {name}: re-warped frame {i} differs from the reference in {frac_diff*100:.2f}% of voxels")
        self.check(f"{name}: transforms and re-warped frames match the reference", True, f"{disp_seq_node.GetNumberOfDataNodes()} frames")

    def sample_vector_volume(self, vector_volume, pts_ras):
        """Trilinear sample of a 3-component vector volume (RAS vectors) at RAS points."""
        ras_to_ijk = np.linalg.inv(self.ijk_to_ras(vector_volume))
        a = self.volume_array(vector_volume).astype(np.float64)   # (k, j, i, 3)
        out = np.zeros((len(pts_ras), 3))
        for n, p in enumerate(pts_ras):
            ijk = ras_to_ijk @ np.array([p[0], p[1], p[2], 1.0])
            i, j, k = ijk[:3]
            i0, j0, k0 = int(math.floor(i)), int(math.floor(j)), int(math.floor(k))
            di, dj, dk = i - i0, j - j0, k - k0
            acc = np.zeros(3)
            for ci, wi in ((i0, 1 - di), (i0 + 1, di)):
                for cj, wj in ((j0, 1 - dj), (j0 + 1, dj)):
                    for ck, wk in ((k0, 1 - dk), (k0 + 1, dk)):
                        ci_, cj_, ck_ = (min(max(ci, 0), a.shape[2] - 1), min(max(cj, 0), a.shape[1] - 1), min(max(ck, 0), a.shape[0] - 1))
                        acc += wi * wj * wk * a[ck_, cj_, ci_]
            out[n] = acc
        return out

    # ------------------------------------------------------------------------------------------------------------
    # Group 4: displacement field + warped reference, velocity field (MRHead geometry), RAS twins
    # ------------------------------------------------------------------------------------------------------------
    def make_tps_transform(self, name, center, half, amplitude_mm, mode="bump"):
        """Thin-plate-spline transform node: fixed corner landmarks + displaced interior landmarks."""
        src_pts, dst_pts = vtk.vtkPoints(), vtk.vtkPoints()
        for sx, sy, sz in itertools.product([-1, 1], repeat=3):
            p = center + np.array([sx, sy, sz]) * half * 1.2
            src_pts.InsertNextPoint(p)
            dst_pts.InsertNextPoint(p)
        if mode == "bump":
            # one landmark pushed in the center, a few pulled on a ring
            src_pts.InsertNextPoint(center)
            dst_pts.InsertNextPoint(center + np.array([amplitude_mm, -0.6 * amplitude_mm, 0.4 * amplitude_mm]))
            for ang in np.linspace(0, 2 * math.pi, 6, endpoint=False):
                p = center + np.array([math.cos(ang), math.sin(ang), 0]) * half * 0.5
                src_pts.InsertNextPoint(p)
                dst_pts.InsertNextPoint(p + np.array([0, 0, 0.5 * amplitude_mm * math.cos(2 * ang)]))
        else:
            # radial contraction/expansion of a sphere of landmarks around the center
            src_pts.InsertNextPoint(center)
            dst_pts.InsertNextPoint(center)
            for ang in np.linspace(0, 2 * math.pi, 8, endpoint=False):
                for el in (-0.5, 0.5):
                    d = np.array([math.cos(ang) * math.cos(el), math.sin(ang) * math.cos(el), math.sin(el)])
                    p = center + d * half * 0.5
                    src_pts.InsertNextPoint(p)
                    dst_pts.InsertNextPoint(p + d * amplitude_mm)
        tps = vtk.vtkThinPlateSplineTransform()
        tps.SetSourceLandmarks(src_pts)
        tps.SetTargetLandmarks(dst_pts)
        tps.SetBasisToR()
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode", name)
        node.SetAndObserveTransformToParent(tps)
        return node

    def make_velocity_volume(self, geometry_node, center, half, name, scale=1.0, swirl=0.0):
        """Synthetic smooth velocity field (mm/s) on the grid of geometry_node: swirl around the S axis inside an
        ellipsoid, decaying towards the boundary, plus a pulsatile axial component."""
        m = self.ijk_to_ras(geometry_node)
        dims = geometry_node.GetImageData().GetDimensions()
        kk, jj, ii = np.meshgrid(np.arange(dims[2]), np.arange(dims[1]), np.arange(dims[0]), indexing="ij")
        ijk1 = np.stack([ii, jj, kk, np.ones_like(ii)], axis=-1).astype(np.float64)
        ras = ijk1 @ m.T
        rel = (ras[..., :3] - center) / half
        r2 = (rel ** 2).sum(axis=-1)
        envelope = np.exp(-2.0 * r2)
        vx = -rel[..., 1] * 400.0 * envelope * math.cos(swirl)
        vy = rel[..., 0] * 400.0 * envelope * math.cos(swirl)
        vz = 300.0 * envelope * (1.0 - r2) * math.sin(swirl + 0.3)
        vel = np.stack([vx, vy, vz], axis=-1).astype(np.float32) * np.float32(scale)
        node = self.new_volume("vtkMRMLVectorVolumeNode", name, vel, m, slicer.vtkMRMLVolumeNode.VoxelVectorTypeSpatial)
        # Quantity and unit of the voxel values: Slicer writes them as 'labels' and 'units' of the component (pixel) axis
        node.SetVoxelValueQuantityFromLabel("velocity")
        units = slicer.vtkCodedEntry()
        units.SetValueSchemeMeaning("mm/s", "UCUM", "mm/s")
        node.SetVoxelValueUnits(units)
        return node

    def ensure_mrhead(self):
        if getattr(self, "mrhead", None) is None:
            self.generate_mrhead()
        return self.mrhead

    def make_displacement_set(self, volume, tps, field_name, reference_name, src, geometry_note):
        """Grid transform of tps on a 4x downsampled grid of volume, saved as a displacement field, plus the volume
        resampled through it; both are round-trip checked. Returns (grid node, warped node, sample points, transformed points)."""
        ref = self.downsample_volume(volume, (4, 4, 4), field_name + "_grid_geometry")
        tl = slicer.modules.transforms.logic()
        grid = tl.ConvertToGridTransform(tps, ref)
        grid.SetName(field_name)
        self.save(grid, field_name + ".nrrd")
        self.record(field_name + ".nrrd", "3D+displacement", f"3D displacement field (double, 3 'vector' components) on a 4x downsampled {geometry_note} grid, "
                    "written by Slicer's Transforms module as a grid transform ('displacement field type: resampling', 'intent_code: 1006'). "
                    f"Applying it to {reference_name.replace('_displacement_resampled', '')}_3D{'_oblique' if 'oblique' in field_name else ''}.nrrd "
                    f"(resampling: output voxel at p samples input at p + d(p), LPS) gives {reference_name}.nrrd",
                    src, "transform", expect={"node_class": "vtkMRMLGridTransformNode", "components": 3})
        reloaded = slicer.util.loadTransform(self.path(field_name + ".nrrd"))
        a0, m0 = self.grid_array(grid)
        a1, m1 = self.grid_array(reloaded)
        self.check(f"{field_name}: reloaded displacement grid identical", a0.shape == a1.shape and np.allclose(a0, a1, atol=1e-6) and np.allclose(m0, m1, atol=1e-4),
                   f"grid {a1.shape[2]}x{a1.shape[1]}x{a1.shape[0]}")
        pts = self.sample_points(volume)
        d0 = self.transform_points(grid, pts)
        # point evaluation differs slightly (< 0.1 mm) because the two in-memory grid transforms use different interpolation settings
        self.check(f"{field_name}: reloaded transform matches at sample points", np.allclose(d0, self.transform_points(reloaded, pts), atol=0.2),
                   f"max displacement {np.abs(d0 - pts).max():.2f} mm")
        warped = self.resample_through_transform(volume, grid, volume, reference_name)
        self.save(warped, reference_name + ".nrrd")
        self.record(reference_name + ".nrrd", "3D (reference)", f"Reference: the {geometry_note} volume resampled (linear interpolation, same grid) through {field_name}.nrrd",
                    src, "volume", expect={"node_class": "vtkMRMLScalarVolumeNode", "components": 1, "dimensions": list(volume.GetImageData().GetDimensions())})
        self.compare_volume(reference_name, warped, reference_name + ".nrrd")
        rewarped = self.resample_through_transform(volume, reloaded, volume, field_name + "_rewarped")
        self.check(f"{field_name}: re-warping with the reloaded field reproduces the reference", self.images_almost_equal(warped, rewarped))
        return grid, warped, pts, d0

    def generate_displacement(self):
        self.log("== MRHead displacement / velocity ==")
        mr = self.ensure_mrhead()
        b = [0.0] * 6
        mr.GetRASBounds(b)
        center = np.array([(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2])
        half = np.array([(b[1] - b[0]) / 2, (b[3] - b[2]) / 2, (b[5] - b[4]) / 2])
        tps = self.make_tps_transform("MRHead_tps", center, half, 8.0, mode="bump")
        src = ("Synthetic: thin-plate-spline deformation of MRHead (8 mm push in the center, ripple on a ring) converted to a "
               "grid transform; 'displacement field type: resampling' = transform from parent, as Slicer writes grid transforms")
        grid, warped, pts, d0 = self.make_displacement_set(mr, tps, "MRHead_displacement", "MRHead_displacement_resampled", src, "axis-aligned MRHead_3D.nrrd")

        # RAS twin of the displacement field
        self.ras_twin("MRHead_displacement.nrrd", "MRHead_displacement_RAS.nrrd", vector_mode="lps_components")
        self.record("MRHead_displacement_RAS.nrrd", "3D+displacement", "RAS-space twin of MRHead_displacement.nrrd: geometry in RAS, vector components kept in LPS "
                    "with 'measurement frame' diag(-1,-1,1) (the only RAS form Slicer accepts as a transform)", src, "transform",
                    coordinate_system="RAS", written_by="pynrrd (from MRHead_displacement.nrrd)",
                    expect={"node_class": "vtkMRMLGridTransformNode", "components": 3, "same_geometry_as": "MRHead_displacement.nrrd"})
        reloaded_ras = slicer.util.loadTransform(self.path("MRHead_displacement_RAS.nrrd"))
        self.check("MRHead_displacement_RAS: reloaded transform matches", np.allclose(d0, self.transform_points(reloaded_ras, pts), atol=0.2))
        rewarped_ras = self.resample_through_transform(mr, reloaded_ras, mr, "MRHead_rewarped_ras")
        self.check("MRHead_displacement_RAS: re-warping reproduces the reference", self.images_almost_equal(warped, rewarped_ras))

        # Probe (not shipped): RAS twin with the vector components also in RAS (identity measurement frame). Slicer
        # rejects it as a transform (non-identity measurement frame after conversion to LPS) and, loaded as a vector
        # volume, ignores the measurement frame, so the vectors come out with flipped x/y. Recorded as a note only.
        probe = "MRHead_displacement_RASvectors_probe.nrrd"
        self.ras_twin("MRHead_displacement.nrrd", probe, vector_mode="ras_components")
        try:
            slicer.util.loadTransform(self.path(probe))
            loads_as_transform = True
        except Exception:
            loads_as_transform = False
        vras = slicer.util.loadVolume(self.path(probe), properties={"singleFile": True, "show": False})
        vlps = slicer.util.loadVolume(self.path("MRHead_displacement.nrrd"), properties={"singleFile": True, "show": False})
        ras_vectors_ok = bool(np.allclose(self.volume_array(vras), self.volume_array(vlps), atol=1e-6))
        self.notes["ras_vector_components"] = (
            f"A RAS-space displacement field whose vector components are also in RAS (identity measurement frame) "
            f"{'loads' if loads_as_transform else 'does not load'} as a transform in Slicer and, loaded as a vector volume, its vectors are "
            f"{'converted correctly' if ras_vectors_ok else 'NOT converted (Slicer ignores the measurement frame of vector volumes)'}; "
            "therefore the RAS twins keep their vector components in LPS and declare 'measurement frame' diag(-1,-1,1).")
        self.log("  note: " + self.notes["ras_vector_components"])
        os.remove(self.path(probe))

        # the same physical deformation on the oblique grid
        oblique = getattr(self, "mrhead_oblique", None)
        if oblique is not None:
            self.make_displacement_set(oblique, tps, "MRHead_oblique_displacement", "MRHead_oblique_displacement_resampled",
                                       src + "; identical physical deformation as MRHead_displacement.nrrd, sampled on the oblique grid of MRHead_3D_oblique.nrrd",
                                       "oblique MRHead_3D_oblique.nrrd")

        # velocity field on the 2x downsampled MRHead grid
        ref2 = self.downsample_volume(mr, (2, 2, 2), "MRHead_down2_vel")
        vel = self.make_velocity_volume(ref2, center, half, "MRHead_velocity")
        self.save(vel, "MRHead_velocity.nrrd")
        src_v = "Synthetic smooth swirling velocity field (mm/s) on the 2x downsampled grid of MRHead_3D.nrrd"
        self.record("MRHead_velocity.nrrd", "3D+velocity", "3D velocity vector field (float32, 3 'vector' components, measurement frame identity, "
                    "components in LPS; component axis labelled 'velocity' with unit 'mm/s'); not a transform (no 'displacement field type')", src_v, "volume",
                    expect={"node_class": "vtkMRMLVectorVolumeNode", "components": 3, "voxel_vector_type": "Spatial"})
        self.compare_volume("MRHead_velocity", vel, "MRHead_velocity.nrrd", exact=False)
        self.ras_twin("MRHead_velocity.nrrd", "MRHead_velocity_RAS.nrrd", vector_mode="lps_components")
        self.record("MRHead_velocity_RAS.nrrd", "3D+velocity", "RAS-space twin of MRHead_velocity.nrrd (geometry in RAS, vector components in LPS mapped by "
                    "'measurement frame' diag(-1,-1,1))", src_v, "volume", coordinate_system="RAS", written_by="pynrrd (from MRHead_velocity.nrrd)",
                    expect={"node_class": "vtkMRMLVectorVolumeNode", "components": 3, "voxel_vector_type": "Spatial", "same_geometry_as": "MRHead_velocity.nrrd"})
        self.compare_volume("MRHead_velocity_RAS", vel, "MRHead_velocity_RAS.nrrd", exact=False)

    def images_almost_equal(self, n0, n1, tol=1, max_frac=0.005):
        a0, a1 = self.volume_array(n0).astype(np.float64), self.volume_array(n1).astype(np.float64)
        if a0.shape != a1.shape:
            return False
        frac = float((np.abs(a0 - a1) > tol).mean())
        self.log(f"  images differ (> {tol}) in {frac*100:.3f}% of voxels")
        return frac <= max_frac

    # ------------------------------------------------------------------------------------------------------------
    # Group 5: segmentations
    # ------------------------------------------------------------------------------------------------------------
    def make_tier_segmentation(self, volume, name):
        """Segmentation with three non-overlapping intensity tiers of volume (imported from a labelmap -> one shared layer)."""
        arr = self.volume_array(volume)
        lab = np.zeros(arr.shape, np.uint8)
        lab[(arr > 20) & (arr <= 60)] = 1
        lab[(arr > 60) & (arr <= 100)] = 2
        lab[arr > 100] = 3
        lm = self.new_volume("vtkMRMLLabelMapVolumeNode", name + "_labelmap", lab, self.ijk_to_ras(volume))
        seg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", name)
        seg.SetReferenceImageGeometryParameterFromVolumeNode(volume)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(lm, seg)
        names = {1: "Low intensity tissue", 2: "Medium intensity tissue", 3: "High intensity tissue"}
        colors = {1: (0.2, 0.5, 0.8), 2: (0.9, 0.7, 0.2), 3: (0.8, 0.2, 0.2)}
        for i in range(seg.GetSegmentation().GetNumberOfSegments()):
            segment = seg.GetSegmentation().GetNthSegment(i)
            segment.SetName(names[segment.GetLabelValue()])
            segment.SetColor(*colors[segment.GetLabelValue()])
            segment.SetTag("TerminologyEntry", "Segmentation category and type - 3D Slicer General Anatomy list"
                           "~SCT^85756007^Tissue~SCT^85756007^Tissue~^^~Anatomic codes - DICOM master list~^^~^^|")
        slicer.mrmlScene.RemoveNode(lm)
        return seg

    def generate_segmentation(self):
        self.log("== Segmentations ==")
        mr = self.ensure_mrhead()
        src = "Derived from 3D Slicer SampleData 'MRHead' (intensity thresholds 20-60, 60-100, >100 of MRHead_3D.nrrd)"
        seg = self.make_tier_segmentation(mr, "MRHead_segmentation")
        self.save(seg, "MRHead_segmentation.seg.nrrd")
        self.record("MRHead_segmentation.seg.nrrd", "3D segmentation", "Slicer segmentation (.seg.nrrd) with 3 non-overlapping segments stored in one layer: "
                    "3D unsigned char labelmap + Segment<N>_* header fields (name, color, label value, layer, extent, terminology)", src,
                    "segmentation", expect={"node_class": "vtkMRMLSegmentationNode", "segments": 3, "layers": 1})
        self.compare_segmentation("MRHead_segmentation", seg, "MRHead_segmentation.seg.nrrd", mr)
        self.ras_twin("MRHead_segmentation.seg.nrrd", "MRHead_segmentation_RAS.seg.nrrd")
        self.record("MRHead_segmentation_RAS.seg.nrrd", "3D segmentation", "RAS-space twin of MRHead_segmentation.seg.nrrd (header-only change)", src,
                    "segmentation", coordinate_system="RAS", written_by="pynrrd (from MRHead_segmentation.seg.nrrd)",
                    expect={"node_class": "vtkMRMLSegmentationNode", "segments": 3, "layers": 1, "same_geometry_as": "MRHead_segmentation.seg.nrrd"})
        self.compare_segmentation("MRHead_segmentation_RAS", seg, "MRHead_segmentation_RAS.seg.nrrd", mr)

        # the same tiers on the oblique grid
        oblique = getattr(self, "mrhead_oblique", None)
        if oblique is not None:
            seg_o = self.make_tier_segmentation(oblique, "MRHead_segmentation_oblique")
            self.save(seg_o, "MRHead_segmentation_oblique.seg.nrrd")
            self.record("MRHead_segmentation_oblique.seg.nrrd", "3D segmentation (oblique)", "Same three intensity tiers computed on MRHead_3D_oblique.nrrd: "
                        "segmentation with oblique 'space directions' (single layer)", "Intensity thresholds of MRHead_3D_oblique.nrrd",
                        "segmentation", expect={"node_class": "vtkMRMLSegmentationNode", "segments": 3, "layers": 1})
            self.compare_segmentation("MRHead_segmentation_oblique", seg_o, "MRHead_segmentation_oblique.seg.nrrd", oblique)

        # overlapping: three segments from overlapping intensity ranges of the anatomy -> several layers (4D file)
        arr = self.volume_array(mr)
        ranges = [("Intensity 20-80", (arr > 20) & (arr <= 80), (0.2, 0.5, 0.8)),
                  ("Intensity 60-140", (arr > 60) & (arr <= 140), (0.9, 0.7, 0.2)),
                  ("Intensity above 100", arr > 100, (0.8, 0.2, 0.2))]
        segO = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "MRHead_segmentation_overlapping")
        segO.SetReferenceImageGeometryParameterFromVolumeNode(mr)
        for name, mask, col in ranges:
            lm = self.new_volume("vtkMRMLLabelMapVolumeNode", "MRHead_overlap_labelmap", mask.astype(np.uint8), self.ijk_to_ras(mr))
            slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(lm, segO)
            slicer.mrmlScene.RemoveNode(lm)
            segment = segO.GetSegmentation().GetNthSegment(segO.GetSegmentation().GetNumberOfSegments() - 1)
            segment.SetName(name)
            segment.SetColor(*col)
            segment.SetTag("TerminologyEntry", "Segmentation category and type - 3D Slicer General Anatomy list"
                           "~SCT^85756007^Tissue~SCT^85756007^Tissue~^^~Anatomic codes - DICOM master list~^^~^^|")
        # store in as few layers as possible: segments that do not overlap share a layer (with different label values)
        segO.GetSegmentation().CollapseBinaryLabelmaps(False)
        n_layers = segO.GetSegmentation().GetNumberOfLayers()
        self.check("MRHead_segmentation_overlapping: segments overlap (more than one layer)", n_layers > 1, f"{n_layers} layers")
        self.save(segO, "MRHead_segmentation_overlapping.seg.nrrd")
        self.record("MRHead_segmentation_overlapping.seg.nrrd", "3D segmentation (overlapping)", "Slicer segmentation with 3 segments from overlapping intensity ranges "
                    f"(20-80, 60-140, >100) of MRHead_3D.nrrd stored in {n_layers} layers: 4D file ('list' axis first, one 3D labelmap per layer, "
                    "'space directions' starts with 'none'); Segment<N>_Layer selects the layer and Segment<N>_LabelValue the value within it "
                    "(non-overlapping segments share a layer)",
                    "Intensity thresholds of MRHead_3D.nrrd", "segmentation", expect={"node_class": "vtkMRMLSegmentationNode", "segments": 3, "layers": n_layers})
        self.compare_segmentation("MRHead_segmentation_overlapping", segO, "MRHead_segmentation_overlapping.seg.nrrd", mr)

    def compare_segmentation(self, name, seg, filename, reference_volume):
        reloaded = slicer.util.loadSegmentation(self.path(filename))
        s0, s1 = seg.GetSegmentation(), reloaded.GetSegmentation()
        self.check(f"{name}: segment count", s0.GetNumberOfSegments() == s1.GetNumberOfSegments(), str(s1.GetNumberOfSegments()))
        self.check(f"{name}: layer count", s0.GetNumberOfLayers() == s1.GetNumberOfLayers(), str(s1.GetNumberOfLayers()))
        for i in range(s0.GetNumberOfSegments()):
            sid = s0.GetNthSegmentID(i)
            a, b_ = s0.GetSegment(sid), s1.GetSegment(sid)
            if b_ is None or a.GetName() != b_.GetName() or a.GetLabelValue() != b_.GetLabelValue():
                raise RuntimeError(f"CHECK FAILED: {name}: segment {sid} metadata differs")
            m0 = slicer.util.arrayFromSegmentBinaryLabelmap(seg, sid, reference_volume)
            m1 = slicer.util.arrayFromSegmentBinaryLabelmap(reloaded, sid, reference_volume)
            if not np.array_equal(m0 > 0, m1 > 0):
                raise RuntimeError(f"CHECK FAILED: {name}: segment {sid} voxels differ")
        self.check(f"{name}: all segments identical", True)

    # ------------------------------------------------------------------------------------------------------------
    # Group 6: DWI
    # ------------------------------------------------------------------------------------------------------------
    def generate_dwi(self):
        self.log("== DWI ==")
        dwi = self.sample_data.downloadSample("DWIVolume")
        arr = self.volume_array(dwi)                       # (k, j, i, 43)
        n_grad = dwi.GetNumberOfGradients()
        grads = np.array([list(dwi.GetDiffusionGradient(i)) for i in range(n_grad)])
        bvals = np.array([dwi.GetBValue(i) for i in range(n_grad)])
        norms = np.linalg.norm(grads, axis=1)
        b0_indices = [i for i in range(n_grad) if norms[i] < 1e-6 or bvals[i] < 1e-6]
        dw_indices = [i for i in range(n_grad) if i not in b0_indices]
        self.log(f"  source: {arr.shape}, {len(b0_indices)} b0 + {len(dw_indices)} DW images")
        # crop to the head (b0 intensity)
        b0 = arr[..., b0_indices[0]].astype(np.float32)
        mask = b0 > 0.15 * b0.max()
        import scipy.ndimage as ndi
        mask = ndi.binary_opening(mask, iterations=2)
        kk, jj, ii = np.where(mask)
        pad = 2
        k0, k1 = max(kk.min() - pad, 0), min(kk.max() + pad + 1, arr.shape[0])
        j0, j1 = max(jj.min() - pad, 0), min(jj.max() + pad + 1, arr.shape[1])
        i0, i1 = max(ii.min() - pad, 0), min(ii.max() + pad + 1, arr.shape[2])
        n_keep = 6
        keep = [b0_indices[0]] + [dw_indices[int(round(x))] for x in np.linspace(0, len(dw_indices) - 1, n_keep)]
        cropped = np.ascontiguousarray(arr[k0:k1, j0:j1, i0:i1][..., keep])
        m = self.ijk_to_ras(dwi)
        m_new = m.copy()
        m_new[:3, 3] = (m @ np.array([i0, j0, k0, 1.0]))[:3]
        mf = vtk.vtkMatrix4x4()
        dwi.GetMeasurementFrameMatrix(mf)

        def make_dwi(name, array, ijk_to_ras):
            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLDiffusionWeightedVolumeNode", name)
            node.SetAndObserveImageData(self.make_image_data(array))
            self.set_ijk_to_ras(node, ijk_to_ras)
            node.SetNumberOfGradients(len(keep))
            for n, idx in enumerate(keep):
                node.SetDiffusionGradient(n, grads[idx])
                node.SetBValue(n, bvals[idx])
            node.SetMeasurementFrameMatrix(mf)
            node.CreateDefaultDisplayNodes()
            return node

        new = make_dwi("DWI_small", cropped, m_new)
        self.save(new, "DWI_small.nrrd")
        resolution_note = "native 1.5 mm resolution"
        if os.path.getsize(self.path("DWI_small.nrrd")) > self.max_bytes:
            # still too large: downsample 2x (linear interpolation of all components)
            self.log("  DWI too large at native resolution, downsampling 2x")
            down = self.downsample_volume(new, (2, 2, 2), "DWI_small_down2", cls="vtkMRMLVectorVolumeNode")
            slicer.mrmlScene.RemoveNode(new)
            new = make_dwi("DWI_small", self.volume_array(down).astype(cropped.dtype), self.ijk_to_ras(down))
            cropped = self.volume_array(new)
            m_new = self.ijk_to_ras(new)
            self.save(new, "DWI_small.nrrd")
            resolution_note = "2x downsampled (3 mm)"
        src = (f"3D Slicer SampleData 'DWIVolume' (dwi.nhdr, 43 gradient images 128x128x94 @ 1.5 mm, b=1000): cropped to the head "
               f"(ijk {i0}:{i1}, {j0}:{j1}, {k0}:{k1}), {resolution_note}, reduced to the b0 image + {n_keep} gradient directions; re-saved by Slicer")
        self.record("DWI_small.nrrd", "3D DWI", f"Diffusion weighted MRI (unsigned short, {len(keep)} images along a 'list' axis), with "
                    "'modality:=DWMRI', 'DWMRI_b-value', 'DWMRI_gradient_NNNN' key/value fields and a 'measurement frame'; written in RAS space by Slicer's Teem writer",
                    src, "volume", coordinate_system="RAS",
                    expect={"node_class": "vtkMRMLDiffusionWeightedVolumeNode", "components": len(keep), "gradients": len(keep), "dimensions": list(new.GetImageData().GetDimensions())})
        reloaded = self.compare_volume("DWI_small", new, "DWI_small.nrrd")
        g1 = np.array([list(reloaded.GetDiffusionGradient(i)) for i in range(reloaded.GetNumberOfGradients())])
        self.check("DWI_small: gradients and b-values identical",
                   reloaded.GetNumberOfGradients() == len(keep) and np.allclose(g1, grads[keep], atol=1e-5)
                   and np.allclose([reloaded.GetBValue(i) for i in range(len(keep))], bvals[keep], atol=1e-3))
        # b0 companion
        b0node = self.new_volume("vtkMRMLScalarVolumeNode", "DWI_small_b0", np.ascontiguousarray(cropped[..., 0]), m_new)
        self.save(b0node, "DWI_small_b0.nrrd")
        self.record("DWI_small_b0.nrrd", "3D", "The b=0 image of DWI_small.nrrd as a plain scalar volume, written by Slicer's ITK writer in LPS "
                    "(same physical grid as the RAS DWI file)", src, "volume",
                    expect={"node_class": "vtkMRMLScalarVolumeNode", "components": 1, "same_geometry_as": "DWI_small.nrrd"})
        self.compare_volume("DWI_small_b0", b0node, "DWI_small_b0.nrrd")

    # ------------------------------------------------------------------------------------------------------------
    # Group 7: DTI (+ symmetric storage, FA map, baseline volume)
    # ------------------------------------------------------------------------------------------------------------
    def generate_dti(self):
        self.log("== DTI ==")
        dti = self.sample_data.downloadSample("DTIBrain")
        dti.SetName("DTIBrain")
        self.save(dti, "DTIBrain_3D_tensor.nrrd")
        src = "3D Slicer SampleData 'DTIBrain' (DTI-Brain.nrrd, 144x144x85 @ 1.67x1.67x1.7 mm, float tensors), re-saved by Slicer"
        self.record("DTIBrain_3D_tensor.nrrd", "3D DTI", "Diffusion tensor volume: 9 float components ('3D-matrix' axis, row-major tensor) + 3 domain axes, "
                    "'measurement frame'; written in RAS space by Slicer's Teem writer", src, "volume", coordinate_system="RAS",
                    expect={"node_class": "vtkMRMLDiffusionTensorVolumeNode", "components": 9, "dimensions": [144, 144, 85]})
        self.compare_volume("DTIBrain_3D_tensor", dti, "DTIBrain_3D_tensor.nrrd", exact=False)
        # symmetric (6 component) variant
        data, h = nrrd.read(self.path("DTIBrain_3D_tensor.nrrd"))     # (9, i, j, k)
        sym = np.ascontiguousarray(data[[0, 1, 2, 4, 5, 8], ...])
        hs = dict(h)
        hs["sizes"] = list(sym.shape)
        hs["kinds"] = ["3D-symmetric-matrix", "domain", "domain", "domain"]
        nrrd.write(self.path("DTIBrain_3D_tensor_symmetric.nrrd"), sym, hs)
        self.record("DTIBrain_3D_tensor_symmetric.nrrd", "3D DTI", "Same tensors stored with the 6 unique components ('3D-symmetric-matrix': xx xy xz yy yz zz)",
                    src, "volume", coordinate_system="RAS", written_by="pynrrd (from DTIBrain_3D_tensor.nrrd)",
                    expect={"node_class": "vtkMRMLDiffusionTensorVolumeNode", "components": 9, "dimensions": [144, 144, 85], "same_geometry_as": "DTIBrain_3D_tensor.nrrd"})
        self.compare_volume("DTIBrain_3D_tensor_symmetric", dti, "DTIBrain_3D_tensor_symmetric.nrrd", exact=False)
        # FA map on the same grid
        t = self.volume_array(dti).astype(np.float64).reshape(-1, 3, 3)
        ev = np.linalg.eigvalsh(t)
        md = ev.mean(axis=1, keepdims=True)
        num = np.sqrt(((ev - md) ** 2).sum(axis=1))
        den = np.sqrt((ev ** 2).sum(axis=1))
        fa = np.where(den > 0, np.sqrt(1.5) * num / np.maximum(den, 1e-12), 0.0).astype(np.float32)
        dims = dti.GetImageData().GetDimensions()
        fa_node = self.new_volume("vtkMRMLScalarVolumeNode", "DTIBrain_FA", fa.reshape(dims[2], dims[1], dims[0]), self.ijk_to_ras(dti))
        self.save(fa_node, "DTIBrain_FA.nrrd")
        self.record("DTIBrain_FA.nrrd", "3D", "Fractional anisotropy (float32, 0..1) computed from DTIBrain_3D_tensor.nrrd on the same grid; LPS (ITK writer)",
                    "Computed with numpy from DTIBrain_3D_tensor.nrrd", "volume",
                    expect={"node_class": "vtkMRMLScalarVolumeNode", "components": 1, "same_geometry_as": "DTIBrain_3D_tensor.nrrd"})
        self.compare_volume("DTIBrain_FA", fa_node, "DTIBrain_FA.nrrd", exact=False)
        # baseline volume from the same tutorial
        base = self.sample_data.downloadSample("BaselineVolume")
        base.SetName("DTIBrain_baseline")
        self.save(base, "DTIBrain_baseline.nrrd")
        self.record("DTIBrain_baseline.nrrd", "3D", "Baseline (b=0-like) anatomical image from the Slicer diffusion tutorial (short, 256x256x51 @ 1x1x2.6 mm). "
                    "Note: its grid differs from DTIBrain_3D_tensor.nrrd (different acquisition), so it is a companion image, not a voxel-aligned b0",
                    "3D Slicer SampleData 'BaselineVolume' (BaselineVolume.nrrd), re-saved by Slicer", "volume",
                    expect={"node_class": "vtkMRMLScalarVolumeNode", "components": 1, "dimensions": [256, 256, 51]})
        self.compare_volume("DTIBrain_baseline", base, "DTIBrain_baseline.nrrd")

    # ------------------------------------------------------------------------------------------------------------
    # Manifest
    # ------------------------------------------------------------------------------------------------------------
    def write_manifest(self):
        existing = {}
        mp = self.path("manifest.json")
        if os.path.exists(mp):
            with open(mp) as f:
                try:
                    existing = {e["name"]: e for e in json.load(f).get("files", [])}
                except Exception:
                    existing = {}
        # keep entries of files that were not regenerated in this run but still exist
        for name, e in existing.items():
            if name not in self.entries and os.path.exists(self.path(name)):
                self.entries[name] = e
        files = [self.entries[k] for k in sorted(self.entries)]
        manifest = {
            "release": RELEASE_TAG,
            "base_url": RELEASE_BASE_URL,
            "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "generator": "slicerio/scripts/testing_data/generate_test_data.py",
            "slicer": {"version": slicer.app.applicationVersion, "revision": slicer.app.revision, "repositoryRevision": slicer.app.repositoryRevision},
            "notes": self.notes,
            "files": files,
        }
        with open(mp, "w") as f:
            json.dump(manifest, f, indent=2)
        total = sum(e["size_bytes"] for e in files)
        self.log(f"manifest.json: {len(files)} files, {total/1e6:.1f} MB total")
        return manifest


GROUPS = ("mrhead", "visiblehuman", "ctcardio", "displacement", "segmentation", "dwi", "dti")


def load_scripted_module(module_path):
    """Register and load a scripted module from a .py file into the running Slicer (no restart needed)."""
    import qt
    name = os.path.splitext(os.path.basename(module_path))[0]
    factory = slicer.app.moduleManager().factoryManager()
    if not factory.isRegistered(name):
        factory.registerModule(qt.QFileInfo(module_path))
    if not factory.isLoaded(name):
        factory.loadModules([name])
    if not factory.isLoaded(name):
        raise RuntimeError(f"Failed to load module {name} from {module_path}")


def main(argv):
    parser = argparse.ArgumentParser(description="Generate NRRD test data sets with 3D Slicer")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--only", default=",".join(GROUPS))
    parser.add_argument("--max-mb", type=float, default=10.0)
    parser.add_argument("--extra-module-paths", default="",
                        help="';'-separated paths of scripted module .py files to load before generating (e.g. Elastix.py and "
                             "SequenceRegistration.py from source checkouts when the extensions are not installed)")
    args = parser.parse_args(argv)
    for module_path in [m for m in args.extra_module_paths.split(";") if m.strip()]:
        load_scripted_module(module_path.strip())
    groups = [g.strip() for g in args.only.split(",") if g.strip()]
    for g in groups:
        if g not in GROUPS:
            raise SystemExit(f"unknown group {g}; choose from {GROUPS}")

    gen = Generator(args.output, args.max_mb)
    start = time.time()
    slicer.mrmlScene.Clear(False)
    generators = {"mrhead": gen.generate_mrhead, "visiblehuman": gen.generate_visible_human, "ctcardio": gen.generate_ctcardio,
                  "displacement": gen.generate_displacement, "segmentation": gen.generate_segmentation,
                  "dwi": gen.generate_dwi, "dti": gen.generate_dti}
    for group in GROUPS:
        if group in groups:
            generators[group]()
            gen.write_manifest()   # persist after every group so that a failure later does not lose the entries
    manifest = gen.write_manifest()
    gen.log(f"done in {time.time()-start:.0f} s, {len(gen.checks)} checks passed")
    return {
        "status": "ok",
        "output": gen.output_dir,
        "files": {e["name"]: round(e["size_bytes"] / 1e6, 2) for e in manifest["files"]},
        "total_mb": round(sum(e["size_bytes"] for e in manifest["files"]) / 1e6, 1),
        "checks": len(gen.checks),
        "log": gen.log_lines,
    }


if __name__ == "__main__":
    # When started with "Slicer --python-script script.py -- args" or through run_in_slicer.py, sys.argv holds our arguments.
    _argv = sys.argv[1:]
    if "--" in _argv:
        _argv = _argv[_argv.index("--") + 1:]
    __execResult = main(_argv)
