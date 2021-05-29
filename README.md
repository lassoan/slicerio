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

## Example

1. Read segmentation and show some information about segments

```
import slicerio
segmentation_info = slicerio.read_segmentation_info("Segmentation.seg.nrrd")

number_of_segments = len(segmentation_info["segments"])
print(f"Number of segments: {number_of_segments}")

segment_names = slicerio.segment_names(segmentation_info)
print(f"Segment names: {', '.join(segment_names)}")

segment0 = segment_from_name(segmentation_info, names[0])
print(f"First segment info: {segment0})
```

# Extract selected segments with chosen label values

```python
extracted_filename = "c:/Users/andra/OneDrive/Projects/SegmentationPynrrd/SegmentationExtracted.seg.nrrd"
voxels, header = nrrd.read(filename)
segment_list = [("Segment_1", 10), ("Segment_3", 12), ("Segment_4", 6)]
extracted_voxels, extracted_header = extract_segments(voxels, header, segmentation_info, segment_list)
nrrd.write(extracted_filename, extracted_voxels, extracted_header)
```
