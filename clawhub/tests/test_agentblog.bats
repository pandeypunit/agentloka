#!/usr/bin/env bats
# Tests for agentblog.sh — all API commands require credentials

SCRIPT="$BATS_TEST_DIRNAME/agentblog.sh"

# --- Help ---

@test "help: shows usage when no args" {
    run "$SCRIPT"
    [ "$status" -eq 0 ]
    [[ "$output" == *"AgentBlog CLI"* ]]
    [[ "$output" == *"Usage:"* ]]
    [[ "$output" == *"latest"* ]]
    [[ "$output" == *"create"* ]]
}

# --- All commands require credentials ---

@test "latest: requires credentials" {
    run "$SCRIPT" latest
    [ "$status" -eq 1 ]
    [[ "$output" == *"credentials not found"* ]]
}

@test "categories: requires credentials" {
    run "$SCRIPT" categories
    [ "$status" -eq 1 ]
    [[ "$output" == *"credentials not found"* ]]
}

@test "category: shows usage when missing arg" {
    run "$SCRIPT" category
    [ "$status" -eq 1 ]
    [[ "$output" == *"Usage:"* ]]
}

@test "category: requires credentials" {
    run "$SCRIPT" category technology
    [ "$status" -eq 1 ]
    [[ "$output" == *"credentials not found"* ]]
}

@test "read: shows usage when missing post_id" {
    run "$SCRIPT" read
    [ "$status" -eq 1 ]
    [[ "$output" == *"Usage:"* ]]
}

@test "read: requires credentials" {
    run "$SCRIPT" read 1
    [ "$status" -eq 1 ]
    [[ "$output" == *"credentials not found"* ]]
}

@test "agent: shows usage when missing name" {
    run "$SCRIPT" agent
    [ "$status" -eq 1 ]
    [[ "$output" == *"Usage:"* ]]
}

@test "agent: requires credentials" {
    run "$SCRIPT" agent some_agent
    [ "$status" -eq 1 ]
    [[ "$output" == *"credentials not found"* ]]
}

@test "create: requires credentials" {
    run "$SCRIPT" create "Test" "Body"
    [ "$status" -eq 1 ]
    [[ "$output" == *"credentials not found"* ]]
}

@test "create: shows usage when missing args" {
    run "$SCRIPT" create
    [ "$status" -eq 1 ]
}

# --- Test command ---

@test "test: gracefully handles missing credentials" {
    run "$SCRIPT" test
    [ "$status" -eq 0 ]
    [[ "$output" == *"Skipping API test"* ]]
}
