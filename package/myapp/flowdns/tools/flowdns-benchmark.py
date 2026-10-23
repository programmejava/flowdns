#!/usr/bin/env python3
"""Run on a LAN computer. Manually select each mode; no router settings change.

python flowdns-benchmark.py --mode flowdns-proxy --url https://YOUR_SERVER/test.bin
Compare direct, flowdns-direct, ssr-proxy, flowdns-proxy with matching targets.
Optional --ssh root@ROUTER records /proc metrics before and after each sample.
Optional --iperf-server SERVER --udp enables a bounded iperf3 UDP measurement.
"""
import argparse
import concurrent.futures
import json
import pathlib
import socket
import ssl
import subprocess
import time
import urllib.parse
import urllib.request

MODES = ('direct', 'flowdns-direct', 'ssr-proxy', 'flowdns-proxy')


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != 'https':
            raise ValueError('benchmark redirect must retain HTTPS')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def metrics(target):
    if not target:
        return None
    if target.startswith('-') or any(c.isspace() for c in target):
        raise ValueError('invalid SSH destination')
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', target,
                             '/usr/libexec/flowdns metrics'], capture_output=True, text=True, timeout=10, check=True)
    return json.loads(result.stdout)


def utilization(before, after):
    if not before or not after:
        return None
    cpus = {}
    for name, end in after['cpus'].items():
        start = before['cpus'].get(name, end)
        total = end['total'] - start['total']
        cpus[name] = round(100 * (1 - (end['idle'] - start['idle']) / total), 1) if total > 0 else 0
    total = after['cpus']['cpu']['total'] - before['cpus']['cpu']['total']
    cores = len(after['cpus']) - 1
    old = {(p['pid'], p['start']): p for p in before['processes']}
    processes = []
    for p in after['processes']:
        value = dict(p)
        previous = old.get((p['pid'], p['start']))
        if previous and total > 0:
            value['cpu_percent_one_core'] = round(100 * cores * (p['ticks'] - previous['ticks']) / total, 1)
        processes.append(value)
    return {'cpu_busy_percent': cpus, 'processes': processes, 'available_kb': after.get('available_kb')}


def transfer(url, limit, context):
    # Ignore local HTTP proxy environment variables: measure the router path.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context), HTTPSRedirect())
    start = time.monotonic()
    request = urllib.request.Request(url, headers={'Range': f'bytes=0-{limit - 1}', 'Cache-Control': 'no-cache'})
    count = 0
    with opener.open(request, timeout=15) as response:
        if urllib.parse.urlsplit(response.url).scheme != 'https':
            raise ValueError('benchmark redirect must retain HTTPS')
        first = response.read(1)
        ttfb = time.monotonic() - start
        count = len(first)
        while count < limit:
            if time.monotonic() - start > 30:
                break
            block = response.read(min(65536, limit - count))
            if not block:
                break
            count += len(block)
    elapsed = time.monotonic() - start
    return {'bytes': count, 'seconds': round(elapsed, 4), 'ttfb_ms': round(ttfb * 1000, 2),
            'mbps': round(count * 8 / max(elapsed, .000001) / 1_000_000, 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=MODES, required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--runs', type=int, choices=range(1, 11), default=3)
    parser.add_argument('--parallel', type=int, choices=range(1, 5), default=1)
    parser.add_argument('--mib', type=int, choices=range(1, 65), default=8)
    parser.add_argument('--ssh')
    parser.add_argument('--ca-file', help='optional trusted CA for a private test endpoint; certificates remain verified')
    parser.add_argument('--iperf-server')
    parser.add_argument('--udp', action='store_true')
    parser.add_argument('--output', default='flowdns-benchmark.json')
    args = parser.parse_args()
    parsed = urllib.parse.urlsplit(args.url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        parser.error('use an HTTPS test URL without embedded credentials')
    context = ssl.create_default_context(cafile=args.ca_file)
    begin = time.monotonic()
    socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    dns_ms = (time.monotonic() - begin) * 1000
    report = {'mode': args.mode, 'time': time.time(), 'host': parsed.hostname, 'path': parsed.path,
              'dns_ms': round(dns_ms, 2), 'parallel': args.parallel, 'samples': []}
    for _ in range(args.runs):
        before = metrics(args.ssh)
        started = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
            samples = list(pool.map(lambda _: transfer(args.url, args.mib * 1048576, context), range(args.parallel)))
        elapsed = time.monotonic() - started
        report['samples'].append({'streams': samples,
                                  'total_mbps': round(sum(s['bytes'] for s in samples) * 8 / elapsed / 1_000_000, 3),
                                  'router': utilization(before, metrics(args.ssh))})
    if args.udp:
        if not args.iperf_server or args.iperf_server.startswith('-'):
            parser.error('--udp requires --iperf-server with a server you control')
        result = subprocess.run(['iperf3', '-c', args.iperf_server, '-u', '-b', '10M', '-t', '10', '-J'],
                                capture_output=True, text=True, timeout=20, check=True)
        report['udp'] = json.loads(result.stdout)
    target = pathlib.Path(args.output)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f'Saved {target}; compare matching video/test targets and node settings across modes.')


if __name__ == '__main__':
    main()
