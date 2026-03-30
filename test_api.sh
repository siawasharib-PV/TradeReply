#!/bin/bash

# TradeReply API Test Script
# Simple curl commands to test the API locally

BASE_URL="http://localhost:8000"
BUSINESS_ID=""

echo "🧪 TradeReply API Test Suite"
echo "=============================="
echo ""

# Color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Test 1: Health check
echo -e "${BLUE}1. Health Check${NC}"
curl -s "$BASE_URL/health" | jq .
echo ""

# Test 2: Create business
echo -e "${BLUE}2. Create Business${NC}"
RESPONSE=$(curl -s -X POST "$BASE_URL/businesses" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "name=Pada's Pizzeria&phone=(02) 9999-0000&sms_recipient=%2B61402707102&description=Award-winning pizzeria in Sydney CBD")

BUSINESS_ID=$(echo $RESPONSE | jq -r '.business_id')
echo "Created Business ID: $BUSINESS_ID"
echo $RESPONSE | jq .
echo ""

# Test 3: Get business details
echo -e "${BLUE}3. Get Business Details${NC}"
curl -s "$BASE_URL/businesses/$BUSINESS_ID" | jq .
echo ""

# Test 4: List businesses
echo -e "${BLUE}4. List All Businesses${NC}"
curl -s "$BASE_URL/businesses" | jq .
echo ""

# Test 5: Submit a 5-star review
echo -e "${BLUE}5. Submit 5-Star Review (Positive)${NC}"
REVIEW_RESPONSE=$(curl -s -X POST "$BASE_URL/reviews" \
  -H "Content-Type: application/json" \
  -d "{
    \"business_id\": \"$BUSINESS_ID\",
    \"reviewer_name\": \"Marco Giuseppe\",
    \"rating\": 5,
    \"review_text\": \"Absolutely fantastic! The margherita pizza was perfection - crispy crust, fresh mozzarella, amazing basil. Marco truly knows his craft. Will definitely be back!\",
    \"reviewer_email\": \"marco@email.com\"
  }")

echo $REVIEW_RESPONSE | jq .
REVIEW_ID=$(echo $REVIEW_RESPONSE | jq -r '.review_id')
APPROVAL_ID=$(echo $REVIEW_RESPONSE | jq -r '.approval_id')
echo ""

# Test 6: Get review details
echo -e "${BLUE}6. Get Review Details${NC}"
curl -s "$BASE_URL/reviews/$REVIEW_ID" | jq .
echo ""

# Test 7: Get pending approvals
echo -e "${BLUE}7. Get Pending Approvals${NC}"
curl -s "$BASE_URL/businesses/$BUSINESS_ID/approvals" | jq .
echo ""

# Test 8: Submit a 1-star review
echo -e "${BLUE}8. Submit 1-Star Review (Negative)${NC}"
REVIEW_RESPONSE=$(curl -s -X POST "$BASE_URL/reviews" \
  -H "Content-Type: application/json" \
  -d "{
    \"business_id\": \"$BUSINESS_ID\",
    \"reviewer_name\": \"Unhappy Customer\",
    \"rating\": 1,
    \"review_text\": \"Terrible experience. Waited 45 minutes for a pizza that arrived cold. The staff was rude and dismissive when we complained. Not coming back.\",
    \"reviewer_email\": \"upset@email.com\"
  }")

echo $REVIEW_RESPONSE | jq .
echo ""

# Test 9: Process approval (YES)
echo -e "${BLUE}9. Process Approval (YES)${NC}"
curl -s -X POST "$BASE_URL/approvals/$APPROVAL_ID" \
  -H "Content-Type: application/json" \
  -d '{"approved": true}' | jq .
echo ""

# Test 10: Debug - Check database status
echo -e "${BLUE}10. Debug - Database Status${NC}"
curl -s "$BASE_URL/debug/database" | jq .
echo ""

# Test 11: Debug - All reviews for business
echo -e "${BLUE}11. Debug - All Reviews for Business${NC}"
curl -s "$BASE_URL/debug/reviews/$BUSINESS_ID" | jq .
echo ""

echo -e "${GREEN}✅ API Test Complete!${NC}"
echo ""
echo "Business ID: $BUSINESS_ID"
echo "Review ID: $REVIEW_ID"
echo "Approval ID: $APPROVAL_ID"
