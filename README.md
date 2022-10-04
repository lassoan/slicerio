[![Python package](https://github.com/lassoan/slicerio/workflows/Python%20package/badge.svg)](https://github.com/lassoan/slicerio/actions?query=workflow%3A%22Python+package%22)
![Upload Python Package](https://github.com/lassoan/slicerio/workflows/Upload%20Python%20Package/badge.svg)
[![PyPI version](https://badge.fury.io/py/slicerio.svg)](https://badge.fury.io/py/slicerio)

# *slicerio*

Python utilities for [3D Slicer](https://www.slicer.org) interoperability.

The package contains utility functions for reading and writing segmentation files and convenience functions for using 3D Slicer via its web API. More functions will be added in the future.

## Installation

Using [pip](https://pip.pypa.io/en/stable/):

```
pip install slicerio
```

## Examples

### Read segmentation and show some information about segments

```python
import slicerio
import json

segmentation_info = slicerio.read_segmentation_info("Segmentation.seg.nrrd")

number_of_segments = len(segmentation_info["segments"])
print(f"Number of segments: {number_of_segments}")

segment_names = slicerio.segment_names(segmentation_info)
print(f"Segment names: {', '.join(segment_names)}")

segment0 = slicerio.segment_from_name(segmentation_info, segment_names[0])
print("First segment info:\n" + json.dumps(segment0, sort_keys=False, indent=4))
```

### Extract selected segments with chosen label values

```python
import slicerio
import nrrd

input_filename = "path/to/Segmentation.seg.nrrd"
output_filename = "path/to/SegmentationExtracted.seg.nrrd"
segment_names_to_labels = [("ribs", 10), ("right lung", 12), ("left lung", 6)]

voxels, header = nrrd.read(input_filename)
extracted_voxels, extracted_header = slicerio.extract_segments(voxels, header, segmentation_info, segment_names_to_labels)
nrrd.write(output_filename, extracted_voxels, extracted_header)
```

### View files in 3D Slicer

It is useful to load several files in a single Slicer instance, because then there is no need to wait for multiple
application startups and multiple data sets can be compared in one environment. This can be achieved by activating
3D Slicer's Web Server module, which provides a web API to control the application.

For example, an image file can be loaded with the command below. The command starts a new Slicer application instance
with the web API enabled.

```python
import slicerio
import os
slicerio.view_file("path/to/SomeImage.nrrd", slicer_executable=f"{os.environ["LOCALAPPDATA"]}/NA-MIC/Slicer 5.2.0/Slicer.exe")
```

A segmentation file can be loaded in the same Slicer instance:

```python
import slicerio
slicerio.view_file("path/to/Segmentation.seg.nrrd", "SegmentationFile")
```

Supported file types:
- image files (nrrd, nii.gz, ...): `VolumeFile`
- segmentation file (.seg.nrrd, nrrd, nii.gz, ...): `SegmentationFile`
- model file (.stl, .ply, .vtk, .vtp, .vtu, ...): `ModelFile`
- markup file (.mrj.json): `MarkupsFile`
- transform file (.tfm, .h5, .txt): `TransformFile`
- spreadsheet file (.csv, .tsv): `TableFile`
- text file (.txt, .json, ...): `TextFile`
- sequence file (.mrb, .seq.nrrd): `SequenceFile`
- Slicer scene file (.mrml, .mrb): `SceneFile`
