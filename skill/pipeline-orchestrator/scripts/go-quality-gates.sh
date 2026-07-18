#!/usr/bin/env bash
# Go Security & Quality Verification Script
# Usage: ./go-quality-gates.sh [project_dir]

set -e

PROJECT_DIR="${1:-.}"

echo "🔍 Running Go quality gates..."

echo "📋 Checking Go version..."
go version

echo "🧹 Formatting..."
go fmt ./...

echo "🔨 Building..."
go build ./...

echo "🔍 Vetting..."
go vet ./...

echo "🔐 Security scan (gosec)..."
if command -v gosec &> /dev/null; then
    gosec -quiet ./...
else
    echo "⚠️ gosec not installed. Run: go install github.com/securego/gosec/v2/cmd/gosec@latest"
fi

echo "🔍 Secret scan (gitleaks)..."
if command -v gitleaks &> /dev/null; then
    gitleaks detect --no-git --verbose
else
    echo "⚠️ gitleaks not installed. Run: go install github.com/zricethezav/gitleaks/v8@latest"
fi

echo "🧪 Testing with race detector..."
go test -race ./...

echo "✅ All quality gates passed!"
