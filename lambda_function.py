from flask_lambda import FlaskLambda
from flask import request, make_response
import json
import os
import pprint

lambda_handler = FlaskLambda(__name__)

pp = pprint.PrettyPrinter(indent=4)

@lambda_handler.route('/', methods=['GET'])
def root():
    response = make_response(json.dumps("Hello from lambda"), 200)
    response.headers["Content-Type"] = "application/json"
    return response

# use state to manage keeping a record of the url being saved
@lambda_handler.route('/_triggerlogin', methods=["GET"])
def login():
    response = make_response("", 301)
    response.headers["Location"] = "https://{cog_domain}.auth.{region}.amazoncognito.com/login?response_type=token&client_id={client_id}&redirect_uri={redirect}&scope=openid+email".format(
        cog_domain = os.environ["cog_domain"],
        region = os.environ["region"],
        client_id = os.environ["cog_client_id"],
        redirect = request.args.get("redirect_uri")
    )
    return response

if __name__ == '__main__':
    lambda_handler.run(debug=True)