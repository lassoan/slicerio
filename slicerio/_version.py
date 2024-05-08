import re
from typing import Tuple

__version__: str = '1.0.0'

__version_info__: Tuple[str, str, str] = tuple(
    re.match(r'(\d+\.\d+\.\d+).*', __version__).group(1).split('.')
)
