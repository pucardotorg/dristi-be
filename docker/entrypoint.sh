#!/bin/sh
set -e

# Show help if requested
if [ "$1" = "help" ] || [ "$1" = "--help" ] || [ -z "$1" ]; then
    echo "Usage: entrypoint.sh [web|worker|migrate|collectstatic|dev|shell]"
    exit 0
fi

# Wait for the database to be ready
wait_for_db() {
    echo "Waiting for database..."
    until pg_isready -h "${DB_HOST:-db}" -p "${DB_PORT:-5432}" -U "${DB_USER:-dristi}"; do
        sleep 1
    done
    echo "Database is ready."
}

# Run migrations
run_migrations() {
    echo "Running migrations..."
    python manage.py migrate --noinput
}

# Collect static files
collect_static() {
    echo "Collecting static files..."
    python manage.py collectstatic --noinput --clear
}

case "$1" in
    web)
        wait_for_db
        run_migrations
        collect_static
        echo "Starting Gunicorn..."
        exec gunicorn config.wsgi:application \
            --bind 0.0.0.0:8000 \
            --workers 4 \
            --worker-class sync \
            --access-logfile - \
            --error-logfile - \
            --capture-output \
            --enable-stdio-inheritance
        ;;
    worker)
        wait_for_db
        echo "Starting Dramatiq workers..."
        exec python manage.py rundramatiq --processes 2 --threads 8
        ;;
    migrate)
        wait_for_db
        run_migrations
        ;;
    collectstatic)
        collect_static
        ;;
    dev)
        wait_for_db
        run_migrations
        echo "Starting Django development server..."
        exec python manage.py runserver 0.0.0.0:8000
        ;;
    shell)
        exec python manage.py shell
        ;;
    *)
        exec "$@"
        ;;
esac
