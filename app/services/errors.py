class ProcessingError(RuntimeError):
    pass


class TemporaryProcessingError(ProcessingError):
    pass


class PermanentProcessingError(ProcessingError):
    pass


class NotFoundError(LookupError):
    pass


class PermissionDenied(RuntimeError):
    pass


class InvalidStateError(RuntimeError):
    pass
