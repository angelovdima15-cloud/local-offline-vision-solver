import httpx


class APIClient:
    def __init__(self,base,secret):
        self.base,self.secret=base,secret

    def request(self,method,path,**kwargs):
        with httpx.Client(base_url=self.base,headers={'Authorization':'Bearer '+self.secret},
                          timeout=300,trust_env=False) as client:
            response=client.request(method,path,**kwargs)
            response.raise_for_status()
            return response

    def get(self,path):
        return self.request('GET',path).json()

    def post(self,path,value=None):
        return self.request('POST',path,json=value or {}).json()
