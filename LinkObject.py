from datetime import datetime, timedelta

from DynamoHandler import DynamoHandler, DynamoDBException

class LinkNotFoundException(DynamoDBException):
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, **kwargs)

class MultipleRecordsFoundException(Exception):
    """Error thrown when multiple records are found and only one is expected"""
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, **kwargs)

class Link(DynamoHandler):
    _dh_field_mapping = {
        "User_id": "id",
        "Link_id": "linkid",
        "s_Url": "url",
        "dt_CreationDate": "creation_date",
        "dt_ModifiedDate": "modified_date"
    }
    _dh_backward_field_mapping = {v:k for (k,v) in _dh_field_mapping.items()}

    _dh_sub_obj_mapping = {}

    _dh_id_fields = [
        "User_id",
        "Link_id"
    ]

    _dh_table_name = "UrlShortenerLinks"

    _dh_indexes = {
        "UrlLinkIdIndex": [
            "Link_id"
        ]
    }

    def __init__(self, **kwargs):
        self.__dict__ = kwargs
        self._dh_modified_fields = []
        super(Link, self).__init__()
    
    def __getitem__(self, key):
        return self.__dict__[key]
    
    def update_record(self, env, **kwargs):
        """
        Instance method to update a link record in the database
        """
        for field in kwargs:
            self._dh_update_field(
                field_name=field,
                field_value=kwargs[field]
            )
        self._dh_save_changes(env=env)
    
    def delete_record(self, env):
        """
        Instance method to delete a link record
        """
        self._dh_delete_item(env=env)

    @staticmethod
    def create_link(env, userid, linkid, url):
        """Static method to create a new a Link"""
        params = {
            "id": userid,
            "linkid": linkid,
            "url": url,
            "creation_date": datetime.utcnow(),
            "modified_date": datetime.utcnow()
        }
        link = Link(**params)
        link._dh_create_item(env=env)
        new_link = Link.get_link_by_id(
            env=env,
            linkid=linkid
        )
        return new_link
    
    @staticmethod
    def get_link_by_id(env, linkid, **kwargs):
        """
        Static method which gets a single link by its ID
        """
        links = Link._dh_get_and_filter_with_index(
            env=env,
            index="UrlLinkIdIndex",
            linkid="{id}".format(id=linkid),
            **kwargs
        )
        if len(links) == 0:
            raise LinkNotFoundException("No Link found which matches query parameters.")
        elif len(links) == 1:
            return_link = Link(**links[0])
            return return_link
        else:
            raise MultipleRecordsFoundException("Found multiple PDFs for the query parameters.")
    
    @staticmethod
    def get_links_for_user(env, userid):
        """
        Static method which gets a list of links for a single user
        """
        links = Link._dh_get_and_filter_with_index(
            env=env,
            index=None,
            consistent=False,
            custom_key_filter=None,
            custom_filter_args=None,
            id=userid
        )
        resp = []
        for link in links:
            resp = resp + [Link(**link)]
        return resp