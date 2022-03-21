class MinerException(Exception):
    """
    Base exception class for this application.
    """
    def __init__(self, *args: object):
        if args:
            super().__init__(*args)
        else:
            super().__init__("Unknown miner error")


class ExitRequest(MinerException):
    """
    Raised when the application is requested to exit from outside of the main loop.

    Intended for internal use only.
    """
    def __init__(self, *args: object):
        if args:
            super().__init__(*args)
        else:
            super().__init__("Unknown error during request")


class RequestException(MinerException):
    """
    Raised for cases where a web request doesn't return what we wanted it to.
    """
    def __init__(self, *args: object):
        if args:
            super().__init__(*args)
        else:
            super().__init__("Unknown error during request")


class LoginException(RequestException):
    """
    Raised when an exception occurs during login phase.
    """
    def __init__(self, *args: object):
        if args:
            super().__init__(*args)
        else:
            super().__init__("Unknown error during login")


class CaptchaRequired(LoginException):
    """
    The most dreaded thing about automated scripts.
    """
    def __init__(self):
        super().__init__("Captcha is required")
