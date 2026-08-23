from django.urls import include, path

urlpatterns = [path("", include("ledger.urls"))]
