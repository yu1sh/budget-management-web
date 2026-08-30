from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"), path("logout/", views.logout_view, name="logout"),
    path("", views.chooser, name="chooser"),
    path("household/", views.household, name="household"), path("household/<int:pk>/edit/", views.household_edit, name="household_edit"), path("household/<int:pk>/delete/", views.household_delete, name="household_delete"),
    path("household/export/", views.download_household_csv, name="household_export"),
    path("sources/", views.sources, name="sources"), path("sources/<int:pk>/", views.source_detail, name="source_detail"),
    path("settlements/", views.settlements, name="settlements"), path("settlements/<int:pk>/", views.settlement_detail, name="settlement_detail"),
    path("sources/<int:source_id>/flea-market/export/", views.download_flea_market_csv, name="flea_market_export"),
    path("sources/<int:source_id>/flea-market/<int:pk>/edit/", views.flea_market_edit, name="flea_market_edit"),
    path("sources/<int:source_id>/flea-market/<int:pk>/delete/", views.flea_market_delete, name="flea_market_delete"),
    path("settings/sources/", views.source_settings, name="source_settings"), path("settings/sources/<int:pk>/", views.source_settings, name="source_edit"),
    path("settings/payment-links/", views.payment_link_settings, name="payment_link_settings"),
    path("medical/", views.medical, name="medical"), path("medical/export/", views.download_medical_csv, name="medical_export"),
    path("medical/hospitals/", views.medical_hospitals, name="medical_hospitals"),
    path("medical/<int:person_id>/", views.medical_person, name="medical_person"), path("medical/<int:person_id>/export/", views.download_medical_csv, name="medical_person_export"),
    path("medical/<int:person_id>/hospitals/", views.medical_person_hospitals, name="medical_person_hospitals"),
    path("medical/<int:person_id>/hospital/add/", views.medical_hospital_add, name="medical_hospital_add"),
    path("medical/<int:person_id>/hospital/", views.medical_hospital_detail, name="medical_hospital_detail"),
    path("medical/visit/<int:pk>/edit/", views.medical_visit_edit, name="medical_visit_edit"), path("medical/visit/<int:pk>/delete/", views.medical_visit_delete, name="medical_visit_delete"),
    path("medical/entry/<int:pk>/edit/", views.medical_edit, name="medical_edit"), path("medical/entry/<int:pk>/delete/", views.medical_delete, name="medical_delete"),
    path("settings/people/", views.people_settings, name="people_settings"), path("settings/people/<int:pk>/", views.people_settings, name="person_edit"),
    path("settings/password/", views.password_change, name="password_change"),
]
