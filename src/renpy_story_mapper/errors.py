"""Domain errors surfaced by the analyzer CLI."""


class StoryMapperError(Exception):
    """Base class for expected, user-facing analyzer failures."""


class ArchiveFormatError(StoryMapperError):
    """The archive is unsupported or violates safety constraints."""


class ScriptParseError(StoryMapperError):
    """A Ren'Py script cannot be parsed safely."""
