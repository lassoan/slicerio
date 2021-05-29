[![Python package](https://github.com/lassoan/slicerio/workflows/Python%20package/badge.svg)](https://github.com/lassoan/slicerio/actions?query=workflow%3A%22Python+package%22)
![Upload Python Package](https://github.com/lassoan/slicerio/workflows/Upload%20Python%20Package/badge.svg)
[![PyPI version](https://badge.fury.io/py/slicerio.svg)](https://badge.fury.io/py/slicerio)

# *slicerio*

Python utilities for [3D Slicer](https://www.slicer.org) interoperability.

The package contains utility functions for reading and writing segmentation files.
More functions will be added in the future.

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
