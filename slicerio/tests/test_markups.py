# -*- coding: utf-8 -*-

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import slicerio
from slicerio.markups import (
    fcsv_to_markups_json,
    read_markups_fcsv,
)


class TestReadMarkupsFcsv(unittest.TestCase):
    def setUp(self):
        self.file_path = slicerio.get_testdata_file("F_1.fcsv")
        self.markups = read_markups_fcsv(self.file_path)

    def test_top_level_structure(self):
        self.assertIn("markups", self.markups)
        self.assertEqual(len(self.markups["markups"]), 1)

    def test_markup_metadata(self):
        markup = self.markups["markups"][0]
        self.assertEqual(markup["type"], "Fiducial")
        self.assertEqual(markup["coordinateSystem"], "LPS")

    def test_control_point_count(self):
        self.assertEqual(len(self.markups["markups"][0]["controlPoints"]), 12)

    def test_first_control_point(self):
        cp = self.markups["markups"][0]["controlPoints"][0]
        self.assertEqual(cp["id"], "1")
        self.assertEqual(cp["label"], "F_1-1")
        self.assertNotIn("description", cp)
        self.assertEqual(cp["associatedNodeID"], "vtkMRMLScalarVolumeNode1")
        self.assertAlmostEqual(cp["position"][0], -6.282824184397157)
        self.assertAlmostEqual(cp["position"][1], -51.06216973995272)
        self.assertAlmostEqual(cp["position"][2], -10.2143)
        self.assertTrue(cp["selected"])
        self.assertFalse(cp["locked"])
        self.assertTrue(cp["visibility"])
        self.assertNotIn("positionStatus", cp)

    def test_not_selected(self):
        # Points id=9 and id=13 have sel=0
        cp = self.markups["markups"][0]["controlPoints"][4]
        self.assertEqual(cp["id"], "9")
        self.assertFalse(cp["selected"])
        cp = self.markups["markups"][0]["controlPoints"][8]
        self.assertEqual(cp["id"], "13")
        self.assertFalse(cp["selected"])

    def test_not_visible(self):
        # Point id=2 has vis=0
        cp = self.markups["markups"][0]["controlPoints"][1]
        self.assertEqual(cp["id"], "2")
        self.assertFalse(cp["visibility"])

    def test_locked(self):
        # Point id=7 has lock=1
        cp = self.markups["markups"][0]["controlPoints"][2]
        self.assertEqual(cp["id"], "7")
        self.assertTrue(cp["locked"])

    def test_not_visible_and_locked(self):
        # Point id=8 has vis=0 and lock=1
        cp = self.markups["markups"][0]["controlPoints"][3]
        self.assertEqual(cp["id"], "8")
        self.assertFalse(cp["visibility"])
        self.assertTrue(cp["locked"])

    def test_custom_label(self):
        # Point id=8 has label="Different name"
        cp = self.markups["markups"][0]["controlPoints"][3]
        self.assertEqual(cp["id"], "8")
        self.assertEqual(cp["label"], "Different name")

    def test_non_empty_description(self):
        # Point id=2 has desc="Some description"
        cp = self.markups["markups"][0]["controlPoints"][1]
        self.assertEqual(cp["id"], "2")
        self.assertEqual(cp["description"], "Some description")
        # Point id=11 has desc="Another description"
        cp = self.markups["markups"][0]["controlPoints"][6]
        self.assertEqual(cp["id"], "11")
        self.assertEqual(cp["description"], "Another description")

    def test_empty_description_omitted(self):
        # Points with no description should not have the key at all
        cp = self.markups["markups"][0]["controlPoints"][0]
        self.assertEqual(cp["id"], "1")
        self.assertNotIn("description", cp)

    def test_position_status_omitted(self):
        for cp in self.markups["markups"][0]["controlPoints"]:
            self.assertNotIn("positionStatus", cp)

    def test_non_sequential_ids(self):
        # IDs in the file are not consecutive
        cps = self.markups["markups"][0]["controlPoints"]
        ids = [cp["id"] for cp in cps]
        self.assertEqual(ids, ["1", "2", "7", "8", "9", "10", "11", "12", "13", "14", "47", "51"])

    def test_default_orientation_omitted(self):
        # All points in F_1.fcsv use the default quaternion (0,0,0,1), so orientation is omitted
        for cp in self.markups["markups"][0]["controlPoints"]:
            self.assertNotIn("orientation", cp)

    def _read_fcsv_string(self, content):
        with tempfile.NamedTemporaryFile(suffix=".fcsv", delete=False, mode="w") as f:
            f.write(content)
            temp_path = f.name
        try:
            return read_markups_fcsv(temp_path)
        finally:
            os.remove(temp_path)

    def test_coordinate_system_integer_lps(self):
        markups = self._read_fcsv_string(
            "# Markups fiducial file version = 4.10\n"
            "# CoordinateSystem = 1\n"
            "# columns = id,x,y,z,ow,ox,oy,oz,vis,sel,lock,label,desc,associatedNodeID\n"
            "1,0,0,0,0,0,0,1,1,1,0,P-1,,\n"
        )
        self.assertEqual(markups["markups"][0]["coordinateSystem"], "LPS")

    def test_coordinate_system_integer_ras(self):
        markups = self._read_fcsv_string(
            "# Markups fiducial file version = 4.10\n"
            "# CoordinateSystem = 0\n"
            "# columns = id,x,y,z,ow,ox,oy,oz,vis,sel,lock,label,desc,associatedNodeID\n"
            "1,0,0,0,0,0,0,1,1,1,0,P-1,,\n"
        )
        self.assertEqual(markups["markups"][0]["coordinateSystem"], "RAS")

    def test_coordinate_system_missing_defaults_to_ras(self):
        markups = self._read_fcsv_string(
            "# Markups fiducial file version = 4.10\n"
            "# columns = id,x,y,z,ow,ox,oy,oz,vis,sel,lock,label,desc,associatedNodeID\n"
            "1,0,0,0,0,0,0,1,1,1,0,P-1,,\n"
        )
        self.assertEqual(markups["markups"][0]["coordinateSystem"], "RAS")

    def test_coordinate_system_string(self):
        # Verify the current string format still works for both values
        for cs in ("LPS", "RAS"):
            markups = self._read_fcsv_string(
                f"# Markups fiducial file version = 5.11\n"
                f"# CoordinateSystem = {cs}\n"
                "# columns = id,x,y,z,ow,ox,oy,oz,vis,sel,lock,label,desc,associatedNodeID\n"
                "1,0,0,0,0,0,0,1,1,1,0,P-1,,\n"
            )
            self.assertEqual(markups["markups"][0]["coordinateSystem"], cs)

    def test_non_default_orientation_set_on_all(self):
        # If any point has a non-default quaternion, orientation is written for all points.
        fcsv_content = (
            "# Markups fiducial file version = 5.11\n"
            "# CoordinateSystem = LPS\n"
            "# columns = id,x,y,z,ow,ox,oy,oz,vis,sel,lock,label,desc,associatedNodeID\n"
            "1,0,0,0,0.7071,0.7071,0,0,1,1,0,P-1,,\n"  # non-default
            "2,1,0,0,0,0,0,1,1,1,0,P-2,,\n"            # default
        )
        with tempfile.NamedTemporaryFile(suffix=".fcsv", delete=False, mode="w") as f:
            f.write(fcsv_content)
            temp_path = f.name
        try:
            markups = read_markups_fcsv(temp_path)
            cps = markups["markups"][0]["controlPoints"]
            self.assertEqual(len(cps), 2)
            for cp in cps:
                self.assertIn("orientation", cp)
                self.assertEqual(len(cp["orientation"]), 9)
        finally:
            os.remove(temp_path)


class TestFcsvToMarkupsJson(unittest.TestCase):
    def test_conversion_output(self):
        fcsv_path = slicerio.get_testdata_file("F_1.fcsv")
        with tempfile.NamedTemporaryFile(suffix=".mrk.json", delete=False, mode="w") as f:
            temp_path = f.name
        try:
            fcsv_to_markups_json(fcsv_path, temp_path)
            with open(temp_path, encoding="utf-8") as f:
                converted = json.load(f)
            markup = converted["markups"][0]

            self.assertEqual(markup["coordinateSystem"], "LPS")
            self.assertEqual(len(markup["controlPoints"]), 12)

            # Spot-check a few control points
            cp0 = markup["controlPoints"][0]
            self.assertEqual(cp0["id"], "1")
            self.assertEqual(cp0["label"], "F_1-1")
            self.assertAlmostEqual(cp0["position"][0], -6.282824184397157)
            self.assertTrue(cp0["selected"])
            self.assertFalse(cp0["locked"])

            cp1 = markup["controlPoints"][1]
            self.assertEqual(cp1["id"], "2")
            self.assertFalse(cp1["visibility"])
            self.assertEqual(cp1["description"], "Some description")

            cp2 = markup["controlPoints"][2]
            self.assertEqual(cp2["id"], "7")
            self.assertTrue(cp2["locked"])

            cp3 = markup["controlPoints"][3]
            self.assertEqual(cp3["id"], "8")
            self.assertEqual(cp3["label"], "Different name")
            self.assertFalse(cp3["visibility"])
            self.assertTrue(cp3["locked"])
        finally:
            os.remove(temp_path)

    def test_default_output_path(self):
        # Use a temp copy of the fcsv so the generated output goes to a temp
        # directory and does not overwrite the reference data file.
        fcsv_path = Path(slicerio.get_testdata_file("F_1.fcsv"))
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_fcsv = Path(tmp_dir) / fcsv_path.name
            shutil.copy2(fcsv_path, tmp_fcsv)
            expected_output = tmp_fcsv.with_suffix(".mrk.json")
            result = fcsv_to_markups_json(tmp_fcsv)
            self.assertEqual(Path(result), expected_output)
            self.assertTrue(expected_output.exists())


if __name__ == "__main__":
    unittest.main()
