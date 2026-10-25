# -*- coding: utf-8 -*-
"""Tests of slicerio.volume with the files of the TestingData release (downloaded on first use)."""

import os
import tempfile
import unittest

import numpy as np

import slicerio

_volumes = {}


def volume(name):
    """Read a TestingData file once per test session."""
    if name not in _volumes:
        _volumes[name] = slicerio.read_volume(slicerio.get_testdata_file(name))
    return _volumes[name]


class TemporaryFile:
    def __init__(self, suffix):
        self.suffix = suffix

    def __enter__(self):
        handle, self.path = tempfile.mkstemp(suffix=self.suffix)
        os.close(handle)
        return self.path

    def __exit__(self, *args):
        if os.path.exists(self.path):
            os.remove(self.path)


def warped_matches_reference(warped, reference, tolerance=4, max_fraction=0.005):
    """Fraction of voxels whose resampled value differs from Slicer's reference by more than `tolerance`."""
    a = warped["voxels"].astype(np.float64)
    b = reference["voxels"].astype(np.float64)
    fraction = float((np.abs(a - b) > tolerance).mean())
    return fraction <= max_fraction, fraction


class TestReadAllTestingData(unittest.TestCase):
    """Every file of the release can be read and its array matches the header."""

    def test_read_all(self):
        import nrrd
        manifest = slicerio.testing_data_manifest()
        for entry in manifest["files"]:
            name = entry["name"]
            if not name.endswith((".nrrd", ".nhdr")):
                continue
            with self.subTest(file=name):
                path = slicerio.get_testdata_file(name)
                header = nrrd.read_header(path)
                vol = slicerio.read_volume(path)
                self.assertEqual(vol["voxels"].shape, tuple(header["sizes"]))
                self.assertEqual(vol["ijkToLPS"].shape, (4, 4))
                self.assertTrue(np.all(np.isfinite(vol["ijkToLPS"])))
                kinds = header["kinds"]
                self.assertEqual("component" in vol, kinds[0] not in ("domain", "space"))
                self.assertEqual("sequence" in vol, len(kinds) > 1 and kinds[-1] == "list" and kinds[-2] == "domain")
                self.assertEqual(vol["spaceDimension"], kinds.count("domain"))
                self.assertEqual("LPS" if "space" in header else "2D",
                                 "LPS" if vol["spaceDimension"] == 3 else "2D")

    def test_header_only(self):
        vol = slicerio.read_volume(slicerio.get_testdata_file("MRHead_3D.nrrd"), skip_voxels=True)
        self.assertIsNone(vol["voxels"])
        self.assertEqual(vol["spaceDimension"], 3)


class TestGeometry(unittest.TestCase):

    def test_anisotropic_spacing(self):
        vol = volume("MRHead_3D.nrrd")
        spacing = np.linalg.norm(vol["ijkToLPS"][0:3, 0:3], axis=0)
        np.testing.assert_allclose(spacing, [1.0, 1.25, 1.6], atol=1e-6)
        self.assertEqual(vol["voxels"].shape, (256, 205, 106))
        self.assertEqual(vol["voxels"].dtype, np.int16)

    def test_lps_ras_twins_load_at_the_same_position(self):
        manifest = slicerio.testing_data_manifest()
        pairs = [(e["name"], e["expect"]["same_geometry_as"]) for e in manifest["files"] if e.get("expect", {}).get("same_geometry_as")]
        self.assertGreaterEqual(len(pairs), 8)
        for name, twin in pairs:
            with self.subTest(file=name):
                a, b = volume(name), volume(twin)
                np.testing.assert_allclose(a["ijkToLPS"], b["ijkToLPS"], atol=1e-4)
                if a.get("component", {}).get("kind") in ("vector",) and a["voxels"].shape[0] == 3:
                    np.testing.assert_allclose(slicerio.component_vectors_to_lps(a), slicerio.component_vectors_to_lps(b), atol=1e-5)
                elif a["voxels"].shape == b["voxels"].shape:
                    np.testing.assert_array_equal(a["voxels"], b["voxels"])

    def test_ras_file_measurement_frame(self):
        ras = volume("MRHead_displacement_RAS.nrrd")
        lps = volume("MRHead_displacement.nrrd")
        # components stay in LPS in the RAS twin, the measurement frame expresses that: in LPS it is the identity
        np.testing.assert_allclose(ras["measurementFrame"], np.eye(3), atol=1e-9)
        np.testing.assert_allclose(lps["measurementFrame"], np.eye(3), atol=1e-9)
        np.testing.assert_allclose(ras["voxels"], lps["voxels"])

    def test_oblique_volume_has_the_same_physical_content(self):
        aligned = volume("MRHead_3D.nrrd")
        oblique = volume("MRHead_3D_oblique.nrrd")
        directions = oblique["ijkToLPS"][0:3, 0:3] / np.linalg.norm(oblique["ijkToLPS"][0:3, 0:3], axis=0)
        np.testing.assert_allclose(directions.T @ directions, np.eye(3), atol=1e-6)   # orthogonal axes
        self.assertGreater(np.abs(directions - np.round(directions)).max(), 0.1)      # but not axis aligned
        # sample the aligned volume at the oblique voxel positions: must match the oblique voxels
        shape = oblique["voxels"].shape
        ii, jj, kk = np.meshgrid(np.arange(0, shape[0], 4), np.arange(0, shape[1], 4), np.arange(0, shape[2], 4), indexing="ij")
        ijk = np.column_stack([ii.ravel(), jj.ravel(), kk.ravel()]).astype(float)
        points = ijk @ oblique["ijkToLPS"][0:3, 0:3].T + oblique["ijkToLPS"][0:3, 3]
        sampled = slicerio.sample_volume(aligned, points)
        actual = oblique["voxels"][::4, ::4, ::4].ravel().astype(float)
        self.assertLess(np.median(np.abs(sampled - actual)), 3)

    def test_2d(self):
        vol = volume("MRHead_2D.nrrd")
        self.assertEqual(vol["spaceDimension"], 2)
        self.assertEqual(vol["voxels"].shape, (256, 205))
        np.testing.assert_allclose(vol["ijkToLPS"], np.diag([1.0, 1.25, 1.0, 1.0]))
        self.assertNotIn("component", vol)


class TestColorVectorTensor(unittest.TestCase):

    def test_rgb_rgba(self):
        rgb = volume("VisibleHumanHead_3D_RGB.nrrd")
        rgba = volume("VisibleHumanHead_3D_RGBA.nrrd")
        self.assertEqual(rgb["component"]["kind"], "RGB-color")
        self.assertEqual(rgba["component"]["kind"], "RGBA-color")
        self.assertEqual(rgb["voxels"].shape, (3, 190, 200, 80))
        self.assertEqual(rgba["voxels"].shape, (4, 190, 200, 80))
        self.assertEqual(rgb["voxels"].dtype, np.uint8)
        np.testing.assert_array_equal(rgba["voxels"][0:3], rgb["voxels"])
        self.assertTrue(set(np.unique(rgba["voxels"][3])) <= set(range(256)))
        rgb2d = volume("VisibleHumanHead_2D_RGBA.nrrd")
        self.assertEqual(rgb2d["spaceDimension"], 2)
        self.assertEqual(rgb2d["voxels"].shape, (4, 760, 800))

    def test_velocity(self):
        vel = volume("MRHead_velocity.nrrd")
        self.assertEqual(vel["component"], {"kind": "vector", "label": "velocity", "unit": "mm/s"})
        self.assertEqual(vel["voxels"].shape, (3, 128, 102, 53))
        self.assertNotIn("displacementFieldType", vel)
        self.assertNotIn("intentCode", vel)
        vel_ras = volume("MRHead_velocity_RAS.nrrd")
        np.testing.assert_allclose(slicerio.component_vectors_to_lps(vel_ras), slicerio.component_vectors_to_lps(vel), atol=1e-5)

    def test_tensor(self):
        dti = volume("DTIBrain_3D_tensor.nrrd")
        sym = volume("DTIBrain_3D_tensor_symmetric.nrrd")
        self.assertEqual(dti["component"]["kind"], "3D-matrix")
        self.assertEqual(dti["voxels"].shape, (9, 144, 144, 85))
        self.assertEqual(sym["component"]["kind"], "3D-symmetric-matrix")
        self.assertEqual(sym["voxels"].shape, (6, 144, 144, 85))
        np.testing.assert_array_equal(sym["voxels"], dti["voxels"][[0, 1, 2, 4, 5, 8]])
        self.assertEqual(dti["measurementFrame"].shape, (3, 3))
        np.testing.assert_allclose(dti["ijkToLPS"], volume("DTIBrain_FA.nrrd")["ijkToLPS"], atol=1e-4)

    def test_dwi(self):
        dwi = volume("DWI_small.nrrd")
        self.assertEqual(dwi["component"]["kind"], "list")
        self.assertEqual(dwi["voxels"].shape, (7, 92, 119, 80))
        self.assertEqual(dwi["modality"], "DWMRI")
        self.assertAlmostEqual(float(dwi["DWMRI_b-value"]), 1000.0, places=2)
        self.assertEqual(len([k for k in dwi if k.startswith("DWMRI_gradient_")]), 7)
        np.testing.assert_allclose(dwi["ijkToLPS"], volume("DWI_small_b0.nrrd")["ijkToLPS"], atol=1e-4)
        np.testing.assert_array_equal(dwi["voxels"][0], volume("DWI_small_b0.nrrd")["voxels"])


class TestSequences(unittest.TestCase):

    def test_sequence_metadata(self):
        seq = volume("CTCardio_3Dt.seq.nrrd")
        self.assertEqual(seq["voxels"].shape, (128, 104, 72, 5))
        self.assertEqual(slicerio.number_of_frames(seq), 5)
        self.assertEqual(seq["sequence"]["indexName"], "time")
        self.assertEqual(seq["sequence"]["indexUnit"], "s")
        self.assertEqual(seq["sequence"]["indexType"], "numeric")
        self.assertEqual([float(v) for v in seq["sequence"]["indexValues"]], [0.0, 0.1, 0.2, 0.3, 0.4])
        frame = slicerio.sequence_frame(seq, 2)
        self.assertNotIn("sequence", frame)
        np.testing.assert_array_equal(frame["voxels"], seq["voxels"][..., 2])
        np.testing.assert_allclose(frame["ijkToLPS"], seq["ijkToLPS"])

    def test_2d_plus_t(self):
        seq = volume("CTCardio_2Dt.seq.nrrd")
        self.assertEqual(seq["spaceDimension"], 2)
        self.assertEqual(seq["voxels"].shape, (128, 104, 5))
        self.assertEqual(slicerio.number_of_frames(seq), 5)
        self.assertEqual(seq["sequence"]["indexName"], "time")
        full = volume("CTCardio_3Dt.seq.nrrd")
        np.testing.assert_array_equal(seq["voxels"], full["voxels"][:, :, 36, :])

    def test_vector_sequences(self):
        disp = volume("CTCardio_3Dt_displacement.seq.nrrd")
        vel = volume("CTCardio_3Dt_velocity.seq.nrrd")
        for seq in (disp, vel):
            self.assertEqual(seq["voxels"].shape, (3, 64, 52, 36, 5))
            self.assertEqual(seq["component"]["kind"], "vector")
            self.assertEqual(slicerio.number_of_frames(seq), 5)
        self.assertEqual(disp["displacementFieldType"], "resampling")
        self.assertEqual(disp["intentCode"], "1006")
        self.assertEqual(vel["component"]["label"], "velocity")
        self.assertEqual(vel["component"]["unit"], "mm/s")
        self.assertNotIn("intentCode", vel)
        # frame 0 is the fixed frame of the registration: zero displacement
        self.assertEqual(float(np.abs(slicerio.sequence_frame(disp, 0)["voxels"]).max()), 0.0)

    def test_create_sequence_roundtrip(self):
        seq = volume("CTCardio_3Dt.seq.nrrd")
        frames = [slicerio.sequence_frame(seq, i) for i in range(slicerio.number_of_frames(seq))]
        rebuilt = slicerio.create_sequence(frames, seq["sequence"]["indexValues"])
        np.testing.assert_array_equal(rebuilt["voxels"], seq["voxels"])
        self.assertEqual(rebuilt["sequence"]["indexValues"], seq["sequence"]["indexValues"])


class TestDisplacementFields(unittest.TestCase):

    def test_metadata(self):
        field = volume("MRHead_displacement.nrrd")
        self.assertEqual(field["component"]["kind"], "vector")
        self.assertEqual(field["displacementFieldType"], "resampling")
        self.assertEqual(field["intentCode"], "1006")
        self.assertEqual(field["voxels"].shape, (3, 64, 51, 26))
        self.assertEqual(field["voxels"].dtype, np.float64)

    def test_warping_matches_slicer(self):
        image = volume("MRHead_3D.nrrd")
        reference = volume("MRHead_displacement_resampled.nrrd")
        for field_name in ("MRHead_displacement.nrrd", "MRHead_displacement_RAS.nrrd"):
            with self.subTest(field=field_name):
                warped = slicerio.apply_displacement_field(image, volume(field_name))
                self.assertEqual(warped["voxels"].shape, image["voxels"].shape)
                ok, fraction = warped_matches_reference(warped, reference)
                self.assertTrue(ok, f"{fraction*100:.2f}% of voxels differ from Slicer's resampled image")
                # and the warp did change the image
                self.assertGreater(np.abs(warped["voxels"] - image["voxels"]).mean(), 1.0)

    def test_oblique_warping_matches_slicer(self):
        image = volume("MRHead_3D_oblique.nrrd")
        warped = slicerio.apply_displacement_field(image, volume("MRHead_oblique_displacement.nrrd"))
        ok, fraction = warped_matches_reference(warped, volume("MRHead_oblique_displacement_resampled.nrrd"))
        self.assertTrue(ok, f"{fraction*100:.2f}% of voxels differ from Slicer's resampled image")

    def test_sequence_warping_matches_slicer(self):
        images = volume("CTCardio_3Dt.seq.nrrd")
        fields = volume("CTCardio_3Dt_displacement.seq.nrrd")
        references = volume("CTCardio_3Dt_displacement_resampled.seq.nrrd")
        for i in (1, 3):
            with self.subTest(frame=i):
                warped = slicerio.apply_displacement_field(slicerio.sequence_frame(images, i), slicerio.sequence_frame(fields, i),
                                                           reference=slicerio.sequence_frame(images, 0))
                ok, fraction = warped_matches_reference(warped, slicerio.sequence_frame(references, i))
                self.assertTrue(ok, f"{fraction*100:.2f}% of voxels differ from Slicer's resampled frame")

    def test_modeling_field_is_rejected(self):
        field = dict(volume("MRHead_displacement.nrrd"))
        field["displacementFieldType"] = "modeling"
        with self.assertRaises(ValueError):
            slicerio.apply_displacement_field(volume("MRHead_3D.nrrd"), field)


class TestSegmentationFiles(unittest.TestCase):

    def test_overlapping_segmentation_as_volume(self):
        vol = volume("MRHead_segmentation_overlapping.seg.nrrd")
        self.assertEqual(vol["component"]["kind"], "list")
        self.assertEqual(vol["voxels"].shape, (2, 256, 205, 106))
        self.assertEqual(vol["Segment0_Layer"], "0")
        np.testing.assert_allclose(vol["ijkToLPS"], volume("MRHead_3D.nrrd")["ijkToLPS"], atol=1e-4)
        segmentation = slicerio.read_segmentation(slicerio.get_testdata_file("MRHead_segmentation_overlapping.seg.nrrd"))
        self.assertEqual(len(segmentation["segments"]), 3)
        np.testing.assert_allclose(segmentation["ijkToLPS"], vol["ijkToLPS"], atol=1e-4)
        # a segment of the second layer
        layers = {s["layer"] for s in segmentation["segments"]}
        self.assertEqual(layers, {0, 1})

    def test_segmentations_follow_the_anatomy(self):
        image = volume("MRHead_3D.nrrd")["voxels"]
        segmentation = slicerio.read_segmentation(slicerio.get_testdata_file("MRHead_segmentation.seg.nrrd"))
        high = slicerio.segment_mask(segmentation, "High intensity tissue")
        self.assertTrue(np.all(image[high] > 100))
        self.assertTrue(np.all(image[~high] <= 100))


class TestWrite(unittest.TestCase):

    ROUNDTRIP_FILES = ["MRHead_3D.nrrd", "MRHead_2D.nrrd", "VisibleHumanHead_2D_RGB.nrrd", "VisibleHumanHead_3D_RGBA.nrrd",
                       "MRHead_velocity.nrrd", "MRHead_displacement_RAS.nrrd", "CTCardio_3Dt.seq.nrrd", "CTCardio_2Dt.seq.nrrd",
                       "CTCardio_3Dt_displacement.seq.nrrd", "MRHead_segmentation_overlapping.seg.nrrd", "DWI_small.nrrd",
                       "DTIBrain_3D_tensor_symmetric.nrrd", "MRHead_3D_oblique.nrrd"]

    def assert_volumes_equal(self, a, b):
        np.testing.assert_array_equal(a["voxels"], b["voxels"])
        self.assertEqual(a["voxels"].dtype, b["voxels"].dtype)
        np.testing.assert_allclose(a["ijkToLPS"], b["ijkToLPS"], atol=1e-9)
        for key in ("spaceDimension", "component", "sequence", "displacementFieldType", "intentCode", "modality", "DWMRI_b-value"):
            self.assertEqual(a.get(key), b.get(key), key)
        if "measurementFrame" in a or "measurementFrame" in b:
            np.testing.assert_allclose(a["measurementFrame"], b["measurementFrame"], atol=1e-9)
        for key in a:
            if key.startswith(("DWMRI_gradient_", "Segment")):
                self.assertEqual(a[key], b[key], key)

    def test_roundtrip(self):
        import nrrd
        for name in self.ROUNDTRIP_FILES:
            with self.subTest(file=name):
                original = volume(name)
                with TemporaryFile(".nrrd") as path:
                    slicerio.write_volume(path, original)
                    header = nrrd.read_header(path)
                    reread = slicerio.read_volume(path)
                original_header = nrrd.read_header(slicerio.get_testdata_file(name))
                self.assertEqual(header["kinds"], original_header["kinds"])
                self.assertEqual(header["sizes"].tolist(), original_header["sizes"].tolist())
                if original["spaceDimension"] == 3:
                    self.assertEqual(header["space"], "left-posterior-superior")
                else:
                    self.assertEqual(header["space dimension"], 2)
                self.assert_volumes_equal(reread, original)

    def test_write_ras(self):
        import nrrd
        for name in ("MRHead_3D.nrrd", "MRHead_velocity.nrrd", "CTCardio_3Dt_displacement.seq.nrrd"):
            with self.subTest(file=name):
                original = volume(name)
                with TemporaryFile(".nrrd") as path:
                    slicerio.write_volume(path, original, space="RAS")
                    header = nrrd.read_header(path)
                    reread = slicerio.read_volume(path)
                self.assertEqual(header["space"], "right-anterior-superior")
                np.testing.assert_allclose(reread["ijkToLPS"], original["ijkToLPS"], atol=1e-9)
                np.testing.assert_array_equal(reread["voxels"], original["voxels"])
                if "component" in original and original["voxels"].shape[0] == 3:
                    # the measurement frame written to the RAS file maps the unchanged LPS components to RAS
                    np.testing.assert_allclose(header["measurement frame"], np.diag([-1.0, -1.0, 1.0]), atol=1e-9)
                    np.testing.assert_allclose(slicerio.component_vectors_to_lps(reread), slicerio.component_vectors_to_lps(original), atol=1e-9)

    def test_write_new_volume(self):
        voxels = np.arange(2 * 3 * 4, dtype=np.float32).reshape(2, 3, 4)
        ijk_to_lps = np.array([[0.0, 0.0, 2.0, 10.0], [1.5, 0.0, 0.0, -5.0], [0.0, -1.0, 0.0, 3.0], [0.0, 0.0, 0.0, 1.0]])
        vol = {"voxels": voxels, "ijkToLPS": ijk_to_lps, "spaceDimension": 3}
        with TemporaryFile(".nrrd") as path:
            slicerio.write_volume(path, vol)
            reread = slicerio.read_volume(path)
        np.testing.assert_array_equal(reread["voxels"], voxels)
        np.testing.assert_allclose(reread["ijkToLPS"], ijk_to_lps)
        self.assertEqual(reread["encoding"], "gzip")
        # a vector volume with label/unit and a sequence
        field = {"voxels": np.zeros((3, 2, 3, 4), np.float32), "ijkToLPS": ijk_to_lps, "spaceDimension": 3,
                 "component": {"kind": "vector", "label": "velocity", "unit": "mm/s"}, "measurementFrame": np.eye(3)}
        seq = slicerio.create_sequence([field, field], [0.0, 0.5])
        with TemporaryFile(".seq.nrrd") as path:
            slicerio.write_volume(path, seq)
            reread = slicerio.read_volume(path)
        self.assertEqual(reread["voxels"].shape, (3, 2, 3, 4, 2))
        self.assertEqual(reread["component"], {"kind": "vector", "label": "velocity", "unit": "mm/s"})
        self.assertEqual(reread["sequence"]["indexValues"], ["0.0", "0.5"])
        self.assertEqual(reread["sequence"]["indexName"], "time")

    def test_wrong_number_of_axes_is_rejected(self):
        vol = {"voxels": np.zeros((3, 4), np.uint8), "ijkToLPS": np.eye(4), "spaceDimension": 3}
        with TemporaryFile(".nrrd") as path:
            with self.assertRaises(ValueError):
                slicerio.write_volume(path, vol)


if __name__ == "__main__":
    unittest.main()
