class ProcessingError(RuntimeError):
    pass


class TemporaryProcessingError(ProcessingError):
    pass


class PermanentProcessingError(ProcessingError):
    pass


class NotFoundError(LookupError):
    pass


class InvalidStateError(RuntimeError):
    pass
