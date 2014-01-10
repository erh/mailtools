
import datetime
import dateutil.parser
import getpass
import gmail
import keyring
import os
import pprint
import sys
import time

import myjira

imapHost = "imap.gmail.com"
imapUser = "eliot@10gen.com"

jiraHost = "jira.mongodb.org"
jiraUser = "eliot"

def getPassword( server , account ):
    pwd = keyring.get_password( server , account )
    if pwd and len(pwd) > 0 :
        return pwd

    try:
        import mypwd
        if server == jiraHost and "jira" in dir(mypwd):
            return mypwd.jira
        if "servers" in dir(mypwd):
            if server in mypwd.servers:
                s = mypwd.servers[server]
                if account in s:
                    return s[account]

    except:
        pass

    print( "enter password for %s@%s" % ( account, server ) )
    pwd = getpass.getpass()
    try:
        keyring.set_password( server , account , pwd )
    except Exception,e:
        print( "can't save password: %s" % str(e) )
    return pwd

j = myjira.JiraRest( jiraUser , getPassword( jiraHost , jiraUser ) )

hoursBack = 1

def search( query ):
    return j.fetch( "search", jql=query, fields="*all", expand="changelog", maxResults=1000 )

def getUpdated():
    return search( "project=SERVER AND updated >= -%sh" % hoursBack )

def happendInTimeWindow( dateString ):
    parsed = dateutil.parser.parse( dateString )
    now = datetime.datetime.utcnow()
    now = now.replace(tzinfo=parsed.tzinfo)
    diff = now-parsed
    return diff.total_seconds() < (hoursBack*3600)


# { "created" : [ ] , "resolved" : [ ] }
categories = {}

def addToCategory( cat, issue ):
    if cat not in categories:
        categories[cat] = []
    categories[cat].append( issue )

def removeIssuesForCategory( cat ):
    if cat not in categories:
        return []
    toreturn = categories[cat]
    del categories[cat]
    return toreturn

def findCategory( issue ):

    fields = issue["fields"]

    if happendInTimeWindow( fields["created"] ):
        return "created"

    if fields["watches"]["isWatching"]:
        return "watching"

    for change in issue["changelog"]["histories"]:
        if not happendInTimeWindow( change["created"] ):
            continue
        return "modified"

    for comment in fields["comment"]["comments"]:
        if happendInTimeWindow( comment["created"] ):
            return "commented"

    for comment in fields["comment"]["comments"]:
        if happendInTimeWindow( comment["updated"] ):
            return "comment edited"

    return "unknown"

def person( p ):
    if not p:
        return "NONE"

    if p["name"] == ["emailAddress"]:
        return p["name"]

    return p["name"] + "/" + p["emailAddress"]

def issueString( issue ):
    fields = issue["fields"]

    def prefix( howMany=1):
        return "   " * howMany

    def getPrettyString( howMany, theString ):
        big = ""
        lines = theString.split( "\n" )

        trimmed = False
        if len(lines) > 5:
            trimmed = True
            lines = lines[0:5]

        for x in lines:
            big = big + prefix(howMany) + x + "\n"

        if trimmed:
            big = big + prefix(howMany) + "****snipped****\n"

        return big


    s = issue["key"] + " " + fields["summary"] + "\n"
    s = s + prefix() + "https://jira.mongodb.org/browse/" + issue["key"] + "\n"

    def printField( name, stringer ):
        if name not in fields:
            return
        return "%s%s: %s\n" % ( prefix(), name, stringer( fields[name] ) )

    s = s + printField( "status", lambda x: x["name"] )
    s = s + printField( "reporter", person )
    s = s + printField( "assignee", person )
    s = s + printField( "fixVersions", lambda x: ",".join( map( lambda y: str(y["name"]), x ) ) )
    s = s + printField( "priority", lambda x: x["name"] )
    s = s + printField( "components", lambda x: ",".join( map( lambda y: str(y["name"]), x ) ) )

    firstChange = True
    for change in issue["changelog"]["histories"]:
        if not happendInTimeWindow( change["created"] ):
            continue

        if firstChange:
            s = s + prefix() + "changes\n"
            firstChange = False

        s = s + prefix(2) + person( change["author"] ) + "\n"

        for item in change["items"]:
            s = s + prefix(3) + item["field"] + "\n"
            if item["toString"]:
                s = s + getPrettyString( 4, item["toString"] )

    firstComments = True
    for comment in fields["comment"]["comments"]:
        created = comment["created"]
        updated = comment["updated"]
        if not happendInTimeWindow( updated ):
            continue

        if firstComments:
            s = s + prefix() + "comments:\n"
            firstComments = False

        s = s + prefix(2) + "by: " + person( comment["author"] ) + "\n"
        if created != updated:
            s = s + prefix(2) + "modified by: " + person( comment["updateAuthor"] ) + "\n"
        s = s + getPrettyString( 3, comment["body"] )

    return s

def issuesString( name, issues ):
    s = "**" + name.upper() + "**\n\n"
    for x in issues:
        s = s + issueString(x) + "\n"
    return s + "\n"


def getText():
    updated = getUpdated()
    allIssues = updated["issues"]

    if len(allIssues) == 0:
        return ""

    for issue in allIssues:
        addToCategory( findCategory( issue ), issue )

    fullString = ""
    fullString = fullString + issuesString( "created", removeIssuesForCategory( "created" ) )
    fullString = fullString + issuesString( "modified", removeIssuesForCategory( "modified" ) )
    fullString = fullString + issuesString( "comment added", removeIssuesForCategory( "commented" ) )
    watching = removeIssuesForCategory( "watching" )
    for x in categories:
        fullString = fullString + issuesString( x, categories[x] )

    fullString = fullString +  "below supressed since should have gotten email\n"
    for x in watching:
        fullString = "%s%s - %s\n" % ( fullString, x["key"], x["fields"]["summary"] )

    return fullString

def findOldestInInbox():
    import mailutil

    m = mailutil.imapclient( imapHost, imapUser, cache=True, pwd=getPassword( imapHost, imapUser ) )
    m.select( "INBOX" , False )

    last_seen = time.time()

    l = m.list()

    oldUIDs = []
    mostBack = 0

    done = 0
    for uid in l:
        done = done + 1
        msg = m.fetch( uid , True )

        m.get_cache().update( { "_id" : m.get_id( uid ) },
                              { "$set" : { "lastSeen" : last_seen } } )

        headers = msg["headers"]
        if not headers:
            continue
        who = headers["from"]
        subject = headers["subject"]
        if not subject.startswith( "jira summary @" ):
            continue

        pcs = subject.split( "@" )
        if len(pcs) != 3:
            raise Exception( "bad subject [%s]" % subject )

        hoursFromSubject = 1 + int(pcs[1].strip())

        thing = dateutil.parser.parse( pcs[2].strip() )
        now = datetime.datetime.utcnow()
        diff = now-thing
        hours = int(diff.total_seconds() / 3600)

        oldUIDs.append( uid )
        if hours > mostBack:
            mostBack = hours

        if hoursFromSubject > mostBack:
            mostBack = hoursFromSubject

    return mostBack,oldUIDs

def archiveOldMail( uids ):
    if len(uids) == 0:
        return

    import mailutil

    m = mailutil.imapclient( imapHost, imapUser, cache=True, pwd=getPassword( imapHost, imapUser ) )
    m.select( "INBOX" , False )

    for uid in uids:
        m.archive( uid )

    m.expunge()


if __name__=="__main__":

    sendEmail = True
    checkInbox = False

    for x in sys.argv[1:]:
        if x == "--debug":
            sendEmail = False
            continue
        if x.startswith( "--hours=" ):
            hoursBack = int(x.partition("=")[2])
            continue
        if x == "--inbox":
            checkInbox = True
            continue
        raise Exception( "unknown option: " + x )

    allBadUIDs = []

    if checkInbox:
        try:
            mailHoursBack,allBadUIDs = findOldestInInbox()
            if mailHoursBack > hoursBack:
                hoursBack = mailHoursBack
        except Exception,e:
            print( "couldn't check inbox: " + str(e) )

    text = getText()

    if text == "":
        sys.exit(0)

    if sendEmail:
        import mypwd
        gmail.send_message( "eliot@mongodb.com",
                            "jira summary @ %s @ %s" % ( hoursBack,  str(datetime.datetime.utcnow() ) ),
                            text,
                            smtpPass=mypwd.pwd,
                            smtpNiceName="Eliot Jira Bot")

        if len(allBadUIDs) > 0:
            archiveOldMail( allBadUIDs )
    else:
        print( text )


