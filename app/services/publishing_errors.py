class PublishingError(RuntimeError):
    code = "PROVIDER_ERROR"
    retryable = False
    user_message = "Площадка отклонила публикацию."

    def __init__(
        self,
        message: str = "",
        *,
        provider_code: str | None = None,
        provider_metadata: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message or self.user_message)
        self.provider_code = provider_code
        self.provider_metadata = provider_metadata or {}


class AuthenticationError(PublishingError):
    code = "AUTH_REQUIRED"
    user_message = "Требуется повторное подключение аккаунта."


class PublisherPermissionError(PublishingError):
    code = "PERMISSION_DENIED"
    user_message = "У аккаунта недостаточно прав для публикации."


class RateLimitError(PublishingError):
    code = "RATE_LIMIT"
    retryable = True
    user_message = "Площадка временно ограничила частоту запросов."


class InvalidMediaError(PublishingError):
    code = "INVALID_MEDIA"
    user_message = "Медиафайл не соответствует требованиям площадки."


class InvalidMetadataError(PublishingError):
    code = "INVALID_METADATA"
    user_message = "Текст или настройки публикации не прошли проверку."


class PolicyRejectedError(PublishingError):
    code = "POLICY_REJECTED"
    user_message = "Публикация отклонена правилами площадки."


class ProviderTemporaryError(PublishingError):
    code = "PROVIDER_TEMPORARY"
    retryable = True
    user_message = "Площадка временно недоступна. Повторим автоматически."


class ProviderPermanentError(PublishingError):
    code = "PROVIDER_PERMANENT"
    user_message = "Площадка окончательно отклонила запрос."


class ProcessingTimeoutError(PublishingError):
    code = "PROCESSING_TIMEOUT"
    retryable = True
    user_message = "Площадка слишком долго обрабатывает публикацию."


class UploadInterruptedError(ProviderTemporaryError):
    code = "UPLOAD_INTERRUPTED"
    user_message = "Загрузка прервалась и будет продолжена с сохранённой позиции."
