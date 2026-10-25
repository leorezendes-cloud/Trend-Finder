import json,re,unittest
from html.parser import HTMLParser
from unittest.mock import patch
from xml.etree import ElementTree as ET
from app import app


class HeadParser(HTMLParser):
    def __init__(self):
        super().__init__();self.metas={};self.canonicals=[];self.titles=[];self.in_title=False
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='meta':self.metas[attrs.get('name') or attrs.get('property')]=attrs.get('content')
        if tag=='link' and attrs.get('rel')=='canonical':self.canonicals.append(attrs['href'])
        if tag=='title':self.in_title=True;self.titles.append('')
    def handle_data(self,value):
        if self.in_title:self.titles[-1]+=value
    def handle_endtag(self,tag):
        if tag=='title':self.in_title=False


class SeoTests(unittest.TestCase):
    def head(self,path,**options):
        response=app.test_client().get(path,**options)
        self.assertEqual(response.status_code,200)
        parser=HeadParser();parser.feed(response.text)
        return parser,response

    def test_unique_public_descriptions_titles_and_canonical_urls(self):
        descriptions=set()
        for path in ('/','/trend-finder','/the-plug','/sunday-results'):
            head,_=self.head(path)
            self.assertEqual(len(head.titles),1)
            self.assertIn('NFL',head.titles[0])
            self.assertEqual(head.canonicals,['https://trendfindah.com'+path])
            self.assertEqual(head.metas['robots'],'index, follow')
            self.assertEqual(head.metas['og:title'],head.titles[0])
            descriptions.add(head.metas['description'])
        self.assertEqual(len(descriptions),4)

    def test_plug_metadata_describes_current_models(self):
        head,_ = self.head('/the-plug')
        self.assertIn('points-based ATS', head.metas['description'])
        self.assertIn('Scout-based total', head.metas['description'])

    def test_legacy_market_redirect_is_not_an_indexable_page(self):
        client = app.test_client()
        response = client.get('/market')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], '/the-plug')
        self.assertNotIn('https://trendfindah.com/market', client.get('/sitemap.xml').text)

    def test_host_headers_cannot_poison_links_and_alias_is_canonical(self):
        head,_=self.head('/sunday-scout',headers={'Host':'attacker.example'})
        self.assertEqual(head.canonicals,['https://trendfindah.com/the-plug'])
        self.assertTrue(head.metas['og:image'].startswith('https://trendfindah.com/static/'))
        self.assertEqual(head.metas['twitter:image'], head.metas['og:image'])

    def test_private_and_filtered_pages_are_not_indexable(self):
        for path in ('/members/login','/members/register','/members/forgot-password','/trend-finder?season=2026'):
            head,response=self.head(path)
            self.assertEqual(head.metas['robots'],'noindex, follow')
            self.assertEqual(response.headers['X-Robots-Tag'],'noindex, follow')
        response=app.test_client().get('/this-page-does-not-exist')
        self.assertEqual(response.status_code,404)
        self.assertIn('noindex',response.headers['X-Robots-Tag'])

    def test_matchup_metadata_is_descriptive(self):
        head,_=self.head('/matchup/2026_06_BUF_LV')
        self.assertIn('Buffalo Bills',head.titles[0]);self.assertIn('Las Vegas Raiders',head.titles[0])
        self.assertIn('2026',head.metas['description'])

    def test_discovery_routes_are_valid_and_do_not_run_collectors(self):
        with patch('scheduled_ats_capture.run',side_effect=AssertionError('No collection')),patch('scout4.blend.run',side_effect=AssertionError('No model run')):
            client=app.test_client();robots=client.get('/robots.txt');sitemap=client.get('/sitemap.xml')
        self.assertEqual(robots.status_code,200)
        self.assertEqual(robots.mimetype,'text/plain')
        self.assertIn('Sitemap: https://trendfindah.com/sitemap.xml',robots.text)
        self.assertEqual(sitemap.status_code,200)
        self.assertEqual(sitemap.mimetype,'application/xml')
        root=ET.fromstring(sitemap.data)
        urls=[element.text for element in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
        self.assertIn('https://trendfindah.com/the-plug',urls)
        self.assertIn('https://trendfindah.com/matchup/2026_06_BUF_LV',urls)
        self.assertEqual(len(urls),len(set(urls)))
        self.assertFalse(any('/members/' in url or '/picks/' in url or '/newsletter/' in url or '?' in url or '/sunday-scout' in url for url in urls))

    def test_homepage_body_and_design_are_unchanged(self):
        client=app.test_client()
        body=lambda html:html.split('<body',1)[1]
        with patch.dict(app.config,{'SEO_ENABLED':False}):old=client.get('/').text
        new=client.get('/').text
        self.assertEqual(body(old),body(new))
        structured=re.search(r'<script type="application/ld\+json">(.*?)</script>',new,re.S)
        self.assertEqual(json.loads(structured.group(1))['name'],'Trend Findah')
