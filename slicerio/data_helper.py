# Copyright 2008-2020 pydicom authors. See LICENSE file for details.
"""Helper functions for accessing test data.
"""

import os
from pathlib import Path

DATA_ROOT = Path(__file__).parent.joinpath('data')
"""The absolute path to the data_files directory."""


def get_testdata_file(filename):
    """Return an absolute path to the first matching dataset with filename `filename`.
    :param filename: file name (without path)
    :return: absolute path of the test data file.
    """
    absolute_path = DATA_ROOT.joinpath(filename)

    if not absolute_path.is_file():
        raise FileNotFoundError(filename)

    return os.fspath(absolute_path.resolve())
