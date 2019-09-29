"""
Module to manage dynamodb queries
"""
import logging
import boto3
import dateutil.parser

logger = logging.getLogger(__name__)

class DynamoDBException(Exception):
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, **kwargs)

class InconsistencyException(DynamoDBException):
    def __init__(self, *args, **kwargs):
        DynamoDBException.__init__(self, *args, **kwargs)

class IntegrityException(DynamoDBException):
    def __init__(self, *args, **kwargs):
        DynamoDBException.__init__(self, *args, **kwargs)

class DynamoHandler(object):
    DEFAULT_ITEM_LIMIT = 100

    """
    Object which all data classes will extend
    """
    def __init__(self):
        """
        Constructor
        """
        a = 1

    def _dh_prepare_field(self, field_name, field_value, parent_name=None):
        """
        Prepares a field to be saved to dynamodb
        """
        field_type = field_name.split("_")[0].lower()
        if field_type == "s":
            return {"S": field_value}
        elif field_type == "n":
            return {"N": str(field_value)}
        elif field_type == "dt":
            return {"S": field_value.isoformat()}
        elif field_type == "l":
            new_list = []
            if field_name.split("_")[1].lower() == "m":
                # for lists of maps we do something special
                for entry in field_value:
                    new_list.append(self._dh_prepare_field(
                        field_name=field_name[2:],
                        field_value=entry,
                        parent_name=field_name
                    ))
            else:
                # otherwise we don't
                for entry in field_value:
                    new_list.append(self._dh_prepare_field(
                        field_name=field_name[2:],
                        field_value=entry
                    ))
            return {"L": new_list}
        elif field_type == "m":
            # we need to get the reverse mapping for the map field names
            sub_name = field_name
            if parent_name:
                sub_name = parent_name
            field_mapping = {v:k for (k,v) in self._dh_sub_obj_mapping[sub_name].items()}
            new_map = {}
            for key in field_value:
                new_map.update({
                    field_mapping[key]: self._dh_prepare_field(
                        field_name=field_mapping[key],
                        field_value=field_value[key]
                    )
                })
            return {"M": new_map}
        else:
            # catch all if we don't know what to do
            return DynamoHandler._dh_wrap_field(field_value)

    def _dh_delete_item(self, env):
        """
        Deletes the item
        """
        ddb = boto3.client("dynamodb")
        logger.info("In delete method")
        # get keys for update
        keys = {k:DynamoHandler._dh_wrap_field(self.__dict__[self._dh_field_mapping[k]]) for k in self._dh_id_fields}
        params = {
            "TableName": "{t}_{e}".format(e=env, t=self._dh_table_name),
            "Key": keys
        }
        ddb.delete_item(**params)

    def _dh_create_item(self, env, check_uniqueness=False):
        """
        Creates the item in the database for the first time, fails if the key is duplicated
        """
        ddb = boto3.client("dynamodb")
        logger.info("In create method")
        # need to check we have the keys available
        mapped_fields = {self._dh_backward_field_mapping[k]:v for (k,v) in self.__dict__.items() if k in self._dh_backward_field_mapping.keys()}
        if not all(key in mapped_fields.keys() for key in self._dh_id_fields):
            raise DynamoDBException("Calls to _dh_create_item need all the key fields on the object including {f}".format(f=",".join(self._dh_id_fields)))
        # prep the fields for dynamo
        attributes = {}
        for key in mapped_fields:
            logger.info("Working on field {f}".format(f=key))
            if mapped_fields[key]:
                attributes.update({
                    key: self._dh_prepare_field(
                        field_name=key,
                        field_value=mapped_fields[key]
                    )
                })
        logger.info("Prepared object to be saved", extra={"item": attributes})
        params = {
            "TableName": "{t}_{e}".format(e=env, t=self._dh_table_name),
            "Item": attributes
        }
        if check_uniqueness:
            # we need to ensure a field is unique
            if check_uniqueness in self._dh_backward_field_mapping:
                logger.info("Checking for uniqueness of '{field}'".format(field=check_uniqueness))
                params.update({
                    "ConditionExpression": "attribute_not_exists({attr})".format(attr=self._dh_backward_field_mapping[check_uniqueness])
                })
                logger.info("Updated parameters are", extra={"params": params})
            else:
                raise DynamoDBException("Cannot check uniqueness on a field which does not exist")
        try:
            ddb.put_item(**params)
            logging.info("Item created")
        except ddb.exceptions.ConditionalCheckFailedException as err:
            logging.info("Uniqueness check failed, raising")
            raise IntegrityException("Uniqueness check failed")

    def _dh_save_changes(self, env):
        """
        Saves the in memory changes
        """
        logger.info("In save changes method")
        if len(self._dh_modified_fields) == 0:
            raise DynamoDBException("No modified fields")
        else:
            fields_added = {}
            fields_changed = {}
            fields_removed = {}
            for mod_field in self._dh_modified_fields:
                if self.__dict__[mod_field] == "" or self.__dict__[mod_field] == None:
                    fields_removed.update({self._dh_backward_field_mapping[mod_field]: ""})
                else:
                    fields_changed.update({self._dh_backward_field_mapping[mod_field]: self._dh_prepare_field(
                        field_name=self._dh_backward_field_mapping[mod_field],
                        field_value=self.__dict__[mod_field]
                    )})
            logger.info("Fields that will be changed are", extra={
                "added": fields_added,
                "updated": fields_changed,
                "removed": fields_removed
            })
            update_map = {}
            for f in fields_added:
                update_map.update({
                    f: {
                        "Value": fields_added[f],
                        "Action": "PUT"
                    }
                })
            for f in fields_changed:
                update_map.update({
                    f: {
                        "Value": fields_changed[f],
                        "Action": "PUT"
                    }
                })
            for f in fields_removed:
                update_map.update({
                    f: {
                        "Action": "DELETE"
                    }
                })
            # get keys for update
            keys = {k:DynamoHandler._dh_wrap_field(self.__dict__[self._dh_field_mapping[k]]) for k in self._dh_id_fields}
            # perform update
            ddb = boto3.client("dynamodb")
            params = {
                "TableName": "{t}_{e}".format(e=env, t=self._dh_table_name),
                "Key": keys,
                "AttributeUpdates": update_map
            }
            ddb.update_item(**params)
            # reset updated fields
            logger.info("Changes saved, resetting changes list")
            logger.info(self)
            self._dh_modified_fields[:] = []

    def _dh_update_field(self, field_name, field_value, ignore_inconsistency=False):
        """
        Updates the in memory representation of a field and then 
        """
        if field_name not in self._dh_modified_fields:
            # we are good
            self.__dict__.update({
                field_name: field_value
            })
            self._dh_modified_fields.append(field_name)
        else:
            # we are ignorning inconsistency, useful for modified dates
            if ignore_inconsistency:
                self.__dict__.update({
                    field_name: field_value
                })
            else:
                logger.info(self)
                raise InconsistencyException("{field} is already modified and not yet saved".format(field=field_name))

    @classmethod
    def _dh_flatten_field(cls, item_name, item_value):
        """
        Flattens a single field
        """
        logger.debug("Flattening field", extra={"item_name": item_name, "item_value": item_value})
        # check if field is an ID field
        if item_name in cls._dh_id_fields:
            if "N" in item_value:
                number = int(item_value["N"])
                return {cls._dh_field_mapping[item_name]: number}
            if "S" in item_value:
                return {cls._dh_field_mapping[item_name]: item_value["S"]}
        # get first part of item name (before the _)
        item_type = item_name.split("_")[0]
        if item_type.lower() == "l":
            # item is a list
            return {cls._dh_field_mapping[item_name]: cls._dh_flatten_single_item(
                item_type=item_type.lower(),
                item_value=item_value,
                item_name=item_name
            )}
        elif item_type.lower() == "m":
            # item is a map
            return {cls._dh_field_mapping[item_name]: cls._dh_flatten_single_item(
                item_type=item_type.lower(),
                item_value=item_value,
                item_name=item_name
            )}
        else:
            # item is a not a list or map
            return {cls._dh_field_mapping[item_name]: cls._dh_flatten_single_item(
                item_type=item_type.lower(),
                item_value=item_value,
                item_name=item_name
            )}
    
    @classmethod
    def _dh_flatten_single_item(cls, item_type, item_value, item_name, parent_name = None):
        if item_type == "n":
            number = item_value["N"]
            try:
                number = int(number)
            except ValueError:
                try:
                    number = float(number)
                except ValueError:
                    raise DynamoDBException("Error converting number to int or float, check this value '{v}' for field '{f}'".format(v=number, f=item_name))
            return number
        elif item_type == "s":
            string = item_value["S"]
            return string
        elif item_type == "dt":
            string = item_value["S"]
            date = dateutil.parser.parse(string)
            return date
        elif item_type == "l":
            # need to know what the subtype of the item is
            item_sub_type = item_name.split("_")[1].lower()
            new_items = [cls._dh_flatten_single_item(
                item_type=item_sub_type,
                item_value=i,
                item_name=item_name
            ) for i in item_value["L"]]
            return new_items
        elif item_type == "m":
            # for each key we need to flatten
            new_item = {}
            for key in item_value["M"]:
                item_sub_type = key.split("_")[0].lower()
                new_item.update({
                    cls._dh_sub_obj_mapping[item_name][key]: cls._dh_flatten_single_item(
                        item_type=item_sub_type,
                        item_value=item_value["M"][key],
                        item_name=key
                    )
                })
            return new_item
        else:
            raise DynamoDBException("Unsupported field type '{t}'".format(t=item_type))

    @classmethod
    def _dh_flatten_item(cls, item):
        """
        Flattens a single item
        """
        logger.debug("Flattening this item", extra={"item": item})
        new_item = {}
        for key in item:
            if not key == "_meta":
                new_item.update(cls._dh_flatten_field(key, item[key]))
        return new_item

    @classmethod
    def _dh_flatten_items(cls, items):
        """
        Flattens all the items returned from Dynamo
        """
        new_items = []
        for i in range(0, len(items)):
            new_items.append(cls._dh_flatten_item(items[i]))
        return new_items

    @classmethod
    def _dh_get_and_filter_with_index(cls, env, index=None, consistent=False, custom_key_filter=None, custom_filter_args=None, **kwargs):
        """
        Gets a list of items using the index and index keys, optionally filtering on the other values provided in kwargs

        env = environment to query
        consistent = do a consistent read (does not work for global secondary index)
        custom_key_filter = allows a special key filter to be added
        custom_filter_args = dict of values for custom key filter
        **kwargs = the values to filter on
        """
        ddb = boto3.client("dynamodb")
        # check that we have the fields we need
        mapped_fields = {cls._dh_backward_field_mapping[k]:v for (k,v) in kwargs.items()}
        if index and not all(key in mapped_fields.keys() for key in cls._dh_indexes[index]):
            raise DynamoDBException("Index '{idx}' needs the following fields '{fields}'".format(idx=index, fields=",".join(cls._dh_indexes[index])))
        # if we are not using the index we need at least the partition key specified, this is the first entry in _dh_id_fields
        if not index and not cls._dh_id_fields[0] in mapped_fields.keys():
            raise DynamoDBException("Calls to_dh_get_and_filter_with_index without using an index needs at least the partition key '{key}' specified".format(key=cls._dh_id_fields[0])) 
        # create key expression
        expression_bits = []
        if index:
            for key in cls._dh_indexes[index]:
                expression_bits.append("{key} = :{val}".format(key=key, val=cls._dh_field_mapping[key]))
        if not index:
            for key in [key for key in cls._dh_id_fields if key in mapped_fields.keys()]:
                expression_bits.append("{key} = :{val}".format(key=key, val=cls._dh_field_mapping[key]))
        if custom_key_filter:
            expression_bits.append(custom_key_filter)
        key_expression = " AND ".join(expression_bits)
        logger.info("Key expression: {expr}".format(expr=key_expression))
        # create filter expression, if we have anything in kwargs which is not a key
        expression_bits = []
        if index:
            for key in [key for key in mapped_fields.keys() if key not in cls._dh_indexes[index]]:
                expression_bits.append("{key} = :{val}".format(key=key, val=cls._dh_field_mapping[key]))
        if not index:
            for key in [key for key in mapped_fields.keys() if key not in cls._dh_id_fields]:
                expression_bits.append("{key} = :{val}".format(key=key, val=cls._dh_field_mapping[key]))
        filter_expression = " AND ".join(expression_bits)
        if filter_expression:
            logger.info("Filter expression: {expr}".format(expr=filter_expression))
        # create attribute expression dict
        attributes = {":{key}".format(key=k):cls._dh_wrap_field(v) for (k,v) in kwargs.items()}
        if custom_filter_args:
            attributes.update(custom_filter_args)
        logger.info("Expression attribute list", extra={"attributes": attributes})
        # create parameters for query
        params = {
            "TableName": "{t}_{e}".format(e=env, t=cls._dh_table_name),
            "Select": "ALL_ATTRIBUTES",
            "KeyConditionExpression": key_expression,
            "ExpressionAttributeValues": attributes,
            "Limit": cls.DEFAULT_ITEM_LIMIT
        }
        if consistent:
            params.update({
                "ConsistentRead": True
            })
        if index:
            params.update({
                "IndexName": "{i}".format(i=index),
                "Select": "ALL_PROJECTED_ATTRIBUTES",
            })
        if filter_expression:
            params.update({
                "FilterExpression": filter_expression
            })
        # run query
        keep_scanning = True
        logger.info("Starting query...")
        items = []
        while keep_scanning:
            response = ddb.query(**params)
            items = items + response["Items"]
            if "LastEvaluatedKey" in response:
                # there is still more to go
                params.update({
                    "ExclusiveStartKey": response["LastEvaluatedKey"]
                })
            else:
                # we are done
                keep_scanning = False
        logger.info("Finished query, got {n} items".format(n=len(items)))
        logger.debug("Items are", extra={"items": items})
        # flatten items
        items = cls._dh_flatten_items(items)
        logger.debug("Flattened items are", extra={"items": items})
        return items
        

    @classmethod
    def _dh_get_items(cls, env, consistent=False, **kwargs):
        """
        Gets a list of items filtering using attributes in kwargs if provided

        This is an expensive method to use if you don't want to scan all the items and it should be avoided.

        Rather use _dh_get_and_filter_with_index or _dh_get_and_filter
        """
        ddb = boto3.client("dynamodb")
        params = {
            "TableName": "{t}_{e}".format(e=env, t=cls._dh_table_name),
            "Limit": cls.DEFAULT_ITEM_LIMIT
        }
        if consistent:
            params.update({
                "ConsistentRead": True
            })
        if len(kwargs) == 0:
            # get all the items
            # no further parameters to add here
            logger.info("Request for all items in table")
        else:
            # need to filter the items
            logger.info("Request to filter on...")
            # need to add filters here
            for field in kwargs:
                pass
        # now run scan
        keep_scanning = True
        logger.info("Starting scan...")
        items = []
        while keep_scanning:
            response = ddb.scan(**params)
            items = items + response["Items"]
            if "LastEvaluatedKey" in response:
                params.update({
                    "ExclusiveStartKey": response["LastEvaluatedKey"]
                })
            else:
                keep_scanning = False
        logger.info("Finished scan, got {n} items".format(n=len(items)))
        logger.debug("Items are", extra={"items": items})
        # flatten items
        items = cls._dh_flatten_items(items)
        logger.debug("Flattened items are", extra={"items": items})
        return items

    @classmethod
    def _dh_wrap_field(cls, field):
        """
        Wraps a field value for DynamoDB
        """
        if isinstance(field, str):
            return {"S": field}
        else:
            return {"N": str(field)}

    @classmethod
    def _dh_get_item(cls, env, consistent=False, **kwargs):
        """
        Method to get a single item, this only works where the ID fields is specified in kwargs
        """
        ddb = boto3.client("dynamodb")
        mapped_fields = {cls._dh_backward_field_mapping[k]:v for (k,v) in kwargs.items()}
        logger.info("Input fields have been mapped", extra={"original": kwargs, "mapped_fields": mapped_fields})
        if not all(key in mapped_fields.keys() for key in cls._dh_id_fields):
            raise DynamoDBException("Calls to _dh_get_item need all the key fields including {f}".format(f=",".join(cls._dh_id_fields)))
        # if we get past this we have the id fields
        keys_for_dynamo = {k: cls._dh_wrap_field(v) for (k,v) in mapped_fields.items() if k in cls._dh_id_fields}
        logger.info("Keys for query are", extra={"keys": keys_for_dynamo})
        params = {
            "TableName": "{t}_{e}".format(e=env, t=cls._dh_table_name),
            "Key": keys_for_dynamo
        }
        if consistent:
            params.update({
                "ConsistentRead": True
            })
        logger.info("Getting item with parameters", extra={"params": params})
        response = ddb.get_item(**params)
        if "Item" in response:
            # we got an item back from dynamo
            item = cls._dh_flatten_item(response["Item"])
            logger.info("Got an item, fields have been mapped", extra={"item": item})
            # now we need to check if the rest of the attributes match
            if kwargs.viewitems() <= item.viewitems():
                return item
            else:
                return False
        else:
            # we did not get an item
            logger.info("No item found")
            # return false so the caller can handle this.
            return False
    
    @classmethod
    def _dh_get_next_counter(cls, env):
        """
        Gets the next counter value for this table
        """
        ddb = boto3.client("dynamodb")
        params = {
            "TableName": "{e}_RycCounters".format(e=env),
            "Key": {
                "Counter_id": {"S": cls._dh_table_name}
            },
            "UpdateExpression": "set CounterVal = CounterVal + :val",
            "ExpressionAttributeValues": {
                ":val": {"N": "1"}
            },
            "ReturnValues": "UPDATED_NEW"
        }
        resp = ddb.update_item(**params)
        logger.info("Got counter increment response", extra={"response": resp})
        return int(resp["Attributes"]["CounterVal"]["N"])
    
    @staticmethod
    def _dh_increment_any_counter(env, counter):
        """
        Static method used to increment any counter
        """
        ddb = boto3.client("dynamodb")
        params = {
            "TableName": "{e}_RycCounters".format(e=env),
            "Key": {
                "Counter_id": {"S": counter}
            },
            "UpdateExpression": "set CounterVal = CounterVal + :val",
            "ExpressionAttributeValues": {
                ":val": {"N": "1"}
            },
            "ReturnValues": "UPDATED_NEW"
        }
        resp = ddb.update_item(**params)
        logger.info("Got counter increment response for custom counter '{name}'".format(name=counter), extra={"response": resp})
        return int(resp["Attributes"]["CounterVal"]["N"])