from contextlib import closing

def global_protect(sess, server):
    # with closing(sess.get('https://{}/ssl-tunnel-connect.sslvpn'.format(server), stream=True)) as r:
    #    if r.status_code==502:
    #        components.append('gateway')

    components = []
    r = sess.get('https://{}/global-protect/prelogin.esp'.format(server), headers={'user-agent':'PAN GlobalProtect'})
    if b'<status>Success</status>' in r.content:
        components.append('portal')
    r = sess.get('https://{}/ssl-vpn/prelogin.esp'.format(server), headers={'user-agent':'PAN GlobalProtect'})
    if b'<status>Success</status>' in r.content:
        components.append('gateway')
    if components:
        return "PAN GlobalProtect ({})".format(' and '.join(components))

def juniper_nc(sess, server):
    # Juniper is frustrating because mostly it just spits out standard HTML, sometimes along with DS* cookies

    r = sess.get('https://{}/dana-na/auth/url_default/welcome.cgi'.format(server), headers={'user-agent':'ncsrv'})
    if (r.status_code==200 and b'/dana-na/' in r.content) or any(c.startswith('DS') for c in r.cookies.keys()):
        return "Juniper Network Connect"

def check_point(sess, server):
    # "GET /sslvpn/Login/Login" gives too many false positives

    r = sess.post('https://{}/clients/abc'.format(server), headers={'user-agent':'TRAC/986000125'}, data=b'(CCCclientRequest)')
    if r.content.startswith(b'(CCCserverResponse'):
        return "Check Point"

def sstp(sess, server):
    # Yes, this is for real...
    # See section 3.2.4.1 of v17.0 doc at https://msdn.microsoft.com/en-us/library/cc247338.aspx

    with closing(sess.request('SSTP_DUPLEX_POST', 'https://{}/sra_{{BA195980-CD49-458b-9E23-C84EE0ADCD75}}/'.format(server), stream=True)) as r:
        if r.status_code==200 and r.headers.get('content-length')=='18446744073709551615':
            return "SSTP"

def anyconnect(sess, server):
    # Try GET-tunnel (Cisco returns X-Reason, ocserv doesn't) and CONNECT-tunnel with bogus cookie (OpenConnect returns X-Reason)
    # "GET /+CSCOE+/logon.html" but this gives too many false positives.

    r = sess.get('https://{}/CSCOSSLC/tunnel'.format(server))
    if 'X-Reason' in r.headers:
        return "Cisco AnyConnect"

    with closing(sess.request('CONNECT', 'https://{}/CSCOSSLC/tunnel'.format(server), headers={'Cookie': 'webvpn='}, stream=True)) as r:
        if 'X-Reason' in r.headers:
            return "OpenConnect ocserv"

sniffers = [
    ('AnyConnect/OpenConnect', anyconnect),
    ('Juniper Network Connect', juniper_nc),
    ('PAN GlobalProtect', global_protect),
    ('Check Point', check_point),
    ('SSTP', sstp),
]