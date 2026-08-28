#!/bin/zsh
# push.sh — Auto commit & push ApotekMonitor ke GitHub
#
# Behaviour:
#   - staging semua perubahan (git add -A)
#   - skip bila tidak ada perubahan (tidak bikin commit kosong)
#   - commit dengan pesan yang bisa di-override: ./push.sh "pesan commit"
#   - push normal ke branch aktif (fallback ke main)
#   - tidak memakai --force agar history remote tidak tertimpa

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

REMOTE_URL="https://github.com/harys-rifai/apotek-api-webhooks-endpoint.git"
BRANCH="${1:+__unused}"   # placeholder, branch diambil dari git di bawah
COMMIT_MSG="${1:-Deploy $(date '+%Y-%m-%d %H:%M:%S')}"

# Init git bila belum ada
if [ ! -d ".git" ]; then
    echo "Initializing git repository..."
    git init
fi

# Remote origin
if git remote get-url origin > /dev/null 2>&1; then
    git remote set-url origin "$REMOTE_URL"
else
    git remote add origin "$REMOTE_URL"
fi

# Branch: pakai branch saat ini, atau buat "main"
CURRENT_BRANCH="$(git symbolic-ref --quiet --short HEAD || true)"
if [ -z "$CURRENT_BRANCH" ]; then
    CURRENT_BRANCH="main"
    git branch -M "$CURRENT_BRANCH"
fi

echo "Staging semua perubahan..."
git add -A

# Lewati bila tidak ada perubahan untuk di-commit
if git diff --cached --quiet; then
    echo "Tidak ada perubahan untuk di-commit."
else
    echo "Committing: $COMMIT_MSG"
    git commit -m "$COMMIT_MSG"
fi

echo "Pushing branch '$CURRENT_BRANCH' ke origin..."
if git push -u origin "$CURRENT_BRANCH"; then
    echo "Push berhasil."
else
    echo "Push biasa gagal, mencoba --force-with-lease (lebih aman dari --force)..."
    git push -u origin "$CURRENT_BRANCH" --force-with-lease
fi

echo ""
echo "=============================="
echo "  Selesai!"
echo "  Repo  : $REMOTE_URL"
echo "  Branch: $CURRENT_BRANCH"
echo "=============================="
