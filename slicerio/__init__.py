"""slicerio package -- Python utilities for readin and writing 3D Slicer supported data sets.

-----------
Quick Start
-----------

See the files in the examples directory that came with this package for more examples.

Any questions or need help? Post on 3D Slicer forum: https://discourse.slicer.org

Bugs and other issues can be reported in the issue tracker: https://www.github.com/lassoan/slicerio

"""

from .segmentation import (add_segment, create_segmentation, extract_segments, read_segmentation, write_segmentation,
                           segment_from_id, segment_from_name, segment_mask, segment_names)
from .volume import (apply_displacement_field, component_vectors_to_lps, create_sequence, number_of_frames, read_volume,
                     sample_volume, sequence_frame, write_volume)
from .markups import fcsv_to_markups_json, read_markups_fcsv
from .data_helper import download_testing_data_file, get_testdata_file, testing_data_file_names, testing_data_manifest
from importlib.metadata import version, PackageNotFoundError
try:
    __version__ = version("slicerio")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = [
   '__version__',
   'add_segment',
   'apply_displacement_field',
   'component_vectors_to_lps',
   'create_segmentation',
   'create_sequence',
   'download_testing_data_file',
   'extract_segments',
   'fcsv_to_markups_json',
   'get_testdata_file',
   'number_of_frames',
   'read_markups_fcsv',
   'read_segmentation',
   'read_volume',
   'sample_volume',
   'segment_from_id',
   'segment_from_name',
   'segment_mask',
   'segment_names',
   'sequence_frame',
   'testing_data_file_names',
   'testing_data_manifest',
   'write_segmentation',
   'write_volume',
]
