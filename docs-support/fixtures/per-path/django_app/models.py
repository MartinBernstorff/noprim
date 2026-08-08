class Order:
    class Meta:
        ordering: str = "id"

    def label(self, value: str) -> str:
        return value
