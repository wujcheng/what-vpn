from contextlib import closing
from urllib.parse import urlsplit
import re
import attr

@attr.s
class Hit(object):
    def __bool__(self):
        return self.confidence > 0.0

    @property
    def details(self):
        strings = []
        if self.name:
            strings.append(self.name)
        if self.version:
            strings.append(self.version)
        if self.components:
            strings.append('+'.join(self.components))
        if self.confidence < 1.0:
            strings.append('%d%%' % (self.confidence*100))
        return ', '.join(strings)

    confidence = attr.ib(default=1.0, validator=attr.validators.instance_of(float))
    name = attr.ib(default=None)
    version = attr.ib(default=None)
    components = attr.ib(default=None)

def _meaningless(x, *vals):
    if x not in vals:
        return x

#####
# Sniffers based on protocol details
#####

def global_protect(sess, server):
    '''PAN GlobalProtect'''
    # with closing(sess.get('https://{}/ssl-tunnel-connect.sslvpn'.format(server), stream=True)) as r:
    #    if r.status_code==502:
    #        components.append('gateway')

    components = []
    version = hit = None

    for component, path in (('portal','global-protect'), ('gateway','ssl-vpn')):
        r = sess.get('https://{}/{}/prelogin.esp'.format(server, path), headers={'user-agent':'PAN GlobalProtect'})
        if r.headers.get('content-type','').startswith('application/xml') and b'<prelogin-response>' in r.content:
            hit = True

            if b'<status>Success</status>' in r.content:
                components.append(component)
            m = re.search(rb'<panos-version>([^<]+)</panos-version>', r.content)
            if m:
                version = m.group(1).decode()

    if hit:
        return Hit(components=components, version=_meaningless(version, '1'))

def check_point(sess, server):
    '''Check Point'''
    confidence = version = None

    # Try an empty client request in Check Point's parenthesis-heavy format
    r = sess.post('https://{}/clients/abc'.format(server), headers={'user-agent':'TRAC/986000125'}, data=b'(CCCclientRequest)')
    if r.content.startswith(b'(CCCserverResponse'):
        confidence = 1.0

    r = sess.get('https://{}/'.format(server), headers={'user-agent':'TRAC/986000125'})
    m = re.search(rb'(\d+-)?(\d+).+Check Point Software Technologies', r.content)
    if m:
        version = m.group(2).decode()
        confidence = confidence or 0.2

    return confidence and Hit(version=version, confidence=confidence)

def sstp(sess, server):
    '''SSTP'''
    # Yes, this is for real...
    # See section 3.2.4.1 of v17.0 doc at https://msdn.microsoft.com/en-us/library/cc247338.aspx

    with closing(sess.request('SSTP_DUPLEX_POST', 'https://{}/sra_%7BBA195980-CD49-458b-9E23-C84EE0ADCD75%7D/'.format(server), stream=True)) as r:
        if r.status_code==200 and r.headers.get('content-length')=='18446744073709551615':
            version = _meaningless( r.headers.get('server'), "Microsoft-HTTPAPI/2.0" )
            return Hit(version=version)

def anyconnect(sess, server):
    '''AnyConnect/OpenConnect'''

    # Cisco returns X-Reason in response to GET-tunnel...
    r = sess.get('https://{}/CSCOSSLC/tunnel'.format(server))
    if 'X-Reason' in r.headers:
        return Hit(name="Cisco", version=r.headers.get('server'))

    with closing(sess.request('CONNECT', 'https://{}/CSCOSSLC/tunnel'.format(server), headers={'Cookie': 'webvpn='}, stream=True)) as r:
        if r.reason=='Cookie is not acceptable':
            return Hit(name="ocserv", version='0.11.7+')
        # ... whereas ocserv 7e06e1ac..3feec670 inadvertently sends X-Reason header in the *body*
        elif r.raw.read(9)==b'X-Reason:':
            return Hit(name="ocserv", version='0.8.0-0.11.6')

#####
# Sniffers based on behavior of web front-end
#####

def openvpn(sess, server):
    '''OpenVPN'''
    r = sess.get('https://{}/'.format(server))
    if any(c.name.startswith('openvpn_sess_') for c in sess.cookies):
        return Hit(version=r.headers.get('server'))

def juniper_nc(sess, server):
    '''Juniper Network Connect'''

    confidence = None
    r = sess.get('https://{}/dana-na'.format(server), headers={'user-agent':'ncsrv', 'NCP-Version': '3'})
    if any(c.name.startswith('DS') for c in sess.cookies):
        confidence = 1.0
    elif urlsplit(r.url).path.startswith('/dana-na/auth/'):
        confidence = 0.8

    return confidence and Hit(confidence=confidence, version=r.headers.get('NCP-Version'))

def barracuda(sess, server):
    '''Barracuda'''

    r = sess.get('https://{}/'.format(server))

    m = re.search(rb'(\d+-)?(\d+)\s+Barracuda Networks', r.content)
    version = m and m.group(2).decode()

    confidence = None
    if 'SSLX_SSESHID' in sess.cookies:
        confidence = 1.0
    elif urlsplit(r.url).path.startswith('/default/showLogon.do'):
        confidence = 0.9 if version else 0.8
    elif version:
        confidence = 0.2

    return confidence and Hit(version=version, confidence=confidence)

def fortinet(sess, server):
    '''Fortinet'''

    # server sets *empty* SVPNCOOKIE/SVPNNETWORKCOOKIE
    r = sess.get('https://{}/remote/login'.format(server))
    if r.headers.get('set-cookie','').startswith('SVPNCOOKIE'):
        server = r.headers.get('server')
        confidence = 1.0 if server=='xxxxxxxx-xxxxx' else 0.9
        return Hit(confidence=confidence, version=_meaningless(server,'xxxxxxxx-xxxxx'))

sniffers = [
    anyconnect,
    juniper_nc,
    global_protect,
    barracuda,
    check_point,
    sstp,
    openvpn,
    fortinet,
]
