"""User-facing ingestion and recovery failures."""

from renpy_story_mapper.errors import StoryMapperError


class IngestionError(StoryMapperError):
    pass


class AmbiguousSourceError(IngestionError):
    pass


class UnsupportedCompiledSourceError(IngestionError):
    pass


class RecoveryError(IngestionError):
    pass


class RecoveryTimeoutError(RecoveryError):
    pass


class RecoveryLimitError(RecoveryError):
    pass


class UnsafeExportError(IngestionError):
    pass
