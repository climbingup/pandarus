from pandarus.filesystem import sha256, json_exporter, get_appdirs_path
import tempfile
import os

dirpath = os.path.abspath(os.path.join(os.path.dirname(__file__), "data"))


def test_hashing():
    assert sha256(os.path.join(dirpath, "testfile.hash")) == \
        'd2adeda32326a6576b73f9f387d75798d5bd6f0b4d385d36684fdb7d205a0ab0'


def test_json_exporting():
    with tempfile.TemporaryDirectory() as dirpath:
        new_fp = os.path.join(dirpath, 'testfile')
        fp = json_exporter([1,2,3], {'foo': 'bar'}, new_fp, False)
        assert fp
        assert not fp.endswith(".bz2")
        assert os.path.isfile(fp)

        fp = json_exporter([1,2,3], {'foo': 'bar'}, new_fp, True)
        assert fp
        assert fp.endswith(".bz2")
        assert os.path.isfile(fp)

def test_appdirs_path():
    dp = get_appdirs_path("test-dir")
    assert os.path.exists(dp)
    assert os.path.isdir(dp)
    assert "test-dir" in dp
    assert "pandarus" in dp

    os.rmdir(dp)
    assert not os.path.exists(dp)
    dp = get_appdirs_path("test-dir")
    assert os.path.exists(dp)
    os.rmdir(dp)
