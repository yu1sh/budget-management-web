import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from ledger.models import Person


@pytest.mark.django_db
@pytest.mark.parametrize("route", ["people_settings", "bank_settings", "source_settings"])
def test_settings_errors_link_to_invalid_field_and_preserve_input(client, route):
    client.force_login(User.objects.create_user("ui-tester"))
    name = "長い名前" * 100
    response = client.post(reverse(route), {"name": name, "is_active": "on"})
    assert response.status_code == 200
    html = response.content.decode()
    assert 'data-error-summary' in html
    assert 'href="#id_name"' in html
    assert f'value="{name}"' in html
    assert 'aria-invalid="true"' in html


@pytest.mark.django_db
def test_people_checkbox_can_be_disabled_and_reenabled(client):
    client.force_login(User.objects.create_user("ui-tester"))
    person = Person.objects.create(name="対象者", is_active=True)
    url = reverse("person_edit", args=[person.pk])
    response = client.get(url)
    assert 'class="checkbox-field"' in response.content.decode()
    assert client.post(url, {"name": person.name}).status_code == 302
    person.refresh_from_db()
    assert not person.is_active
    assert client.post(url, {"name": person.name, "is_active": "on"}).status_code == 302
    person.refresh_from_db()
    assert person.is_active
