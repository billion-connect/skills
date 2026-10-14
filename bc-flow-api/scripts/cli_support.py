"""Presentation and transport diagnostics; never changes API request data."""

import copy
import errno
import socket
import ssl
import sys
import urllib.error
import urllib.parse


def configure_stdio():
    # Explicit encoding also applies to redirected output on Windows.
    for name in ('stdin', 'stdout', 'stderr'):
        stream = getattr(sys, name, None)
        if hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(encoding='utf-8',
                                   errors='strict' if name == 'stdin' else 'backslashreplace')
            except (OSError, ValueError):
                pass  # Embedded hosts / already-read streams may not support reconfiguration.


def request_route(request):
    if not (request.has_proxy() or getattr(request, '_tunnel_host', None)):
        return {'route': 'direct'}
    # Request.host is the selected proxy after urllib applied NO_PROXY and removed userinfo.
    # Never expose the original proxy URL, path, query, or authentication headers.
    route = {'route': 'proxy'}
    try:
        address = urllib.parse.urlsplit('//' + request.host)
        host, port = address.hostname, address.port
        if host and all(c.isalnum() or c in '.-:' for c in host):
            host = '[' + host + ']' if ':' in host else host
            route['proxy'] = host + (':' + str(port) if port is not None else '')
    except ValueError:
        pass
    return route


def network_details(exc):
    details = dict(getattr(exc, '_flow_route', {'route': 'unknown'}))
    cause = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    number = getattr(cause, 'errno', None)
    if getattr(exc, 'code', None) == 407 or (
            isinstance(cause, OSError) and 'Tunnel connection failed: 407' in str(cause)):
        kind, message = 'proxy_authentication', 'Proxy authentication failed (407); check local proxy login and credentials.'
    elif isinstance(cause, ssl.SSLCertVerificationError):
        kind, message = 'tls_certificate', 'TLS certificate verification failed; check the certificate chain and proxy certificate configuration. Do not disable verification.'
    elif isinstance(cause, ssl.SSLError):
        kind, message = 'tls', 'TLS handshake failed; check the target service or proxy TLS configuration.'
    elif isinstance(cause, (TimeoutError, socket.timeout)) or number in (errno.ETIMEDOUT, 10060):
        kind, message = 'timeout', 'Connection or read timed out.'
    elif isinstance(cause, socket.gaierror):
        kind, message = 'dns', 'DNS lookup failed; check name resolution for the connection target.'
    elif isinstance(cause, ConnectionRefusedError) or number in (errno.ECONNREFUSED, 10061):
        kind, message = 'connection_refused', 'Connection refused; check whether the service is available on the target port.'
    else:
        kind, message = 'connection', 'Network connection failed.'
    if details['route'] == 'proxy':
        message += ' This request used a proxy. Check the proxy service and NO_PROXY configuration first; the client does not bypass proxies automatically.'
    elif details['route'] == 'direct':
        message += ' This request used a direct connection.'
    else:
        message += ' The connection route could not be determined. If a proxy is configured, also check it and NO_PROXY.'
    details.update(kind=kind, hint=message)
    return details


def has_view(args):
    return any((args.sku_id is not None, args.country_code is not None,
                args.product_type is not None, args.limit is not None, args.summary))


def validate_view(args):
    if not has_view(args):
        return
    if args.code not in ('F002', 'F003'):
        raise ValueError('Local filters and summaries support only F002/F003.')
    if args.code == 'F003' and (args.country_code is not None or args.product_type is not None):
        raise ValueError('F003 has no country/product-type fields; select products with F002, then filter prices with --sku-id.')
    if args.limit is not None and args.limit <= 0:
        raise ValueError('--limit must be a positive integer.')
    for name in ('sku_id', 'country_code', 'product_type'):
        if getattr(args, name) is not None and not getattr(args, name).strip():
            raise ValueError('Local filter values must not be empty.')


def display_result(result, args):
    if not has_view(args) or not result.get('success'):
        return result
    response = result.get('response', {})
    rows = response.get('tradeData')
    view = copy.deepcopy(result)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        view['local_view'] = {'applied': False, 'reason': 'tradeData is not a product array; the original response is preserved.'}
        return view
    selected = []
    for row in rows:
        if args.sku_id is not None and str(row.get('skuId', '')) != args.sku_id:
            continue
        if args.product_type is not None and str(row.get('type', '')) != args.product_type:
            continue
        if args.country_code is not None:
            countries = row.get('country')
            if not isinstance(countries, list) or not any(
                    isinstance(c, dict) and str(c.get('mcc', '')).upper() == args.country_code.upper()
                    for c in countries):
                continue
        selected.append(row)
    limit = args.limit if args.limit is not None else (20 if args.summary else None)
    shown = selected[:limit] if limit is not None else selected
    if args.summary:
        if args.code == 'F002':
            fields = ('skuId', 'name', 'type', 'days', 'capacity', 'highFlowSize', 'planType',
                      'applyToDevice', 'applyToDeviceType', 'rechargeableProduct',
                      'estimatedUseTimeFlag', 'estimatedUseTimeGapHours')
            brief = []
            for row in shown:
                item = {k: row[k] for k in fields if k in row}
                if isinstance(row.get('country'), list):
                    item['country'] = [{k: c[k] for k in ('mcc', 'name') if k in c}
                                       for c in row['country'] if isinstance(c, dict)]
                brief.append(item)
            shown = brief
        else:
            # Keep every quotation of each selected SKU, including copies/days and amounts.
            shown = [{k: row[k] for k in ('skuId', 'price', 'currency') if k in row} for row in shown]
    view['response']['tradeData'] = shown
    view['local_view'] = {'applied': True, 'local_only': True, 'total_count': len(rows),
                          'matched_count': len(selected), 'shown_count': len(shown),
                          'truncated': len(shown) < len(selected), 'summary': args.summary}
    if not selected:
        view['local_view']['note'] = 'No matches in this response; this does not prove the product is absent from other channels or query scopes.'
    return view
