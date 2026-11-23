"""Orders URL routing (spec 0039 #11).

Owns ``/cases/{case_id}/orders/`` and ``/hearings/{hearing_id}/next-hearing/`` too,
so ``apps.cases`` and ``apps.hearings`` stay unaware of orders.
"""

from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("orders", views.OrderViewSet, basename="order")
router.register("shortcuts", views.ShortcutViewSet, basename="shortcut")

urlpatterns = [
    path("order-items/", views.OrderItemCatalogueView.as_view(), name="order-items"),
    path("diary-entries/", views.DiaryEntriesView.as_view(), name="diary-entries"),
    path(
        "hearings/<uuid:hearing_id>/next-hearing/",
        views.HearingNextHearingView.as_view(),
        name="hearing-next-hearing",
    ),
    path("cases/<uuid:case_id>/orders/", views.CaseOrdersView.as_view(), name="case-orders"),
    *router.urls,
]
