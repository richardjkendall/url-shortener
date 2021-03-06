import logging
from flask_lambda import FlaskLambda
from flask import request, jsonify, make_response, g
from flask_cors import CORS
from error_handler import error_handler, BadRequestException, UnauthorisedException
from random_string_gen import get_rand_string
from LinkObject import Link
from datetime import datetime
import json
import os

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] (%(threadName)-10s) %(message)s')

lambda_handler = FlaskLambda(__name__)
CORS(lambda_handler)

def success_json_response(payload):
    """Turns payload into a JSON HTTP200 response"""
    response = make_response(jsonify(payload), 200)
    response.headers["Content-type"] = "application/json"
    return response

@lambda_handler.before_request
def get_user_details():
    #g.username = "rjk"
    try:
        g.username = request.aws_event["requestContext"]["authorizer"]["claims"]["cognito:username"]
    except KeyError as err:
        print("No username found")
        g.username = None
    g.env = request.aws_event["stageVariables"]["env"]
    print("Full request context {c}".format(c=json.dumps(request.aws_event)))

@lambda_handler.route('/', methods=['GET'])
def root():
    response = make_response(json.dumps("Hello from lambda"), 200)
    response.headers["Content-Type"] = "application/json"
    return response

@lambda_handler.route('/<link_id>', methods=['GET'])
@error_handler
def redirect(link_id):
    link = Link.get_link_by_id(
        env = os.environ.get('environment_name'),
        linkid = link_id
    )
    response = make_response("", 301)
    response.headers["Location"] = link.url
    return response

@lambda_handler.route('/', methods=['POST'])
@error_handler
def api():
    if "username" not in g:
        raise UnauthorisedException("Not allowed")
    if not request.json:
        raise BadRequestException("Request should be JSON") 
    if "action" not in request.json:
        raise BadRequestException("Expecting 'action' field, but not found")
    action = request.json["action"]
    if action not in ["list", "add", "update", "delete"]:
        raise BadRequestException("Action must be one of 'list', 'add', 'update', 'delete'")
    if action == "add":
        # add a URL to the table
        # check we have the mandatory fields
        if "url" not in request.json:
            raise BadRequestException("When action is 'add' the 'url' field must be present")
        link = Link.create_link(
            env = os.environ.get('environment_name'),
            userid = g.username,
            linkid = get_rand_string(4),
            url = request.json["url"]
        )
        return success_json_response(link.__dict__)
    if action == "list":
        # check if we have pagination instructions
        page = None
        page_size = 0
        if "page" in request.json:
            page = request.json["page"]
            if "page_size" not in request.json:
                raise BadRequestException("When 'page' is specified, 'page_size' should also specified")
            page_size = request.json["page_size"]
        # get list of links from DDB
        links = Link.get_links_for_user(
            env = os.environ.get('environment_name'),
            userid = g.username
        )
        links.sort(key=lambda x: x.creation_date, reverse=True)
        link_dicts = []
        for link in links:
            link_dicts = link_dicts + [link.__dict__]
        total_length = len(link_dicts)
        # we need to filter the list if we were asked to
        filtered = False
        if "filter" in request.json:
            if len(request.json["filter"]["url"]) > 0:
                link_dicts = [l for l in link_dicts if request.json["filter"]["url"] in l["url"]]
            if len(request.json["filter"]["linkid"]) > 0:
                link_dicts = [l for l in link_dicts if request.json["filter"]["linkid"] in l["linkid"]]
            total_length = len(link_dicts)
            filtered = True
        # if we are in pagination mode, need to get and return only the page wanted
        if page is not None:
            start_index = int(page) * int(page_size)
            if start_index > total_length:
                raise BadRequestException("No page with that page number exists")
            end_index = start_index + int(page_size)
            if end_index > total_length:
                end_index = total_length
            # now return slice of the array
            return success_json_response({
                "links": link_dicts[start_index:end_index],
                "total_number": total_length,
                "page": page,
                "filtered": filtered
            })
        else:
            return success_json_response({
                "links": link_dicts,
                "total_number": total_length,
                "filtered": filtered
            })
    if action == "update":
        # change existing URL, assuming the current user is the owner
        # check we have the mandatory fields
        if "url" not in request.json or "linkid" not in request.json:
            raise BadRequestException("When action is 'update' the 'url' and 'linkid' fields must be present")
        link = Link.get_link_by_id(
            env = os.environ.get('environment_name'),
            linkid = request.json["linkid"],
            id = g.username
        )
        link.update_record(
            env = os.environ.get('environment_name'),
            url = request.json["url"],
            modified_date = datetime.utcnow()
        )
        return success_json_response(link.__dict__)
    if action == "delete":
        # delete existing URL, assuming the current user is the owner
        if "linkid" not in request.json:
            raise BadRequestException("When action is 'delete' the 'linkid' field must be present")
        link = Link.get_link_by_id(
            env = os.environ.get('environment_name'),
            linkid = request.json["linkid"],
            id = g.username
        )
        link.delete_record(env = os.environ.get('environment_name'))
        return success_json_response({
            "status": "deleted"
        })

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
    if not os.environ.get('environment_name'):
        print("We need the ENV environment variable to be set, exiting")
        exit(1)
    lambda_handler.run(debug=True)