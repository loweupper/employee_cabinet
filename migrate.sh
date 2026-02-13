#!/bin/bash
# Alembic Migration Helper Script for Docker
# Usage: ./migrate.sh [command]
# Commands: upgrade, downgrade, current, history, autogenerate

set -e

CONTAINER_NAME="${DOCKER_CONTAINER_NAME:-employees_app}"
APP_DIR="/app"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

print_usage() {
    echo "Usage: ./migrate.sh [command]"
    echo ""
    echo "Commands:"
    echo "  upgrade [revision]    - Apply migrations (default: head)"
    echo "  downgrade [revision]  - Rollback migrations (default: -1)"
    echo "  current              - Show current revision"
    echo "  history              - Show migration history"
    echo "  autogenerate <msg>   - Generate new migration from model changes"
    echo "  stamp <revision>     - Stamp database with revision without running migration"
    echo ""
    echo "Environment variables:"
    echo "  DOCKER_CONTAINER_NAME - Docker container name (default: employees_app)"
    echo ""
    echo "Examples:"
    echo "  ./migrate.sh upgrade              # Apply all pending migrations"
    echo "  ./migrate.sh upgrade +1           # Apply next migration"
    echo "  ./migrate.sh downgrade -1         # Rollback last migration"
    echo "  ./migrate.sh autogenerate 'Add user field'  # Create new migration"
    echo "  ./migrate.sh current              # Show current database version"
}

check_container() {
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo -e "${RED}Error: Container '${CONTAINER_NAME}' is not running${NC}"
        echo "Available containers:"
        docker ps --format "table {{.Names}}\t{{.Status}}"
        exit 1
    fi
}

run_alembic() {
    echo -e "${GREEN}Running: alembic $@${NC}"
    docker exec -it "${CONTAINER_NAME}" sh -c "cd ${APP_DIR} && alembic $@"
}

case "${1:-}" in
    upgrade)
        check_container
        REVISION="${2:-head}"
        echo -e "${YELLOW}Upgrading database to: ${REVISION}${NC}"
        run_alembic upgrade "${REVISION}"
        echo -e "${GREEN}✓ Migration completed successfully${NC}"
        ;;
    
    downgrade)
        check_container
        REVISION="${2:--1}"
        echo -e "${YELLOW}Downgrading database to: ${REVISION}${NC}"
        echo -e "${RED}Warning: This will rollback migrations!${NC}"
        read -p "Are you sure? (yes/no): " confirm
        if [ "$confirm" = "yes" ]; then
            run_alembic downgrade "${REVISION}"
            echo -e "${GREEN}✓ Rollback completed${NC}"
        else
            echo "Cancelled"
            exit 0
        fi
        ;;
    
    current)
        check_container
        echo -e "${YELLOW}Current database revision:${NC}"
        run_alembic current
        ;;
    
    history)
        check_container
        echo -e "${YELLOW}Migration history:${NC}"
        run_alembic history
        ;;
    
    autogenerate)
        check_container
        if [ -z "${2:-}" ]; then
            echo -e "${RED}Error: Migration message is required${NC}"
            echo "Usage: ./migrate.sh autogenerate 'Your migration message'"
            exit 1
        fi
        MESSAGE="$2"
        echo -e "${YELLOW}Generating migration: ${MESSAGE}${NC}"
        run_alembic revision --autogenerate -m "${MESSAGE}"
        echo -e "${GREEN}✓ Migration file created${NC}"
        echo -e "${YELLOW}Remember to review the generated migration file before applying!${NC}"
        ;;
    
    stamp)
        check_container
        if [ -z "${2:-}" ]; then
            echo -e "${RED}Error: Revision is required${NC}"
            echo "Usage: ./migrate.sh stamp <revision>"
            exit 1
        fi
        REVISION="$2"
        echo -e "${YELLOW}Stamping database with revision: ${REVISION}${NC}"
        run_alembic stamp "${REVISION}"
        echo -e "${GREEN}✓ Database stamped${NC}"
        ;;
    
    help|--help|-h)
        print_usage
        ;;
    
    *)
        echo -e "${RED}Error: Unknown command '${1:-}'${NC}"
        echo ""
        print_usage
        exit 1
        ;;
esac
