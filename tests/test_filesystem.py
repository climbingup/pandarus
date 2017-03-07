from pandarus.filesystem import sha256, json_exporter
import tempfile
import os

dirpath = os.path.abspath(os.path.join(os.path.dirname(__file__), "data"))


def test_hashing():
    assert sha256(os.path.join(dirpath, "testfile.hash")) == \
        'd2adeda32326a6576b73f9f387d75798d5bd6f0b4d385d36684fdb7d205a0ab0'


def test_json_exporting():
    new_fp = os.path.join(tempfile.mkdtemp(), 'testfile')
    fp = json_exporter([1,2,3], {'foo': 'bar'}, new_fp, False)
    assert fp
    assert not fp.endswith(".bz2")
    assert os.path.isfile(fp)

    fp = json_exporter([1,2,3], {'foo': 'bar'}, new_fp, True)
    assert fp
    assert fp.endswith(".bz2")
    assert os.path.isfile(fp)
