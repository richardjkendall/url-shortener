from functools import wraps
from flask import request, make_response, jsonify, g
from LinkObject import LinkNotFoundException

class BadRequestException(Exception):
    """Class for BadRequestException"""
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, **kwargs)

class UnauthorisedException(Exception):
    """Class for UnauthorisedException"""
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, **kwargs)

def exception_to_json_response(exception, code):
    """
    Turns an exception into a JSON payload to respond to a service call
    """
    
    payload = {
        "error": type(exception).__name__,
        "message": str(exception),
        "code": code
    }
    resp = make_response(jsonify(payload), code)
    resp.headers["Content-type"] = "application/json"
    return resp

def generic_exception_json_response(code):
    """
    Turns an unhandled exception into a JSON payload to respond to a service call
    """
    
    payload = {
        "error": "TechnicalException",
        "message": "An unknown error occured",
        "code": code
    }
    resp = make_response(jsonify(payload), code)
    resp.headers["Content-type"] = "application/json"
    return resp

def error_handler(f):
    """
    Function to manage errors coming back to webservice calls
    """

    @wraps(f)
    def error_decorator(*args, **kwargs):
        """
        Function to manage errors coming back to webservice calls
        """
        
        try:
            return f(*args, **kwargs)
        except BadRequestException as err:
            return exception_to_json_response(err, 400)
        except UnauthorisedException as err:
            return exception_to_json_response(err, 403)
        except LinkNotFoundException as err:
            return exception_to_json_response(err, 404)
        #except Exception as err:
        #    return generic_exception_json_response(500)
    return error_decorator