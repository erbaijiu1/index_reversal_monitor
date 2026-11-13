import json
import urllib.request

class _Response:
    def raise_for_status(self):
        return None

def post(url, json=None, timeout=10):
    request = urllib.request.Request(url, data=__import__("json").dumps(json or {}).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(request, timeout=timeout).read()
    return _Response()
