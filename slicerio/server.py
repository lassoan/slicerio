# -*- coding: utf-8 -*-

import logging
import requests

# Initially stores default server port.
# If successfully co
SERVER_PORT = 2016

def start_server(slicer_executable=None, timeoutSec=60):
    """Starts local Slicer server.
    Requires slicer_executable argument or `SLICER_EXECUTABLE` environment variable to be set to a Slicer executable (version 5.2 or later).
    :param slicer_executable: Slicer application main executable.
    """
    import os
    import subprocess
    import time
    if not slicer_executable:
        if 'SLICER_EXECUTABLE' not in os.environ:
            raise ValueError('SLICER_EXECUTABLE environment variable is not specified')
        slicer_executable = os.environ['SLICER_EXECUTABLE']
    p = subprocess.Popen([slicer_executable, "--python-code", f"wslogic = getModuleLogic('WebServer'); wslogic.port={SERVER_PORT}; wslogic.addDefaultRequestHandlers(); wslogic.start()"])
    start = time.time()
    connected = False
    while not connected:
        connected = is_server_running()
        if time.time() - start > timeoutSec:
            raise requests.exceptions.ConnectTimeout("Timeout while waiting for application to start")
    return p

def stop_server():
    """Stop local Slicer server.
    """
    response = requests.delete(f"http://localhost:{SERVER_PORT}/slicer/gui")
    return response.json()

def is_server_running():
    """Check if a local Slicer server is running.
    Returns true if a responsive Slicer instance is found with Web Server and Slicer API enabled.
    """
    try:
        response = requests.get(f"http://localhost:{SERVER_PORT}/slicer/gui/version", timeout=3)
        if 'applicationName' in response.json():
            # Found a responsive Slicer
            return True
    except Exception as e:
        logging.debug("Application is not available: "+str(e))
    return False

def reset_server():
    """Clear all data loaded into the local Slicer server.
    """
    response = requests.delete(f"http://localhost:{SERVER_PORT}/slicer/mrml")
    return response.json()

def view_file(file_path, file_type=None, properties=None, auto_start=True, timeout_sec=60, slicer_executable=None):
    """Load a file into the local Slicer server.
    :param path: local filename or URL of the file to open
    :param type: type of the file to open `VolumeFile` (nrrd, nii, ... files; this is the default), `SegmentationFile` (nrrd, nii, ... files),
        `ModelFile` (stl, ply, vtk, vtp, vtu, ... files), `MarkupsFile` (mrk.json files),
        `TransformFile` (tfm, h5, ... files), `TableFile` (csv, tsv, ... files), `TextFile` (txt, json, ... files),
        `SequenceFile` (seq.nrrd, mrb, ... files), `SceneFile` (mrml, mrb files), etc.
    :param properties: dictionary of additional properties. For example, `name` specifies name by the loaded file will appear in the application.
    :param auto_start: automatically start a Slicer application if a server not found at the specified port. Requires slicer_executable
        argument or `SLICER_EXECUTABLE` environment variable to be set to a Slicer executable (version 5.2 or later),
        such as `/Applications/Slicer.app/Contents/MacOS/Slicer` or `c:/Users/username/appdata/Local/NA-MIC/Slicer 5.2.0/Slicer.exe`
    :param slicer_executable: Slicer application main executable. Used if `auto_start` is enabled.
    :return: dictionary of load result. `loadedNodeIDs` contain list of loaded node IDs (that may be used in further requests).
    """
    import urllib
    if file_type is None:
        file_type = "VolumeFile"
    p = urllib.parse.urlparse(file_path)
    if p.scheme == 'slicer':
        # Slicer URL - use it as is. For example:
        # slicer://viewer/?studyUID=1.2.826.0.1.3680043.8.498.77209180964150541470378654317482622226&dicomweb_endpoint=http%3A%2F%2F130.15.7.119:2016%2Fdicom&bulk_retrieve=0
        url_encoded_path = urllib.request.quote(file_path, safe='')
        api_url = f"http://localhost:{SERVER_PORT}/slicer/open?url={url_encoded_path}"
    else:
        # Local file path or remote download path
        path_type = 'url' if p.scheme in ['http', 'https'] else 'localfile'
        url_encoded_path = urllib.request.quote(file_path, safe='')
        api_url = f"http://localhost:{SERVER_PORT}/slicer/mrml?{path_type}={url_encoded_path}&filetype={file_type}"
        if properties:
            for key in properties:
                url_encoded_key = urllib.request.quote(key.encode(), safe='')
                url_encoded_value = urllib.request.quote(str(properties[key]).encode(), safe='')
                api_url += f"&{url_encoded_key}={url_encoded_value}"
    try:
        response = requests.post(api_url)
    except requests.exceptions.ConnectionError as e:
        if not auto_start:
            raise
        # Try again, with starting a server first
        start_server(slicer_executable)
        response = requests.post(api_url)
    return response.json()
