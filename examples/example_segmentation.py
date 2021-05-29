"""
============================
Segmentations
============================

Simple example that reads segmentation metadata and voxels.

"""

import slicerio  # pylint: disable=import-error

input_segmentation_filepath = slicerio.get_testdata_file('Segmentation.seg.nrrd')

segmentation_info = slicerio.read_segmentation_info(input_segmentation_filepath)

number_of_segments = len(segmentation_info["segments"])
print(f"Number of segments: {number_of_segments}")

segment_names = slicerio.segment_names(segmentation_info)
print(f"Segment names: {', '.join(segment_names)}")

segment = slicerio.segment_from_name(segmentation_info, segment_names[4])

import json
print(json.dumps(segment, sort_keys=False, indent=4))
