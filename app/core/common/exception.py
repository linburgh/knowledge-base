
class BusiException(Exception):
    def __init__(self, message,status_code=400, payload=None):
        super(BusiException, self).__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload
        
    def __str__(self):

        return self.message

    def to_dict(self):
        rv = dict(self.payload or ())
        rv['message'] = self.message

        return rv
