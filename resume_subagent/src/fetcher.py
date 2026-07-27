"""
In-Memory Streaming Fetcher.

Fetches resume files over HTTP as raw binary streams directly into
Python's io.BytesIO buffer — zero bytes written to disk.
Respects hard caps on stream size to prevent memory spikes.
"""

from __future__ import annotations

import io
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class InMemoryStreamFetcher:
    """Fetches a file via HTTP GET and returns it as an in-memory BytesIO stream.

    Features:
        - Zero-disk I/O: loads directly into RAM via response.content.
        - Content-Length inspection: aborts early if the file exceeds max_stream_size_mb.
        - Timeout-controlled requests to avoid hanging.
    """

    def __init__(
        self,
        max_stream_size_mb: int = 10,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self.max_stream_bytes = max_stream_size_mb * 1024 * 1024
        self.request_timeout_seconds = request_timeout_seconds

    async def fetch(self, url: str) -> Optional[io.BytesIO]:
        """Fetch a file from *url* into a BytesIO buffer.

        Returns:
            A BytesIO buffer containing the raw file bytes, or None if the
            fetch fails or the file exceeds the size cap.
        """
        logger.info("Fetching stream from URL: %s (max %d MB)", url, self.max_stream_bytes // (1024 * 1024))

        try:
            async with httpx.AsyncClient(timeout=self.request_timeout_seconds) as client:
                # Stream the response to inspect Content-Length before full download
                async with client.stream("GET", url) as response:
                    response.raise_for_status()

                    # Check Content-Length header for early rejection
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        file_size = int(content_length)
                        if file_size > self.max_stream_bytes:
                            logger.warning(
                                "File too large: %d bytes (cap: %d bytes). Skipping.",
                                file_size,
                                self.max_stream_bytes,
                            )
                            return None

                    # Read the full response into memory
                    raw_bytes = await response.aread()

                    if len(raw_bytes) > self.max_stream_bytes:
                        logger.warning(
                            "Downloaded %d bytes exceeds cap of %d bytes. Skipping.",
                            len(raw_bytes),
                            self.max_stream_bytes,
                        )
                        return None

                    buffer = io.BytesIO(raw_bytes)
                    logger.info(
                        "Successfully fetched %d bytes into memory.", len(raw_bytes)
                    )
                    return buffer

        except httpx.HTTPStatusError as e:
            logger.error("HTTP error fetching %s: %s", url, e)
        except httpx.RequestError as e:
            logger.error("Request error fetching %s: %s", url, e)
        except Exception as e:
            logger.exception("Unexpected error fetching %s: %s", url, e)

        return None

