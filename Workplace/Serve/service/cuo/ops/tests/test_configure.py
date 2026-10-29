import json
import tomllib
import pytest
from ops.configure import APP_ROOT, initialize


def test_initialize_covers_index_without_copying_private_values(tmp_path):
    initialize(tmp_path)
    index=json.loads((tmp_path/'config_index.json').read_text(encoding='utf-8'))
    entries=[entry for entry in index['modules'] if entry.get('config')]
    assert entries
    for entry in entries:
        relative=entry['config']
        actual=tmp_path/relative
        example=APP_ROOT/'var/config'/actual.relative_to(tmp_path).with_name(actual.stem+'.example.toml')
        assert tomllib.loads(actual.read_text(encoding='utf-8'))==tomllib.loads(example.read_text(encoding='utf-8'))
    first=tmp_path/entries[0]['config']
    first.write_text('private_value = "synthetic-do-not-overwrite"',encoding='utf-8')
    assert initialize(tmp_path)==0
    assert 'synthetic-do-not-overwrite' in first.read_text(encoding='utf-8')


def test_initialize_rejects_index_path_escape_before_writes(tmp_path):
    source=tmp_path/'source';source.mkdir()
    (source/'config_index.json').write_text(json.dumps({'modules':[{'config':'../outside.toml'}]}),encoding='utf-8')
    with pytest.raises(ValueError):initialize(tmp_path/'destination',source)
    assert not (tmp_path/'destination').exists()
