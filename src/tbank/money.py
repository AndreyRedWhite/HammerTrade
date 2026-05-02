def quotation_to_float(value) -> float:
    """Convert T-Bank Quotation (units + nano) to float."""
    return value.units + value.nano / 1_000_000_000


def money_value_to_float(value) -> float:
    """Convert T-Bank MoneyValue (units + nano) to float."""
    return value.units + value.nano / 1_000_000_000
