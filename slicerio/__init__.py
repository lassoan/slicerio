"""slicerio package -- Python utilities for readin and writing 3D Slicer supporte data sets.

-----------
Quick Start
-----------

See the files in the examples directory that came with this package for more examples.

Any questions or need help? Post on 3D Slicer forum: https://discourse.slicer.org

Bugs and other issues can be reported in the issue tracker: https://www.github.com/lassoan/slicerio

"""

from .segmentation import extract_segments, read_segmentation, write_segmentation, segment_from_name, segment_names
from .data_helper import get_testdata_file
from ._version import __version__, __version_info__

__all__ = [
   'extract_segments',
   'get_testdata_file',
   'read_segmentation',
   'write_segmentation',
   'segment_from_name',
   'segment_names',
   '__version__',
   '__version_info__'
   ]
