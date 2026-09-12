from ninja import Schema
from ninja.errors import HttpError


class Page[T](Schema):
    items: list[T]
    total: int
    page: int
    pageSize: int


def paginate(queryset, serializer, page=1, page_size=25):
    if page < 1 or not 1 <= page_size <= 100:
        raise HttpError(400, "Página inválida; use de 1 a 100 itens por página.")
    ordering = queryset.query.order_by or queryset.model._meta.ordering or ("pk",)
    queryset = queryset.order_by(*ordering, "pk")
    total = queryset.count()
    return {
        "items": [serializer(item) for item in queryset[(page - 1) * page_size : page * page_size]],
        "total": total,
        "page": page,
        "pageSize": page_size,
    }
