import hashlib
from pathlib import Path

from orgm_home.assets import MANIFEST, asset_url


def test_manifest_matches_all_shipped_assets():
    root=Path(__file__).parents[1]/'orgm_home/static'
    for path,digest in MANIFEST['files'].items():
        assert hashlib.sha256((root/path).read_bytes()).hexdigest()[:12]==digest,path


def test_public_assets_cache_and_revalidate_but_private_data_does_not(configured,paired):
    client,_,headers=paired
    url=asset_url('cards/spotify.webp')
    r=client.get(url)
    assert r.status_code==200 and 'immutable' in r.headers['cache-control']
    assert r.headers['content-type']=='image/webp'
    assert client.get(url,headers={'if-none-match':r.headers['etag']}).status_code==304
    assert 'immutable' not in client.get('/static/home.css').headers['cache-control']
    assert client.get('/api/status').headers['cache-control']=='no-store'
    assert client.get('/').headers['cache-control']=='no-store'
    r=client.get(asset_url('home.js'),headers={'accept-encoding':'gzip'})
    assert r.headers['content-encoding']=='gzip'
