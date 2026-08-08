import pytest

from informatica_dbt_bridge.expressions import translate_expression


def test_translate_expression_passes_plain_arithmetic_through_unchanged() -> None:
    result = translate_expression("AMOUNT * 1.1")

    assert result.sql == "AMOUNT * 1.1"
    assert result.unrecognized_functions == []


def test_translate_expression_translates_iif_to_case_when() -> None:
    result = translate_expression("IIF(AMOUNT > 1000, 'Y', 'N')")

    assert result.sql == "CASE WHEN AMOUNT > 1000 THEN 'Y' ELSE 'N' END"
    assert result.unrecognized_functions == []


def test_translate_expression_translates_nvl_to_coalesce() -> None:
    result = translate_expression("NVL(REGION, 'UNKNOWN')")

    assert result.sql == "COALESCE(REGION, 'UNKNOWN')"


def test_translate_expression_translates_nvl2() -> None:
    result = translate_expression("NVL2(REGION, 'HAS_REGION', 'NO_REGION')")

    assert result.sql == "CASE WHEN REGION IS NOT NULL THEN 'HAS_REGION' ELSE 'NO_REGION' END"


def test_translate_expression_translates_isnull() -> None:
    result = translate_expression("ISNULL(REGION)")

    assert result.sql == "REGION IS NULL"


def test_translate_expression_translates_decode_with_default() -> None:
    result = translate_expression("DECODE(STATUS, 'A', 'Active', 'I', 'Inactive', 'Unknown')")

    assert result.sql == (
        "CASE STATUS WHEN 'A' THEN 'Active' WHEN 'I' THEN 'Inactive' ELSE 'Unknown' END"
    )


def test_translate_expression_translates_decode_without_default() -> None:
    result = translate_expression("DECODE(STATUS, 'A', 'Active', 'I', 'Inactive')")

    assert result.sql == "CASE STATUS WHEN 'A' THEN 'Active' WHEN 'I' THEN 'Inactive' END"


def test_translate_expression_translates_substr() -> None:
    result = translate_expression("SUBSTR(NAME, 1, 3)")

    assert result.sql == "SUBSTRING(NAME, 1, 3)"


def test_translate_expression_translates_bare_sysdate() -> None:
    result = translate_expression("SYSDATE")

    assert result.sql == "CURRENT_TIMESTAMP"


def test_translate_expression_translates_nested_functions_recursively() -> None:
    result = translate_expression("NVL(IIF(AMOUNT > 1000, 'Y', 'N'), 'N')")

    assert result.sql == "COALESCE(CASE WHEN AMOUNT > 1000 THEN 'Y' ELSE 'N' END, 'N')"


def test_translate_expression_leaves_unrecognized_function_verbatim_and_records_it() -> None:
    result = translate_expression("MY_CUSTOM_FUNC(AMOUNT)")

    assert result.sql == "MY_CUSTOM_FUNC(AMOUNT)"
    assert result.unrecognized_functions == ["MY_CUSTOM_FUNC"]


def test_translate_expression_handles_comma_inside_string_literal() -> None:
    result = translate_expression("IIF(STATUS = 'A,B', 'Y', 'N')")

    assert result.sql == "CASE WHEN STATUS = 'A,B' THEN 'Y' ELSE 'N' END"


@pytest.mark.parametrize("bad_iif", ["IIF(A, B)", "IIF(A, B, C, D)"])
def test_translate_expression_falls_back_to_verbatim_on_wrong_arg_count(bad_iif: str) -> None:
    result = translate_expression(bad_iif)

    assert result.sql == bad_iif
    assert result.unrecognized_functions == ["IIF"]
