import re


SENSITIVE_VALUE = "[redacted]"

_PATTERNS = [
    re.compile(r"(?i)(access_token=)[^&\s'\"<>]+"),
    re.compile(r"(?i)(appsecret_proof=)[^&\s'\"<>]+"),
    re.compile(r"(?i)(client_secret=)[^&\s'\"<>]+"),
    re.compile(r"(?i)(app_secret=)[^&\s'\"<>]+"),
    re.compile(r"(?i)(\"(?:access_token|client_secret|app_secret)\"\s*:\s*\")[^\"]+(\")"),
    re.compile(r"(?i)('(?:access_token|client_secret|app_secret)'\s*:\s*')[^']+(')"),
    re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._-]+"),
]


def redact_sensitive(value: str | None) -> str | None:
    if not value:
        return value

    redacted = value
    for pattern in _PATTERNS:
        if pattern.groups == 2:
            redacted = pattern.sub(rf"\1{SENSITIVE_VALUE}\2", redacted)
        else:
            redacted = pattern.sub(rf"\1{SENSITIVE_VALUE}", redacted)
    return redacted
