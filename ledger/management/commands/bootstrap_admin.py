from getpass import getpass
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Interactively create or reset the single administrator account."

    def add_arguments(self, parser):
        parser.add_argument("--username")

    def handle(self, *args, **options):
        username = options["username"] or input("管理者ユーザー名: ").strip()
        if not username:
            raise CommandError("ユーザー名は必須です。")
        password = getpass("管理者パスワード（表示されません）: ")
        confirmation = getpass("もう一度入力: ")
        if password != confirmation:
            raise CommandError("パスワードが一致しません。")
        User = get_user_model()
        if User.objects.exclude(username=username).exists():
            raise CommandError("この設置には既に別の管理者がいます。既存のユーザー名を指定してください。")
        candidate = User(username=username)
        try:
            validate_password(password, candidate)
        except ValidationError as exc:
            raise CommandError("パスワードが要件を満たしません: " + " ".join(exc.messages))
        user, created = User.objects.get_or_create(username=username)
        user.is_staff = user.is_superuser = True
        user.set_password(password)
        user.full_clean()
        user.save()
        self.stdout.write(self.style.SUCCESS("管理者を作成しました。" if created else "管理者パスワードを更新しました。"))
