class AppError(Exception):
    """Base exception for application-layer errors."""


class ValidationError(AppError):
    """Raised when user input fails business validation."""


class NotFoundError(AppError):
    """Raised when requested entity is not found."""
