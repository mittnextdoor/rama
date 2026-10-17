"""Domain errors the API turns into HTTP answers. A record another firm owns is NotFound, never Forbidden, so its
existence isn't revealed.

An error can name the form field it's about (field=...), so the screen shows it beside that field, and the API always
answers with a JSON body {"error", "field"?, "request_id"} (product/api.py): a screen never has to show an empty error."""


class ProductError(Exception):
    status = 400

    def __init__(self, message="", field=None):
        super().__init__(message)
        self.field = field


class NotFound(ProductError):
    status = 404


class Forbidden(ProductError):
    status = 403


class Conflict(ProductError):
    """The request is valid but the state doesn't allow it: a locked period, a stale approval, missing authorization."""
    status = 409


class Invalid(ProductError):
    status = 422
