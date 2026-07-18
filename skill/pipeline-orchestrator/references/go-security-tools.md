# Go Security Tools Installation & Usage

## Installation Commands

```bash
# Install gosec - Go security scanner
go install github.com/securego/gosec/v2/cmd/gosec@latest

# Install gitleaks - Git secrets scanner
go install github.com/zricethezav/gitleaks/v8@latest
```

## Critical: Package Path

**gitleaks** is hosted at `github.com/zricethezav/gitleaks/v8`, NOT `github.com/gitleaks/gitleaks/v8`.

Incorrect command:
```bash
go install github.com/gitleaks/gitleaks/v8@latest  # FAILS
```

Correct command:
```bash
go install github.com/zricethezav/gitleaks/v8@latest  # WORKS
```

## Quality Gate Commands

```bash
# Run gosec - expect 0 issues
gosec -quiet ./...

# Run gitleaks - expect no leaks
gitleaks detect --no-git --verbose

# Run tests with race detector
go test -race ./...
```

## Common Issues

### Issue: "gosec: command not found"
**Fix:** Binary installs to `~/go/bin/`. Add to PATH:
```bash
export PATH="$HOME/go/bin:$PATH"
```

### Issue: gitleaks version conflict
**Fix:** Use correct import path `github.com/zricethezav/gitleaks/v8`

### Issue: Go version too old for gosec
**Fix:** gosec v2.28.0 requires Go 1.25.8+. Run:
```bash
go install golang.org/toolchain@latest
```

## Pipeline Integration

In Phase 4 (Quality Gates), run:
1. `gosec -quiet ./...` → fix any issues
2. `gitleaks detect --no-git` → fix any leaks
3. `go test -race ./...` → fix failing tests

Pass condition: All three commands return 0 exit code.
