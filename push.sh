#!/bin/zsh
# push.sh — Push ApotekMonitor ke GitHub

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

REMOTE_URL="https://github.com/harys-rifai/ApotekMonitor.git"
BRANCH="main"

# Init git jika belum ada
if [ ! -d ".git" ]; then
    echo "Initializing git..."
    git init
fi

# Buat .gitignore jika belum ada
if [ ! -f ".gitignore" ]; then
    cat > .gitignore << 'EOF'
__pycache__/
*.pyc
venv/
.venv/
.env
*.sqlite3
.vscode/
.idea/
staticfiles/
media/
.DS_Store
EOF
    echo ".gitignore dibuat"
fi

echo "Staging semua perubahan..."
git add -A

echo "Committing..."
COMMIT_MSG="Deploy $(date '+%Y-%m-%d %H:%M:%S')"
git commit -m "$COMMIT_MSG" --allow-empty

echo "Mengatur remote origin..."
if git remote get-url origin > /dev/null 2>&1; then
    git remote set-url origin "$REMOTE_URL"
else
    git remote add origin "$REMOTE_URL"
fi

echo "Pushing ke $REMOTE_URL ..."
git branch -M "$BRANCH"
git push -u origin "$BRANCH" --force

echo ""
echo "=============================="
echo "  Push selesai!"
echo "  Repo : $REMOTE_URL"
echo "  Branch: $BRANCH"
echo "=============================="
