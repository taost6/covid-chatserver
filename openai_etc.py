from os import environ
import re

def openai_get_apikey(storage):
    apikey = None
    if storage is None:
        apikey = environ.get("OPENAI_APIKEY")
    r = re.match(r"env:([\w\d]+)", storage)
    if r:
        apikey = environ.get(r.group(1))
    else:
        apikey = open(storage).read().strip()
    if apikey is None:
        raise ValueError(f"APIKEY is not defined.")
    return apikey

