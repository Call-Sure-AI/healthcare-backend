#!/bin/bash

# docker-cleanup.sh
# Comprehensive Docker cleanup script

set -e

echo "=========================================="
echo "Docker Cleanup Script"
echo "=========================================="
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Show current disk usage
echo -e "${BLUE}=== Current Docker Disk Usage ===${NC}"
docker system df

echo ""
echo -e "${YELLOW}This script will:${NC}"
echo "  1. Remove stopped containers"
echo "  2. Remove dangling images"
echo "  3. Remove unused images (keep last 2 for each app)"
echo "  4. Remove unused volumes"
echo "  5. Remove build cache"
echo ""
read -p "Continue with cleanup? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo -e "${RED}Cleanup cancelled.${NC}"
    exit 1
fi

echo ""
echo -e "${BLUE}=== Step 1: Removing stopped containers ===${NC}"
stopped_containers=$(docker ps -a -q -f status=exited 2>/dev/null | wc -l)
if [ "$stopped_containers" -gt 0 ]; then
    docker ps -a -q -f status=exited | xargs -r docker rm
    echo -e "${GREEN}✓ Removed $stopped_containers stopped containers${NC}"
else
    echo -e "${YELLOW}! No stopped containers found${NC}"
fi

echo ""
echo -e "${BLUE}=== Step 2: Removing dangling images ===${NC}"
dangling_images=$(docker images -q -f dangling=true 2>/dev/null | wc -l)
if [ "$dangling_images" -gt 0 ]; then
    docker images -q -f dangling=true | xargs -r docker rmi
    echo -e "${GREEN}✓ Removed $dangling_images dangling images${NC}"
else
    echo -e "${YELLOW}! No dangling images found${NC}"
fi

echo ""
echo -e "${BLUE}=== Step 3: Cleaning up old application images ===${NC}"

# Cleanup production images (keep last 2)
prod_count=$(docker images healthcare-backend-app --format "{{.ID}}" 2>/dev/null | wc -l)
if [ "$prod_count" -gt 2 ]; then
    echo "Cleaning production images (keeping last 2)..."
    docker images healthcare-backend-app --format "{{.ID}} {{.CreatedAt}}" | \
      tail -n +3 | \
      awk '{print $1}' | \
      xargs -r docker rmi -f 2>/dev/null || true
    removed=$((prod_count - 2))
    echo -e "${GREEN}✓ Removed $removed old production images${NC}"
else
    echo -e "${YELLOW}! Production images already optimal ($prod_count images)${NC}"
fi

# Cleanup dev images (keep last 2)
dev_count=$(docker images healthcare-backend-app:dev --format "{{.ID}}" 2>/dev/null | wc -l)
if [ "$dev_count" -gt 2 ]; then
    echo "Cleaning dev images (keeping last 2)..."
    docker images healthcare-backend-app:dev --format "{{.ID}} {{.CreatedAt}}" | \
      tail -n +3 | \
      awk '{print $1}' | \
      xargs -r docker rmi -f 2>/dev/null || true
    removed=$((dev_count - 2))
    echo -e "${GREEN}✓ Removed $removed old dev images${NC}"
else
    echo -e "${YELLOW}! Dev images already optimal ($dev_count images)${NC}"
fi

echo ""
echo -e "${BLUE}=== Step 4: Removing unused volumes ===${NC}"
unused_volumes=$(docker volume ls -q -f dangling=true 2>/dev/null | wc -l)
if [ "$unused_volumes" -gt 0 ]; then
    docker volume ls -q -f dangling=true | xargs -r docker volume rm
    echo -e "${GREEN}✓ Removed $unused_volumes unused volumes${NC}"
else
    echo -e "${YELLOW}! No unused volumes found${NC}"
fi

echo ""
echo -e "${BLUE}=== Step 5: Cleaning build cache ===${NC}"
docker builder prune -f --filter until=24h
echo -e "${GREEN}✓ Build cache cleaned${NC}"

echo ""
echo -e "${BLUE}=== Final Docker Disk Usage ===${NC}"
docker system df

echo ""
echo -e "${GREEN}=========================================="
echo -e "Cleanup Complete!"
echo -e "==========================================${NC}"

# Show saved space
echo ""
echo "Summary:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
