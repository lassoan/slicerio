# -*- coding: utf-8 -*-

import logging
import requests

# Port number of the local Slicer server.
# It can be modified before starting the server if the default port number is not desirable.
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
    response = requests.delete(f"http://127.0.0.1:{SERVER_PORT}/system")
    return response.json()

def is_server_running():
    """Check if a local Slicer server is running.
    Returns true if a responsive Slicer instance is found with Web Server and Slicer API enabled.
    """
    try:
        response = requests.get(f"http://127.0.0.1:{SERVER_PORT}/slicer/system/version", timeout=3)
        if 'applicationName' in response.json():
            # Found a responsive Slicer
            return True
    except Exception as e:
        logging.debug("Application is not available: "+str(e))
    return False

def _node_query_parameters(name, id, class_name):
    param_list = []
    import urllib
    if name:
        param_list.append(f"name={urllib.request.quote(name, safe='')}")
    if id:
        param_list.append(f"id={urllib.request.quote(id, safe='')}")
    if class_name:
        param_list.append(f"class={urllib.request.quote(class_name, safe='')}")
    return '&'.join(param_list)

def _report_error(response):
    if response.ok:
        return
    if response.headers['Content-Type'] == 'application/json':
        if "message" in response.json():
            raise RuntimeError(response.json()["message"])
    raise RuntimeError("Request failed")

def node_remove(name=None, id=None, class_name=None):
    """Remove data nodes from the local Slicer server.
    Nodes can be selected using name, id, and/or class_name.
    """
    api_url = f"http://127.0.0.1:{SERVER_PORT}/slicer/mrml"
    node_query = _node_query_parameters(name, id, class_name)
    if node_query:
        api_url += "?" + node_query
    response = requests.delete(api_url)
    _report_error(response)

def node_reload(name=None, id=None, class_name=None):
    """Reload the node from that file it was originally loaded from.
    This can be used for updating a node that was loaded using `file_load()`,
    to prevent proliferation of displayed nodes.
    Nodes can be selected using name, id, and/or class_name.
    """
    api_url = f"http://127.0.0.1:{SERVER_PORT}/slicer/mrml"
    node_query = _node_query_parameters(name, id, class_name)
    if node_query:
        api_url += "?" + node_query
    response = requests.put(api_url)
    _report_error(response)

def node_properties(name=None, id=None, class_name=None):
    """Get properties of data nodes on the local Slicer server.
    Nodes can be selected using name, id, and/or class_name.
    """
    api_url = f"http://127.0.0.1:{SERVER_PORT}/slicer/mrml/properties"
    node_query = _node_query_parameters(name, id, class_name)
    if node_query:
        api_url += "?" + node_query
    response = requests.get(api_url)
    _report_error(response)
    response_json = response.json()
    properties = [response_json[key] for key in response_json]
    return properties

def node_ids(name=None, id=None, class_name=None):
    """Get list of ids of nodes availalbe on the local Slicer server.
    Nodes can be selected using name, id, and/or class_name.
    """
    api_url = f"http://127.0.0.1:{SERVER_PORT}/slicer/mrml/ids"
    node_query = _node_query_parameters(name, id, class_name)
    if node_query:
        api_url += "?" + node_query
    response = requests.get(api_url)
    _report_error(response)
    return response.json()

def node_names(name=None, id=None, class_name=None):
    """Get list of names of nodes availalbe on the local Slicer server.
    Nodes can be selected using name, id, and/or class_name.
    """
    api_url = f"http://127.0.0.1:{SERVER_PORT}/slicer/mrml/names"
    node_query = _node_query_parameters(name, id, class_name)
    if node_query:
        api_url += "?" + node_query
    response = requests.get(api_url)
    _report_error(response)
    return response.json()

def file_save(file_path, name=None, id=None, class_name=None, properties=None):
    """Save node into file on the local Slicer server.
    :param path: local filename or URL of the file to write
    :param properties: dictionary of additional properties. For example, `useCompression` specifies if the written file will be compressed.
    """
    import urllib

    if file_path is not None:
        file_path = str(file_path)

    url_encoded_path = urllib.request.quote(file_path, safe='')
    api_url = f"http://127.0.0.1:{SERVER_PORT}/slicer/mrml/file?localfile={url_encoded_path}"
    node_query = _node_query_parameters(name, id, "")
    if node_query:
        api_url += "&" + node_query
    if properties:
        for key in properties:
            url_encoded_key = urllib.request.quote(key.encode(), safe='')
            url_encoded_value = urllib.request.quote(str(properties[key]).encode(), safe='')
            api_url += f"&{url_encoded_key}={url_encoded_value}"
    response = requests.get(api_url)
    _report_error(response)

def file_load(file_path, file_type=None, properties=None, auto_start=True, timeout_sec=60, slicer_executable=None):
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
    :return: list of loaded node IDs (they can be used in further queries).
    """
    import urllib

    if file_path is not None:
        file_path = str(file_path)

    if file_type is None:
        file_type = "VolumeFile"
    p = urllib.parse.urlparse(file_path)
    if p.scheme == 'slicer':
        # Slicer URL - use it as is. For example:
        # slicer://viewer/?studyUID=1.2.826.0.1.3680043.8.498.77209180964150541470378654317482622226&dicomweb_endpoint=http%3A%2F%2F130.15.7.119:2016%2Fdicom&bulk_retrieve=0
        url_encoded_path = urllib.request.quote(file_path, safe='')
        api_url = f"http://127.0.0.1:{SERVER_PORT}/slicer/open?url={url_encoded_path}"
    else:
        # Local file path or remote download path
        path_type = 'url' if p.scheme in ['http', 'https'] else 'localfile'
        url_encoded_path = urllib.request.quote(file_path, safe='')
        api_url = f"http://127.0.0.1:{SERVER_PORT}/slicer/mrml?{path_type}={url_encoded_path}&filetype={file_type}"
        if properties:
            for key in properties:
                url_encoded_key = urllib.request.quote(key.encode(), safe='')
                url_encoded_value = urllib.request.quote(str(properties[key]).encode(), safe='')
                api_url += f"&{url_encoded_key}={url_encoded_value}"

    retry_after_starting_server = True
    try:
        response = requests.post(api_url)
        retry_after_starting_server = False
    except requests.exceptions.ConnectionError as e:
        if not auto_start:
            raise

    if retry_after_starting_server:
        # Try again, with starting a server first
        server_process = start_server(slicer_executable)
        response = requests.post(api_url)

    _report_error(response)

    response_json = response.json()
    return response_json["loadedNodeIDs"] if "loadedNodeIDs" in response_json else []
