from app.ldap_authentication.service import _attribute, _immutable_id, _text_attribute


def test_empty_decoded_values_fall_back_to_raw_ldap_attributes():
    entry = {
        "attributes": {"uid": [], "entryUUID": []},
        "raw_attributes": {"uid": [b"alice"], "entryUUID": [b"d911d54e-38ef-1041-9e85-033d33eb932c"]},
    }

    assert _text_attribute(entry, "uid") == "alice"
    assert _attribute(entry, "entryUUID") == b"d911d54e-38ef-1041-9e85-033d33eb932c"
    assert _immutable_id(
        {"immutable_id_attribute": "entryUUID", "directory_type": "ldap"},
        entry,
    ) == b"d911d54e-38ef-1041-9e85-033d33eb932c".hex()
