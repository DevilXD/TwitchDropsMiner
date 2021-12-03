class MinerException(Exception):
    def __init__(self, *args: object):
        if args:
            super().__init__(*args)
        else:
            super().__init__("Unknown miner error")


class RequestException(MinerException):
    def __init__(self, *args: object):
        if args:
            super().__init__(*args)
        else:
            super().__init__("Unknown error during request")


class LoginException(RequestException):
    def __init__(self, *args: object):
        if args:
            super().__init__(*args)
        else:
            super().__init__("Unknown error during login")


class CaptchaRequired(LoginException):
    def __init__(self):
        super().__init__("Captcha is required")


class IncorrectCredentials(LoginException):
    def __init__(self):
        super().__init__("Incorrect username or password")
