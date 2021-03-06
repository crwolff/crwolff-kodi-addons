from __future__ import unicode_literals
from future import standard_library
standard_library.install_aliases()
from builtins import str
from builtins import range
from builtins import object
import collections, re, socket, sys, threading, time, urllib.request, urllib.parse, urllib.error, urllib.request, urllib.error, urllib.parse, os, unicodedata
import xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs
import musicbrainzngs, mypithos

try:
    import urllib3
    import urllib3.contrib.pyopenssl
    urllib3.contrib.pyopenssl.inject_into_urllib3()
    _urllib3 = True
except ImportError:
    _urllib3 = False
    pass

from mutagen.mp3 import MP3
from mutagen.easyid3 import EasyID3
from mutagen.easymp4 import EasyMP4



_addon	= xbmcaddon.Addon()
_base	= sys.argv[0]
_id	= _addon.getAddonInfo('id')
_stamp	= str(time.time())

# xbmc.LOGDEBUG = 0
# xbmc.LOGERROR = 4
# xbmc.LOGFATAL = 6
# xbmc.LOGINFO = 1
# xbmc.LOGNONE = 7
# xbmc.LOGNOTICE = 2
# xbmc.LOGSEVERE = 5
# xbmc.LOGWARNING = 3

def Log(msg, s = None, level = xbmc.LOGNOTICE):
    try:
        if s and s.get('artist'): xbmc.log(("%s %s %s '%s - %s'" % (_id, msg, s['token'][-4:], s['artist'], s['title'])).encode('ascii','replace'), level) # song
        elif s:                   xbmc.log(("%s %s %s '%s'"      % (_id, msg, s['token'][-4:], s['title'])).encode('ascii','replace'), level)              # station
        else:                     xbmc.log(("%s %s"              % (_id, msg)).encode('ascii','replace'), level)
    except UnicodeEncodeError:
        xbmc.log("%s %s (UnicodeEncodeError)" % (_id, slugify(msg)), level)
        pass
#        import json
#        tpath = xbmc.translatePath('log_errs.json')
#        with open(tpath, 'a') as fp:
#            fp.write('\nLog Failure\n')
#            json.dump(s, fp, indent=4)

# setup the ability to provide notification to the Kodi GUI
iconart = xbmc.translatePath(os.path.join('special://home/addons/plugin.audio.pandoki',  'icon.png'))

def notification(title, message, ms, nart):
    xbmcgui.Dialog().notification( title, message, icon=nart, time=ms )

def slugify(value):
    """
    Normalizes string
    """
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('utf-8')
    value = re.sub('[\\/|]', '-', value)
    value = re.sub('[?%*:<>]', ' ', value)		# remove bad filename chars
    return ' '.join(value.split())			# collapse multiple spaces

def Val(key, val = None):
    if key in [ 'author', 'changelog', 'description', 'disclaimer', 'fanart', 'icon', 'id', 'name', 'path', 'profile', 'stars', 'summary', 'type', 'version' ]:
        return _addon.getAddonInfo(key)

    if val:      _addon.setSetting(key, val)
    else: return _addon.getSetting(key)


def Prop(key, val = 'get'):
    if val == 'get':
        retVal = xbmcgui.Window(10000).getProperty("%s.%s" % (_id, key))
        Log('def Prop %s=%s value=%s' % (key, val, retVal), None, xbmc.LOGDEBUG)
        return retVal
    else:
        Log('def Prop %s=%s ' % (key, val), None, xbmc.LOGDEBUG)
        xbmcgui.Window(10000).setProperty("%s.%s" % (_id, key), val)


_maxdownloads=int(Val('maxdownload'))

class Pandoki(object):
    def __init__(self):
        run = Prop('run')
        if (run) and (time.time() < float(run) + 3): return

        Prop('run', str(time.time()))
        Prop('stamp', _stamp)

        self.once	= True
        self.downloading = 0  # number of files currently being downloaded
        self.abort	= False
        self.mesg	= None
        self.station	= None
        self.stations	= None
        self.songs	= { }
        self.pithos	= mypithos.Pithos()
        self.player	= xbmc.Player()
        self.playlist	= xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
        self.ahead	= { }
        self.queue	= collections.deque()
        self.prof	= Val('prof')
        self.wait	= { 'auth' : 0, 'stations' : 0, 'flush' : 0, 'scan' : 0, 'next' : 0 }
        self.silent	= xbmc.translatePath("special://home/addons/%s/resources/media/silent.m4a" % _id)

        musicbrainzngs.set_useragent("kodi.%s" % _id, Val('version'))
        try:
            xbmcvfs.mkdirs(xbmc.translatePath(Val('cache')).decode("utf-8"))
            xbmcvfs.mkdirs(xbmc.translatePath(Val('library')).decode("utf-8"))
        except AttributeError:
            xbmcvfs.mkdirs(xbmc.translatePath(Val('cache')))
            xbmcvfs.mkdirs(xbmc.translatePath(Val('library')))


        # Clean cache at startup
        self.Flush()

    def Proxy(self):
        Log('def Proxy ', None, xbmc.LOGDEBUG)
        proxy = Val('proxy')

        if proxy == '1':	# None
            hand = urllib.request.ProxyHandler({})
            return urllib.request.build_opener(hand)

        elif proxy == '0':	# Global
            if (Val('sni') == 'true') and _urllib3:
                return urllib3.PoolManager()
            else:
                return urllib.request.build_opener()

        elif proxy == '2':	# Custom
            http = "http://%s:%s@%s:%s" % (Val('proxy_user'), Val('proxy_pass'), Val('proxy_host'), Val('proxy_port'))

            if (Val('sni') == 'true') and _urllib3:
                return urllib3.ProxyManager(http)
            else:
                hand = urllib.request.ProxyHandler({ 'http' : http, 'https' : http })
                return urllib.request.build_opener(hand)


    def Auth(self):
        Log('def Auth ', None, xbmc.LOGDEBUG)
        p = Val('prof')
        if self.prof != p:
            self.wait['auth'] = 0
            self.stations = None
            self.prof = p

        if time.time() < self.wait['auth']: return True

        self.pithos.set_url_opener(self.Proxy(), (Val('sni') == 'true'))

        try: self.pithos.connect(Val('one' + p), Val('username' + p), Val('password' + p))
        except mypithos.PithosError:
            Log('Auth BAD')
            return False

        self.wait['auth'] = time.time() + (60 * 60)	# Auth every hour
        Log('Auth  OK', None, xbmc.LOGINFO)
        return True


    def Login(self):
        Log('def Login ', None, xbmc.LOGDEBUG)
        if (Val('sni') == 'true') and (not _urllib3):
            if xbmcgui.Dialog().yesno(Val('name'), 'SNI Support not found', 'Please install: pyOpenSSL/ndg-httpsclient/pyasn1', 'Check Settings?'):
                xbmcaddon.Addon().openSettings()
            else:
                exit()

        while not self.Auth():
            if xbmcgui.Dialog().yesno(Val('name'), '          Login Failed', 'Bad User / Pass / Proxy', '       Check Settings?'):
                xbmcaddon.Addon().openSettings()
            else:
                exit()


    def Stations(self):
        Log('def Stations ', None, xbmc.LOGDEBUG)
        if (self.stations) and (time.time() < self.wait['stations']):
            return self.stations

        if not self.Auth(): return None
        self.stations = self.pithos.get_stations()

        self.wait['stations'] = time.time() + (60 * 5)				# Valid for 5 mins
        return self.stations


    def Sorted(self):
        Log('def Sorted ', None, xbmc.LOGDEBUG)
        sort = Val('sort')

        stations = list(self.Stations())
        quickmix = stations.pop(0)						# Quickmix

        if   sort == '0': stations = stations					# Normal
        elif sort == '2': stations = stations[::-1]				# Reverse
        elif sort == '1': stations = sorted(stations, key=lambda s: s['title'])	# A-Z

        stations.insert(0, quickmix)						# Quickmix back on top
        return stations


    def Dir(self, handle):
        Log('def Dir ', None, xbmc.LOGDEBUG)
        self.Login()

        ic = Val('icon')
        li = xbmcgui.ListItem('New Station ...')
        li.setArt({'icon':ic,'thumb':ic})
        xbmcplugin.addDirectoryItem(int(handle), "%s?search=hcraes" % _base, li, True)

        for s in self.Sorted():
            li = xbmcgui.ListItem(s['title'], s['token'])
            if self.station == s: li.select(True)

            art = Val("art-%s" % s['token'])
            if not art: art = s.get('art', ic)

            li.setArt({'icon':art,'thumb':art})

            title = slugify(s['title'])
            rurl = "RunPlugin(plugin://%s/?%s)" % (_id, urllib.parse.urlencode({ 'rename' : s['token'], 'title' : title }))
            durl = "RunPlugin(plugin://%s/?%s)" % (_id, urllib.parse.urlencode({ 'delete' : s['token'], 'title' : title }))
            surl = "RunPlugin(plugin://%s/?%s)" % (_id, urllib.parse.urlencode({  'thumb' : s['token'], 'title' : title }))

            li.addContextMenuItems([('Rename Station', rurl),
                                    ('Delete Station', durl),
                                    ('Select Thumb',   surl), ])

            burl = "%s?%s" % (_base, urllib.parse.urlencode({ 'play' : s['token'] }))
            xbmcplugin.addDirectoryItem(int(handle), burl, li)
#            Log(burl)

        xbmcplugin.endOfDirectory(int(handle), cacheToDisc = False)
        # wait for the window to appear in Kodi before continuing
        xbmc.sleep(3000)
        Log("Dir   OK %4s" % handle, None, xbmc.LOGINFO)


    def Search(self, handle, query):
        Log('def Search %s ' % query, None, xbmc.LOGDEBUG)
        self.Login()

        for s in self.pithos.search(query, True):
            title = s['artist']
            title += (' - %s' % s['title']) if s.get('title') else ''

            li = xbmcgui.ListItem(title, s['token'])
            xbmcplugin.addDirectoryItem(int(handle), "%s?create=%s" % (_base, s['token']), li)

        xbmcplugin.endOfDirectory(int(handle), cacheToDisc = False)
        Log("Search   %4s '%s'" % (handle, query), None, xbmc.LOGINFO)


    def Info(self, s):
        Log('def Info ', None, xbmc.LOGDEBUG)
        info = { 'artist' : s['artist'], 'album' : s['album'], 'title' : s['title'], 'rating' : s['rating'] }

        if s.get('duration'):
            info['duration'] = s['duration']

        return info


    def Add(self, song):
        Log('def Add ', song, xbmc.LOGDEBUG)
        if song['token'] != 'mesg':
            self.songs[song['token']] = song

        # This line adds the line in the playlist on Kodi GUI
        li = xbmcgui.ListItem(song['artist'], song['title'])
        li.setArt({'icon':song['art'],'thumb':song['art']})
        li.setProperty("%s.token" % _id, song['token'])
        li.setInfo('music', self.Info(song))

        if song.get('encoding') == 'm4a': li.setProperty('mimetype', 'audio/aac')
        if song.get('encoding') == 'mp3': li.setProperty('mimetype', 'audio/mpeg')

        Log('def Add  adding %s' % song['path'], song, xbmc.LOGDEBUG)
        self.playlist.add(song['path'], li)
        self.Scan(False)

        Log('Add   OK', song, xbmc.LOGINFO)


    def Queue(self, song):
        Log('def Queue ', song, xbmc.LOGDEBUG)
        self.queue.append(song)


    def Msg(self, msg):
        Log('def Msg %s ' % msg, None, xbmc.LOGDEBUG)
        if self.mesg == msg: return
        else: self.mesg = msg

        # added ready (true if file is ready to play and starttime to know how
        # long it has been taking to download file
        song = { 'starttime' : time.time(), 'ready' : False, 'token' : 'mesg', 'title' : msg, 'path' : self.silent, 'artist' : Val('name'),  'album' : Val('description'), 'art' : Val('icon'), 'rating' : '' }
        self.Queue(song)

#        while True:		# Remove old messages
#            item = None
#            for pos in range(0, self.playlist.getposition() - 1):
#                try: item = self.playlist[pos]
#                except RuntimeError:
#                    item = None
#                    break
#
#                id = item.getProperty("%s.id" % _id)
#                if (id == 'mesg'):
#                    xbmc.executeJSONRPC('{"jsonrpc":"2.0", "id":1, "method":"Playlist.Remove", "params":{"playlistid":' + str(xbmc.PLAYLIST_MUSIC) + ', "position":' + str(pos) + '}}')
#                    break
#
#            if not item:
#                break


    def M3U(self, song, delete = False):
        if (Val('m3u') != 'true'): return
        if (not song.get('saved', False)): return

        m3u = xbmcvfs.File(song['path_m3u'], 'r')
        lines = m3u.read().splitlines()
        m3u.close()

        if (song['path_rel'] in lines):
            if (not delete): return

            lines.remove(song['path_rel'])

        else:
            if (not xbmcvfs.exists(song['path_lib'])): return

            lines.append(song['path_rel'])

        lines = '\n'.join(lines)

        m3u = xbmcvfs.File(song['path_m3u'], 'w')
        m3u.write(lines)
        m3u.close()


    def Tag(self, song):
        Log('def Tag ', song, xbmc.LOGDEBUG)
        try:
            res = musicbrainzngs.search_recordings(limit = 1, query = song['title'], artist = song['artist'], release = song['album'], qdur = str(song['duration'] * 1000))['recording-list'][0]
            song['score']  =     res['ext:score']
            song['brain']  =     res['id']
            for lst in res['release-list']:	# Find a numeric track number
                song['count']  = lst['medium-list'][-1]['track-count']
                try:
                    song['number'] = int(lst['medium-list'][-1]['track-list'][0]['number'])
                    break
                except ValueError:
                    song['number'] = 0

        except:
            song['score']  = '0'

        Log("Tag%4s%%" % song['score'], song, xbmc.LOGINFO)
        return song['score'] == '100'


    def Save(self, song):
        Log('def Save ', song, xbmc.LOGDEBUG)
        if (song['title'] == 'Advertisement') or (song.get('saved')) or (not song.get('cached', False)): return
        if (Val('mode') in ('0', '3')) or ((Val('mode') == '2') and (song.get('voted') != 'up')): return
        if (not self.Tag(song)):
            Log("Tag failed ", song)
            return

        # Blocklists
        Okay = True
        if (Val('artist_bl') != ""):
            for xl_item in Val('artist_bl').split(','):
                if (xl_item.strip() in song['artist']): Okay = False
        if (Val('album_gl') != ""):
            for xl_item in Val('album_gl').split(','):
                if (xl_item.strip() in song['album']): Okay = False
        if (Val('title_gl') != ""):
            for xl_item in Val('title_gl').split(','):
                if (xl_item.strip() in song['title']): Okay = False
        if not Okay:
            xbmcvfs.delete(song['path_cch'])	# Normally deleted from cache after playing
            return

        tmp = "%s.%s" % (song['path'], song['encoding'])
        if not xbmcvfs.copy(song['path_cch'], tmp):
            Log('Save BAD', song)
            return

        if   song['encoding'] == 'm4a': tag = EasyMP4(tmp)
        elif song['encoding'] == 'mp3': tag = MP3(tmp, ID3 = EasyID3)

        if tag == None:
            Log('Save BAD', song)
            xbmcvfs.delete(tmp)
            return

        tag['tracknumber']         = "%d/%d" % (song['number'], song['count'])
        tag['musicbrainz_trackid'] = song['brain']
        tag['artist']              = song['artist']
        tag['album']               = song['album']
        tag['title']               = song['title']
        Log("Save: metadata %s" % song['brain'], song, xbmc.LOGDEBUG)

        if song['encoding'] == 'mp3':
            tag.save(v2_version = 3)
        else:
            tag.save()

        xbmcvfs.mkdirs(song['path_dir'])
        xbmcvfs.copy(tmp, song['path_lib'])
        xbmcvfs.delete(tmp)
        Log('Save: Song Cached ', song, xbmc.LOGDEBUG)

        song['saved'] = True
        self.M3U(song)

        if (song.get('art', False)) and ((not xbmcvfs.exists(song['path_alb'])) or (not xbmcvfs.exists(song['path_art']))):
            try:
                strm = self.Proxy().open(song['art'])
                data = strm.read()
            except ValueError:
                Log("Save ART      '%s'" % song['art'], None, xbmc.LOGINFO)
#                xbmc.log(str(song))
                return

            for jpg in [ song['path_alb'], song['path_art'] ]:
                if not xbmcvfs.exists(jpg):
                    file = xbmcvfs.File(jpg, 'wb')
                    file.write(bytearray(data))
                    file.close()

        Log('Save  OK', song, xbmc.LOGINFO)


    def Hook(self, song, size, totl):
        Log('def Hook ', song, xbmc.LOGDEBUG)
        if totl in (341980, 340554, 173310):	# empty song cause requesting to fast
            self.Msg('Too Many Songs Requested')
            Log('Cache MT', song, xbmc.LOGINFO)
            return False

        if (song['title'] != 'Advertisement') and (totl <= int(Val('adsize')) * 1024):
            Log('Cache AD', song, xbmc.LOGINFO)

            song['artist'] = Val('name')
            song['album']  = Val('description')
            song['art']    = Val('icon')
            song['title']  = 'Advertisement'

            if (Val('skip') == 'true'):
                song['qued'] = True
                self.Msg('Skipping Advertisements')

        # Blocklists
        if (not song.get('qued')) and (Val('artist_bl') != ""):
            for xl_item in Val('artist_bl').split(','):
                if (xl_item.strip() in song['artist']):
                    self.pithos.add_feedback(song['token'], False)	# Thumbs down
                    notification('Banned', song['artist'], 3000, iconart)
                    Log('Artist blocklist: %s' % song['artist'])
                    song['qued'] = True
                    break

        if (not song.get('qued')) and (Val('album_gl') != ""):
            for xl_item in Val('album_gl').split(','):
                if (xl_item.strip() in song['album']):
                    self.pithos.set_tired(song['token'])
                    notification('Tired', song['album'], 3000, iconart)
                    Log('Album greylist: %s - %s' % (song['artist'], song['album']))
                    song['qued'] = True
                    break

        if (not song.get('qued')) and (Val('title_gl') != ""):
            for xl_item in Val('title_gl').split(','):
                if (xl_item.strip() in song['title']):
                    self.pithos.set_tired(song['token'])
                    notification('Tired', song['title'], 3000, iconart)
                    Log('Title greylist: %s - %s' % (song['artist'], song['title']))
                    song['qued'] = True
                    break

        Log('Cache QU: ready=%s size=%8d bitrate:%8d' % (song.get('ready'), size, song['bitrate']), song, xbmc.LOGDEBUG)
        if song.get('ready',False) and (not song.get('qued')) and (size >= (song['bitrate'] / 8 * 1024 * int(Val('delay')))):
            song['qued'] = True
            self.Queue(song)

        return True


    def Cache(self, song):
        monitor = xbmc.Monitor()
        Log('def Cache ', song, xbmc.LOGDEBUG)
        try:
            strm = self.Proxy().open(song['url'], timeout = 10)
        except: # HTTPError:
            self.wait['auth'] = 0
            if not self.Auth():
                Log("Cache ER", song, xbmc.LOGINFO)
                return
            strm = self.Proxy().open(song['url'], timeout = 10)

        # Handle missing data
        if strm.headers.get('Content-Length') == None:
            Log('Cache didn\'t get headers', song )
            self.wait['next'] = time.time() + 60.0	# Wait 1 minute to allow network to recover
            return

        totl = int(strm.headers['Content-Length'])
        size = 0
        lastsize = -1

        Log("Expecting %8d bytes " % totl, song, xbmc.LOGINFO)

        cont = self.Hook(song, size, totl)
        if not cont: return

        file = xbmcvfs.File(song['path_cch'], 'wb')
        self.downloading = self.downloading + 1
        song['starttime'] = time.time()
        lastnotify = time.time()
        title = song['title']
        short_title = title[:32] if len(title) > 32 else title
        if (not song.get('qued')):
            notification('Caching', '[COLOR lime]' + short_title + ' [/COLOR]' , 3000, iconart)
        short_title = title[:28] if len(title) > 28 else title
        while (cont) and (size < totl) and (not monitor.abortRequested()) and (not self.abort):
            Log("Downloading %8d bytes, currently %8d bytes " % (totl, size), song, xbmc.LOGDEBUG)
            try: data = strm.read(min(8192, totl - size))
            except socket.timeout:
                Log('Socket Timeout: Bytes Received %8d: Cache TO' % size, song)
                song['ready'] = True
                break

            file.write(bytearray(data))
            size += len(data)

            if ( lastnotify + 60 < time.time() ):
                if (size == lastsize):
                    Log('Aborting Song, Song Stopped Buffering: %d out of %d downloaded' % (size, totl), song)
                    notification('Song Stopped Buffering', '[COLOR lime] %d' % (size * 100 / totl ) + '% ' + short_title + ' [/COLOR]' , 5000, iconart)
                    break

                lastnotify = time.time()
                lastsize = size
                notification('Song Buffering', '[COLOR lime] %d' % (size * 100 / totl ) + '% ' + short_title + ' [/COLOR]' , 5000, iconart)


            if ( size >= totl ):
                Log('Setting song to ready ', song, xbmc.LOGDEBUG)
                song['ready'] = True
            cont = self.Hook(song, size, totl)

        file.close()
        strm.close()
        self.downloading = self.downloading - 1

        if (not cont) or (size != totl):
            #xbmc.sleep(3000)
            xbmcvfs.delete(song['path_cch'])
            Log('Cache RM', song, xbmc.LOGINFO)

        else:
            song['cached'] = True
            self.Save(song)

        Log('Cache Download Complete, Still Downloading:%d' % self.downloading, song, xbmc.LOGINFO)


    def Fetch(self, song):
        Log('def Fetch ', song, xbmc.LOGDEBUG)
        if xbmcvfs.exists(song['path_mp3']):	# Found MP3 in Library
            Log('Song MP3', song, xbmc.LOGINFO)
            song['path_lib'] = song['path_mp3']
            song['path'] = song['path_lib']
            song['saved'] = True

        elif xbmcvfs.exists(song['path_m4a']):	# Found M4A in Library
            Log('Song M4A', song, xbmc.LOGINFO)
            song['path_lib'] = song['path_m4a']
            song['path'] = song['path_lib']
            song['saved'] = True

        elif xbmcvfs.exists(song['path_cch']):	# Found in Cache
            Log('Song CCH', song, xbmc.LOGINFO)
            song['path'] = song['path_cch']

        elif Val('mode') == '0':		# Stream Only
            Log('Song PAN', song, xbmc.LOGINFO)
            song['path'] = song['url']

        else:					# Cache / Save
            Log('Song GET', song, xbmc.LOGINFO)
            song['path'] = song['path_cch']
            self.Cache(song)
            return

        self.Queue(song)



    def Seed(self, song):
        Log('def Seed ', None, xbmc.LOGDEBUG)
        if not self.Stations(): return
        result = self.pithos.search("%s by %s" % (song['title'], song['artist']))[0]

        if (result['title'] == song['title']) and (result['artist'] == song['artist']):
            self.pithos.seed_station(song['station'], result['token'])
        else:
            Log('Seed BAD', song)


    def Branch(self, song):
        Log('def Branch ', None, xbmc.LOGDEBUG)
        if not self.Stations(): return
        station = self.pithos.branch_station(song['token'])

        Prop('play', station['token'])
        Prop('action', 'play')

        Log('Branch  ', song, xbmc.LOGINFO)


#    def Del(self, song):
#        self.M3U(song, True)
#        xbmcvfs.delete(song['path_lib'])


    def Rate(self, mode):
        Log('def Rate ', None, xbmc.LOGDEBUG)
        pos  = self.playlist.getposition()
        item = self.playlist[pos]
        tokn = item.getProperty("%s.token" % _id)
        song = self.songs.get(tokn)

        if not song:
            return

        elif (mode == 'branch'):
            self.Branch(song)
            return

        elif (mode == 'seed'):
            self.Seed(song)

        elif (mode == 'up'):
            song['voted'] = 'up'
            Prop('voted', 'up')
            self.pithos.add_feedback(song['token'], True)
            notification('Thumb UP', song['title'], 3000, iconart)
            self.Save(song)

        elif (mode == 'tired'):
            self.player.playnext()
            self.pithos.set_tired(song['token'])
            notification('Tired', song['title'], 3000, iconart)

        elif (mode == 'down'):
            song['voted'] = 'down'
            Prop('voted', 'down')
            self.player.playnext()
            self.pithos.add_feedback(song['token'], False)
            notification('Thumb DOWN', song['title'], 3000, iconart)
            self.M3U(song, True)

        elif (mode == 'clear'):
            song['voted'] = ''
            Prop('voted', '')
            feedback = self.pithos.add_feedback(song['token'], True)
            self.pithos.del_feedback(song['station'], feedback)
            notification('Thumb CLEARED', song['title'], 3000, iconart)

        else: return

        Log("%-8s" % mode.title(), song, xbmc.LOGNOTICE)


    def Rated(self, song, rating):
        Log("Rate %1s>%1s" % (song['rating'], rating), song, xbmc.LOGNOTICE)

        expert = (Val('rating') == '1')
        song['rating'] = rating
        song['rated'] = rating

        if (rating == '5'):
            if (expert):
                self.Branch(song)
            else:
                self.pithos.add_feedback(song['token'], True)
                notification('Thumb UP', song['title'], 3000, iconart)
            self.Save(song)

        elif (rating == '4'):
            if (expert):
                self.Seed(song)
            else:
                self.pithos.add_feedback(song['token'], True)
                notification('Thumb UP', song['title'], 3000, iconart)
            self.Save(song)

        elif (rating == '3'):
            self.pithos.add_feedback(song['token'], True)
            notification('Thumb UP', song['title'], 3000, iconart)
            self.Save(song)

        elif (rating == '2'):
            if (expert):
                self.pithos.set_tired(song['token'])
            else:
                self.pithos.add_feedback(song['token'], False)
                notification('Thumb DOWN', song['title'], 3000, iconart)
            self.player.playnext()

        elif (rating == '1'):
            self.pithos.add_feedback(song['token'], False)
            notification('Thumb DOWN', song['title'], 3000, iconart)
            self.player.playnext()

        elif (rating == ''):
            feedback = self.pithos.add_feedback(song['token'], True)
            self.pithos.del_feedback(song['station'], feedback)
            notification('Thumb CLEARED', song['title'], 3000, iconart)


    def Scan(self, rate = False):
        Log('def Scan ', None, xbmc.LOGDEBUG)
        if ((rate) and (time.time() < self.wait['scan'])) or (xbmcgui.getCurrentWindowDialogId() == 10135): return
        self.wait['scan'] = time.time() + 15

        songs = dict()
        for pos in range(0, self.playlist.size()):
            tk = self.playlist[pos].getProperty("%s.token" % _id)
            rt = xbmc.getInfoLabel("MusicPlayer.Position(%d).Rating" % pos)
            if (rt == ''): rt = '0'

            if tk in self.songs:
                song = self.songs[tk]
                del self.songs[tk]
                songs[tk] = song

                if (rate) and (song.get('rating', rt) != rt):
                    self.Rated(song, rt)
                elif not song.get('rating'):
                    song['rating'] = rt

        for s in self.songs:
            if (not self.songs[s].get('keep', False)) and xbmcvfs.exists(self.songs[s].get('path_cch')):
                xbmcvfs.delete(self.songs[s]['path_cch'])
                Log('Scan  RM', self.songs[s], xbmc.LOGINFO)

        self.songs = songs


    def Path(self, s):
        Log('def Path ', None, xbmc.LOGDEBUG)
        lib  = Val('library')

        artist = slugify(s['artist'])
        album = slugify(s['album'])
        title = slugify(s['title'])
        s['path_cch'] = xbmc.translatePath("%s/%s - %s.%s"            % (Val('cache'), artist, title,  s['encoding']))
        s['path_dir'] = xbmc.translatePath("%s/%s/%s - %s"            % (lib,          artist, artist, album))
        s['path_m4a'] = xbmc.translatePath("%s/%s/%s - %s/%s - %s.%s" % (lib,          artist, artist, album, artist, title, 'm4a'))
        s['path_mp3'] = xbmc.translatePath("%s/%s/%s - %s/%s - %s.%s" % (lib,          artist, artist, album, artist, title, 'mp3'))
        s['path_lib'] = xbmc.translatePath("%s/%s/%s - %s/%s - %s.%s" % (lib,          artist, artist, album, artist, title, s['encoding']))
        s['path_alb'] = xbmc.translatePath("%s/%s/%s - %s/folder.jpg" % (lib,          artist, artist, album))
        s['path_art'] = xbmc.translatePath("%s/%s/folder.jpg"         % (lib,          artist))

        title = slugify(self.station['title'])
        s['path_m3u'] = xbmc.translatePath("%s/%s.m3u"                % (lib, title))
        s['path_rel'] = xbmc.translatePath("%s/%s - %s/%s - %s.%s"    % (     artist, artist, album, artist, title, s['encoding']))


    def Fill(self):
        Log('def Fill ', None, xbmc.LOGDEBUG)
        token = self.station['token']
        if len(self.ahead.get(token, '')) > 0: return

        if not self.Auth():
            self.Msg('Login Failed. Check Settings')
            self.abort = True
            return

        try: songs = self.pithos.get_playlist(token, int(Val('quality')))
        except (mypithos.PithosTimeout, mypithos.PithosNetError): pass
        except (mypithos.PithosAuthTokenInvalid, mypithos.PithosAPIVersionError, mypithos.PithosError) as e:
            Log("%s, %s" % (e.message, e.submsg))
            self.Msg(e.message)
            self.abort = True
            return

        for song in songs:
            self.Path(song)

        self.ahead[token] = collections.deque(songs)

        Log('Fill  OK', self.station, xbmc.LOGINFO)


    def Next(self):
        Log('def Next %s %s' % (time.time(), self.wait['next']), None, xbmc.LOGDEBUG)
        # keeps the number of downloads clamped to _maxdownloads
        if time.time() < self.wait['next'] or self.downloading >= _maxdownloads: return
        self.wait['next'] = time.time() + float(Val('delay')) + 1

        self.Fill()

        token = self.station['token']
        if len(self.ahead.get(token, '')) > 0:
            song = self.ahead[token].popleft()
            threading.Timer(0, self.Fetch, (song,)).start()


    def List(self):
        Log('def List ', None, xbmc.LOGDEBUG)
        if (not self.station) or (not self.player.isPlayingAudio()): return

        len1  = self.playlist.size()
        pos  = self.playlist.getposition()
        item = self.playlist[pos]
        tokn = item.getProperty("%s.token" % _id)

        if tokn in self.songs:
            Prop('voted', self.songs[tokn].get('voted', ''))

#        skip = xbmc.getInfoLabel("MusicPlayer.Position(%d).Rating" % pos)
#        skip = ((tokn == 'mesg') or (skip == '1') or (skip == '2')) and (xbmcgui.getCurrentWindowDialogId() != 10135)

        # keep adding until number of max downloads is in list not played

        if ((len1 - pos) < 2) or ((len1 - pos + self.downloading) < (_maxdownloads + 1)):
            self.Next()

        if ((len1 - pos) > 1) and (tokn == 'mesg'):
            self.player.playnext()


    def Deque(self):
        Log('def Deque %2d' % len(self.queue), None, xbmc.LOGDEBUG)
        if len(self.queue) == 0: return
        elif self.once:
            self.playlist.clear()
            self.Flush()

        while len(self.queue) > 0:
            song = self.queue.popleft()
            self.Add(song)
            self.M3U(song)

        if self.once:
            # this will start the  playlist playing
            self.player.play(self.playlist)
            Log('def Deque setting once to False', None, xbmc.LOGDEBUG)
            self.once = False

        for x in range(min( self.playlist.size() - int(Val('history')), self.playlist.getposition() )):
            xbmc.executeJSONRPC('{"jsonrpc":"2.0", "id":1, "method":"Playlist.Remove", "params":{"playlistid":' + str(xbmc.PLAYLIST_MUSIC) + ', "position":0}}')
            xbmc.sleep(100)

        if xbmcgui.getCurrentWindowId() == 10500:
            xbmc.executebuiltin("Container.Refresh")


    def Tune(self, token):
        Log('def Tune %s' % token, None, xbmc.LOGDEBUG)
        for s in self.Stations():
            if (token == s['token']) or (token == s['token'][-4:]):
                if self.station == s: return False

                self.station = s
                Val('station' + self.prof, token)
                return True

        return False


    def Play(self, token):
        Log('Play  ??', self.station, xbmc.LOGINFO)
        last = self.station

        if self.Tune(token):
            self.Fill()

            while True:
                len = self.playlist.size() - 1
                pos = self.playlist.getposition()
                if len > pos:
                    item = self.playlist[len]
                    tokn = item.getProperty("%s.token" % _id)

                    if (last) and (tokn in self.songs):
                        self.songs[tokn]['keep'] = True
                        self.ahead[last['token']].appendleft(self.songs[tokn])

                    xbmc.executeJSONRPC('{"jsonrpc":"2.0", "id":1, "method":"Playlist.Remove", "params":{"playlistid":' + str(xbmc.PLAYLIST_MUSIC) + ', "position":' + str(len) + '}}')
                else: break

            self.Msg("%s" % self.station['title'])
            Log('Play  OK', self.station, xbmc.LOGINFO)

        xbmc.executebuiltin('ActivateWindow(10500)')


    def Create(self, token):
        Log('%s' % token, None, xbmc.LOGINFO)
        self.Stations()
#        self.Auth()
        station = self.pithos.create_station(token)

        Log('Create  ', station, xbmc.LOGINFO)
        self.Play(station['token'])


    def Delete(self, token):
        if (self.station) and (self.station['token'] == token): self.station = None

        self.Stations()
        station = self.pithos.delete_station(token)

        Log('Delete  ', station, xbmc.LOGNOTICE)
        xbmc.executebuiltin("Container.Refresh")


    def Rename(self, token, title):
        self.Stations()
        station = self.pithos.rename_station(token, title)

        Log('Rename  ', station, xbmc.LOGINFO)
        xbmc.executebuiltin("Container.Refresh")


    def Action(self):
        act = Prop('action')
        Log('def Action action=%s' % act, None, level = xbmc.LOGDEBUG)

        if _stamp != Prop('stamp'):
            self.abort = True
            self.station = None
            return

        elif act == '':
            Prop('run', str(time.time()))
            return

        elif act == 'search':
            self.Search(Prop('handle'), Prop('search'))

        elif act == 'create':
            self.Create(Prop('create'))

        elif act == 'rename':
            self.Rename(Prop('rename'), Prop('title'))

        elif act == 'delete':
            self.Delete(Prop('delete'))

        elif act == 'rate':
            self.Rate(Prop('rate'))

        act = Prop('action')

        if   act == 'play':
            self.Play(Prop('play'))

        elif act == 'dir':
            self.Dir(Prop('handle'))
            if (self.once or not self.player.isPlayingAudio()) and (Val('autoplay') == 'true') and (Val('station' + self.prof)):
                self.Play(Val('station' + self.prof))

        Prop('action', '')
        Prop('run', str(time.time()))


    def Flush(self):
        Log('def Flush', None, level = xbmc.LOGDEBUG)
        try:
            cch = xbmc.translatePath(Val('cache')).decode("utf-8")
        except AttributeError:
            cch = xbmc.translatePath(Val('cache'))
        reg = re.compile('^.*\.(m4a|mp3)')

        (dirs, list) = xbmcvfs.listdir(cch)

        for file in list:
            if reg.match(file):
                xbmcvfs.delete("%s/%s" % (cch, file))
                Log("Flush OK      '%s'" % file, None, xbmc.LOGINFO)


    def Loop(self):
        monitor = xbmc.Monitor()
        Log('def Loop', None, level = xbmc.LOGDEBUG)
        while (not monitor.abortRequested()) and (not self.abort) and (self.once or self.player.isPlayingAudio()):
            time.sleep(0.01)
            xbmc.sleep(3000)

            self.Action()
            self.Deque()
            self.List()
            self.Scan()

            for i in range(20):
                if not (self.once or self.player.isPlayingAudio()):
                    xbmc.sleep(200)
                else:
                    break

        if (self.player.isPlayingAudio()):
            notification('Exiting', '[COLOR lime]No longer queuing new songs[/COLOR]' , 5000, iconart)
        Log('Pankodi Exiting XBMCAbort?=%s PandokiAbort?=%s ' % (monitor.abortRequested(), self.abort), None, level = xbmc.LOGNOTICE)
        Prop('run', '0')

