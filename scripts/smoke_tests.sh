#!/bin/bash

# Smoke Tests - Quick validation that deployment succeeded
# Usage: ./scripts/smoke_tests.sh [staging|production]

set -e

ENV=${1:-staging}
if [ "$ENV" = "staging" ]; then
    BASE_URL="https://staging.finai.app"
    TEST_USER="test@staging.finai.app"
    TEST_PASS="test_password_123"
elif [ "$ENV" = "production" ]; then
    BASE_URL="https://finai.app"
    TEST_USER="test@finai.app"
    TEST_PASS="$PROD_TEST_PASSWORD"
else
    echo "Usage: ./smoke_tests.sh [staging|production]"
    exit 1
fi

echo "🔥 Running smoke tests on $ENV ($BASE_URL)"
echo ""

PASSED=0
FAILED=0

# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Health Check
# ─────────────────────────────────────────────────────────────────────────────

echo "Test 1: Health check (basic)..."
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/health/basic/")
if [ "$RESPONSE" = "200" ]; then
    echo "✅ PASS: Health check responding (HTTP $RESPONSE)"
    ((PASSED++))
else
    echo "❌ FAIL: Health check not responding (HTTP $RESPONSE)"
    ((FAILED++))
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Readiness Check
# ─────────────────────────────────────────────────────────────────────────────

echo "Test 2: Readiness check (dependencies)..."
RESPONSE=$(curl -s "$BASE_URL/health/ready/" | jq -r '.ready')
if [ "$RESPONSE" = "true" ]; then
    echo "✅ PASS: App is ready"
    ((PASSED++))
else
    echo "❌ FAIL: App not ready: $RESPONSE"
    ((FAILED++))
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Authentication
# ─────────────────────────────────────────────────────────────────────────────

echo "Test 3: Authentication (login)..."
AUTH_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/login/" \
    -H "Content-Type: application/json" \
    -d "{\"username\": \"$TEST_USER\", \"password\": \"$TEST_PASS\"}")

TOKEN=$(echo "$AUTH_RESPONSE" | jq -r '.access_token // empty')
if [ -n "$TOKEN" ]; then
    echo "✅ PASS: User authenticated"
    ((PASSED++))
else
    echo "❌ FAIL: Authentication failed"
    ((FAILED++))
    TOKEN="invalid"
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Document List (requires auth)
# ─────────────────────────────────────────────────────────────────────────────

echo "Test 4: Document list (API access)..."
DOC_RESPONSE=$(curl -s -X GET "$BASE_URL/api/documents/" \
    -H "Authorization: Bearer $TOKEN" \
    -o /dev/null -w "%{http_code}")

if [ "$DOC_RESPONSE" = "200" ]; then
    echo "✅ PASS: API responding (HTTP $DOC_RESPONSE)"
    ((PASSED++))
else
    echo "❌ FAIL: API error (HTTP $DOC_RESPONSE)"
    ((FAILED++))
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Invoice List
# ─────────────────────────────────────────────────────────────────────────────

echo "Test 5: Invoice list..."
INV_RESPONSE=$(curl -s -X GET "$BASE_URL/api/invoices/" \
    -H "Authorization: Bearer $TOKEN" \
    -o /dev/null -w "%{http_code}")

if [ "$INV_RESPONSE" = "200" ]; then
    echo "✅ PASS: Invoice API responding (HTTP $INV_RESPONSE)"
    ((PASSED++))
else
    echo "❌ FAIL: Invoice API error (HTTP $INV_RESPONSE)"
    ((FAILED++))
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Test 6: Response Time Check
# ─────────────────────────────────────────────────────────────────────────────

echo "Test 6: Response time (should be < 1000ms)..."
START=$(date +%s%N)
curl -s -X GET "$BASE_URL/api/documents/" \
    -H "Authorization: Bearer $TOKEN" > /dev/null
END=$(date +%s%N)
ELAPSED=$(( (END - START) / 1000000 ))

if [ $ELAPSED -lt 1000 ]; then
    echo "✅ PASS: Response time is ${ELAPSED}ms (limit: 1000ms)"
    ((PASSED++))
else
    echo "⚠️  SLOW: Response time is ${ELAPSED}ms (limit: 1000ms)"
    # Don't fail on slow response, might be first deploy
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Test Results: $PASSED passed, $FAILED failed"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $FAILED -eq 0 ]; then
    echo "✅ All smoke tests passed! Deployment successful."
    exit 0
else
    echo "❌ Some tests failed. Check deployment logs."
    exit 1
fi
