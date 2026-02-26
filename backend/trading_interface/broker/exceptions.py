class BrokerException(Exception):
    """Base exception for all trading interface errors."""
    pass

class RateLimitError(BrokerException):
    """Trigger exponential backoff due to 429."""
    pass

class NetworkError(BrokerException):
    """Retryable network failures (HTTP 500, timeouts)."""
    pass

class InsufficientFundsError(BrokerException):
    """Non-Retryable HTTP 403 or logic failure."""
    pass

class InvalidTickerError(BrokerException):
    """Non-Retryable asset resolution failure."""
    pass

class MarketClosedError(BrokerException):
    """Attempted execution outside hours without explicit extended configuration."""
    pass

class UnauthorizedError(BrokerException):
    """Invalid API Keys / Security Rotation Failures."""
    pass
