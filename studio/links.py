"""Backward-compatible imports. Canonical URL policy lives in domain.links."""
from .domain.links import CHANNEL_SEGMENTS, HOSTS, VIDEO_RE, Link, parse_link

__all__ = ["CHANNEL_SEGMENTS", "HOSTS", "VIDEO_RE", "Link", "parse_link"]
