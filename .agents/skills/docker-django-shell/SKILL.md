---
name: docker-django-shell
description: Prepare the Docker Django environment, run migrations, ensure a test admin exists, and then prompt the user to open Django shell.
---

Use this skill when the user asks to prepare Docker and open a Django shell inside the `web` container.

## Steps

1. Move to the Docker directory:

   ```bash
   cd docker
   ```

2. Build and start the stack:

   ```bash
   docker compose up -d --build
   ```

3. Wait for the `web` service to become ready:

   ```bash
   until docker compose exec -T web python manage.py check >/dev/null 2>&1; do
     echo "Waiting for web service to be ready..."
     sleep 2
   done
   echo "Web service is ready."
   ```

4. Show the status of compose containers:

   ```bash
   docker compose ps
   ```

5. Run migrations:

   ```bash
   docker compose exec web python manage.py migrate
   ```

6. Run Django system checks and print a success message:

   ```bash
   docker compose exec web python manage.py check && echo "Django system checks passed."
   ```

7. Ensure test admin user exists (`admin@pucar.org` / password `admin`):

   ```bash
   docker compose exec -T web python manage.py shell <<'PY'
   from django.contrib.auth import get_user_model

   User = get_user_model()
   username = "admin@pucar.org"
   password = "admin"

   user, created = User.objects.get_or_create(
       username=username,
       defaults={"email": username, "is_staff": True, "is_superuser": True},
   )

   user.email = username
   user.is_staff = True
   user.is_superuser = True
   user.is_active = True
   user.set_password(password)
   user.save()

   print("created" if created else "exists")
   print(
       f"username={username} is_staff={user.is_staff} "
       f"is_superuser={user.is_superuser} is_active={user.is_active}"
   )
   PY
   ```

   - If the user already exists, this should not fail.
   - Always ensure the user has `is_staff=True` and `is_superuser=True`.

## Final prompt to user

After completing the steps, ask the user to run:

```bash
cd docker
docker compose exec web python manage.py shell
```

## Notes

- Use `docker compose up -d --build` (equivalent intent to `docker compose -d --build`).
- Run all commands from the `docker/` directory unless the user asks otherwise.
- If running from repository root, use: `docker compose -f docker/docker-compose.yml ...`.
- Fixed admin credentials (`admin@pucar.org` / `admin`) are for local development only. Never use this pattern in shared or production environments.
- If any step fails, collect quick diagnostics:

  ```bash
  docker compose ps
  docker compose logs --tail=100 web db redis
  ```
