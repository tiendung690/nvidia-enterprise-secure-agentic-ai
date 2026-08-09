from nvidia_agentic_rag.nvidia.errors import classify_provider_error


def test_resource_exhausted_is_transient() -> None:
    info = classify_provider_error(
        RuntimeError("ResourceExhausted: Worker local total request limit reached (33/32)")
    )
    assert info.transient is True
    assert info.retry_after_seconds == 20


def test_validation_error_is_not_capacity_error() -> None:
    info = classify_provider_error(ValueError("invalid tool arguments"))
    assert info.transient is False


def test_timeout_is_transient_with_specific_code() -> None:
    info = classify_provider_error(RuntimeError("ReadTimeout: request timed out"))
    assert info.transient
    assert info.error_code == "NVIDIA_PROVIDER_TIMEOUT"


def test_gateway_error_is_transient() -> None:
    info = classify_provider_error(RuntimeError("502 bad gateway"))
    assert info.transient
    assert info.error_code == "NVIDIA_GATEWAY_UNAVAILABLE"


class _Response:
    def __init__(self, status_code: int, retry_after: str | None = None) -> None:
        self.status_code = status_code
        self.headers = {} if retry_after is None else {"Retry-After": retry_after}


class _HTTPError(RuntimeError):
    def __init__(self, status_code: int, retry_after: str | None = None) -> None:
        super().__init__(f"http {status_code}")
        self.response = _Response(status_code, retry_after)


def test_structured_429_respects_retry_after() -> None:
    info = classify_provider_error(_HTTPError(429, "7"))
    assert info.transient is True
    assert info.error_code == "NVIDIA_CAPACITY_EXHAUSTED"
    assert info.retry_after_seconds == 7
    assert info.status_code == 429


def test_structured_401_is_permanent_request_rejection() -> None:
    info = classify_provider_error(_HTTPError(401))
    assert info.transient is False
    assert info.error_code == "NVIDIA_PROVIDER_REQUEST_REJECTED"
    assert info.status_code == 401
