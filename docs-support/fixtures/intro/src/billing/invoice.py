class Invoice: ...


def issue(invoice: Invoice) -> Invoice:
    return invoice


def total_for(customer: str) -> int:
    return len(customer)
