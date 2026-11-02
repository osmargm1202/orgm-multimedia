"""Recognize content links without redirects, DNS, or arbitrary browser fallbacks."""
from dataclasses import dataclass
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit
from .protocol import ControlError
from .youtube import canonical_url as youtube_url

LABELS = {'youtube':'YouTube','netflix':'Netflix','disney-plus':'Disney+', 'max':'Max',
          'crunchyroll':'Crunchyroll','prime-video':'Prime Video','spotify':'Spotify'}
MESSAGE = 'Selecciona un enlace de contenido de YouTube, Netflix, Disney+, Max, Crunchyroll, Prime Video o Spotify.'

@dataclass(frozen=True)
class MediaLink:
    app: str
    url: str
    identity: str

    @property
    def endpoint(self):
        return '/api/apps/youtube/open-url' if self.app == 'youtube' else '/api/media/open-url'

    @property
    def spotify_uri(self):
        parts=urlsplit(self.url).path.strip('/').split('/')
        return 'spotify:' + ':'.join(parts[-2:])


def media_link(value):
    try:
        if not isinstance(value,str):raise ValueError
        value=value.strip()
        if not value or len(value)>2048 or '\\' in value or any(ord(c)<33 or ord(c)==127 for c in value):raise ValueError
        u=urlsplit(value)
        if u.scheme!='https' or u.username or u.password or u.port not in {None,443}:raise ValueError
        host=(u.hostname or '').lower()
        path=u.path.rstrip('/')
        if host in {'youtube.com','www.youtube.com','m.youtube.com','music.youtube.com','youtu.be','www.youtu.be'}:
            url=youtube_url(value)
            return MediaLink('youtube',url,parse_qs(urlsplit(url).query)['v'][0])
        locale=r'(?:/[a-z]{2}(?:-[A-Za-z0-9]{2,3})?)?'
        if host in {'netflix.com','www.netflix.com'}:
            m=re.fullmatch(locale+r'/(title|watch)/([0-9]{6,12})',path)
            if m:return MediaLink('netflix',f'https://www.netflix.com/{m[1]}/{m[2]}',m[2])
            ids=parse_qs(u.query).get('jbv',[])
            if path=='/browse' and len(ids)==1 and re.fullmatch(r'[0-9]{6,12}',ids[0]):
                return MediaLink('netflix','https://www.netflix.com/title/'+ids[0],ids[0])
        elif host in {'disneyplus.com','www.disneyplus.com'}:
            m=re.fullmatch(locale+r'/(?:browse/entity-|(?:video|play)/)([a-fA-F0-9-]{36})',path)
            if m and re.fullmatch(r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}',m[1]):
                return MediaLink('disney-plus','https://www.disneyplus.com'+path,m[1])
            m=re.fullmatch(locale+r'/(?:movies|series)/[A-Za-z0-9-]+/([A-Za-z0-9]{8,64})',path)
            if m:return MediaLink('disney-plus','https://www.disneyplus.com'+path,m[1])
        elif host in {'max.com','www.max.com','play.max.com','hbomax.com','www.hbomax.com','play.hbomax.com'}:
            m=re.fullmatch(locale+r'/(?:movie|movies|show|shows|video|feature)/([A-Za-z0-9-]{8,64})(?:/[A-Za-z0-9-]+)*',path)
            if m:return MediaLink('max',urlunsplit(('https',host,path,'','')),m[1])
        elif host in {'crunchyroll.com','www.crunchyroll.com'}:
            m=re.fullmatch(locale+r'/(?:watch|series)/([A-Za-z0-9]{6,20})(?:/[A-Za-z0-9-]+)?',path)
            if m:return MediaLink('crunchyroll','https://www.crunchyroll.com'+path,m[1])
        elif host in {'primevideo.com','www.primevideo.com'}:
            m=re.fullmatch(r'(?:/region/[a-z]{2})?/(?:detail|dp)/([A-Za-z0-9]{8,32})(?:/[A-Za-z0-9_-]+)*',path)
            if m:return MediaLink('prime-video','https://www.primevideo.com/detail/'+m[1],m[1])
        elif host=='open.spotify.com':
            m=re.fullmatch(r'(?:/intl-[a-z]{2})?/(track|album|playlist|episode|show|artist)/([A-Za-z0-9]{22})',path)
            if m:return MediaLink('spotify',f'https://open.spotify.com/{m[1]}/{m[2]}',m[2])
        raise ValueError
    except (ValueError,UnicodeError):
        raise ControlError(MESSAGE,422) from None
