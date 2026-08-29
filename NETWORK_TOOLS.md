# Network Tools

## Purpose

Network Tools provides bounded diagnostics without exposing a browser shell or generic command executor. Hostnames, IPv4/IPv6 addresses, DNS servers, ports, record types and URLs are validated by typed Pydantic models before execution.

## Architecture

Existing Networking collectors are reused: `network_diagnostics.test_connectivity`, `network_overview`, `routing_snapshot` and `dns_configuration`. Network Tools adds the missing typed DNS record lookup, reverse DNS, route lookup, neighbor/connection views and HTTP/TLS probe. System utilities are selected server-side and always invoked as argv arrays with `shell=False`.

The module limits diagnostics to four concurrent operations and thirty requests per actor per minute. Commands and sockets use explicit timeouts, and command/result output is bounded. Every diagnostic creates a secret-free Activity Center event.

## Tools

- Ping: 3 bounded ICMP probes through the existing diagnostics helper.
- Traceroute: `tracepath`/`traceroute`, max 20 hops.
- DNS Lookup: A, AAAA, CNAME, MX, TXT, NS and PTR; optional validated DNS server IP.
- Reverse DNS: validated IPv4/IPv6 address through the system resolver.
- TCP Port Test: hostname/IP + port, success/failure and latency.
- HTTP/HTTPS Test: DNS resolution, resolved IPs, TCP connect timing, TLS handshake timing, HTTP status, response timing, redirect chain and basic peer-certificate metadata.
- Route Lookup: fixed `ip -j route get` command.
- Routing Table: shared Networking routing snapshot.
- ARP/Neighbor Table: fixed `ip -j neigh show`.
- Interfaces: shared Networking interface inventory.
- Listening Ports: shared Firewall Manager listener correlation.
- Active Connections: bounded `ss -H -tunap` parsing.
- DNS Configuration: shared resolver configuration inventory.

## API

- `GET /api/modules/network-tools/overview`
- `POST /api/modules/network-tools/ping`
- `POST /api/modules/network-tools/traceroute`
- `POST /api/modules/network-tools/dns`
- `POST /api/modules/network-tools/reverse-dns`
- `POST /api/modules/network-tools/port-test`
- `POST /api/modules/network-tools/http-test`
- `POST /api/modules/network-tools/route-lookup`
- `GET /api/modules/network-tools/routes`
- `GET /api/modules/network-tools/neighbors`
- `GET /api/modules/network-tools/interfaces`
- `GET /api/modules/network-tools/connections`
- `GET /api/modules/network-tools/listening-ports`
- `GET /api/modules/network-tools/dns-configuration`

## Permissions

`network_tools.view`, `network_tools.ping`, `network_tools.traceroute`, `network_tools.dns`, `network_tools.port_test`, `network_tools.http_test`, `network_tools.routes`, `network_tools.connections`.

## Packages

APT: `iproute2`, `iputils-ping`, `traceroute`, `dnsutils`. DNF/YUM: `iproute`, `iputils`, `traceroute`, `bind-utils`.

## Security limitations

The tools intentionally permit an authorized administrator/operator to test private or public network destinations because this is a diagnostic function. They do not permit custom binaries, switches, shell syntax, file paths or environment variables. HTTP URLs reject embedded credentials and redirects are bounded. The feature is not a port scanner and exposes only one explicit TCP port per request.

## Troubleshooting

Missing `dig`, `ip`, `ss`, `ping` or traceroute tooling is reported as an unavailable diagnostic rather than falling back to a shell. Install the declared Module Center dependencies and repeat the test.
