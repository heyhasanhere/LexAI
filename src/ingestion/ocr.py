# OCR is now handled by Marker (GPU-accelerated) via src.ingestion._marker.
# This module is kept as a shim so external scripts that import it don't break.

from src.ingestion._marker import convert_file  # noqa: F401
