from app.modules.proxmox_manager.advanced import (
    _capacity_count,
    _config_summary,
    _policy_violations,
    _score_node,
)


def test_score_node_prefers_lower_resource_pressure():
    healthy = _score_node(0.20, 0.30, 0.40)
    loaded = _score_node(0.80, 0.85, 0.90)

    assert healthy > loaded
    assert healthy == 72.0
    assert _score_node(0.0, 0.0, 0.0, online=False) == -1.0


def test_capacity_count_uses_tightest_resource():
    capacity = _capacity_count(
        free_cpu_cores=12,
        free_memory_bytes=20 * 1024 * 1024 * 1024,
        free_storage_bytes=500 * 1024 * 1024 * 1024,
        cpu_cores=2,
        memory_mb=4096,
        disk_gb=40,
    )

    assert capacity == 5


def test_vm_policy_reports_name_tags_limits_and_backup():
    vm = {
        "name": "dev-api-01",
        "tags": ["dev"],
        "maxcpu": 8,
        "maxmem": 16 * 1024 * 1024 * 1024,
    }
    policy = {
        "naming_regex": r"^prd-[a-z0-9-]+$",
        "required_tags": ["production", "backup"],
        "max_cpu": 4,
        "max_memory_mb": 8192,
        "require_backup": True,
    }

    assert _policy_violations(vm, policy, has_backup=False) == ["name", "tags", "cpu", "memory", "backup"]


def test_config_summary_normalizes_drift_fields():
    summary = _config_summary(
        {
            "cores": 4,
            "sockets": 2,
            "memory": 8192,
            "balloon": 4096,
            "cpu": "host",
            "bios": "ovmf",
            "machine": "q35",
            "agent": "1,fstrim_cloned_disks=1",
            "tags": "production;backup",
            "scsi0": "local-lvm:vm-100-disk-0,size=64G",
            "net0": "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=20",
            "unused0": "local-lvm:vm-100-disk-1",
        }
    )

    assert summary["cores"] == 4
    assert summary["memory_mb"] == 8192
    assert summary["disks"] == {"scsi0": "local-lvm:vm-100-disk-0,size=64G"}
    assert summary["networks"] == {"net0": "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=20"}
