
import base64
import json
import urllib
import urllib2

class MyAuth(urllib2.BaseHandler):
    def __init__(self,u,p):
        self.enc = "%s:%s" % (u,p)

    def default_open(self,r):
        r.add_header( "Authorization" , "Basic %s" % ( base64.b64encode(self.enc).strip() ) )

class JiraRest:

    def __init__(self,username,passwd,version="latest",host="https://jira.mongodb.org"):
        self.username = username
        self.passwd = passwd

        self.version = version
        self.host = host

        self.opener = urllib2.build_opener( MyAuth( self.username , self.passwd ) )

    def fetch(self,suffix,**params):
        url = "%s/rest/api/%s/%s" % ( self.host , self.version , suffix )

        if params:
            url = "%s?%s" % ( url , urllib.urlencode( params ) )

        data = self.opener.open( url )
        data = data.read()
        result = json.loads( data )

        return result

    def issue(self,key):
        return self.fetch( "issue/" + key )
