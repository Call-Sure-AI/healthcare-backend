#!/bin/bash

# deploy-production.sh
# Manual deployment script for production environment

set -e

echo "=========================================="
echo "Production Deployment Script"
echo "=========================================="
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Navigate to project directory
cd ~/healthcare-backend

# Confirm deployment
echo -e "${YELLOW}This will deploy the main branch to production.${NC}"
echo -e "${YELLOW}Current branch: $(git branch --show-current)${NC}"
read -p "Continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo -e "${RED}Deployment cancelled.${NC}"
    exit 1
fi

echo ""
echo "=== Step 1: Pulling latest code ==="
git fetch origin
git checkout main
git pull origin main

echo ""
echo "=== Step 2: Stopping production container ==="
if docker stop healthcare-backend 2>/dev/null; then
    echo -e "${GREEN}✓ Container stopped${NC}"
else
    echo -e "${YELLOW}! Container was not running${NC}"
fi

if docker rm healthcare-backend 2>/dev/null; then
    echo -e "${GREEN}✓ Container removed${NC}"
else
    echo -e "${YELLOW}! Container did not exist${NC}"
fi

echo ""
echo "=== Step 3: Cleaning up old images ==="

# Count current images
image_count=$(docker images healthcare-backend-app --format "{{.ID}}" | wc -l)
echo "Found $image_count production images"

# Remove old images (keep latest 2)
if [ "$image_count" -gt 2 ]; then
    echo "Removing old images..."
    docker images healthcare-backend-app --format "{{.ID}} {{.CreatedAt}}" | \
      tail -n +3 | \
      awk '{print $1}' | \
      xargs -r docker rmi -f 2>/dev/null || true
    echo -e "${GREEN}✓ Old images removed${NC}"
fi

# Remove dangling images
echo "Removing dangling images..."
docker image prune -f
echo -e "${GREEN}✓ Dangling images removed${NC}"

echo ""
echo "=== Step 4: Building production image ==="
docker build --no-cache -t healthcare-backend-app:latest .

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Image built successfully${NC}"
else
    echo -e "${RED}✗ Image build failed${NC}"
    exit 1
fi

echo ""
echo "=== Step 5: Starting production container ==="
docker run -d \
  --name healthcare-backend \
  --env-file .env \
  --memory="300m" \
  --cpus="0.8" \
  -p 127.0.0.1:8000:8000 \
  --network healthcare-backend_healthcare-network \
  --restart unless-stopped \
  --health-cmd="curl -f http://localhost:8000/api/health || exit 1" \
  --health-interval=30s \
  --health-timeout=10s \
  --health-retries=3 \
  healthcare-backend-app:latest

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Container started${NC}"
else
    echo -e "${RED}✗ Container failed to start${NC}"
    exit 1
fi

echo ""
echo "=== Step 6: Waiting for container to be healthy ==="
timeout 60 sh -c 'until docker inspect --format="{{.State.Health.Status}}" healthcare-backend 2>/dev/null | grep -q healthy; do sleep 2; echo -n "."; done' || {
    echo ""
    echo -e "${RED}✗ Container failed to become healthy${NC}"
    echo "Last 50 log lines:"
    docker logs healthcare-backend --tail 50
    exit 1
}

echo ""
echo -e "${GREEN}✓ Container is healthy${NC}"

echo ""
echo "=== Deployment Summary ==="
docker ps -a | grep healthcare-backend || true

echo ""
echo "=== Container Logs (last 20 lines) ==="
docker logs healthcare-backend --tail 20

echo ""
echo -e "${GREEN}=========================================="
echo -e "Production Deployment Complete!"
echo -e "==========================================${NC}"
echo ""
echo "Useful commands:"
echo "  View logs:       docker logs -f healthcare-backend"
echo "  Check health:    docker inspect healthcare-backend | grep -A 5 Health"
echo "  Restart:         docker restart healthcare-backend"
echo "  Stop:            docker stop healthcare-backend"
