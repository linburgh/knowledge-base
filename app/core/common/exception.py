class BusiException(Exception):
    def __init__(self, message: str, status_code: int = 400, payload: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict:
        result = dict(self.payload or ())
        result["message"] = self.message
        return result
