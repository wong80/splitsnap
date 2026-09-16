from django.urls import path

from . import views

urlpatterns = [
    path("b/<str:admin_token>/", views.admin_bill_detail, name="admin-bill-detail"),
    path("s/<str:share_token>/", views.share_bill_detail, name="share-bill-detail"),
]
