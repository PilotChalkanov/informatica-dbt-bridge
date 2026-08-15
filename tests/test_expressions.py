import pytest

from informatica_dbt_bridge.expressions import is_aggregate_function_call, translate_expression


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


@pytest.mark.parametrize("func", ["SUM", "COUNT", "AVG", "MIN", "MAX"])
def test_translate_expression_recognizes_aggregate_functions_as_passthrough(func: str) -> None:
    result = translate_expression(f"{func}(AMOUNT)")

    assert result.sql == f"{func}(AMOUNT)"
    assert result.unrecognized_functions == []


def test_translate_expression_recognizes_aggregate_function_nested_arg_translated() -> None:
    result = translate_expression("SUM(IIF(AMOUNT > 0, AMOUNT, 0))")

    assert result.sql == "SUM(CASE WHEN AMOUNT > 0 THEN AMOUNT ELSE 0 END)"
    assert result.unrecognized_functions == []


@pytest.mark.parametrize("func", ["FIRST", "LAST"])
def test_translate_expression_still_flags_first_and_last_as_unrecognized(func: str) -> None:
    result = translate_expression(f"{func}(AMOUNT)")

    assert result.sql == f"{func}(AMOUNT)"
    assert result.unrecognized_functions == [func]


@pytest.mark.parametrize("func", ["SUM", "COUNT", "AVG", "MIN", "MAX"])
def test_translate_expression_translates_aggregate_conditional_clause_to_case_when(
    func: str,
) -> None:
    result = translate_expression(f"{func}(AMOUNT, STATUS = 'ACTIVE')")

    assert result.sql == f"{func}(CASE WHEN STATUS = 'ACTIVE' THEN AMOUNT END)"
    assert result.unrecognized_functions == []


@pytest.mark.parametrize("func", ["SUM", "COUNT", "AVG", "MIN", "MAX"])
def test_translate_expression_one_arg_aggregate_still_unaffected_by_conditional_clause(
    func: str,
) -> None:
    result = translate_expression(f"{func}(AMOUNT)")

    assert result.sql == f"{func}(AMOUNT)"
    assert result.unrecognized_functions == []


def test_translate_expression_aggregate_conditional_clause_condition_can_be_compound() -> None:
    result = translate_expression("SUM(AMOUNT, STATUS = 'ACTIVE' AND REGION = 'US')")

    assert result.sql == "SUM(CASE WHEN STATUS = 'ACTIVE' AND REGION = 'US' THEN AMOUNT END)"


def test_translate_expression_aggregate_conditional_clause_condition_is_recursive() -> None:
    result = translate_expression("SUM(AMOUNT, IIF(STATUS = 'ACTIVE', TRUE, FALSE))")

    assert result.sql == (
        "SUM(CASE WHEN CASE WHEN STATUS = 'ACTIVE' THEN TRUE ELSE FALSE END THEN AMOUNT END)"
    )


@pytest.mark.parametrize("func", ["SUM", "COUNT", "AVG", "MIN", "MAX"])
def test_translate_expression_aggregate_falls_back_to_unrecognized_on_too_many_args(
    func: str,
) -> None:
    result = translate_expression(f"{func}(AMOUNT, STATUS = 'ACTIVE', 1)")

    assert result.sql == f"{func}(AMOUNT, STATUS = 'ACTIVE', 1)"
    assert result.unrecognized_functions == [func]


@pytest.mark.parametrize("func", ["SUM", "MEDIAN", "FIRST", "LAST"])
def test_is_aggregate_function_call_true_for_known_aggregate_names(func: str) -> None:
    assert is_aggregate_function_call(f"{func}(AMOUNT)") is True


def test_is_aggregate_function_call_false_for_non_aggregate_call() -> None:
    assert is_aggregate_function_call("UPPER(REGION_DESC)") is False


def test_is_aggregate_function_call_false_for_bare_identifier() -> None:
    assert is_aggregate_function_call("STATUS") is False


def test_is_aggregate_function_call_false_for_trailing_content_after_call() -> None:
    assert is_aggregate_function_call("SUM(AMOUNT) + 1") is False


def test_is_aggregate_function_call_false_for_unbalanced_parens() -> None:
    assert is_aggregate_function_call("SUM(AMOUNT") is False
