"""
models.py
---------
Data model for the LinkedIn URL Discovery Tool.

This tool collects profile URLs from LinkedIn search results only.
It does NOT scrape individual profiles.

All field values use "N/A" as the sentinel for missing data so that
downstream CSV writers always have a string to write.
"""

from dataclasses import dataclass, field as dataclass_field
from datetime import datetime


@dataclass
class DiscoveredProfile:
    """
    Represents a single LinkedIn profile URL discovered from a search result.

    Only fields that are directly visible on a search-result card are populated
    here.  The tool never opens the profile page to obtain additional data.

    Fields
    ------
    linkedin_url  : Canonical normalised LinkedIn profile URL (primary key).
    name          : Person's name as shown on the search card, or "N/A".
    headline      : Professional headline as shown on the search card, or "N/A".
    location      : Location as shown on the search card, or "N/A".
    search_query  : The search query that produced this result.
    scraped_at    : ISO-style timestamp of when the URL was collected.
    """

    linkedin_url: str = "N/A"
    name: str = "N/A"
    headline: str = "N/A"
    location: str = "N/A"
    search_query: str = "N/A"
    scraped_at: str = dataclass_field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        """Return all fields as a plain dictionary in CSV column order."""
        return {
            "linkedin_url": self.linkedin_url,
            "name": self.name,
            "headline": self.headline,
            "location": self.location,
            "search_query": self.search_query,
            "scraped_at": self.scraped_at,
        }

    @property
    def is_valid(self) -> bool:
        """True if the URL is a non-sentinel value."""
        return self.linkedin_url != "N/A"
