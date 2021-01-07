from collections import namedtuple

__all__ = ["_HTTP_REQUEST", "_get_headers", "_KNOWN_METHODS", "_HTTP_PLACEHOLDER", "AttrDict"]

_HTTP_PLACEHOLDER = {"method":"","headers":None,"path":"", "query":None, "uri": "", "protocol": None, "scheme": None, "ip": ""}

_HTTP_REQUEST = namedtuple("HttpRequest", ["header", "body"])

_KNOWN_METHODS = ["GET","POST","PUT","OPTIONS","CONNECT","HEAD","PATCH","DELETE","PROPFIND","PROPPATCH"]

def _get_headers():
    return [("Server","ashttp")]

class AttrDict():
    def __init__(self, dict_):
        if not hasattr(dict_, "get"):
            raise TypeError(f"{type(dict_)} type must have a get function")

        if not hasattr(dict_, "keys"):
            raise TypeError(f"{type(dict_)} type must have a keys function")

        if not hasattr(dict_, "values"):
            raise TypeError(f"{type(dict_)} type must have a values function")

        if not hasattr(dict_, "__getitem__"):
            raise Exception(dict_[0])

        '''
        nd = dict_.copy()
        nd.clear()

        for k in dict_:
            d = k.replace("-","_")
            nd[d] = dict_[k]
        '''

        self._dict = dict_

    def __getattr__(self,key):
        if not key.replace("_","-") in self._dict:
            return self._dict.get(key)
        return self._dict.get(key.replace("_","-"))

    def __getitem__(self,key):
        return self._dict[key]

    def __iter__(self):
        return self._dict.__iter__()

    def __str__(self):
        return str(self._dict)

    def __repr__(self):
        return self._dict.__repr__()