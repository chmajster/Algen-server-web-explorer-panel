from __future__ import annotations

from app.modules.storage_manager.collectors.pools import PoolCollector


def test_mdstat_parser_reports_degraded_recovery_progress() -> None:
    payload = """Personalities : [raid1]
md0 : active raid1 sdb1[0] sdc1[1](F)
      976630336 blocks super 1.2 [2/1] [U_]
      [=>...................]  recovery =  8.4% (8234232/976630336) finish=120.0min speed=100000K/sec
unused devices: <none>
"""

    arrays = PoolCollector.parse_mdstat(payload)

    assert len(arrays) == 1
    assert arrays[0]["name"] == "md0"
    assert arrays[0]["level"] == "raid1"
    assert arrays[0]["state"] == "degraded"
    assert arrays[0]["expected_members"] == 2
    assert arrays[0]["active_members"] == 1
    assert arrays[0]["missing_members"] >= 1
    assert arrays[0]["operation"] == "recovery"
    assert arrays[0]["progress_percent"] == 8.4
    assert arrays[0]["finish"] == "120.0min"
    assert arrays[0]["speed"] == "100000K/sec"


def test_zpool_status_parser_extracts_members_scan_and_errors() -> None:
    payload = """
  pool: tank
 state: DEGRADED
  scan: scrub in progress since Sun Aug 30 00:00:00 2026
        1.20T scanned at 1.00G/s, 700G issued at 500M/s, 60.5% done, 00:20:00 to go
config:

        NAME            STATE     READ WRITE CKSUM
        tank            DEGRADED     0     0     0
          mirror-0      DEGRADED     0     0     0
            /dev/sdb    ONLINE       0     0     0
            /dev/sdc    FAULTED      2     3     4

errors: 1 data errors, use '-v' for a list
"""

    result = PoolCollector.parse_zpool_status(payload, "tank")

    assert result["health"] == "DEGRADED"
    assert result["scan"]["action"] == "scrub"
    assert result["scan"]["state"] == "in_progress"
    assert result["scan"]["progress_percent"] == 60.5
    assert any(item["path"] == "/dev/sdb" and item["state"] == "ONLINE" for item in result["members"])
    failed = next(item for item in result["members"] if item["path"] == "/dev/sdc")
    assert failed["read_errors"] == 2
    assert failed["write_errors"] == 3
    assert failed["checksum_errors"] == 4
    assert result["errors"].startswith("1 data errors")


def test_zfs_dataset_parser_preserves_capacity_and_mountpoint() -> None:
    payload = "tank\tfilesystem\t1073741824\t9663676416\t536870912\t/tank\n"

    assert PoolCollector.parse_zfs_datasets(payload) == [
        {
            "name": "tank",
            "type": "filesystem",
            "used": 1073741824,
            "available": 9663676416,
            "referenced": 536870912,
            "mount_point": "/tank",
        }
    ]


def test_btrfs_parsers_extract_devices_profiles_errors_and_scrub() -> None:
    show = """Label: 'data'  uuid: 1234-5678
        Total devices 2 FS bytes used 1000
        devid    1 size 100000 used 50000 path /dev/sdb1
        devid    2 size 100000 used 50000 path /dev/sdc1
"""
    usage = """Overall:
    Device size: 200000
Data,RAID1: Size:80000, Used:60000
Metadata,RAID1: Size:10000, Used:5000
System,RAID1: Size:1000, Used:500
"""
    stats = """[/dev/sdb1].write_io_errs    0
[/dev/sdb1].read_io_errs     2
[/dev/sdc1].flush_io_errs    0
"""
    scrub = """UUID: 1234-5678
Scrub started: Sun Aug 30 00:00:00 2026
Status: running
Duration: 0:10:00
55.2%
Error summary: no errors found
"""

    parsed_show = PoolCollector.parse_btrfs_show(show)
    parsed_usage = PoolCollector.parse_btrfs_usage(usage)
    parsed_stats = PoolCollector.parse_btrfs_device_stats(stats)
    parsed_scrub = PoolCollector.parse_btrfs_scrub(scrub)

    assert parsed_show["uuid"] == "1234-5678"
    assert parsed_show["label"] == "data"
    assert [item["path"] for item in parsed_show["devices"]] == ["/dev/sdb1", "/dev/sdc1"]
    assert {item["kind"] for item in parsed_usage} == {"data", "metadata", "system"}
    assert parsed_stats["total_errors"] == 2
    assert parsed_scrub["state"] == "in_progress"
    assert parsed_scrub["progress_percent"] == 55.2
