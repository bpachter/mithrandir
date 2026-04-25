#!/bin/bash
# Quick push script to deploy voice module fixes to Railway

set -e

echo "=== Mithrandir Voice Module Deployment Fixes ==="
echo ""
echo "Verifying local state..."
git status --short

echo ""
echo "Files changed:"
git diff --name-only HEAD~1 HEAD 2>/dev/null || echo "(First commit, showing staged files)"

echo ""
echo "Pushing to Railway..."
git push

echo ""
echo "✓ Pushed successfully!"
echo ""
echo "Railway will auto-redeploy in 2-3 minutes."
echo "Monitor at: Railway → your Mithrandir service → Deployments → View Logs"
echo ""
echo "What to look for in logs:"
echo "  ✓ 'Voice module loaded'"
echo "  ✓ 'Voice pre-warm started'"
echo "  ✗ 'Voice pre-warm failed' → means there's an error to debug"
echo ""
