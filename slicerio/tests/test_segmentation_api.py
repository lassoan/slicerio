# -*- coding: utf-8 -*-

import os
import tempfile
import unittest

import numpy as np

import slicerio
from slicerio import segmentation as slicerio_segmentation


class TemporaryFile:
    """Path of a temporary file that is removed when the context exits."""

    def __init__(self, suffix):
        self.suffix = suffix

    def __enter__(self):
        handle, self.path = tempfile.mkstemp(suffix=self.suffix)
        os.close(handle)
        return self.path

    def __exit__(self, *args):
        if os.path.exists(self.path):
            os.remove(self.path)


class TestTerminology(unittest.TestCase):
    """Terminology entry strings (TerminologyEntry segment tag) and terminology matching."""

    FULL_ENTRY = ("Segmentation category and type - 3D Slicer General Anatomy list"
                  "~SCT^49755003^Morphologically Altered Structure~SCT^4147007^Mass~^^"
                  "~Anatomic codes - DICOM master list~SCT^23451007^Adrenal gland~SCT^24028007^Right")

    def test_from_string(self):
        terminology = slicerio_segmentation.terminology_entry_from_string(self.FULL_ENTRY)
        self.assertEqual(terminology, {
            "contextName": "Segmentation category and type - 3D Slicer General Anatomy list",
            "category": ["SCT", "49755003", "Morphologically Altered Structure"],
            "type": ["SCT", "4147007", "Mass"],
            "anatomicContextName": "Anatomic codes - DICOM master list",
            "anatomicRegion": ["SCT", "23451007", "Adrenal gland"],
            "anatomicRegionModifier": ["SCT", "24028007", "Right"]})

    def test_string_roundtrip(self):
        terminology = slicerio_segmentation.terminology_entry_from_string(self.FULL_ENTRY)
        self.assertEqual(slicerio_segmentation.terminology_entry_to_string(terminology), self.FULL_ENTRY)
        # Without the optional parts
        minimal = {"category": ["SCT", "123037004", "Anatomical Structure"], "type": ["SCT", "10200004", "Liver"]}
        entry = slicerio_segmentation.terminology_entry_to_string(minimal)
        self.assertEqual(entry, "~SCT^123037004^Anatomical Structure~SCT^10200004^Liver~^^~~^^~^^")
        self.assertEqual(slicerio_segmentation.terminology_entry_from_string(entry), dict(minimal, contextName=""))

    def test_matching(self):
        matches = slicerio_segmentation.terminology_entry_matches
        lung = {"category": ["SCT", "123037004", "Anatomical Structure"], "type": ["SCT", "39607008", "Lung"]}
        right_lung = dict(lung, typeModifier=["SCT", "24028007", "Right"])
        left_lung = dict(lung, typeModifier=["SCT", "7771000", "Left"])
        # Only coding scheme and code value are compared, not the code meaning
        self.assertTrue(matches(lung, {"category": ["SCT", "123037004", "Structure"], "type": ["SCT", "39607008", "Lungs"]}))
        self.assertTrue(matches(right_lung, dict(right_lung)))
        self.assertFalse(matches(right_lung, left_lung))
        # A modifier that only one of them has is a mismatch
        self.assertFalse(matches(lung, right_lung))
        self.assertFalse(matches(right_lung, lung))
        region = dict(lung, anatomicRegion=["SCT", "23451007", "Adrenal gland"])
        self.assertFalse(matches(lung, region))
        self.assertTrue(matches(region, dict(region)))

    def test_segments_from_terminology(self):
        segmentation = slicerio.read_segmentation(slicerio.get_testdata_file("Segmentation.seg.nrrd"), skip_voxels=True)
        lung = {"category": ["SCT", "123037004", "Anatomical Structure"], "type": ["SCT", "39607008", "Lung"],
                "typeModifier": ["SCT", "24028007", "Right"]}
        found = slicerio_segmentation.segments_from_terminology(segmentation, lung)
        self.assertEqual([segment["name"] for segment in found], ["right lung"])


class TestSegmentLookup(unittest.TestCase):
    """Finding segments by ID and name."""

    def setUp(self):
        self.segmentation = slicerio.read_segmentation(slicerio.get_testdata_file("Segmentation.seg.nrrd"))

    def test_from_id_and_name(self):
        self.assertEqual(slicerio.segment_from_id(self.segmentation, "Segment_5")["name"], "right lung")
        self.assertEqual(slicerio.segment_from_name(self.segmentation, "right lung")["id"], "Segment_5")
        self.assertEqual(slicerio_segmentation.segment_id_from_name(self.segmentation, "ribs"), "Segment_1")

    def test_not_found(self):
        with self.assertRaises(KeyError):
            slicerio.segment_from_id(self.segmentation, "no such ID")
        with self.assertRaises(KeyError):
            slicerio.segment_from_name(self.segmentation, "no such name")
        with self.assertRaises(KeyError):
            slicerio.segment_mask(self.segmentation, "no such segment")

    def test_duplicate_names(self):
        # A name that several segments have is ambiguous, the segment must be specified by ID
        self.segmentation["segments"][1]["name"] = "ribs"
        with self.assertRaises(KeyError):
            slicerio.segment_mask(self.segmentation, "ribs")
        self.assertEqual(slicerio.segment_mask(self.segmentation, "Segment_2").sum(),
                         (self.segmentation["voxels"] == self.segmentation["segments"][1]["labelValue"]).sum())

    def test_id_takes_precedence_over_name(self):
        # A segment named as the ID of another segment
        self.segmentation["segments"][1]["name"] = "Segment_1"
        mask = slicerio.segment_mask(self.segmentation, "Segment_1")
        self.assertTrue(np.array_equal(mask, self.segmentation["voxels"] == self.segmentation["segments"][0]["labelValue"]))


class TestSegmentMask(unittest.TestCase):
    """Binary mask of a segment."""

    def test_single_layer(self):
        segmentation = slicerio.read_segmentation(slicerio.get_testdata_file("Segmentation.seg.nrrd"))
        self.assertEqual(segmentation["voxels"].ndim, 3)
        ribs = slicerio.segment_mask(segmentation, "ribs")
        self.assertEqual(ribs.dtype, bool)
        self.assertEqual(ribs.shape, segmentation["voxels"].shape)
        self.assertEqual(int(ribs.sum()), 8487)
        self.assertEqual(int(slicerio.segment_mask(segmentation, "right lung").sum()), 34450)
        # Segments of a single layer do not overlap
        masks = [slicerio.segment_mask(segmentation, segment) for segment in segmentation["segments"]]
        self.assertEqual(int(np.sum(masks, axis=0).max()), 1)

    def test_overlapping_segments_are_kept(self):
        # The overlapping test segmentation has the segments of the single layer test segmentation and a sphere that
        # overlaps them: the masks of the shared segments are the same in both files
        single = slicerio.read_segmentation(slicerio.get_testdata_file("Segmentation.seg.nrrd"))
        overlapping = slicerio.read_segmentation(slicerio.get_testdata_file("SegmentationOverlapping.seg.nrrd"))
        for name in ("ribs", "right lung"):
            self.assertTrue(np.array_equal(slicerio.segment_mask(single, name),
                                           slicerio.segment_mask(overlapping, name)), name)
        masks = [slicerio.segment_mask(overlapping, segment) for segment in overlapping["segments"]]
        self.assertGreater(int(np.sum(masks, axis=0).max()), 1)

    def test_requires_voxels(self):
        segmentation = slicerio.read_segmentation(slicerio.get_testdata_file("Segmentation.seg.nrrd"), skip_voxels=True)
        with self.assertRaises(ValueError):
            slicerio.segment_mask(segmentation, "ribs")


class TestAddSegment(unittest.TestCase):
    """Adding segments from binary masks."""

    IJK_TO_LPS = [[0.5, 0, 0, 10], [0, 0.5, 0, 30], [0, 0, 0.8, 15], [0, 0, 0, 1]]

    def box(self, shape, *ranges):
        mask = np.zeros(shape, bool)
        mask[tuple(slice(*r) for r in ranges)] = True
        return mask

    def test_create_segmentation(self):
        segmentation = slicerio.create_segmentation([4, 5, 6], self.IJK_TO_LPS)
        self.assertEqual(segmentation["voxels"].shape, (4, 5, 6))
        self.assertEqual(segmentation["voxels"].dtype, np.uint8)
        self.assertFalse(segmentation["voxels"].any())
        self.assertEqual(segmentation["segments"], [])
        self.assertTrue(np.allclose(segmentation["ijkToLPS"], self.IJK_TO_LPS))

    def test_generated_id_and_defaults(self):
        segmentation = slicerio.create_segmentation([10, 10, 10], self.IJK_TO_LPS)
        first = slicerio.add_segment(segmentation, self.box([10, 10, 10], (0, 2), (0, 2), (0, 2)))
        second = slicerio.add_segment(segmentation, self.box([10, 10, 10], (5, 7), (5, 7), (5, 7)))
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["name"], first["id"])
        self.assertEqual(first["extent"], [0, 1, 0, 1, 0, 1])
        # The segment dict that is passed is not modified
        properties = {"name": "liver"}
        added = slicerio.add_segment(segmentation, self.box([10, 10, 10], (3, 4), (3, 4), (3, 4)), properties)
        self.assertEqual(properties, {"name": "liver"})
        self.assertEqual(added["name"], "liver")

    def test_empty_mask(self):
        segmentation = slicerio.create_segmentation([10, 10, 10], self.IJK_TO_LPS)
        added = slicerio.add_segment(segmentation, np.zeros([10, 10, 10], bool), {"id": "empty"})
        self.assertEqual(added["extent"], [0, -1, 0, -1, 0, -1])
        self.assertFalse(slicerio.segment_mask(segmentation, "empty").any())

    def test_invalid_input(self):
        segmentation = slicerio.create_segmentation([10, 10, 10], self.IJK_TO_LPS)
        with self.assertRaises(ValueError):
            slicerio.add_segment(segmentation, np.zeros([10, 10, 9], bool))
        slicerio.add_segment(segmentation, np.zeros([10, 10, 10], bool), {"id": "a"})
        with self.assertRaises(ValueError):
            slicerio.add_segment(segmentation, np.zeros([10, 10, 10], bool), {"id": "a"})
        without_voxels = slicerio.read_segmentation(slicerio.get_testdata_file("Segmentation.seg.nrrd"), skip_voxels=True)
        with self.assertRaises(ValueError):
            slicerio.add_segment(without_voxels, np.zeros([128, 128, 34], bool))

    def test_add_to_segmentation_from_file(self):
        segmentation = slicerio.read_segmentation(slicerio.get_testdata_file("Segmentation.seg.nrrd"))
        original_masks = {s["id"]: slicerio.segment_mask(segmentation, s) for s in segmentation["segments"]}
        shape = segmentation["voxels"].shape
        free = segmentation["voxels"] == 0
        # A segment in voxels that no segment occupies goes into the existing layer, with the next label value
        label_values = [s["labelValue"] for s in segmentation["segments"]]
        corner = self.box(shape, (0, 2), (0, 2), (0, 2)) & free
        self.assertTrue(corner.any())
        added = slicerio.add_segment(segmentation, corner, {"id": "corner"})
        self.assertEqual((added["layer"], added["labelValue"]), (0, max(label_values) + 1))
        self.assertEqual(segmentation["voxels"].ndim, 3)
        # A segment that overlaps existing segments goes into a new layer
        added = slicerio.add_segment(segmentation, ~free, {"id": "everything"})
        self.assertEqual((added["layer"], added["labelValue"]), (1, 1))
        self.assertEqual(segmentation["voxels"].shape, (2,) + shape)
        # Existing segments are not changed
        for segment_id, mask in original_masks.items():
            self.assertTrue(np.array_equal(slicerio.segment_mask(segmentation, segment_id), mask), segment_id)
        self.assertTrue(np.array_equal(slicerio.segment_mask(segmentation, "corner"), corner))
        self.assertTrue(np.array_equal(slicerio.segment_mask(segmentation, "everything"), ~free))

    def test_label_value_overflow(self):
        # A layer of an 8-bit labelmap holds at most 255 label values
        segmentation = slicerio.create_segmentation([3, 3, 3], self.IJK_TO_LPS)
        full = slicerio.add_segment(segmentation, self.box([3, 3, 3], (0, 1), (0, 1), (0, 1)), {"id": "full"})
        full["labelValue"] = 255
        added = slicerio.add_segment(segmentation, self.box([3, 3, 3], (2, 3), (2, 3), (2, 3)), {"id": "next"})
        self.assertEqual((added["layer"], added["labelValue"]), (1, 1))

    def test_many_segments_roundtrip(self):
        # Overlapping and non-overlapping segments, written and read back
        shape = [20, 16, 12]
        rng = np.random.default_rng(0)
        segmentation = slicerio.create_segmentation(shape, self.IJK_TO_LPS)
        masks = {}
        for index in range(12):
            start = rng.integers(0, 10, size=3)
            size = rng.integers(1, 6, size=3)
            masks[f"segment{index}"] = self.box(shape, *zip(start, start + size))
            slicerio.add_segment(segmentation, masks[f"segment{index}"],
                                 {"id": f"segment{index}", "color": [0.1 * index, 0.5, 0.5]})
        with TemporaryFile(".seg.nrrd") as path:
            slicerio.write_segmentation(path, segmentation)
            stored = slicerio.read_segmentation(path)
        self.assertEqual(slicerio.segment_names(stored), list(masks))
        for name, mask in masks.items():
            self.assertTrue(np.array_equal(slicerio.segment_mask(stored, name), mask), name)
        self.assertTrue(np.allclose(stored["ijkToLPS"], self.IJK_TO_LPS))


class TestReadWrite(unittest.TestCase):
    """Reading and writing segmentation files."""

    def test_overlapping_roundtrip(self):
        segmentation = slicerio.read_segmentation(slicerio.get_testdata_file("SegmentationOverlapping.seg.nrrd"))
        self.assertEqual(segmentation["voxels"].ndim, 4)
        with TemporaryFile(".seg.nrrd") as path:
            slicerio.write_segmentation(path, segmentation)
            stored = slicerio.read_segmentation(path)
        self.assertEqual(stored["voxels"].shape, segmentation["voxels"].shape)
        self.assertTrue(np.allclose(stored["ijkToLPS"], segmentation["ijkToLPS"]))
        for segment in segmentation["segments"]:
            self.assertTrue(np.array_equal(slicerio.segment_mask(stored, segment["id"]),
                                           slicerio.segment_mask(segmentation, segment)))
            self.assertEqual(slicerio.segment_from_id(stored, segment["id"]).get("terminology"), segment.get("terminology"))

    def test_write_requires_voxels(self):
        segmentation = slicerio.read_segmentation(slicerio.get_testdata_file("Segmentation.seg.nrrd"), skip_voxels=True)
        with TemporaryFile(".seg.nrrd") as path:
            with self.assertRaises(ValueError):
                slicerio.write_segmentation(path, segmentation)

    def test_ras_space(self):
        # A file in RAS space: the IJK to LPS matrix has the first two axes flipped
        import nrrd
        voxels = np.zeros([4, 5, 6], np.uint8)
        voxels[1:3, 1:3, 1:3] = 1
        header = {"space": "right-anterior-superior", "space origin": np.array([1.0, 2.0, 3.0]),
                  "space directions": np.diag([0.5, 0.6, 0.7]), "kinds": ["domain"] * 3,
                  "Segment0_ID": "box", "Segment0_Name": "box", "Segment0_LabelValue": "1", "Segment0_Layer": "0"}
        with TemporaryFile(".seg.nrrd") as path:
            nrrd.write(path, voxels, header)
            segmentation = slicerio.read_segmentation(path)
        expected = np.diag([-1.0, -1.0, 1.0, 1.0]) @ np.array([[0.5, 0, 0, 1], [0, 0.6, 0, 2], [0, 0, 0.7, 3], [0, 0, 0, 1]])
        self.assertTrue(np.allclose(segmentation["ijkToLPS"], expected))
        self.assertTrue(np.array_equal(slicerio.segment_mask(segmentation, "box"), voxels == 1))

    def test_unsupported_space(self):
        import nrrd
        header = {"space": "left-anterior-superior", "space directions": np.eye(3), "kinds": ["domain"] * 3}
        with TemporaryFile(".seg.nrrd") as path:
            nrrd.write(path, np.zeros([2, 2, 2], np.uint8), header)
            with self.assertRaises(IOError):
                slicerio.read_segmentation(path)

    def test_generate_unique_segment_id(self):
        existing = {"Segment_1", "Segment_2"}
        generated = slicerio_segmentation.generate_unique_segment_id(existing)
        self.assertNotIn(generated, existing)
        self.assertTrue(generated)


if __name__ == "__main__":
    unittest.main()
