#!/bin/bash

# Deployment script for tour bot
# Run on Proxmox/Astro box

set -e

echo "🚀 Deploying Bicycle Tour Bot..."

# Configuration
REPO_URL="https://github.com/kaijurtin/astro-tour-bot.git"
DEPLOY_PATH="/opt/astro-tour-bot"
NAS_PATH="/mnt/nas/tour-inputs"

# Step 1: Clone/update repo
echo "📦 Cloning repository..."
if [ -d "$DEPLOY_PATH" ]; then
  cd "$DEPLOY_PATH"
  git pull origin main
else
  git clone "$REPO_URL" "$DEPLOY_PATH"
  cd "$DEPLOY_PATH"
fi

# Step 2: Set up environment
echo "⚙️  Setting up environment..."
if [ ! -f ".env" ]; then
  echo "❌ .env file not found!"
  echo "   Please copy .env.example to .env and fill in your credentials:"
  echo "   - TELEGRAM_TOKEN"
  echo "   - OPENAI_API_KEY"
  echo "   - ANTHROPIC_API_KEY"
  exit 1
fi

# Step 3: Create NAS directories
echo "📁 Creating NAS directories..."
mkdir -p "$NAS_PATH"/{pending,processed}
chmod 755 "$NAS_PATH"

# Step 4: Create Docker network (if needed)
echo "🌐 Setting up Docker network..."
docker network create astro-net 2>/dev/null || true

# Step 5: Build and start container
echo "🐳 Building Docker container..."
docker-compose build

echo "▶️  Starting bot service..."
docker-compose up -d

# Step 6: Configure Telegram webhook
echo ""
echo "⚠️  IMPORTANT: Configure Telegram webhook manually:"
echo ""
echo "Replace TOKEN with your actual token, then run:"
echo ""
echo "curl -X POST https://api.telegram.org/bot{TOKEN}/setWebhook \\"
echo "  -d 'url=https://jurtin.de/tour-bot/webhook'"
echo ""
echo "Check: curl https://api.telegram.org/bot{TOKEN}/getWebhookInfo"
echo ""

# Step 7: Verify deployment
echo "✅ Checking deployment..."
sleep 3

if docker ps | grep -q tour-bot; then
  echo "✅ Bot container is running!"
  echo ""
  echo "🎉 Deployment complete!"
  echo ""
  echo "Next steps:"
  echo "1. Configure Telegram webhook (see above)"
  echo "2. Test with: docker logs -f tour-bot"
  echo "3. Send message to @KaiKiste_bot"
else
  echo "❌ Bot container failed to start"
  docker logs tour-bot
  exit 1
fi
