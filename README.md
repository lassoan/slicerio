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

The `server` module allows using Slicer as a data viewer in any Python environment.
All files are loaded into a single Slicer instance, which eliminates the wait time for application startup
and also allows analyzing, comparing multiple data sets in one workspace. The feature is implemented by using
[3D Slicer's built-in Web Server module](https://slicer.readthedocs.io/en/latest/user_guide/modules/webserver.html), which offers data access via a REST API.

For example, an image file can be loaded with the command below. The command starts a new Slicer application instance
with the web API enabled.

```python
import os
import slicerio.server

# Load from remote URL
slicerio.server.file_load("https://github.com/rbumm/SlicerLungCTAnalyzer/releases/download/SampleData/LungCTAnalyzerChestCT.nrrd")

# Load from local file
# A Slicer application instance (with Web Server enabled) is automatically started, if it is not running already.
slicerio.server.file_load("path/to/SomeImage.nrrd", slicer_executable=f"{os.environ["LOCALAPPDATA"]}/NA-MIC/Slicer 5.2.0/Slicer.exe")
```

A segmentation file can be loaded by specifying the `SegmentationFile` file type:

```python
nodeID = slicerio.server.file_load("path/to/Segmentation.seg.nrrd", "SegmentationFile")
```

If the loaded file is modified then it can be reloaded from the updated file:

```python
slicerio.server.node_reload(id=nodeID)
```

#### Supported file types
- image files (nrrd, nii.gz, ...): `VolumeFile`
- segmentation file (.seg.nrrd, nrrd, nii.gz, ...): `SegmentationFile`
- model file (.stl, .ply, .vtk, .vtp, .vtu, ...): `ModelFile`
- markup file (.mrj.json): `MarkupsFile`
- transform file (.tfm, .h5, .txt): `TransformFile`
- spreadsheet file (.csv, .tsv): `TableFile`
- text file (.txt, .json, ...): `TextFile`
- sequence file (.mrb, .seq.nrrd): `SequenceFile`
- Slicer scene file (.mrml, .mrb): `SceneFile`

### Inspect data in 3D Slicer

Metadata of data sets loaded into the server can be obtained using `node_properties` function:

```python
properties= slicerio.server.node_properties(name="MRHead")[0]
print(properties["ClassName"])
print(properties["ImageData"]["Extent"])

properties = slicerio.server.node_properties(id=segmentationId)[0]
segments = properties["Segmentation"]["Segments"]
for segmentId in segments:
   print(f"Segment name: {segments[segmentId]['Name']} - color: {segments[segmentId]['Color']}")
```

List of available nodes can be retrieved using `node_names` and `node_ids`functions:

```python
# Retreve node names of all images
slicerio.server.node_names(class_name="vtkMRMLVolumeNode")

# Retrieve all node IDs
slicerio.server.node_ids(class_name="vtkMRMLVolumeNode")
```

Nodes can be removed from the workspace:

```python
# Remove node by name
slicerio.server.node_remove(name="MRHead")

# Clear the whole scene
slicerio.server.node_remove()
```

### Export files from 3D Slicer

Data sets created in Slicer (e.g., segmentations, landmark point sets), which can be retrieved by writing into file.

```python
# Save the node identified by `MRHead` node name, uncompressed, into the specified file.
slicerio.server.file_save("c:/tmp/MRHeadSaved.nrrd", name="MRHead", properties={'useCompression': False})
```
