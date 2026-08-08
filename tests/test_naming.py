import pytest

from informatica_dbt_bridge.naming import snake_case


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SQ_ORDERS", "sq_orders"),
        ("FIL_ACTIVE", "fil_active"),
        ("FIL Active", "fil_active"),
        ("AGG-BY-REGION", "agg_by_region"),
        ("__LKP_CUSTOMER__", "lkp_customer"),
    ],
)
def test_snake_case_normalizes_transformation_names(raw: str, expected: str) -> None:
    assert snake_case(raw) == expected
