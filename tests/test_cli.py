from pathlib import Path

import pytest

from informatica_dbt_bridge.cli import run

SIMPLE_MAPPING_XML = """
<POWERMART CREATION_DATE="01/01/2024" REPOSITORY_VERSION="1">
  <REPOSITORY NAME="REPO" VERSION="1">
    <FOLDER NAME="MyFolder">

      <SOURCE NAME="ORDERS" DATABASETYPE="Oracle">
        <SOURCEFIELD NAME="ORDER_ID" DATATYPE="decimal" PRECISION="10" SCALE="0"/>
        <SOURCEFIELD NAME="STATUS" DATATYPE="string" PRECISION="20"/>
      </SOURCE>

      <TARGET NAME="TGT_ORDERS" DATABASETYPE="Oracle">
        <TARGETFIELD NAME="ORDER_ID" DATATYPE="decimal"/>
        <TARGETFIELD NAME="STATUS" DATATYPE="varchar"/>
      </TARGET>

      <MAPPING NAME="m_LOAD_ORDERS">
        <TRANSFORMATION NAME="SQ_ORDERS" TYPE="Source Qualifier">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
          <TRANSFORMFIELD NAME="STATUS" PORTTYPE="OUTPUT" DATATYPE="string"/>
        </TRANSFORMATION>
      </MAPPING>

    </FOLDER>
  </REPOSITORY>
</POWERMART>
"""

MULTI_MAPPING_XML = """
<POWERMART CREATION_DATE="01/01/2024" REPOSITORY_VERSION="1">
  <REPOSITORY NAME="REPO" VERSION="1">
    <FOLDER NAME="MyFolder">

      <SOURCE NAME="ORDERS" DATABASETYPE="Oracle">
        <SOURCEFIELD NAME="ORDER_ID" DATATYPE="decimal" PRECISION="10" SCALE="0"/>
      </SOURCE>

      <TARGET NAME="TGT_ORDERS" DATABASETYPE="Oracle">
        <TARGETFIELD NAME="ORDER_ID" DATATYPE="decimal"/>
      </TARGET>

      <TARGET NAME="TGT_CUSTOMERS" DATABASETYPE="Oracle">
        <TARGETFIELD NAME="ORDER_ID" DATATYPE="decimal"/>
      </TARGET>

      <MAPPING NAME="m_LOAD_ORDERS">
        <TRANSFORMATION NAME="SQ_ORDERS" TYPE="Source Qualifier">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
        </TRANSFORMATION>
        <CONNECTOR FROMINSTANCE="SQ_ORDERS" FROMFIELD="ORDER_ID"
                    TOINSTANCE="TGT_ORDERS" TOFIELD="ORDER_ID"/>
      </MAPPING>

      <MAPPING NAME="m_LOAD_CUSTOMERS">
        <TRANSFORMATION NAME="SQ_ORDERS" TYPE="Source Qualifier">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
        </TRANSFORMATION>
        <CONNECTOR FROMINSTANCE="SQ_ORDERS" FROMFIELD="ORDER_ID"
                    TOINSTANCE="TGT_CUSTOMERS" TOFIELD="ORDER_ID"/>
      </MAPPING>

    </FOLDER>
  </REPOSITORY>
</POWERMART>
"""

INVALID_XML = "<POWERMART></POWERMART>"


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content)
    return path


def test_run_convert_writes_sql_file_named_after_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    xml_path = _write(tmp_path, "mapping.xml", SIMPLE_MAPPING_XML)
    out_dir = tmp_path / "out"

    exit_code = run(["convert", str(xml_path), "--out", str(out_dir), "--source-system", "erp"])

    assert exit_code == 0
    written = out_dir / "tgt_orders.sql"
    assert written.is_file()
    content = written.read_text()
    assert "select order_id, status" in content
    assert "{{ source('erp', 'orders') }}" in content

    captured = capsys.readouterr()
    assert str(written) in captured.out


def test_run_convert_creates_out_dir_if_missing(tmp_path: Path) -> None:
    xml_path = _write(tmp_path, "mapping.xml", SIMPLE_MAPPING_XML)
    out_dir = tmp_path / "does" / "not" / "exist" / "yet"
    assert not out_dir.exists()

    exit_code = run(["convert", str(xml_path), "--out", str(out_dir), "--source-system", "erp"])

    assert exit_code == 0
    assert out_dir.is_dir()
    assert (out_dir / "tgt_orders.sql").is_file()


def test_run_convert_selects_named_mapping_from_multi_mapping_export(tmp_path: Path) -> None:
    xml_path = _write(tmp_path, "mapping.xml", MULTI_MAPPING_XML)
    out_dir = tmp_path / "out"

    exit_code = run(
        [
            "convert",
            str(xml_path),
            "--out",
            str(out_dir),
            "--source-system",
            "erp",
            "--mapping-name",
            "m_LOAD_CUSTOMERS",
        ]
    )

    assert exit_code == 0
    assert (out_dir / "tgt_customers.sql").is_file()
    assert not (out_dir / "tgt_orders.sql").exists()


def test_run_convert_prints_manual_review_summary_when_notes_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    xml = SIMPLE_MAPPING_XML.replace('TYPE="Source Qualifier">', 'TYPE="Source Qualifier">', 1)
    xml = xml.replace(
        "</MAPPING>",
        '<TRANSFORMATION NAME="SRT_ORDERS" TYPE="Sorter">'
        '<TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="INPUT/OUTPUT" DATATYPE="decimal"/>'
        "</TRANSFORMATION>"
        '<CONNECTOR FROMINSTANCE="SQ_ORDERS" FROMFIELD="ORDER_ID" '
        'TOINSTANCE="SRT_ORDERS" TOFIELD="ORDER_ID"/>'
        "</MAPPING>",
    )
    xml_path = _write(tmp_path, "mapping.xml", xml)
    out_dir = tmp_path / "out"

    exit_code = run(["convert", str(xml_path), "--out", str(out_dir), "--source-system", "erp"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "1" in captured.out
    assert "manual review" in captured.out.lower()
    assert "SRT_ORDERS" in captured.out


def test_run_convert_returns_nonzero_and_writes_no_file_on_parse_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    xml_path = _write(tmp_path, "mapping.xml", INVALID_XML)
    out_dir = tmp_path / "out"

    exit_code = run(["convert", str(xml_path), "--out", str(out_dir), "--source-system", "erp"])

    assert exit_code != 0
    assert not out_dir.exists() or list(out_dir.glob("*.sql")) == []
    captured = capsys.readouterr()
    assert captured.err != ""


def test_run_convert_returns_nonzero_when_out_path_is_not_a_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    xml_path = _write(tmp_path, "mapping.xml", SIMPLE_MAPPING_XML)
    # A regular file already exists where --out expects a directory - mkdir
    # (and thus the whole write step) must fail cleanly, not with a raw
    # traceback.
    blocked_out = _write(tmp_path, "out", "not a directory")

    exit_code = run(["convert", str(xml_path), "--out", str(blocked_out), "--source-system", "erp"])

    assert exit_code != 0
    captured = capsys.readouterr()
    assert captured.err != ""
    assert "couldn't write" in captured.err


def test_run_convert_returns_nonzero_when_xml_file_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_path = tmp_path / "does_not_exist.xml"
    out_dir = tmp_path / "out"

    exit_code = run(["convert", str(missing_path), "--out", str(out_dir), "--source-system", "erp"])

    assert exit_code != 0
    captured = capsys.readouterr()
    assert captured.err != ""


def test_run_convert_requires_out_argument(tmp_path: Path) -> None:
    xml_path = _write(tmp_path, "mapping.xml", SIMPLE_MAPPING_XML)

    with pytest.raises(SystemExit) as exc_info:
        run(["convert", str(xml_path), "--source-system", "erp"])

    assert exc_info.value.code != 0


def test_run_convert_requires_source_system_argument(tmp_path: Path) -> None:
    xml_path = _write(tmp_path, "mapping.xml", SIMPLE_MAPPING_XML)
    out_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as exc_info:
        run(["convert", str(xml_path), "--out", str(out_dir)])

    assert exc_info.value.code != 0


def test_run_convert_mapping_name_defaults_to_first_mapping(tmp_path: Path) -> None:
    xml_path = _write(tmp_path, "mapping.xml", MULTI_MAPPING_XML)
    out_dir = tmp_path / "out"

    exit_code = run(["convert", str(xml_path), "--out", str(out_dir), "--source-system", "erp"])

    assert exit_code == 0
    assert (out_dir / "tgt_orders.sql").is_file()


def test_main_invokes_run_and_exits_with_its_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from informatica_dbt_bridge import cli

    xml_path = _write(tmp_path, "mapping.xml", SIMPLE_MAPPING_XML)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(
        "sys.argv",
        [
            "idbb",
            "convert",
            str(xml_path),
            "--out",
            str(out_dir),
            "--source-system",
            "erp",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    assert (out_dir / "tgt_orders.sql").is_file()
