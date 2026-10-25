# Copyright 2008-2020 pydicom authors. See LICENSE file for details.
"""Helper functions for accessing test data.

Small test files are bundled with the package (``slicerio/data``). Larger test data sets are published as assets of
the ``TestingData`` GitHub release of slicerio (see ``scripts/testing_data/README_rev001.md``); they are downloaded
on first use into a cache folder and verified with the SHA256 checksums of the release manifest.
"""

import hashlib
import os
from pathlib import Path

DATA_ROOT = Path(__file__).parent.joinpath('data')
"""The absolute path to the data_files directory."""

TESTING_DATA_URL = "https://github.com/lassoan/slicerio/releases/download/TestingData/"
"""Download URL of the TestingData release assets."""

TESTING_DATA_REVISION = "rev001"
"""Revision of the TestingData release that this package version uses."""

_manifests = {}


def testing_data_cache_dir():
    """Folder where downloaded test data files are stored.

    ``SLICERIO_TESTDATA_CACHE`` environment variable overrides the default ``~/.cache/slicerio/testdata``.
    """
    cache_dir = os.environ.get("SLICERIO_TESTDATA_CACHE")
    if cache_dir:
        return Path(cache_dir)
    return Path.home().joinpath(".cache", "slicerio", "testdata")


def testing_data_manifest(revision=TESTING_DATA_REVISION):
    """Manifest (dict) of a TestingData release revision, downloaded once per session."""
    if revision not in _manifests:
        import requests
        response = requests.get(f"{TESTING_DATA_URL}manifest_{revision}.json", timeout=60)
        response.raise_for_status()
        _manifests[revision] = response.json()
    return _manifests[revision]


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_testing_data_file(filename, revision=TESTING_DATA_REVISION, cache_dir=None):
    """Download a file of the TestingData release (if not cached yet) and return its local path.

    Companion files listed in the manifest (such as the ``.raw.gz`` data file of a detached ``.nhdr`` header)
    are downloaded as well.
    """
    import requests

    cache_dir = Path(cache_dir) if cache_dir else testing_data_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = testing_data_manifest(revision)
    entries = {entry["name"]: entry for entry in manifest.get("files", [])}
    if filename not in entries:
        raise FileNotFoundError(f"{filename} is not part of the TestingData release ({revision})")
    for name in [filename] + list(entries[filename].get("companions", [])):
        entry = entries[name]
        path = cache_dir.joinpath(name)
        if path.is_file() and _sha256(path) == entry["sha256"]:
            continue
        url = entry.get("url", TESTING_DATA_URL + name)
        with requests.get(url, stream=True, timeout=300) as response:
            response.raise_for_status()
            temporary_path = path.with_name(path.name + ".part")
            with open(temporary_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        if _sha256(temporary_path) != entry["sha256"]:
            temporary_path.unlink()
            raise IOError(f"Checksum mismatch after downloading {url}")
        temporary_path.replace(path)
    return os.fspath(cache_dir.joinpath(filename).resolve())


def get_testdata_file(filename):
    """Return an absolute path to the test data file `filename`.

    Files bundled with the package are returned directly; files of the TestingData release are downloaded into the
    cache folder on first use (see :func:`download_testing_data_file`).

    :param filename: file name (without path)
    :return: absolute path of the test data file.
    """
    absolute_path = DATA_ROOT.joinpath(filename)
    if absolute_path.is_file():
        return os.fspath(absolute_path.resolve())
    try:
        return download_testing_data_file(filename)
    except FileNotFoundError:
        raise FileNotFoundError(filename)


def testing_data_file_names(revision=TESTING_DATA_REVISION):
    """Names of all files of a TestingData release revision (from its manifest)."""
    return [entry["name"] for entry in testing_data_manifest(revision).get("files", [])]
