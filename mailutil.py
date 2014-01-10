
import imaplib
import keyring
import getpass
import re
import rfc822
import datetime
import time
import bson
import pprint

class imapclient:
    def __init__(self,host,user,secure=True,pwd=None,cache=False):
        self.host = host
        self.user = user
        self.pwd = pwd

        if self.pwd is None:
            try:
                pwd = keyring.get_password( host , user )
                print( pwd )
            except Exception,e:
                print( e )

        if pwd is None:
            pwd = getpass.getpass()
            try:
                keyring.set_password( host , user , pwd )
            except:
                print( "can't save password" )

        if secure:
            self.mailbox = imaplib.IMAP4_SSL( host , 993 )
        else:
            self.mailbox = imaplib.IMAP4( host )

        self.mailbox.login( user , pwd )
        self.select( "INBOX" )

        self.cache = None
        if cache:
            import pymongo
            self.cache = pymongo.Connection().mail_cache.raw

    def _parse(self,res):
        if res[0] != "OK":
            raise Exception( "error: %s" % str(res[0]) )
        return res[1]

    def get_folders(self):
        raw = self._parse( self.mailbox.list() )
        clean = []

        p = re.compile( "\((.*?)\)\s+\"(.*?)\"\s+\"(.*?)\"")
        for x in raw:

            m = p.match( x ).groups();
            if m[1] != "/":
                raise Exception( "ahhh %s" % x )

            if m[0].find( "Noselect" ) < 0:
                clean.append( m[2] )

        return clean

    def select(self,name,readonly=True):
        self.mailbox.select( name , readonly=readonly )
        self.folder = name

    def list(self):
        res = self.mailbox.uid( "search" , "ALL" )
        return res[1][0].split()

    def _parse_headered( self , txt ):
        headers = {}

        prev = ""
        while True:
            line,end,txt = txt.partition( "\n" )
            line = line.replace( "\r" , "" )
            if len(line) == 0:
                break

            if line[0].isspace():
                prev += "\n" + line
                continue

            if len(prev) > 0:
                self._add_header( headers , prev )
            prev = line

        self._add_header( headers , prev )

        for x in headers:
            if len(headers[x]) == 1:
                headers[x] = headers[x][0]

        return ( headers , txt )


    def _add_header( self , headers , line ):
        line = line.rstrip()
        if len(line) == 0:
            return

        name,temp,value = line.partition( ":" )

        name = name.lower()
        value = value.strip()

        value = self._cleanSingleHeader( name , value )

        if name in headers:
            headers[name].append( value )
        else:
            headers[name] = [ value ]


    def _convert_raw( self, txt ):
        try:
            headers , body = self._parse_headered( txt )
            return { "headers" : headers , "body" : body }
        except:
            print( "couldn't parse" )
            print( txt )
            raise

    def _cleanID(self,foo):
        foo = foo.lower();
        foo = foo.strip();

        if foo.count( "<" ) != 1 or foo.count( ">") != 1:
            if foo.count( " " ):
                raise Exception( "bad id [%s]" , foo )
            return foo

        foo = foo.partition( "<" )[2]
        foo = foo.partition( ">" )[0]

        return foo

    def _cleanSingleHeader(self,name,value):
        if name == "message-id":
            return self._cleanID( value )

        if name == "to":
            return [ z.strip() for z in value.split( "," ) ]

        if name == "references":
            return [ self._cleanID( x ) for x in re.split( "\s+" , value.lower() ) ]

        if name == "in-reply-to":
            try :
                return self._cleanID( value )
            except:
                print( "bad id [%s]" % value )
                return value

        if name == "date":
            t = rfc822.parsedate( value )
            return datetime.datetime.fromtimestamp( time.mktime( t ) )

        return value


    def get_cache(self):
        return self.cache
    def get_id(self,uid):
        return self.host + "-" + self.user + "-" + self.folder + "-" + str(uid)

    def fetch(self,uid,headerOnly=False):

        key = self.get_id(uid)

        data = None
        if self.cache:
            data = self.cache.find_one( { "_id" : key } )
            if data:
                if data["headerOnly"] == headerOnly:
                    return self._convert_raw( data["data"] )

        what = "(RFC822)"
        if headerOnly:
            what = "(RFC822.HEADER)"

        typ, data = self.mailbox.uid( "fetch" , uid, what)
        if typ != "OK":
            raise Exception( "failed loading uid: %s typ: %s" % ( str(uid) , str(typ) ) )

        if data is None:
            return None
        data = data[0]

        if data is None:
            return None
        data = data[1]

        converted = self._convert_raw( data )

        if self.cache:
            try:
                self.cache.save( { "_id" : key,
                                   "headerOnly" : headerOnly,
                                   "headers" : converted["headers"],
                                   "data" : bson.binary.Binary( data ) } )
            except Exception,e:
                print( "couldn't save message because of: %s" % e )

        return converted

    def play(self,uid):
        x = self.mailbox.uid( "fetch", uid, "(X-GM-LABELS X-GM-THRID X-GM-MSGID FLAGS RFC822.HEADER)" )
        pprint.pprint( x )


    def archive(self,uid):
        return self.mailbox.uid( "store" , uid , "+FLAGS" , "(\Deleted)" )

    def expunge(self):
        return self.mailbox.expunge()
