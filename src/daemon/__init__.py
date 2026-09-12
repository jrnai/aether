"""Daemon package for autonomous background jobs and scheduled briefings."""
from src.daemon.briefing import BriefingService

__all__ = ["BriefingService"]
