"""Content-Type detection for uploaded objects (issue #807).

Object stores such as Azure Blob Storage do not infer a type client-side, so an
upload without one is served as ``application/octet-stream``. Every put goes
through :func:`put_attributes` so all backends (S3, GCS, Azure) behave alike.
"""

from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath

DEFAULT_CONTENT_TYPE = "application/octet-stream"

# The stdlib table lacks, or disagrees on, these types that STAC clients rely on.
_OVERRIDES: dict[str, str] = {
    ".json": "application/json",
    ".geojson": "application/geo+json",
    ".parquet": "application/vnd.apache.parquet",
    ".tif": "image/tiff; application=geotiff",
    ".tiff": "image/tiff; application=geotiff",
    ".pmtiles": "application/vnd.pmtiles",
    ".md": "text/markdown",
    ".fgb": "application/octet-stream",
}


def guess_content_type(key: str) -> str:
    """Return the Content-Type for an object key, based on its extension."""
    suffix = PurePosixPath(key).suffix.lower()
    if suffix in _OVERRIDES:
        return _OVERRIDES[suffix]
    guessed, _ = mimetypes.guess_type(key)
    return guessed or DEFAULT_CONTENT_TYPE


def put_attributes(key: str) -> dict[str, str]:
    """Build the ``attributes`` argument for ``obs.put`` / ``obs.put_async``."""
    return {"Content-Type": guess_content_type(key)}
