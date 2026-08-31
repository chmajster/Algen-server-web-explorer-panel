# DATA Communication & Segmentation Tool - DCST

DCST is the network communication and segmentation layer for WebNAS. It translates logical application objects such as `APMID.ENV`, reusable Ports and IPSets into managed Proxmox VE Firewall objects while preserving firewall rules that are not owned by DCST.

## Architecture

```text
Proxmox Manager -> shared Hosts Manager inventory -> DCST desired state
                                                   |
                                                   +-> APMID.ENV TAG
                                                   +-> dynamic IPSet
                                                   +-> Service + Port objects
                                                   +-> reconciliation engine
                                                            |
                                                            v
                                                   Proxmox Firewall API
```

DCST does not maintain an independent VM inventory. It consumes the public Hosts Manager network-inventory projection, which is populated by Proxmox Manager and shared with the other infrastructure modules. Proxmox credentials also remain owned by Proxmox Manager; DCST obtains backend-only API clients from the Proxmox Manager public contract. Credentials are never returned to the browser.

## Proxmox configuration

Configure at least one active Proxmox connection in **Proxmox Manager**. DCST uses the same endpoint and credential/token configuration. The Proxmox API principal needs sufficient permissions to read nodes/firewall logs and to manage datacenter firewall options, rules and IPSets used by DCST. Exact Proxmox role composition can vary by Proxmox VE release and local policy; grant the narrowest privileges that allow the following API areas:

- `/cluster/firewall/options`
- `/cluster/firewall/rules`
- `/cluster/firewall/ipset`
- `/nodes/{node}/firewall/log`

Do not place Proxmox tokens or passwords in DCST frontend settings.

## TAGS and VM synchronization

A canonical host with an APMID and environment becomes a logical TAG:

```text
APMID = IAASTEA
ENV   = PROD
        |
        v
IAASTEA.PROD
        |
        v
dynamic IPSet (provider-safe name)
```

The readable name remains `IAASTEA.PROD` in DCST. A separate provider-safe identifier is used when Proxmox naming constraints require it. Dynamic IPSet members are derived from the shared inventory's management/IP address and are not manually editable.

A successful Proxmox Manager inventory synchronization publishes `PROXMOX_INVENTORY_CHANGED`. DCST subscribes to this event and reconciles dynamic TAG/IPSet membership. Manual synchronization is also available from **TAGS** and **Utilities**. Repeating inventory synchronization is idempotent: it does not duplicate TAGS, IP addresses or system Services.

## Default APMID communication

For each APMID, DCST creates one idempotent system Service:

```text
SYSTEM_<APMID>_INTERNAL
source      = <APMID>.*
destination = <APMID>.*
action      = ACCEPT
enabled     = true
```

`APMID.*` is expanded by the reconciliation layer into the current `APMID.ENV` dynamic IPSets.

## Ports

Ports are reusable objects. Supported protocol models are:

- TCP
- UDP
- TCP+UDP
- ICMP
- a single port
- a port range such as `8000-8100`

Port numbers are validated in the range 1-65535. A Port referenced by a Service cannot be deleted until its dependencies are removed. Editing a Port changes the desired rule generated for every Service that references it.

## IPSets

DCST distinguishes:

- `dynamic` - generated from shared VM inventory;
- `manual` - user-managed IPv4, IPv6 and CIDR entries;
- `system` - reserved for application-owned objects.

Addresses are normalized and duplicates are removed. Dynamic/system IPSets cannot be manually modified through the regular manual-IPSet API. Deletion of a referenced IPSet is rejected and its Service dependencies are returned by the API/UI.

## Services

A Service defines logical communication:

```text
Source -> Service -> Destination
```

Fields include name, description, IN/OUT direction, ACCEPT/DROP/REJECT action, source, destination, one or more reusable Ports, enable state, logging and comment. Source and destination can represent:

- `APMID.ENV` TAG
- `APMID.*`
- IPSet
- IP address
- CIDR
- Any

The Services view supports text search, direction/action/state filters, multi-selection and bulk enable/disable/block/unblock/synchronize operations.

## Block / Unblock

Blocking does not delete the Service. It changes its effective desired policy to DROP while preserving the logical definition. Unblock restores the configured action. The state model includes `ACTIVE`, `BLOCKED`, `DISABLED`, `PENDING` and `ERROR`; provider synchronization additionally records `SYNCED`, `DRIFT` or `ERROR`.

## Reconciliation and drift

DCST computes desired Proxmox firewall objects and compares them with current Proxmox state. Managed rules are tagged with a `DCST:` comment marker. Reconciliation only replaces DCST-owned rules and preserves unknown/external rules.

The reconciliation states are conceptually:

```text
CREATE / UPDATE / DELETE / NO_CHANGE / CONFLICT
```

A normal synchronization performs calculate -> apply -> verify. Dry Run only returns planned changes. Drift detection runs the comparison without applying changes and reports objects that are not `NO_CHANGE`.

## Safety

Firewall changes are critical. DCST validates names, addresses, CIDR, protocols, port ranges and object references. A `DROP ANY -> ANY` Service is classified as high risk and cannot be synchronized without explicit high-risk confirmation and the corresponding DCST synchronization permission. DCST does not use hard-coded management IP addresses or node names.

## RBAC

DCST registers the following shared Identity permissions:

- `dcst.read`
- `dcst.manage_services`
- `dcst.manage_ports`
- `dcst.manage_ipsets`
- `dcst.manage_tags`
- `dcst.block_traffic`
- `dcst.sync`
- `dcst.view_logs`
- `dcst.admin`

Administrative roles receive all DCST permissions. Operator/auditor defaults follow the risk of each operation, and explicit Identity allow/deny rules continue to apply.

## API

The API follows the existing module convention and is rooted at `/api/modules/dcst`.

Important routes include:

```text
GET    /overview
GET    /tags
POST   /tags/sync
POST   /tags/{id}/sync
GET    /ipsets
POST   /ipsets
GET    /ipsets/{id}
PUT    /ipsets/{id}
DELETE /ipsets/{id}
POST   /ipsets/{id}/sync
GET    /ports
POST   /ports
GET    /ports/{id}
PUT    /ports/{id}
DELETE /ports/{id}
GET    /services
POST   /services
GET    /services/{id}
PUT    /services/{id}
DELETE /services/{id}
POST   /services/{id}/clone
GET    /services/{id}/preview
POST   /services/{id}/block
POST   /services/{id}/unblock
POST   /services/{id}/enable
POST   /services/{id}/disable
POST   /services/{id}/sync
POST   /services/bulk/{block|unblock|enable|disable|sync}
GET    /firewall/status
GET    /firewall/logs
POST   /firewall/test
POST   /firewall/sync
GET    /firewall/drift
GET    /diagnostics
GET    /audit
```

## Utilities and troubleshooting

Utilities provides:

- Proxmox Firewall status;
- Test Proxmox Firewall API;
- Dry Run;
- Detect Drift;
- diagnostics;
- bounded firewall logs.

If synchronization fails:

1. test the Proxmox connection in Proxmox Manager;
2. run **Test Proxmox Firewall API** in DCST;
3. check whether the API principal can access cluster firewall rules/IPSets and node firewall logs;
4. inspect DCST diagnostics and audit entries;
5. run Dry Run to inspect the intended change;
6. use Detect Drift before applying reconciliation.

DCST records failed provider responses and marks objects `ERROR`; it does not report a failed operation as synchronized.

## End-to-end flow

```text
Create / discover VM
        |
        v
Proxmox Manager sync
        |
        v
Shared Hosts Manager inventory
        |
        v
APMID = IAASTEA, ENV = PROD
        |
        v
IAASTEA.PROD TAG
        |
        v
dynamic IPSet
        |
        v
DCST Service + reusable Port(s)
        |
        v
Reconciliation / Dry Run / Verify
        |
        v
Proxmox Firewall API
```
